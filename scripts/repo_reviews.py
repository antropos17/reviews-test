#!/usr/bin/env python3
"""Repository reviews. Python >= 3.10; standard library only.

Commands: init OWNER/REPO, sync, demo --out DIRECTORY.
Only trusted default-branch code runs; issue text is always data.
"""
from __future__ import annotations

import argparse
import base64
import copy
import html
import json
import os
from pathlib import Path
import re
import string
import sys
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / '.github/repo-reviews/config.json'
VERSION = '2.1.0'
API_VERSION = '2026-03-10'
MAX_TEXT = 4000
DISPLAY_COUNT = 3
LABELS = {
    'review': ('576b7c', 'A user review; closed issues remain open for comments.'),
    'hidden': ('64748b', 'Exclude the latest review from the published rating.'),
    'review:invalid': ('87613b', 'Edit the body: Rating must contain exactly 1–5.'),
}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def date(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def clean_text(value):
    # XML control characters, bidi overrides, and zero-width controls cannot forge UI.
    return ''.join(c for c in unicodedata.normalize('NFC', value)
                   if c in '\n\t' or not unicodedata.category(c).startswith('C'))


def parse_review(body):
    """Only the leading Rating section is authoritative; the rest is review text.

    Never search arbitrary review prose for another rating. GitHub serializes fields
    using their labels, not the YAML id. Changing labels needs a parser migration.
    """
    if not isinstance(body, str) or len(body) > 20000:
        raise ValueError('Invalid or oversized review body')
    body = body.replace('\r\n', '\n').strip()
    match = re.fullmatch(r'### Rating[ \t]*\n+([1-5])[ \t]*\n+### Review[ \t]*(?:\n([\s\S]*))?', body)
    if not match:
        raise ValueError('Expected Rating = one digit 1–5, followed by Review')
    review = (match.group(2) or '').strip()
    if review == '_No response_':
        review = ''
    if len(review) > MAX_TEXT:
        raise ValueError('Review text exceeds 4000 characters')
    return int(match.group(1)), clean_text(review)


def label_names(issue):
    return {x['name'] if isinstance(x, dict) else x for x in issue.get('labels', [])}


def is_review(issue):
    return not issue.get('pull_request') and (
        issue.get('title', '').startswith('[Review]') or 'review' in label_names(issue))


def order_key(entry):
    return (entry['created_at'], int(entry['number']))


def select_latest(issues, watermarks=None):
    """Pick newest-created issue per durable user id BEFORE filtering its content.

    Small persisted watermarks prevent deleted/renamed latest reviews from restoring
    older ratings. They contain ids/dates only, never hidden review text.
    """
    marks = copy.deepcopy(watermarks or {})
    selected = {}
    for issue in issues:
        user = issue.get('user') or {}
        if not is_review(issue) or user.get('type') != 'User' or not user.get('id'):
            continue
        uid = str(user['id'])
        candidate = {'number': issue['number'], 'created_at': issue['created_at']}
        if uid not in marks or order_key(candidate) >= order_key(marks[uid]):
            marks[uid] = candidate
            selected[uid] = issue
    # A later watermark can be encountered after an older issue in any API order.
    selected = {uid: issue for uid, issue in selected.items()
                if order_key(issue) == order_key(marks[uid])}
    return selected, marks


def aggregate(issues, profiles, now, min_age_days=7, watermarks=None, blocked=()):
    selected, marks = select_latest(issues, watermarks)
    blocked = {str(x) for x in blocked}
    stats = dict(count=0, average=None, histogram={str(i): 0 for i in range(1, 6)},
                 hidden=0, pending=0, invalid=0, withdrawn=len(marks) - len(selected))
    reviews = []
    for uid, issue in selected.items():
        labels = label_names(issue)
        if 'hidden' in labels or uid in blocked:
            stats['hidden'] += 1
            continue
        try:
            rating, review = parse_review(issue.get('body'))
        except ValueError:
            stats['invalid'] += 1
            continue
        if min_age_days:
            profile = profiles.get(uid)
            try:
                eligible = bool(profile) and date(profile['created_at']) <= now - timedelta(days=min_age_days)
            except (ValueError, KeyError, TypeError):
                eligible = False
            if not eligible:
                stats['pending'] += 1
                continue
        reviews.append({
            'user_id': int(uid), 'login': clean_text(issue['user']['login']),
            'number': int(issue['number']), 'created_at': issue['created_at'],
            'rating': rating, 'text': review,
            'comments': int(issue.get('comments', 0)),
        })
        stats['histogram'][str(rating)] += 1
    reviews.sort(key=order_key, reverse=True)
    stats['count'] = len(reviews)
    if reviews:
        stats['average'] = sum(r['rating'] for r in reviews) / len(reviews)
    return {'stats': stats, 'reviews': reviews, 'watermarks': marks}


class ApiError(RuntimeError):
    def __init__(self, status, method, path):
        self.status = status
        # Do not log bodies, credentials, or attacker-controlled API error messages.
        super().__init__(f'GitHub API {method} {path.split("?")[0]} returned HTTP {status}')


class API:
    def __init__(self, token, base='https://api.github.com', mutation_interval=1.05):
        self.base = base.rstrip('/')
        self.token = token
        self.calls = 0
        self.last_mutation = 0.0
        self.mutation_interval = mutation_interval

    def request(self, method, path, data=None, optional=False, raw=False):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('API paths must be relative to the trusted API origin')
        headers = {'Accept': 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json',
                   'X-GitHub-Api-Version': API_VERSION, 'User-Agent': f'repo-reviews/{VERSION}'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        payload = None if data is None else json.dumps(data).encode()
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        for attempt in range(3):
            if method != 'GET':
                delay = self.mutation_interval - (time.monotonic() - self.last_mutation)
                if delay > 0:
                    time.sleep(delay)
                self.last_mutation = time.monotonic()
            req = urllib.request.Request(self.base + path, data=payload, headers=headers, method=method)
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    content = response.read()
                    return content.decode('utf-8') if raw else (json.loads(content) if content else None)
            except urllib.error.HTTPError as error:
                if optional and error.code == 404:
                    return None
                # A failed snapshot must never be published as a partial rating.
                # Long rate-limit waits are left for the next scheduled/manual run.
                retry = error.headers.get('Retry-After')
                rate_limited = error.code in (403, 429) and (
                    retry or error.headers.get('X-RateLimit-Remaining') == '0' or error.code == 429)
                if attempt < 2 and (error.code >= 500 or rate_limited):
                    try:
                        seconds = int(retry) if retry else (2 ** (attempt + 1) if error.code >= 500 else 60)
                    except ValueError:
                        seconds = 60
                    if seconds <= 15:
                        time.sleep(max(1, seconds))
                        continue
                raise ApiError(error.code, method, path) from None
        raise RuntimeError('API retry exhaustion')

    def pages(self, path, **params):
        page = 1
        while True:
            query = urllib.parse.urlencode(dict(params, per_page=100, page=page))
            items = self.request('GET', f'{path}?{query}')
            if not isinstance(items, list):
                raise ValueError('Expected a paginated GitHub array')
            yield from items
            if len(items) < 100:
                break
            page += 1


def read_previous(api, prefix, branch, repo_id):
    ref = api.request('GET', f'{prefix}/git/ref/heads/{branch}', optional=True)
    if not ref:
        return None, {}
    sha = ref['object']['sha']
    raw = api.request('GET', f'{prefix}/contents/reviews.json?ref={sha}', raw=True, optional=True)
    if raw is None:
        raise ValueError('Data branch exists without reviews.json; choose an unused data_branch')
    prior = json.loads(raw)
    if prior.get('repository_id') != repo_id or prior.get('schema') != 1:
        raise ValueError('Snapshot belongs to another repository/schema; do not import upstream ratings')
    return sha, prior


def ensure_labels(api, prefix):
    names = {item['name'] for item in api.pages(f'{prefix}/labels')}
    for name, (color, description) in LABELS.items():
        if name not in names:
            api.request('POST', f'{prefix}/labels', {'name': name, 'color': color, 'description': description})


def reconcile_issues(api, prefix, issues, limit):
    changed = 0
    for issue in reversed(issues):
        if not is_review(issue) or (issue.get('user') or {}).get('type') != 'User':
            continue
        labels = label_names(issue)
        try:
            parse_review(issue.get('body'))
            valid = True
        except ValueError:
            valid = False
        additions = ([] if 'review' in labels else ['review'])
        if not valid and 'review:invalid' not in labels:
            additions.append('review:invalid')
        close = valid and issue.get('state') != 'closed'
        remove_invalid = valid and 'review:invalid' in labels
        if not (additions or close or remove_invalid):
            continue
        if changed >= limit:
            break
        changed += 1
        if additions:
            api.request('POST', f'{prefix}/issues/{issue["number"]}/labels', {'labels': additions})
        if remove_invalid:
            encoded = urllib.parse.quote('review:invalid', safe='')
            api.request('DELETE', f'{prefix}/issues/{issue["number"]}/labels/{encoded}', optional=True)
        if close:
            api.request('PATCH', f'{prefix}/issues/{issue["number"]}', {'state': 'closed', 'state_reason': 'completed'})


def get_profiles(api, selected, previous, cfg):
    # Cache only account creation dates. No per-run follower/repo enumeration.
    profiles = copy.deepcopy(previous.get('profiles', {}))
    budget = cfg['max_profile_lookups']
    if not cfg['min_account_age_days']:
        return profiles
    for uid, issue in selected.items():
        if uid in profiles or 'hidden' in label_names(issue):
            continue
        try:
            parse_review(issue.get('body'))
        except ValueError:
            continue
        if budget == 0:
            break
        budget -= 1
        # ID endpoint avoids login rename races (documented in the current REST API).
        profile = api.request('GET', f'/user/{int(uid)}', optional=True)
        if profile and str(profile.get('id')) == uid and profile.get('created_at'):
            profiles[uid] = {'created_at': profile['created_at']}
    return profiles


def attach_replies(api, prefix, reviews):
    permissions = {}
    permission_budget = 10
    for review in reviews[:DISPLAY_COUNT]:
        if not review['comments']:
            continue
        # Bound both reads and authorization lookups on attacker-writable threads.
        # Read the newest two pages; older replies stay available in the issue.
        last_page = (review['comments'] + 99) // 100
        comments = []
        for page in range(last_page, max(0, last_page - 2), -1):
            chunk = api.request('GET', f'{prefix}/issues/{review["number"]}/comments?per_page=100&page={page}')
            comments = chunk + comments
        if last_page > 2:
            review['reply_scan_limited'] = True
        for comment in reversed(comments):
            body = comment.get('body') or ''
            if not body.startswith('/reply ') or not body[7:].strip():
                continue
            user = comment.get('user') or {}
            if user.get('type') != 'User' or not user.get('login'):
                continue
            uid = str(user['id'])
            if uid not in permissions:
                if permission_budget == 0:
                    review['reply_scan_limited'] = True
                    continue
                permission_budget -= 1
                login = urllib.parse.quote(user['login'], safe='')
                try:
                    result = api.request('GET', f'{prefix}/collaborators/{login}/permission', optional=True)
                except ApiError as error:
                    if error.status != 403:
                        raise
                    result = None
                permissions[uid] = bool(result and result.get('permission') in {'admin', 'write'}
                                        and str((result.get('user') or {}).get('id')) == uid)
            if permissions[uid]:
                review['reply'] = {'login': clean_text(user['login']), 'comment_id': int(comment['id']),
                                   'text': clean_text(body[7:].strip())[:MAX_TEXT]}
                break


def text_line(value):
    value = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', value)
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    return ' '.join(clean_text(value).split())


def wrapped(value, width=68, limit=2):
    lines = textwrap.wrap(text_line(value), width=width, break_long_words=True, break_on_hyphens=False) or ['']
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1][:max(1, width-1)].rstrip() + '…'
    return lines


def card_svg(snapshot, dark=False):
    stats = snapshot['stats']
    rows = snapshot['reviews'][:DISPLAY_COUNT]
    height = (295 if rows else 325) + sum(147 if 'reply' in r else 112 for r in rows)
    palette = dict(bg='#0d1117', fg='#f0f3f6', muted='#a3acb7', line='#30363d',
                   track='#242b33', accent='#d1a94e') if dark else dict(
                   bg='#ffffff', fg='#17212b', muted='#536171', line='#d8dee5',
                   track='#edf0f3', accent='#87631d')
    p = palette
    s = stats
    avg = '—' if s['average'] is None else str(Decimal(str(s['average'])).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
    title = f'Reviews: {avg} out of 5, {s["count"]} ratings'
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}" role="img" aria-labelledby="title desc">',
              f'<title id="title">{html.escape(title)}</title>',
              '<desc id="desc">Average rating, rating distribution, and recent reviews. Open the text version for full details.</desc>',
              f'<rect x="0.5" y="0.5" width="759" height="{height-1}" rx="16" fill="{p["bg"]}" stroke="{p["line"]}"/>',
              '<g font-family="DejaVu Sans,Arial,sans-serif">']

    def text(x, y, value, size=14, color=None, weight='400'):
        output.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color or p["fg"]}">{html.escape(str(value))}</text>')

    text(28, 37, 'Community reviews', 20, weight='700')
    text(28, 60, wrapped(snapshot['repository'], width=77, limit=1)[0], 13, p['muted'])
    text(28, 130, avg, 55, weight='700')
    text(145, 128, '/ 5', 22, p['muted'])
    text(28, 160, f'{s["count"]} ratings · one account, one vote', 13, p['muted'])
    for i, rating in enumerate(range(5, 0, -1)):
        y = 85 + i * 21
        n = s['histogram'][str(rating)]
        text(434, y + 4, f'{rating}', 12, p['muted'])
        output.append(f'<rect x="455" y="{y-6}" width="224" height="9" rx="4.5" fill="{p["track"]}"/>')
        if n:
            width = max(3, round(224 * n / max(s['histogram'].values()), 2))
            output.append(f'<rect x="455" y="{y-6}" width="{width}" height="9" rx="4.5" fill="{p["accent"]}"/>')
        text(692, y + 4, n, 12, p['muted'])
    text(28, 204, f'Pending: {s["pending"]}   ·   Hidden: {s["hidden"]}   ·   Invalid: {s["invalid"]}', 12, p['muted'])
    text(28, 227, 'Simple average. Eligible accounts have equal weight.', 12, p['muted'])
    output.append(f'<path d="M28 245H732" stroke="{p["line"]}"/>')
    y = 271
    if not rows:
        text(28, y, 'The first rating will appear here.', 14, p['muted'])
    for row in rows:
        text(28, y, f'@{row["login"]}', 14, weight='700')
        text(487, y, f'{row["rating"]} / 5  ·  #{row["number"]}', 13, p['accent'], '700')
        for j, line in enumerate(wrapped(row['text'] or 'Rating without a review')):
            text(28, y + 25 + 19*j, line, 13)
        text(28, y + 68, f'{row["created_at"][:10]}  ·  Comments: {row["comments"]}', 11, p['muted'])
        if row.get('reply'):
            response = wrapped(row['reply']['text'], width=65, limit=1)[0]
            text(28, y + 95, 'Developer reply: ' + response, 12, p['muted'])
            y += 35
        y += 112
    # Timestamp is snapshot time, not a claim about browser cache freshness.
    text(28, height - 16, 'Updated: ' + snapshot['updated_at'].replace('T', ' ').replace('Z', ' UTC'), 10, p['muted'])
    output.append('</g></svg>\n')
    return '\n'.join(output)


