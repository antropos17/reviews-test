import base64
import hashlib
import hmac
import html
import os
import re
import secrets
import sqlite3
import textwrap
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request

ROOT = Path(__file__).resolve().parent
REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
AGE_DAYS = 30


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=os.getenv('FEEDBACK_DATABASE', str(ROOT / 'feedback.sqlite3')),
                      DATABASE_URL=os.getenv('DATABASE_URL', ''),
                      BASE_URL=os.getenv('FEEDBACK_BASE_URL', 'http://127.0.0.1:8766').rstrip('/'),
                      GITHUB_CLIENT_ID=os.getenv('GITHUB_CLIENT_ID', ''),
                      GITHUB_CLIENT_SECRET=os.getenv('GITHUB_CLIENT_SECRET', ''),
                      COOKIE_SECURE=os.getenv('FEEDBACK_COOKIE_SECURE', 'false').lower() == 'true',
                      MAX_CONTENT_LENGTH=8192)
    if config:
        app.config.update(config)
    origin = urlsplit(app.config['BASE_URL'])
    if origin.scheme not in ('http', 'https') or not origin.netloc or origin.path or origin.query or origin.fragment:
        raise ValueError('FEEDBACK_BASE_URL must be an origin without a path')
    if origin.hostname not in ('127.0.0.1', 'localhost') and (origin.scheme != 'https' or not app.config['COOKIE_SECURE']):
        raise ValueError('Public deployments require HTTPS and secure cookies')
    if origin.hostname not in ('127.0.0.1', 'localhost') and not app.config['DATABASE_URL'] and app.config['DATABASE'] == str(ROOT / 'feedback.sqlite3'):
        raise ValueError('Public deployments require an explicitly configured persistent database path')

    def db():
        if 'db' not in g:
            if app.config['DATABASE_URL']:
                from database import PostgresConnection
                g.db = PostgresConnection(app.config['DATABASE_URL'])
            else:
                g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
                g.db.row_factory = sqlite3.Row
                g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        connection = g.pop('db', None)
        if connection is not None:
            connection.close()

    with app.app_context():
        if app.config['DATABASE_URL']:
            db().execute('SELECT 1 FROM users LIMIT 0')
        else:
            db().executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repositories(id INTEGER PRIMARY KEY, full_name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_states(hash TEXT PRIMARY KEY, verifier TEXT NOT NULL, destination TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS ratings(repo_id INTEGER NOT NULL REFERENCES repositories(id), user_id INTEGER NOT NULL REFERENCES users(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), updated INTEGER NOT NULL, PRIMARY KEY(repo_id,user_id));
        CREATE TABLE IF NOT EXISTS reviews(repo_id INTEGER NOT NULL REFERENCES repositories(id), user_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY(repo_id,user_id));
        CREATE TABLE IF NOT EXISTS write_limits(user_id INTEGER PRIMARY KEY REFERENCES users(id), window_start INTEGER NOT NULL, count INTEGER NOT NULL);
        ''')
        db().commit()

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def cookie(response, name, value, age):
        response.set_cookie(name, value, max_age=age, httponly=True, secure=app.config['COOKIE_SECURE'], samesite='Lax', path='/')
        return response

    def current_user():
        token = request.cookies.get('feedback_session', '')
        if not token or len(token) > 128:
            return None
        return db().execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.hash=? AND sessions.expires>?', (digest(token), int(time.time()))).fetchone()

    def repo_name():
        name = request.args.get('repo', '')
        if not REPO_PATTERN.fullmatch(name) or any(x in ('.', '..') for x in name.split('/')):
            abort(400, 'Use a GitHub repository in owner/name format.')
        return name

    @lru_cache(maxsize=256)
    def lookup_repo(name, period):
        # Bound GitHub API use when many README readers request the same card.
        # Recheck public visibility at least every five minutes.
        try:
            response = requests.get('https://api.github.com/repos/' + name, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'community-feedback-service'}, timeout=8, allow_redirects=False)
            if response.status_code == 404:
                abort(404, 'Public repository not found.')
            if response.status_code != 200:
                abort(503, 'GitHub repository verification is unavailable.')
            data = response.json()
            if data.get('private') is not False or type(data.get('id')) is not int or not REPO_PATTERN.fullmatch(data.get('full_name', '')):
                abort(404, 'Public repository not found.')
        except (requests.RequestException, ValueError):
            abort(503, 'GitHub repository verification is unavailable.')
        return data

    def resolve_repo(name):
        # A fixed API origin and a GitHub repository ID prevent collisions after renames.
        data = lookup_repo(name, int(time.time()) // 300)
        db().execute('INSERT INTO repositories(id,full_name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name', (data['id'], data['full_name']))
        db().commit()
        return data

    def eligible(user):
        try:
            created = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
            return created.tzinfo is not None and created <= datetime.now(timezone.utc) - timedelta(days=AGE_DAYS)
        except (ValueError, TypeError, KeyError):
            return False

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-cache' if request.endpoint == 'card' else 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/auth/login')
    def login():
        name = repo_name()
        if not app.config['GITHUB_CLIENT_ID'] or not app.config['GITHUB_CLIENT_SECRET']:
            abort(503, 'GitHub login is not configured.')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        now = int(time.time())
        db().execute('DELETE FROM oauth_states WHERE expires<?', (now,))
        db().execute('INSERT INTO oauth_states VALUES (?,?,?,?)', (digest(state), verifier, name, now + 600))
        db().commit()
        query = urlencode({'client_id': app.config['GITHUB_CLIENT_ID'], 'redirect_uri': app.config['BASE_URL'] + '/auth/callback', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        return cookie(redirect('https://github.com/login/oauth/authorize?' + query), 'feedback_oauth', state, 600)

    @app.get('/auth/callback')
    def callback():
        state, cookie_state, code = request.args.get('state', ''), request.cookies.get('feedback_oauth', ''), request.args.get('code', '')
        if not state or not cookie_state or len(state) > 128 or not hmac.compare_digest(state, cookie_state) or not code or len(code) > 512:
            abort(400, 'Invalid sign-in state.')
        row = db().execute('SELECT * FROM oauth_states WHERE hash=? AND expires>?', (digest(state), int(time.time()))).fetchone()
        if not row:
            abort(400, 'Sign-in expired or already used.')
        db().execute('DELETE FROM oauth_states WHERE hash=?', (digest(state),))
        db().commit()
        try:
            token_response = requests.post('https://github.com/login/oauth/access_token', data={'client_id': app.config['GITHUB_CLIENT_ID'], 'client_secret': app.config['GITHUB_CLIENT_SECRET'], 'code': code, 'redirect_uri': app.config['BASE_URL'] + '/auth/callback', 'code_verifier': row['verifier']}, headers={'Accept': 'application/json'}, timeout=8)
            token_response.raise_for_status()
            token = token_response.json().get('access_token')
            if not token:
                abort(401, 'GitHub sign-in was not completed.')
            profile_response = requests.get('https://api.github.com/user', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'User-Agent': 'community-feedback-service'}, timeout=8)
            profile_response.raise_for_status()
            user = profile_response.json()
            if user.get('type') != 'User' or type(user.get('id')) is not int or not isinstance(user.get('login'), str) or not isinstance(user.get('created_at'), str):
                abort(403, 'Only GitHub user accounts are accepted.')
        except (requests.RequestException, ValueError):
            abort(503, 'GitHub sign-in is temporarily unavailable.')
        now = int(time.time())
        db().execute('INSERT INTO users VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET login=excluded.login,created_at=excluded.created_at', (user['id'], user['login'], user['created_at']))
        db().execute('DELETE FROM sessions WHERE expires<?', (now,))
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db().execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(session), user['id'], csrf, now + 86400 * 7))
        db().commit()
        response = redirect('/?' + urlencode({'repo': row['destination']}))
        response.delete_cookie('feedback_oauth', path='/')
        return cookie(response, 'feedback_session', session, 86400 * 7)

    @app.get('/api/feedback')
    def feedback():
        repo = resolve_repo(repo_name())
        user = current_user()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=AGE_DAYS)).isoformat().replace('+00:00', 'Z')
        ratings = db().execute('SELECT r.rating FROM ratings r JOIN users u ON u.id=r.user_id WHERE r.repo_id=? AND u.created_at<=?', (repo['id'], cutoff)).fetchall()
        reviews = db().execute('SELECT u.login,r.body,r.updated FROM reviews r JOIN users u ON u.id=r.user_id WHERE r.repo_id=? AND u.created_at<=? ORDER BY r.updated DESC LIMIT 50', (repo['id'], cutoff)).fetchall()
        own_rating = db().execute('SELECT rating FROM ratings WHERE repo_id=? AND user_id=?', (repo['id'], user['id'])).fetchone() if user else None
        own_review = db().execute('SELECT body FROM reviews WHERE repo_id=? AND user_id=?', (repo['id'], user['id'])).fetchone() if user else None
        values = [r['rating'] for r in ratings]
        return jsonify(repository=repo['full_name'], average=sum(values)/len(values) if values else None, count=len(values), reviews=[dict(r) for r in reviews], user={'login':user['login'], 'eligible':eligible(user), 'csrf':user['csrf'], 'rating':own_rating['rating'] if own_rating else None, 'review':own_review['body'] if own_review else ''} if user else None)

    @app.get('/card.svg')
    def card():
        # Reuse the same public, eligibility-filtered data as the service UI.
        data = feedback().get_json()
        def safe(value):
            text = ''.join(c for c in unicodedata.normalize('NFC', value)
                           if not unicodedata.category(c).startswith('C') or c in '\n\t')
            return html.escape(text, quote=True)

        lines = []
        for review in data['reviews'][:3]:
            lines.append(('author', '@' + review['login']))
            body = ' '.join(review['body'].split())
            wrapped = textwrap.wrap(body, width=85, max_lines=2, placeholder='…') or ['']
            lines.extend(('body', part) for part in wrapped)
        if not lines:
            lines.append(('body', 'No reviews yet. Share your experience.'))
        height = 118 + len(lines) * 24
        rating = '—' if data['average'] is None else f"{data['average']:.1f} / 5"
        count = data['count']
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}" role="img" aria-labelledby="title desc">',
               '<title id="title">Community feedback</title>',
               f'<desc id="desc">{safe(rating)}, {count} ratings; recent reviews below.</desc>',
               f'<rect x="0.5" y="0.5" width="759" height="{height - 1}" rx="8" fill="#ffffff" stroke="#d0d7de"/>',
               '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">',
               f'<text x="24" y="39" font-size="22" font-weight="600" fill="#1f2328">{safe(rating)}</text>',
               f'<text x="150" y="39" font-size="14" fill="#59636e">{count} {"rating" if count == 1 else "ratings"}</text>',
               '<path d="M24 58H736" stroke="#d8dee4"/>',
               '<text x="24" y="85" font-size="15" font-weight="600" fill="#1f2328">Recent reviews</text>']
        for index, (kind, value) in enumerate(lines):
            color = '#1f2328' if kind == 'author' else '#444d56'
            weight = '600' if kind == 'author' else '400'
            svg.append(f'<text x="24" y="{112 + index * 24}" font-size="14" font-weight="{weight}" fill="{color}">{safe(value)}</text>')
        svg.append('</g></svg>')
        response = Response(''.join(svg), mimetype='image/svg+xml')
        return response

    @app.post('/api/<action>')
    def write(action):
        if action not in ('rating', 'review', 'logout'):
            abort(404)
        user = current_user()
        if not user:
            abort(401, 'Sign in with GitHub first.')
        if request.headers.get('Origin') != app.config['BASE_URL'] or not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), user['csrf']):
            abort(403, 'Invalid request.')
        if action == 'logout':
            db().execute('DELETE FROM sessions WHERE hash=?', (digest(request.cookies['feedback_session']),))
            db().commit()
            response = jsonify(ok=True)
            response.delete_cookie('feedback_session', path='/')
            return response
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, 'Invalid input.')
        repo = resolve_repo(repo_name())
        now = int(time.time())
        table = 'ratings' if action == 'rating' else 'reviews'
        if app.config['DATABASE_URL']:
            db().execute('SELECT pg_advisory_xact_lock(?)', (user['id'],))
        else:
            db().execute('BEGIN IMMEDIATE')
        limit = db().execute('SELECT window_start,count FROM write_limits WHERE user_id=?', (user['id'],)).fetchone()
        if limit and now - limit['window_start'] < 3600 and limit['count'] >= 20:
            db().rollback()
            abort(429, 'Hourly feedback limit reached. Please try later.')
        previous = db().execute(f'SELECT updated FROM {table} WHERE repo_id=? AND user_id=?', (repo['id'], user['id'])).fetchone()
        if previous and now - previous['updated'] < 5:
            db().rollback()
            abort(429, 'Please wait a few seconds before updating again.')
        if action == 'rating':
            value = data.get('rating')
            if type(value) is not int or not 1 <= value <= 5:
                abort(400, 'Choose a rating from 1 to 5.')
            db().execute('INSERT INTO ratings VALUES (?,?,?,?) ON CONFLICT(repo_id,user_id) DO UPDATE SET rating=excluded.rating,updated=excluded.updated', (repo['id'], user['id'], value, now))
        else:
            value = data.get('body')
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 4000 or any(ord(c)<32 and c not in '\n\r\t' for c in value):
                abort(400, 'Review must be 1 to 4000 characters.')
            db().execute('INSERT INTO reviews VALUES (?,?,?,?) ON CONFLICT(repo_id,user_id) DO UPDATE SET body=excluded.body,updated=excluded.updated', (repo['id'], user['id'], value.strip(), now))
        start = limit['window_start'] if limit and now - limit['window_start'] < 3600 else now
        count = limit['count'] + 1 if limit and start == limit['window_start'] else 1
        db().execute('INSERT INTO write_limits VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (user['id'], start, count))
        db().commit()
        return jsonify(ok=True, pending=not eligible(user))

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.getenv('PORT', '8766')), debug=False)
