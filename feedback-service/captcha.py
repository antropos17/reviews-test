"""Optional Turnstile gate. Tokens and provider responses are never logged."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from flask import abort


def validate_token(token, secret, origin):
    if not isinstance(token, str) or not token.strip() or len(token) > 2048:
        abort(403, 'Complete the human verification before submitting.')
    try:
        response = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                                 data={'secret':secret, 'response':token}, timeout=(5, 10))
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        abort(503, 'Human verification is unavailable. Your change was not submitted. Try again later.')
    if not isinstance(result, dict):
        abort(503, 'Human verification is unavailable. Your change was not submitted.')
    try:
        issued = datetime.fromisoformat(result.get('challenge_ts', '').replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - issued).total_seconds()
        valid = (result.get('success') is True and result.get('action') == 'feedback'
                 and result.get('hostname', '').lower() == urlsplit(origin).hostname.lower()
                 and -30 <= age <= 300)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        abort(403, 'Human verification expired or was rejected. Please complete a new check.')