def escaped_markdown(value):
    # Escape every punctuation character; preserve text, disable links, images,
    # HTML, mentions and forged headings in the generated data-branch README.
    value = clean_text(value)
    return ''.join(f'&#{ord(c)};' if c in string.punctuation else c for c in value)


def branch_readme(snapshot):
    s = snapshot['stats']
    repo = snapshot['repository']
    base = f'https://github.com/{repo}'
    avg = '—' if s['average'] is None else f'{s["average"]:.2f}'
    parts = [f'# Reviews · {repo}', '', f'Average: **{avg} / 5**. Ratings: **{s["count"]}**.',
             '', f'Updated: {snapshot["updated_at"]}. Snapshot time; cached images may lag.', '',
             f'Pending: {s["pending"]}. Hidden: {s["hidden"]}. Invalid: {s["invalid"]}.', '',
             'Each eligible GitHub account has one equally weighted vote. The latest submission replaces earlier ones.',
             f'Accounts younger than {snapshot["min_account_age_days"]} days wait until eligible; no approval label bypasses this rule.',
             'Maintainers can hide reviews or block account IDs; repository owners control the code and can change these rules. Multiple accounts can evade these checks.', '',
             '| Rating | Votes |', '| --- | --- |']
    parts.extend(f'| {i} / 5 | {s["histogram"][str(i)]} |' for i in range(5, 0, -1))
    parts += ['', '## Recent reviews', '']
    for review in snapshot['reviews'][:10]:
        parts += [f'### Review {review["number"]}', '',
                  f'**{review["rating"]} / 5** · @{escaped_markdown(review["login"])} · {review["created_at"][:10]}', '',
                  escaped_markdown(review['text']) or 'Rating without a review.', '',
                  f'[Discussion #{review["number"]} · comments {review["comments"]}]({base}/issues/{review["number"]})', '']
        if review.get('reply'):
            reply = review['reply']
            parts += ['**Developer reply**', '', escaped_markdown(reply['text']), '',
                      f'[Original reply]({base}/issues/{review["number"]}#issuecomment-{reply["comment_id"]})', '']
        if review.get('reply_scan_limited'):
            parts += ['Only part of this discussion was scanned. Open the issue for the full thread.', '']
    parts += ['## Counted ratings', '', 'Latest 300 ratings; the full list is in JSON.', '',
              '| Author | Rating | Source |', '| --- | --- | --- |']
    parts.extend(f'| @{escaped_markdown(r["login"])} | {r["rating"]} / 5 | [#{r["number"]}]({base}/issues/{r["number"]}) |'
                 for r in snapshot['reviews'][:300])
    parts += ['', '[JSON data](reviews.json)', '',
              'Full discussions are in Issues. The card shows excerpts.', '']
    return '\n'.join(parts)


