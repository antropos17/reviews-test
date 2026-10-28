import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import textwrap
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs
from werkzeug.exceptions import HTTPException

import requests
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request
from http_retry import get as retry_get

ROOT = Path(__file__).resolve().parent
REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
AGE_DAYS = 30


class RepositoryMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.crumbs = []
        self.revisions = []
        self.script = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == 'meta' and (fields.get('name', '').startswith('octolytics-dimension-repository_') or fields.get('name') == 'octolytics-dimension-user_id'):
            self.values[fields['name']] = fields.get('content', '')
        if tag == 'script' and fields.get('type') == 'application/json':
            self.script = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                payload = json.loads(''.join(self.script))
                crumbs = payload.get('props', {}).get('contextRegion', {}).get('crumbs', [])
                if isinstance(crumbs, list):
                    self.crumbs.extend(crumbs)
                route = payload.get('payload', {}).get('codeViewLayoutRoute', {})
                if isinstance(route, dict):
                    self.revisions.append(route)
            except (ValueError, AttributeError):
                pass
            self.script = None

    def owner_type(self, name):
        owner = name.split('/')[0].lower()
        kinds = {c.get('crumb_type') for c in self.crumbs if isinstance(c, dict)
                 and isinstance(c.get('label'), str) and c['label'].lower() == owner
                 and isinstance(c.get('href'), str) and c['href'].lower() == '/' + owner
                 and c.get('crumb_type') in ('user', 'organization')}
        return {'user':'User', 'organization':'Organization'}.get(next(iter(kinds))) if len(kinds) == 1 else None

    def revision(self, name, repo_id):
        found = set()
        for route in self.revisions:
            repo, ref = route.get('repo', {}), route.get('refInfo', {})
            if not isinstance(repo, dict) or not isinstance(ref, dict):
                continue
            oid = ref.get('currentOid')
            if (repo.get('id') == repo_id and str(repo.get('ownerLogin', '')).lower() + '/' + str(repo.get('name', '')).lower() == name.lower()
                    and ref.get('name') == repo.get('defaultBranch') and isinstance(oid, str) and re.fullmatch(r'[0-9a-f]{40}', oid)):
                found.add(oid)
        return next(iter(found)) if len(found) == 1 else None


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=os.getenv('FEEDBACK_DATABASE', str(ROOT / 'feedback.sqlite3')),
                      DATABASE_URL=os.getenv('DATABASE_URL', ''),
                      BASE_URL=os.getenv('FEEDBACK_BASE_URL', 'http://127.0.0.1:8766').rstrip('/'),
                      GITHUB_CLIENT_ID=os.getenv('GITHUB_CLIENT_ID', ''),
                      GITHUB_CLIENT_SECRET=os.getenv('GITHUB_CLIENT_SECRET', ''),
                      GITHUB_APP_ID=os.getenv('FEEDBACK_GITHUB_APP_ID', ''),
                      GITHUB_APP_PRIVATE_KEY=os.getenv('FEEDBACK_GITHUB_APP_PRIVATE_KEY', ''),
                      GITHUB_APP_SLUG=os.getenv('FEEDBACK_GITHUB_APP_SLUG', ''),
                      MODERATOR_IDS=os.getenv('FEEDBACK_MODERATOR_IDS', ''),
                      SEAL_CRON_TOKEN=os.getenv('FEEDBACK_SEAL_CRON_TOKEN', ''),
                      TEST_REPO=os.getenv('FEEDBACK_TEST_REPO', ''),
                      JOURNAL_PRIVATE_KEY=os.getenv('FEEDBACK_JOURNAL_PRIVATE_KEY', ''),
                      COOKIE_SECURE=os.getenv('FEEDBACK_COOKIE_SECURE', 'false').lower() == 'true',
                      MAX_CONTENT_LENGTH=50000)
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
        CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, repo_id INTEGER NOT NULL REFERENCES repositories(id), author_id INTEGER NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, reporter_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, created INTEGER NOT NULL, UNIQUE(repo_id,author_id,revision,reporter_id));
        CREATE TABLE IF NOT EXISTS moderation_events(id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(id), repo_id INTEGER NOT NULL REFERENCES repositories(id), author_id INTEGER NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, moderator_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, reason TEXT NOT NULL, event_time INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS owner_replies(repo_id INTEGER NOT NULL REFERENCES repositories(id), author_id INTEGER NOT NULL REFERENCES users(id), owner_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY(repo_id,author_id));
        CREATE TABLE IF NOT EXISTS seals(repo_id INTEGER PRIMARY KEY REFERENCES repositories(id), activated_at INTEGER NOT NULL, removed_at INTEGER, removed_rating REAL, activated_by INTEGER NOT NULL REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS security_concerns(repo_id INTEGER NOT NULL REFERENCES repositories(id), author_id INTEGER NOT NULL REFERENCES users(id), revision INTEGER NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), evidence_url TEXT, PRIMARY KEY(repo_id,author_id));
        CREATE TABLE IF NOT EXISTS journal_events(seq INTEGER PRIMARY KEY, event_json TEXT NOT NULL, event_hash TEXT NOT NULL, signature TEXT NOT NULL);
        ''')
        db().commit()

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def record(kind, repo_id, user_id, details):
        from journal import append, public_key
        try:
            receipt = append(db(), app.config['JOURNAL_PRIVATE_KEY'], kind, repo_id, user_id, details, time.time_ns(), bool(app.config['DATABASE_URL']))
            receipt['public_key'] = public_key(app.config['JOURNAL_PRIVATE_KEY'])
            return receipt
        except ValueError:
            abort(503, 'The signed journal is not configured.')

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
            if response.status_code == 200:
                data = response.json()
                if data.get('private') is not False or type(data.get('id')) is not int or not REPO_PATTERN.fullmatch(data.get('full_name', '')) or type((data.get('owner') or {}).get('id')) is not int:
                    abort(404, 'Public repository not found.')
                return data
        except (requests.RequestException, ValueError):
            pass
        # When the unauthenticated API is rate-limited, require GitHub's public
        # repository metadata and preserve any previously verified repository ID.
        known = db().execute('SELECT id,full_name FROM repositories WHERE lower(full_name)=lower(?)', (name,)).fetchone()
        try:
            page = requests.get('https://github.com/' + name, headers={'User-Agent': 'community-feedback-service'}, timeout=8, allow_redirects=False)
            metadata = RepositoryMetadata()
            if page.status_code == 200:
                metadata.feed(page.text)
            fields = metadata.values
            repo_id = fields.get('octolytics-dimension-repository_id', '')
            full_name = fields.get('octolytics-dimension-repository_nwo', '')
            owner_id = fields.get('octolytics-dimension-user_id', '')
            if (fields.get('octolytics-dimension-repository_public') == 'true'
                    and repo_id.isascii() and repo_id.isdigit() and 0 < int(repo_id) < 2**63
                    and owner_id.isascii() and owner_id.isdigit() and 0 < int(owner_id) < 2**63
                    and (not known or repo_id == str(known['id']))
                    and full_name.lower() == name.lower()):
                return {'id': int(repo_id), 'full_name': full_name, 'private': False, 'owner': {'id': int(owner_id), 'type': metadata.owner_type(full_name)}}
        except requests.RequestException:
            pass
        abort(503, 'GitHub repository verification is unavailable.')

    def resolve_repo(name, fresh=False):
        # A fixed API origin and a GitHub repository ID prevent collisions after renames.
        resolver = lookup_repo.__wrapped__ if fresh else lookup_repo
        data = resolver(name, int(time.time()) // 300)
        db().execute('INSERT INTO repositories(id,full_name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name', (data['id'], data['full_name']))
        db().commit()
        return data

    def eligible(user):
        try:
            created = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
            return created.tzinfo is not None and created <= datetime.now(timezone.utc) - timedelta(days=AGE_DAYS)
        except (ValueError, TypeError, KeyError):
            return False

    def organization_owners(repo):
        if repo['owner'].get('type') == 'User':
            return {repo['owner']['id']}
        if repo['owner'].get('type') != 'Organization':
            return None
        from organization_access import owners, OrganizationUnavailable
        try:
            return owners(repo['full_name'].split('/')[0], repo['owner']['id'], app.config['GITHUB_APP_ID'], app.config['GITHUB_APP_PRIVATE_KEY'])
        except OrganizationUnavailable:
            return None

    def rating_totals(repo, owner_ids=None):
        if owner_ids is None:
            owner_ids = organization_owners(repo)
        if owner_ids is None:
            return {'count': 0, 'average': None}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=AGE_DAYS)).isoformat().replace('+00:00', 'Z')
        excluded = ','.join('?' for _ in owner_ids)
        return db().execute("""SELECT COUNT(*) AS count, AVG(r.rating) AS average FROM ratings r JOIN users u ON u.id=r.user_id
          WHERE r.repo_id=? AND u.created_at<=? AND u.id NOT IN (""" + excluded + """) AND NOT EXISTS (
          SELECT 1 FROM reviews rv WHERE rv.repo_id=r.repo_id AND rv.user_id=r.user_id AND
          COALESCE((SELECT e.action FROM moderation_events e WHERE e.repo_id=rv.repo_id AND e.author_id=rv.user_id AND e.revision=rv.updated AND e.action IN ('hide','restore') ORDER BY e.event_time DESC,e.id DESC LIMIT 1),'restore')='hide')""", (repo['id'], cutoff, *sorted(owner_ids))).fetchone()

    def contains_badge(text, name):
        for match in re.findall(r'https?://[^\s<>"\')]+', html.unescape(text)):
            parsed = urlsplit(match)
            if parsed.scheme + '://' + parsed.netloc == app.config['BASE_URL'] and parsed.path == '/card.svg':
                if parse_qs(parsed.query).get('repo', [''])[0].lower() == name.lower():
                    return True
        return False

    def valid_evidence(value, name):
        if not isinstance(value, str) or len(value) > 2048:
            return False
        try:
            url = urlsplit(value)
        except ValueError:
            return False
        if url.scheme != 'https' or url.netloc.lower() != 'github.com' or url.query:
            return False
        path = url.path.split('/')
        if len(path) < 5 or '/'.join(path[1:3]).lower() != name.lower() or any(part in ('.', '..') or '%' in part for part in path):
            return False
        if path[3] == 'issues':
            return len(path) == 5 and path[4].isascii() and path[4].isdigit() and int(path[4]) > 0
        if path[3] == 'commit':
            return len(path) == 5 and bool(re.fullmatch(r'[0-9a-fA-F]{7,40}', path[4]))
        if path[3] == 'blob':
            return len(path) >= 6 and all(path[4:]) and (not url.fragment or bool(re.fullmatch(r'L[1-9][0-9]*(?:-L[1-9][0-9]*)?',url.fragment)))
        return False

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-cache' if request.endpoint in ('card', 'example_card') else 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = ("default-src 'none'; style-src 'unsafe-inline'; sandbox" if request.endpoint in ('card', 'example_card')
                                                       else "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/projects')
    def project_catalog():
        projects = json.loads((ROOT / 'projects.json').read_text(encoding='utf-8'))
        query = request.args.get('q', '').strip().casefold()[:140]
        topic = request.args.get('topic', '')
        topics = sorted({item['topic'] for item in projects})
        matches = [item for item in projects if (not topic or item['topic'] == topic)
                   and (not query or query in ' '.join(item.values()).casefold())]
        return jsonify(projects=matches, topics=topics, total=len(projects))

    @app.get('/rules')
    def rules():
        return render_template('rules.html')

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

    @app.post('/api/seal/start')
    def seal_start():
        user = authenticated_write()
        name = repo_name()
        resolve_repo(name, fresh=True)
        lock_for(user['id'])
        limit = db().execute('SELECT window_start,count FROM write_limits WHERE user_id=?', (user['id'],)).fetchone()
        now = int(time.time())
        if limit and now-limit['window_start'] < 3600 and limit['count'] >= 20:
            abort(429, 'Hourly request limit reached.')
        start = limit['window_start'] if limit and now-limit['window_start'] < 3600 else now
        count = limit['count']+1 if limit and start == limit['window_start'] else 1
        db().execute('INSERT INTO write_limits VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (user['id'],start,count))
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        db().execute('DELETE FROM oauth_states WHERE expires<?', (now,))
        db().execute('INSERT INTO oauth_states VALUES (?,?,?,?)', (digest(state), verifier, 'seal:' + name, now + 600))
        db().commit()
        query = urlencode({'client_id': app.config['GITHUB_CLIENT_ID'], 'redirect_uri': app.config['BASE_URL'] + '/auth/callback', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        return cookie(jsonify(url='https://github.com/login/oauth/authorize?' + query), 'feedback_oauth', state, 600)

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
        if row['destination'].startswith('seal:'):
            current = current_user()
            if not current or current['id'] != user['id']:
                abort(403, 'Sign in with the same GitHub account before activating the seal.')
            name = row['destination'][5:]
            if not REPO_PATTERN.fullmatch(name):
                abort(400, 'Invalid repository.')
            repo = resolve_repo(name, fresh=True)
            try:
                response = requests.get('https://api.github.com/repos/' + name, headers={'Authorization':'Bearer ' + token, 'Accept':'application/vnd.github+json', 'User-Agent':'community-feedback-service'}, timeout=8, allow_redirects=False)
                permission = response.json() if response.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                abort(503, 'GitHub admin verification is unavailable.')
            if permission.get('id') != repo['id'] or (permission.get('permissions') or {}).get('admin') is not True:
                abort(403, 'GitHub repository admin permission is required.')
            activated = int(time.time())
            result = db().execute('INSERT INTO seals(repo_id,activated_at,removed_at,removed_rating,activated_by) VALUES (?,?,NULL,NULL,?) ON CONFLICT(repo_id) DO NOTHING', (repo['id'], activated, user['id']))
            if result.rowcount:
                record('seal_activated', repo['id'], user['id'], {'activated_at':activated})
            db().commit()
            response = redirect('/?' + urlencode({'repo':repo['full_name']}))
            response.delete_cookie('feedback_oauth', path='/')
            return response
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
        owner_ids = organization_owners(repo)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=AGE_DAYS)).isoformat().replace('+00:00', 'Z')
        totals = rating_totals(repo, owner_ids) if owner_ids is not None else {'count': 0, 'average': None}
        reviews = db().execute("SELECT u.id AS user_id,u.login,r.body,r.updated,c.evidence_url FROM reviews r JOIN users u ON u.id=r.user_id LEFT JOIN security_concerns c ON c.repo_id=r.repo_id AND c.author_id=r.user_id AND c.revision=r.updated AND c.enabled=1 WHERE r.repo_id=? AND u.created_at<=? AND COALESCE((SELECT e.action FROM moderation_events e WHERE e.repo_id=r.repo_id AND e.author_id=r.user_id AND e.revision=r.updated AND e.action IN ('hide','restore') ORDER BY e.event_time DESC,e.id DESC LIMIT 1),'restore')<>'hide' ORDER BY r.updated DESC LIMIT 50", (repo['id'], cutoff)).fetchall()
        concern_count = db().execute("SELECT COUNT(*) AS count FROM security_concerns c JOIN reviews r ON r.repo_id=c.repo_id AND r.user_id=c.author_id AND r.updated=c.revision JOIN users u ON u.id=r.user_id WHERE c.repo_id=? AND c.enabled=1 AND u.created_at<=? AND COALESCE((SELECT e.action FROM moderation_events e WHERE e.repo_id=r.repo_id AND e.author_id=r.user_id AND e.revision=r.updated AND e.action IN ('hide','restore') ORDER BY e.event_time DESC,e.id DESC LIMIT 1),'restore')<>'hide'", (repo['id'], cutoff)).fetchone()['count']
        concerns = db().execute("SELECT u.id AS user_id,u.login,r.body,r.updated,c.evidence_url FROM security_concerns c JOIN reviews r ON r.repo_id=c.repo_id AND r.user_id=c.author_id AND r.updated=c.revision JOIN users u ON u.id=r.user_id WHERE c.repo_id=? AND c.enabled=1 AND u.created_at<=? AND COALESCE((SELECT e.action FROM moderation_events e WHERE e.repo_id=r.repo_id AND e.author_id=r.user_id AND e.revision=r.updated AND e.action IN ('hide','restore') ORDER BY e.event_time DESC,e.id DESC LIMIT 1),'restore')<>'hide' ORDER BY r.updated DESC LIMIT 50", (repo['id'], cutoff)).fetchall()
        own_rating = db().execute('SELECT rating FROM ratings WHERE repo_id=? AND user_id=?', (repo['id'], user['id'])).fetchone() if user else None
        own_review = db().execute('SELECT body FROM reviews WHERE repo_id=? AND user_id=?', (repo['id'], user['id'])).fetchone() if user else None
        own_concern = db().execute('SELECT c.evidence_url FROM security_concerns c JOIN reviews r ON r.repo_id=c.repo_id AND r.user_id=c.author_id AND r.updated=c.revision WHERE c.repo_id=? AND c.author_id=? AND c.enabled=1', (repo['id'], user['id'])).fetchone() if user else None
        replies = db().execute('SELECT author_id,body,updated FROM owner_replies WHERE repo_id=? AND owner_id=?', (repo['id'], repo['owner']['id'])).fetchall()
        by_author = {r['author_id']: {'body':r['body'], 'updated':r['updated']} for r in replies}
        moderator_ids = {int(value) for value in str(app.config['MODERATOR_IDS']).split(',') if value.strip().isdigit()}
        seal = db().execute('SELECT activated_at,removed_at,removed_rating FROM seals WHERE repo_id=?', (repo['id'],)).fetchone()
        seal_data = dict(seal) if seal else None
        public_review = lambda r: dict(r, owner=r['user_id']==repo['owner']['id'], reply=by_author.get(r['user_id']))
        slug = str(app.config['GITHUB_APP_SLUG'])
        install_url = 'https://github.com/apps/' + slug + '/installations/new' if repo['owner'].get('type') == 'Organization' and owner_ids is None and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', slug) else None
        return jsonify(test_available=bool(user and owner_ids is not None and user['id'] in owner_ids and repo['full_name'].lower() in {item.strip().lower() for item in str(app.config['TEST_REPO']).split(',') if item.strip()}), repository=repo['full_name'], organization_install_url=install_url, feedback_unavailable=owner_ids is None, average=float(totals['average']) if totals['average'] is not None else None, count=totals['count'], security_concerns=concern_count, concerns=[public_review(r) for r in concerns], seal=seal_data, reviews=[public_review(r) for r in reviews], moderation_available=repo['owner'].get('type') == 'User' and any(mid != repo['owner']['id'] for mid in moderator_ids), user={'login':user['login'], 'eligible':eligible(user), 'owner':owner_ids is not None and user['id'] in owner_ids, 'moderator':repo['owner'].get('type') == 'User' and user['id'] in moderator_ids and user['id']!=repo['owner']['id'], 'csrf':user['csrf'], 'rating':own_rating['rating'] if own_rating else None, 'review':own_review['body'] if own_review else '', 'evidence_url':own_concern['evidence_url'] if own_concern else None} if user else None)

    @app.get('/card.svg')
    def card():
        from badge import render_badge
        return Response(render_badge(feedback().get_json(), request.args.get('theme','light'), request.args.get('style','card')), mimetype='image/svg+xml')

    @app.get('/badge')
    def badge_preview():
        if request.args.get('repo'):
            repo_name()
        return render_template('badge.html')

    @app.get('/examples/card.svg')
    def example_card():
        from examples import render_example
        return Response(render_example(request.args.get('rating', 'mixed'),
                                       request.args.get('theme', 'light'),
                                       request.args.get('style', 'card')), mimetype='image/svg+xml')

    @app.get('/api/journal')
    def public_journal():
        from journal import public_key
        try:
            key = public_key(app.config['JOURNAL_PRIVATE_KEY'])
        except ValueError:
            abort(503, 'The signed journal is not configured.')
        try:
            after = int(request.args.get('after','0'))
            if not 0 <= after < 2**63:
                raise ValueError()
        except ValueError:
            abort(400, 'Invalid journal cursor.')
        rows = db().execute('SELECT seq,event_json,event_hash,signature FROM journal_events WHERE seq>? ORDER BY seq LIMIT 200', (after,)).fetchall()
        head = db().execute('SELECT seq,event_json,event_hash,signature FROM journal_events ORDER BY seq DESC LIMIT 1').fetchone()
        import json
        envelope = lambda row: {'event':json.loads(row['event_json']), 'hash':row['event_hash'], 'signature':row['signature']}
        return jsonify(public_key=key, entries=[envelope(row) for row in rows], head=envelope(head) if head else None)

    def authenticated_write():
        user = current_user()
        if not user:
            abort(401, 'Sign in with GitHub first.')
        if request.headers.get('Origin') != app.config['BASE_URL'] or not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), user['csrf']):
            abort(403, 'Invalid request.')
        return user

    def test_repo(fresh=False):
        name = repo_name()
        allowed = {item.strip().lower() for item in str(app.config['TEST_REPO']).split(',') if item.strip()}
        if name.lower() not in allowed:
            abort(404, 'Test mode is unavailable for this repository.')
        return resolve_repo(name, fresh=fresh)

    def latest_test_data(repo):
        import json
        rows = db().execute('SELECT event_json FROM journal_events WHERE event_json LIKE ? AND (event_json LIKE ? OR event_json LIKE ?) ORDER BY seq DESC LIMIT 1000',
                            ('%"repo_id":"' + str(repo['id']) + '"%', '%"kind":"test_rating"%', '%"kind":"test_review"%')).fetchall()
        rating, review = None, None
        for row in rows:
            event = json.loads(row['event_json'])
            if event['repo_id'] != str(repo['id']) or (repo['owner'].get('type') == 'User' and event.get('user_id') != str(repo['owner']['id'])):
                continue
            if event['kind'] == 'test_rating' and rating is None:
                rating = event['details']
            if event['kind'] == 'test_review' and review is None:
                review = event['details']
            if rating is not None and review is not None:
                break
        return rating, review

    @app.get('/test')
    def test_page():
        test_repo()
        return render_template('test.html')

    @app.get('/api/test-feedback')
    def test_feedback():
        repo = test_repo()
        user = current_user()
        rating, review = latest_test_data(repo)
        owners = organization_owners(repo)
        return jsonify(test_only=True, repository=repo['full_name'], rating=rating, review=review,
                       user={'owner':owners is not None and user['id'] in owners, 'csrf':user['csrf']} if user else None)

    @app.get('/test-card.svg')
    def test_card():
        from badge import render_badge
        data = test_feedback().get_json()
        reviews = [{'login':'TEST', 'body':data['review']['body'], 'owner':False}] if data['review'] else []
        rating = data['rating']['rating'] if data['rating'] else None
        result = render_badge({'average':rating, 'count':1 if rating is not None else 0,
                               'reviews':reviews, 'security_concerns':0, 'test_only':True}, 'light', 'card')
        return Response(result.replace('View all reviews', 'TEST ONLY · Not a real rating'), mimetype='image/svg+xml')

    @app.post('/api/test/<action>')
    def write_test(action):
        if action not in ('rating', 'review'):
            abort(404)
        user = authenticated_write()
        repo = test_repo(fresh=True)
        owners = organization_owners(repo)
        if owners is None or user['id'] not in owners:
            abort(403, 'Only the repository owner can use this test mode.')
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, 'Invalid input.')
        if action == 'rating':
            value = data.get('rating')
            if type(value) is not int or not 1 <= value <= 5:
                abort(400, 'Choose a rating from 1 to 5.')
            details = {'test_only':True, 'rating':value}
        else:
            value = data.get('body')
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500 or any(ord(c)<32 and c not in '\n\r\t' for c in value):
                abort(400, 'Enter a test review of up to 500 characters.')
            details = {'test_only':True, 'body':value.strip()}
        lock_for(user['id'])
        now = int(time.time())
        limit = db().execute('SELECT window_start,count FROM write_limits WHERE user_id=?', (user['id'],)).fetchone()
        if limit and now-limit['window_start'] < 3600 and limit['count'] >= 20:
            abort(429, 'Hourly feedback limit reached.')
        start = limit['window_start'] if limit and now-limit['window_start'] < 3600 else now
        count = limit['count']+1 if limit and start == limit['window_start'] else 1
        db().execute('INSERT INTO write_limits VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (user['id'],start,count))
        receipt = record('test_' + action, repo['id'], user['id'], details)
        db().commit()
        return jsonify(ok=True, receipt=receipt)

    @app.post('/api/reply')
    def owner_reply():
        user = authenticated_write()
        repo = resolve_repo(repo_name(), fresh=True)
        if user['id'] != repo['owner']['id']:
            abort(403, 'Only the repository owner may reply.')
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get('author_id')) is not int or not 0 < data['author_id'] < 2**63 or not isinstance(data.get('body'), str) or not 1 <= len(data['body'].strip()) <= 4000 or any(ord(c) < 32 and c not in '\n\r\t' for c in data['body']):
            abort(400, 'Enter a valid reply.')
        lock_for(user['id'])
        review = db().execute('SELECT updated FROM reviews WHERE repo_id=? AND user_id=?', (repo['id'], data['author_id'])).fetchone()
        if not review:
            abort(404, 'Review not found.')
        now = int(time.time())
        limit = db().execute('SELECT window_start,count FROM write_limits WHERE user_id=?', (user['id'],)).fetchone()
        if limit and now-limit['window_start'] < 3600 and limit['count'] >= 20:
            abort(429, 'Hourly feedback limit reached.')
        previous = db().execute('SELECT updated FROM owner_replies WHERE repo_id=? AND author_id=?', (repo['id'], data['author_id'])).fetchone()
        if previous and now-previous['updated'] < 5:
            abort(429, 'Please wait a few seconds before updating again.')
        db().execute('INSERT INTO owner_replies VALUES (?,?,?,?,?) ON CONFLICT(repo_id,author_id) DO UPDATE SET owner_id=excluded.owner_id,body=excluded.body,updated=excluded.updated', (repo['id'],data['author_id'],user['id'],data['body'].strip(),now))
        start = limit['window_start'] if limit and now-limit['window_start'] < 3600 else now
        count = limit['count']+1 if limit and start == limit['window_start'] else 1
        db().execute('INSERT INTO write_limits VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (user['id'],start,count))
        from journal import commitment
        salt, body_hash = commitment(data['body'].strip())
        receipt = record('owner_reply', repo['id'], user['id'], {'author_id':str(data['author_id']),'updated':now,'body_hash':body_hash})
        receipt['salt'] = salt
        db().commit()
        return jsonify(ok=True, receipt=receipt)

    def lock_for(value):
        if app.config['DATABASE_URL']:
            db().execute('SELECT pg_advisory_xact_lock(?)', (value,))
        else:
            db().execute('BEGIN IMMEDIATE')

    def is_moderator(user, repo):
        ids = {int(value) for value in str(app.config['MODERATOR_IDS']).split(',') if value.strip().isdigit()}
        return bool(repo['owner'].get('type') == 'User' and user and user['id'] in ids and user['id'] != repo['owner']['id'])

    @app.post('/api/report')
    def report_review():
        user = authenticated_write()
        if not eligible(user):
            abort(403, 'Reporting requires a GitHub account at least 30 days old.')
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get('author_id')) is not int or not 0 < data['author_id'] < 2**63 or type(data.get('revision')) is not int or not 0 < data['revision'] < 2**63 or data.get('reason') not in ('spam', 'abuse', 'personal_information', 'other'):
            abort(400, 'Choose a valid report reason.')
        repo = resolve_repo(repo_name())
        now = int(time.time())
        lock_for(user['id'])
        recent = db().execute('SELECT COUNT(*) AS n FROM reports WHERE reporter_id=? AND created>?', (user['id'], now - 3600)).fetchone()
        if recent['n'] >= 10:
            abort(429, 'Report limit reached. Please try again later.')
        review = db().execute('SELECT r.updated FROM reviews r JOIN users u ON u.id=r.user_id WHERE r.repo_id=? AND r.user_id=? AND u.created_at<=?', (repo['id'], data['author_id'], (datetime.now(timezone.utc)-timedelta(days=AGE_DAYS)).isoformat().replace('+00:00','Z'))).fetchone()
        if not review or review['updated'] != data['revision']:
            abort(409, 'This review has changed. Refresh before reporting.')
        result = db().execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?) ON CONFLICT(repo_id,author_id,revision,reporter_id) DO NOTHING', (secrets.token_urlsafe(18), repo['id'], data['author_id'], data['revision'], user['id'], data['reason'], now))
        if result.rowcount != 1:
            abort(409, 'You have already reported this version of the review.')
        db().commit()
        return jsonify(ok=True)

    @app.get('/api/moderation-log')
    def moderation_log():
        repo = resolve_repo(repo_name())
        events = db().execute('SELECT e.author_id,a.login AS author,e.moderator_id,m.login AS moderator,e.action,e.reason,e.event_time FROM moderation_events e JOIN users a ON a.id=e.author_id JOIN users m ON m.id=e.moderator_id WHERE e.repo_id=? ORDER BY e.event_time DESC,e.id DESC LIMIT 100', (repo['id'],)).fetchall()
        return jsonify(events=[dict(event) for event in events])

    @app.get('/api/reports')
    def moderator_reports():
        user = current_user()
        repo = resolve_repo(repo_name(), fresh=True)
        if not is_moderator(user, repo):
            abort(403, 'Independent moderator access required.')
        items = db().execute("SELECT p.id,p.revision,p.reason,p.created,u.login AS author,r.body,(SELECT e.action FROM moderation_events e WHERE e.report_id=p.id ORDER BY e.event_time DESC,e.id DESC LIMIT 1) AS status FROM reports p JOIN users u ON u.id=p.author_id LEFT JOIN reviews r ON r.repo_id=p.repo_id AND r.user_id=p.author_id AND r.updated=p.revision WHERE p.repo_id=? ORDER BY p.created DESC LIMIT 100", (repo['id'],)).fetchall()
        return jsonify(reports=[dict(item) for item in items if item['status'] in (None, 'hide')])

    @app.post('/api/seal/check')
    def check_seals():
        expected = app.config['SEAL_CRON_TOKEN']
        if not expected:
            abort(503, 'Seal checking is not configured.')
        authorization = request.headers.get('Authorization', '')
        if request.headers.get('Origin') != app.config['BASE_URL'] or not hmac.compare_digest(authorization, 'Bearer ' + expected) or not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), expected):
            abort(403, 'Invalid scheduler credential.')
        results = {'checked': 0, 'removed': 0, 'failed': 0, 'failures': []}
        active = db().execute('SELECT s.repo_id,r.full_name FROM seals s JOIN repositories r ON r.id=s.repo_id WHERE s.removed_at IS NULL').fetchall()
        db().commit()
        for item in active:
            try:
                repo = resolve_repo(item['full_name'], fresh=True)
                if repo['id'] != item['repo_id']:
                    raise ValueError('Repository identity changed.')
                response = retry_get('https://api.github.com/repos/' + repo['full_name'] + '/readme', headers={'Accept':'application/vnd.github+json', 'User-Agent':'community-feedback-service'}, timeout=(8, 15), allow_redirects=False, delay=0.25)
                if response.status_code == 200:
                    readme = response.json()
                    if readme.get('encoding') != 'base64' or type(readme.get('size')) is not int or readme['size'] > 1000000:
                        raise ValueError('README format not supported.')
                    content = base64.b64decode(''.join(readme['content'].split()), validate=True).decode('utf-8')
                elif response.status_code in (403, 429):
                    page = retry_get('https://github.com/' + repo['full_name'], headers={'User-Agent':'community-feedback-service'}, timeout=(8, 15), allow_redirects=False, delay=0.25)
                    if page.status_code != 200:
                        raise ValueError('Repository page could not be verified.')
                    metadata = RepositoryMetadata(); metadata.feed(page.text)
                    fields = metadata.values
                    revision = metadata.revision(repo['full_name'], repo['id'])
                    if (fields.get('octolytics-dimension-repository_public') != 'true' or fields.get('octolytics-dimension-repository_id') != str(repo['id'])
                            or fields.get('octolytics-dimension-repository_nwo', '').lower() != repo['full_name'].lower() or not revision):
                        raise ValueError('Repository revision could not be verified.')
                    raw = retry_get('https://raw.githubusercontent.com/' + repo['full_name'] + '/' + revision + '/README.md', timeout=(8, 15), allow_redirects=False, delay=0.25)
                    if raw.status_code != 200 or len(raw.content) > 1000000:
                        raise ValueError('README fallback could not be verified.')
                    content = raw.content.decode('utf-8')
                else:
                    raise ValueError('README HTTP ' + str(response.status_code))
                results['checked'] += 1
                if not contains_badge(content, repo['full_name']):
                    owner_ids = organization_owners(repo)
                    if owner_ids is None:
                        raise ValueError('Rating unavailable for seal removal.')
                    totals = rating_totals(repo, owner_ids)
                    removed_at = int(time.time())
                    result = db().execute('UPDATE seals SET removed_at=?,removed_rating=? WHERE repo_id=? AND removed_at IS NULL', (removed_at, float(totals['average']) if totals['average'] is not None else None, repo['id']))
                    if result.rowcount:
                        record('seal_removed', repo['id'], None, {'removed_at':removed_at,'rating':float(totals['average']) if totals['average'] is not None else None})
                    results['removed'] += result.rowcount
                    db().commit()
            except (requests.RequestException, ValueError, KeyError, UnicodeError, HTTPException) as error:
                db().rollback()
                results['failed'] += 1
                reason = str(error) if isinstance(error, ValueError) and str(error).startswith('README HTTP ') else type(error).__name__
                results['failures'].append({'repository': item['full_name'], 'reason': reason})
        return jsonify(results)

    @app.post('/api/moderate')
    def moderate():
        user = authenticated_write()
        repo = resolve_repo(repo_name(), fresh=True)
        if not is_moderator(user, repo):
            abort(403, 'Independent moderator access required.')
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get('action') not in ('hide', 'restore', 'dismiss') or data.get('reason') not in ('spam', 'harassment', 'personal_data', 'security_claim_no_evidence', 'no_violation') or not isinstance(data.get('report_id'), str):
            abort(400, 'Invalid moderation decision.')
        lock_for(repo['id'])
        report = db().execute('SELECT * FROM reports WHERE id=? AND repo_id=?', (data['report_id'], repo['id'])).fetchone()
        if report and user['id'] in (report['author_id'], report['reporter_id']):
            abort(403, 'Moderators cannot decide their own reports or reviews.')
        previous = db().execute('SELECT action FROM moderation_events WHERE report_id=? ORDER BY event_time DESC,id DESC LIMIT 1', (data['report_id'],)).fetchone()
        if not report or (data['action'] == 'restore' and (not previous or previous['action'] != 'hide')) or (data['action'] != 'restore' and previous):
            abort(409, 'Report not found or decision is not available.')
        current = db().execute('SELECT updated FROM reviews WHERE repo_id=? AND user_id=?', (repo['id'], report['author_id'])).fetchone()
        if data['action'] in ('hide', 'restore') and (not current or current['updated'] != report['revision']):
            abort(409, 'The review has changed since it was reported.')
        if (data['action'] in ('dismiss', 'restore')) != (data['reason'] == 'no_violation'):
            abort(400, 'Decision and reason do not match.')
        if data['action'] == 'hide' and data['reason'] not in ('spam', 'harassment', 'personal_data', 'security_claim_no_evidence'):
            abort(400, 'Select a specific violation before hiding a review.')
        event_time = time.time_ns()
        db().execute('INSERT INTO moderation_events VALUES (?,?,?,?,?,?,?,?,?)', (secrets.token_urlsafe(18), report['id'], repo['id'], report['author_id'], report['revision'], user['id'], data['action'], data['reason'], event_time))
        receipt = record('moderation', repo['id'], user['id'], {'author_id':str(report['author_id']),'revision':report['revision'],'action':data['action'],'reason':data['reason'],'event_time_ns':str(event_time)})
        db().commit()
        return jsonify(ok=True, receipt=receipt)

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
        repo = resolve_repo(repo_name(), fresh=True)
        owner_ids = organization_owners(repo)
        if owner_ids is None:
            abort(503, 'Feedback is temporarily unavailable: organization ownership cannot be verified.')
        if action in ('rating', 'review') and user['id'] in owner_ids:
            abort(403, 'Repository owners cannot rate or review their own projects.')
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
            concern = data.get('security_concern', False)
            evidence = data.get('evidence_url')
            if type(concern) is not bool or (concern and not valid_evidence(evidence, repo['full_name'])):
                abort(400, 'A security concern requires a file, line, issue, or commit link in this repository.')
            db().execute('INSERT INTO reviews VALUES (?,?,?,?) ON CONFLICT(repo_id,user_id) DO UPDATE SET body=excluded.body,updated=excluded.updated', (repo['id'], user['id'], value.strip(), now))
            db().execute('INSERT INTO security_concerns VALUES (?,?,?,?,?) ON CONFLICT(repo_id,author_id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,evidence_url=excluded.evidence_url', (repo['id'], user['id'], now, 1 if concern else 0, evidence if concern else None))
        start = limit['window_start'] if limit and now - limit['window_start'] < 3600 else now
        count = limit['count'] + 1 if limit and start == limit['window_start'] else 1
        db().execute('INSERT INTO write_limits VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET window_start=excluded.window_start,count=excluded.count', (user['id'], start, count))
        from journal import commitment
        value_data = {'rating':value} if action == 'rating' else {'body':value.strip(), 'security_concern':concern, 'evidence_url':evidence if concern else None}
        salt, value_hash = commitment(value_data)
        details = {'updated':now, 'value_hash':value_hash}
        if action == 'rating':
            details['public_rating'] = value
        else:
            details['public_salt'] = salt
        receipt = record(action, repo['id'], user['id'], details)
        receipt['salt'] = salt
        db().commit()
        return jsonify(ok=True, pending=not eligible(user), receipt=receipt)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.getenv('PORT', '8766')), debug=False)
