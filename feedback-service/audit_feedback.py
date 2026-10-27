"""Recompute feedback from a separately retained, verified journal.

A mismatch is an alert, not proof of fraud: legacy unsigned data, rate limits,
concurrent writes, and a service presenting different views are possible.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import requests
from journal import digest_value
from journal_mirror import load, sync


class AuditUnavailable(ValueError):
    pass


def audit(entries, repo_id, owner_id, ages, feedback, now=None):
    now = now or datetime.now(timezone.utc)
    ratings, reviews, decisions = {}, {}, {}
    for envelope in entries:
        event = envelope['event']
        if event['repo_id'] != str(repo_id):
            continue
        kind, user, details = event['kind'], event['user_id'], event['details']
        if kind == 'rating':
            value = details.get('public_rating')
            if type(value) is not int or not 1 <= value <= 5:
                raise AuditUnavailable('Legacy or malformed rating event cannot be audited')
            ratings[user] = value
        elif kind == 'review':
            if not isinstance(details.get('public_salt'), str):
                raise AuditUnavailable('Legacy review event has no public verification salt')
            reviews[user] = details
        elif kind == 'moderation' and details.get('action') in ('hide', 'restore'):
            decisions[(details['author_id'], details['revision'])] = details['action']
    def eligible(user):
        if user not in ages:
            raise AuditUnavailable('GitHub account identity or age is unavailable')
        return ages[user] <= now - timedelta(days=30)
    visible = {u: d for u, d in reviews.items() if eligible(u) and decisions.get((u,d['updated'])) != 'hide'}
    included = [value for user, value in ratings.items() if user != str(owner_id) and eligible(user)
                and not (user in reviews and decisions.get((user, reviews[user]['updated'])) == 'hide')]
    count = len(included)
    expected = sum(included) / count if count else None
    if feedback['count'] != count or ((expected is None) != (feedback['average'] is None)) or (expected is not None and abs(feedback['average'] - expected) > 1e-9):
        raise AuditUnavailable('Displayed rating differs from journal or includes unsigned legacy data')
    if len(visible) > 50 or len(feedback['reviews']) >= 50:
        raise AuditUnavailable('The public API truncates reviews; a complete review audit is unavailable')
    actual = {str(item['user_id']): item for item in feedback['reviews']}
    if len(actual) != len(feedback['reviews']) or set(actual) != set(visible):
        raise AuditUnavailable('Displayed reviews differ from journal or include unsigned legacy data')
    for user, details in visible.items():
        review = actual[user]
        evidence = review.get('evidence_url')
        value = {'body':review['body'], 'security_concern':bool(evidence), 'evidence_url':evidence}
        if review['updated'] != details['updated'] or digest_value(value, details['public_salt']) != details['value_hash']:
            raise AuditUnavailable('A displayed review differs from its signed event')
    return {'ratings':count, 'reviews':len(visible), 'average':expected}


def fetch_json(url, params=None):
    response = requests.get(url, params=params, headers={'Accept':'application/vnd.github+json', 'User-Agent':'community-feedback-independent-auditor'}, timeout=20, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def run(origin, repo, mirror, key):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo):
        raise AuditUnavailable('Invalid repository')
    sync(origin, mirror, key)
    entries, _, _ = load(mirror, key)
    metadata = fetch_json('https://api.github.com/repos/' + repo)
    if metadata.get('private') is not False or not isinstance(metadata.get('id'), int):
        raise AuditUnavailable('GitHub repository identity is unavailable')
    users = {e['event']['user_id'] for e in entries if e['event']['repo_id'] == str(metadata['id']) and e['event']['kind'] in ('rating','review')}
    ages = {}
    for user in users:
        if not isinstance(user, str) or not user.isascii() or not user.isdecimal():
            raise AuditUnavailable('Invalid journal user ID')
        profile = fetch_json('https://api.github.com/user/' + user)
        if str(profile.get('id')) != user or profile.get('type') != 'User':
            raise AuditUnavailable('GitHub account identity is unavailable')
        ages[user] = datetime.fromisoformat(profile['created_at'].replace('Z','+00:00'))
    feedback = fetch_json(origin.rstrip('/') + '/api/feedback', {'repo':repo})
    if feedback.get('repository', '').lower() != repo.lower():
        raise AuditUnavailable('Service returned a different repository')
    result = audit(entries, metadata['id'], metadata['owner']['id'], ages, feedback)
    print('Journal and public feedback match:', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin'); parser.add_argument('repo'); parser.add_argument('mirror'); parser.add_argument('public_key')
    parser.add_argument('--accept-unverified-baseline', action='store_true', help='Run a limited check even though historic feedback and journal completeness are not independently established')
    args = parser.parse_args()
    if not args.accept_unverified_baseline:
        raise AuditUnavailable('No independently verified baseline is configured; this check cannot certify completeness')
    run(args.origin, args.repo, Path(args.mirror), args.public_key)