def render_files(snapshot):
    return {'reviews.json': json_text(snapshot), 'card-light.svg': card_svg(snapshot),
            'card-dark.svg': card_svg(snapshot, True), 'README.md': branch_readme(snapshot)}


def write_files(directory, files):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


def publish(api, prefix, branch, parent, files):
    # No data-branch checkout or code execution. A single commit contains all files.
    tree = api.request('POST', f'{prefix}/git/trees', {'tree': [
        {'path': name, 'mode': '100644', 'type': 'blob', 'content': content}
        for name, content in files.items()]})
    commit = api.request('POST', f'{prefix}/git/commits', {
        'message': 'Update repository reviews', 'tree': tree['sha'],
        'parents': [parent] if parent else []})
    if parent:
        # Never force-push. Concurrent manual changes cause a clean failure.
        api.request('PATCH', f'{prefix}/git/refs/heads/{branch}', {'sha': commit['sha'], 'force': False})
    else:
        api.request('POST', f'{prefix}/git/refs', {'ref': f'refs/heads/{branch}', 'sha': commit['sha']})
    return commit['sha']


def validate_config(cfg):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', cfg['repository']):
        raise ValueError('repository must be OWNER/REPO')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', cfg['data_branch']):
        raise ValueError('Use a simple dedicated data_branch, such as reviews')
    for field, maximum in [('min_account_age_days', 365), ('max_profile_lookups', 100), ('max_issue_updates', 100)]:
        if type(cfg[field]) is not int or not 0 <= cfg[field] <= maximum:
            raise ValueError(f'Invalid config field: {field}')
    if any(type(uid) is not int or uid <= 0 for uid in cfg['blocked_user_ids']):
        raise ValueError('blocked_user_ids must contain positive numeric IDs')


