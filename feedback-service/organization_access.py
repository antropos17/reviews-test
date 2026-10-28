"""Verify organization owners using an installed, read-only GitHub App."""
import base64
import json
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class OrganizationUnavailable(Exception):
    pass


def _encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _jwt(app_id, key):
    try:
        now = int(time.time())
        head = _encoded(b'{"alg":"RS256","typ":"JWT"}')
        payload = _encoded(json.dumps({'iat':now-60, 'exp':now+540, 'iss':str(app_id)}, separators=(',', ':')).encode())
        message = (head + '.' + payload).encode('ascii')
        private = serialization.load_pem_private_key(key.encode(), password=None)
        return message.decode('ascii') + '.' + _encoded(private.sign(message, padding.PKCS1v15(), hashes.SHA256()))
    except (ValueError, TypeError, AttributeError):
        raise OrganizationUnavailable('GitHub App configuration is invalid') from None


def owners(name, organization_id, app_id, private_key):
    if not app_id or not private_key:
        raise OrganizationUnavailable('Organization verification is not configured')
    jwt = _jwt(app_id, private_key)
    headers = {'Accept':'application/vnd.github+json', 'User-Agent':'community-feedback-service',
               'X-GitHub-Api-Version':'2022-11-28', 'Authorization':'Bearer ' + jwt}
    origin = 'https://api.github.com'
    try:
        response = requests.get(origin + '/orgs/' + name + '/installation', headers=headers, timeout=8, allow_redirects=False)
        response.raise_for_status()
        installation = response.json()
        account = installation.get('account') or {}
        if (type(installation.get('id')) is not int or account.get('id') != organization_id
                or account.get('type') != 'Organization' or str(account.get('login', '')).lower() != name.lower()
                or (installation.get('permissions') or {}).get('members') != 'read'
                or installation.get('suspended_at') is not None):
            raise OrganizationUnavailable('Organization installation cannot be verified')
        response = requests.post(origin + '/app/installations/' + str(installation['id']) + '/access_tokens',
                                 headers=headers, json={'permissions':{'members':'read'}}, timeout=8, allow_redirects=False)
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get('token')
        if not isinstance(token, str) or not token or (token_data.get('permissions') or {}).get('members') != 'read':
            raise OrganizationUnavailable('Organization access cannot be verified')
        headers['Authorization'] = 'Bearer ' + token
        ids = set()
        for page in range(1, 51):
            response = requests.get(origin + '/orgs/' + name + '/members', headers=headers,
                                    params={'role':'admin', 'per_page':100, 'page':page}, timeout=8, allow_redirects=False)
            response.raise_for_status()
            members = response.json()
            if not isinstance(members, list) or any(not isinstance(m, dict) or type(m.get('id')) is not int or m.get('type') != 'User' for m in members):
                raise OrganizationUnavailable('Organization owners could not be verified')
            ids.update(m['id'] for m in members)
            if len(members) < 100:
                if not ids:
                    raise OrganizationUnavailable('Organization owners could not be verified')
                return ids
        raise OrganizationUnavailable('Organization owner list is incomplete')
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise OrganizationUnavailable('GitHub organization verification is unavailable') from None