def sync(cfg, api, out=None):
    validate_config(cfg)
    repo = os.getenv('GITHUB_REPOSITORY', cfg['repository'])
    if repo.casefold() != cfg['repository'].casefold():
        raise ValueError('Repository identity mismatch: run init for this fork/repository')
    prefix = f'/repos/{repo}'
    info = api.request('GET', prefix)
    if not info.get('has_issues'):
        raise ValueError('Issues are disabled. Enable Issues for this MVP; a Discussions adapter is not included.')
    if cfg['data_branch'] == info['default_branch']:
        raise ValueError('The data branch must differ from the default branch')
    head, previous = read_previous(api, prefix, cfg['data_branch'], info['id'])
    issues = list(api.pages(f'{prefix}/issues', state='all', sort='created', direction='asc'))
    # Do not publish until the COMPLETE listing succeeded. Then perform bounded writes.
    ensure_labels(api, prefix)
    reconcile_issues(api, prefix, issues, cfg['max_issue_updates'])
    selected, _ = select_latest(issues, previous.get('watermarks'))
    profiles = get_profiles(api, selected, previous, cfg)
    result = aggregate(issues, profiles, utcnow(), cfg['min_account_age_days'],
                       previous.get('watermarks'), cfg['blocked_user_ids'])
    attach_replies(api, prefix, result['reviews'])
    snapshot = dict(result, schema=1, generator=VERSION, repository=repo,
                    repository_id=info['id'], min_account_age_days=cfg['min_account_age_days'], profiles=profiles)
    old_data = {k: v for k, v in previous.items() if k != 'updated_at'}
    if old_data == snapshot:
        update_readme_card(api, prefix, info['default_branch'], repo, cfg['data_branch'], head)
        print(f'No data changes; no commit. API calls: {api.calls}')
        if out:
            write_files(out, render_files(previous))
        return previous
    snapshot['updated_at'] = stamp(utcnow())
    files = render_files(snapshot)
    if out:
        write_files(out, files)
    sha = publish(api, prefix, cfg['data_branch'], head, files)
    update_readme_card(api, prefix, info['default_branch'], repo, cfg['data_branch'], sha)
    print(f'Published {snapshot["stats"]["count"]} ratings to {cfg["data_branch"]} at {sha[:12]}; API calls: {api.calls}')
    return snapshot


def button_svg(n):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="58" height="42" viewBox="0 0 58 42" role="img" aria-label="Rate {n} out of 5">
<rect x=".5" y=".5" width="57" height="41" rx="9" fill="#f6f8fa" stroke="#c7ced6"/>
<text x="13" y="27" font-family="Arial,sans-serif" font-size="17" font-weight="700" fill="#17212b">{n}</text>
<path d="M38 10l3.1 6.5 7.2 1-5.2 5.1 1.2 7.2L38 26.4l-6.3 3.4 1.2-7.2-5.2-5.1 7.2-1z" fill="#87631d"/>
</svg>\n'''


def readme_block(repo, branch='reviews', card_sha=None):
    base = f'https://github.com/{repo}'
    card_base = f'https://raw.githubusercontent.com/{repo}/{card_sha}' if card_sha else f'/../{branch}'
    min_age = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))['min_account_age_days']
    lines = ['<!-- repo-reviews:start -->', '## Community feedback', '', '<p>']
    for n in range(1, 6):
        query = urllib.parse.urlencode({'title': '[Review] My experience', 'body': f'### Rating\n\n{n}\n\n### Review\n\n'})
        lines.append(f'  <a href="{base}/issues/new?{html.escape(query, quote=True)}"><img src="/.github/repo-reviews/buttons/{n}.svg" width="58" height="42" alt="Rate {n} out of 5" /></a>')
    lines += ['</p>', '', f'<a href="{base}/blob/{branch}/README.md">', '<picture>',
              f'  <source media="(prefers-color-scheme: dark)" srcset="{card_base}/card-dark.svg" />',
              f'  <source media="(prefers-color-scheme: light)" srcset="{card_base}/card-light.svg" />',
              f'  <img alt="Rating and recent reviews; open the accessible text version" src="{card_base}/card-light.svg" width="760" />',
              '</picture>', '</a>', '',
              f'[All feedback]({base}/blob/{branch}/README.md) · [Update status]({base}/actions/workflows/reviews.yml)', '',
              '<details>', '<summary>How ratings work</summary>', '',
              'One vote per GitHub user ID. A new submission replaces the previous one; rating text is optional.', '',
              f'Accounts must be at least {min_age} days old. Newer or unverified accounts wait until eligible; approval labels do not bypass this rule. Bots and pull requests are excluded.', '',
              'The score is the simple average of eligible ratings. Hidden, blocked, invalid, and pending entries are excluded; the owner can hide reviews and block account IDs.', '',
              'This is a self-hosted system: the repository owner can change its code and settings. It cannot identify multiple accounts belonging to the same person.', '',
              f'[Source and settings]({base}/tree/main/.github/repo-reviews) · [Rating code]({base}/blob/main/scripts/repo_reviews.py) · [Data and history]({base}/commits/{branch}/)', '',
              'Updates follow GitHub Actions and may be delayed.', '', '</details>', '<!-- repo-reviews:end -->', '']
    return '\n'.join(lines)


def update_readme_card(api, prefix, default_branch, repo, data_branch, card_sha):
    """Update only the managed block, using the current blob SHA to reject races."""
    if not card_sha or not re.fullmatch(r'[0-9a-f]{40}', card_sha):
        raise ValueError('Missing or invalid snapshot commit')
    ref = urllib.parse.quote(default_branch, safe='')
    for path in ('.github/README.md', 'README.md', 'docs/README.md'):
        record = api.request('GET', f'{prefix}/contents/{path}?ref={ref}', optional=True)
        if record is not None:
            break
    else:
        raise ValueError('README not found; snapshot was published but README was not updated')
    if record.get('encoding') != 'base64' or not record.get('sha'):
        raise ValueError('README cannot be updated safely')
    current = base64.b64decode(record['content']).decode('utf-8')
    block = readme_block(repo, data_branch, card_sha)
    updated, count = re.subn(r'<!-- repo-reviews:start -->[\s\S]*?<!-- repo-reviews:end -->\n?', lambda _: block, current)
    if count != 1:
        raise ValueError('Expected exactly one managed README block')
    if updated != current:
        api.request('PUT', f'{prefix}/contents/{path}', {
            'message': 'Refresh review card snapshot', 'sha': record['sha'],
            'branch': default_branch, 'content': base64.b64encode(updated.encode('utf-8')).decode('ascii')})
        print(f'Updated {path} to snapshot {card_sha[:12]}')


def init(repo):
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg['repository'] = repo
    validate_config(cfg)
    CONFIG_PATH.write_text(json_text(cfg), encoding='utf-8')
    for n in range(1, 6):
        (ROOT / f'.github/repo-reviews/buttons/{n}.svg').write_text(button_svg(n), encoding='utf-8')
    block = readme_block(repo, cfg['data_branch'])
    # Follow GitHub's documented precedence for Markdown README locations.
    candidates = [ROOT / '.github/README.md', ROOT / 'README.md', ROOT / 'docs/README.md']
    readme = next((path for path in candidates if path.exists()), ROOT / 'README.md')
    current = readme.read_text(encoding='utf-8') if readme.exists() else f'# {repo.split("/")[-1]}\n'
    if '<!-- repo-reviews:start -->' in current:
        current, count = re.subn(r'<!-- repo-reviews:start -->[\s\S]*?<!-- repo-reviews:end -->\n?', lambda _: block, current)
        if count != 1:
            raise ValueError('Expected exactly one managed README block')
    else:
        current = current.rstrip() + '\n\n' + block
    readme.write_text(current, encoding='utf-8')
    (ROOT / 'README-BLOCK.md').write_text(block, encoding='utf-8')
    print('Configured repository and README. Commit the files, set REPO_REVIEWS_ENABLED=true, then run the workflow.')


def demo(out):
    """Offline executable example, with explicit synthetic data."""
    now = date('2026-10-27T12:00:00Z')
    values = [('mira-dev', 5, 'Установка заняла пару минут. Наконец видно, что думают пользователи проекта.'),
              ('denis-code', 4, 'Работает стабильно. Хотелось бы больше примеров конфигурации.'),
              ('lea-builds', 5, 'Редактирование оценки сохранило обсуждение. Это удобно.'),
              ('alex-data', 3, 'Хорошая основа, жду следующую версию.')]
    issues = []
    for i, (login, rating, review) in enumerate(values):
        issues.append(dict(number=104-i, title='[Review] My experience', labels=['review'], comments=2 if i == 0 else i,
                           created_at=f'2026-10-{27-i:02}T08:00:00Z', body=f'### Rating\n\n{rating}\n\n### Review\n\n{review}',
                           user={'id': 100+i, 'login': login, 'type': 'User'}))
    profiles = {str(100+i): {'created_at': '2020-01-01T00:00:00Z'} for i in range(4)}
    result = aggregate(issues, profiles, now)
    result['reviews'][0]['reply'] = {'login': 'maintainer', 'comment_id': 42, 'text': 'Спасибо! Добавили короткую инструкцию в README.'}
    snapshot = dict(result, schema=1, generator=VERSION, repository='example/project', repository_id=1,
                    min_account_age_days=7, profiles=profiles, updated_at=stamp(now))
    write_files(out, render_files(snapshot))
    print(f'Synthetic demonstration written to {out}; {result["stats"]["count"]} ratings, mean {result["stats"]["average"]:.2f}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init').add_argument('repository')
    sub.add_parser('sync').add_argument('--out', type=Path)
    sub.add_parser('demo').add_argument('--out', type=Path, default=ROOT / 'demo')
    args = parser.parse_args()
    if args.command == 'init':
        init(args.repository)
    elif args.command == 'demo':
        demo(args.out)
    else:
        token = os.getenv('GH_TOKEN')
        if not token:
            raise ValueError('GH_TOKEN is required; the workflow supplies GITHUB_TOKEN automatically')
        cfg = json.loads(CONFIG_PATH.read_text())
        sync(cfg, API(token, os.getenv('GITHUB_API_URL', 'https://api.github.com')), args.out)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
