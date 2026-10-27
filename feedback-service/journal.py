"""Signed append-only event chain. Signatures prove service-key possession, not user authorship."""
import base64
import hashlib
import json
import secrets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN = b'community-feedback-journal-v1\0'
GENESIS = '0' * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest_value(value, salt):
    return hashlib.sha256(b'community-feedback-value-v1\0' + base64.b64decode(salt, validate=True) + canonical(value).encode('utf-8')).hexdigest()


def commitment(value):
    salt = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
    return salt, digest_value(value, salt)


def private_key(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (TypeError, ValueError):
        raise ValueError('A valid Ed25519 journal key is required') from None


def public_key(encoded):
    key = private_key(encoded)
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode('ascii')


def append(connection, encoded, kind, repo_id, user_id, details, now, postgres=False):
    key = private_key(encoded)
    if postgres:
        connection.execute('SELECT pg_advisory_xact_lock(?)', (-7854061203148,))
    previous = connection.execute('SELECT seq,event_hash FROM journal_events ORDER BY seq DESC LIMIT 1').fetchone()
    event = {'version':1, 'seq':previous['seq'] + 1 if previous else 1,
             'previous':previous['event_hash'] if previous else GENESIS, 'kind':kind,
             'repo_id':str(repo_id), 'user_id':str(user_id) if user_id is not None else None,
             'time_ns':str(now), 'details':details}
    text = canonical(event)
    event_hash = hashlib.sha256(DOMAIN + text.encode('utf-8')).hexdigest()
    signature = base64.b64encode(key.sign(bytes.fromhex(event_hash))).decode('ascii')
    connection.execute('INSERT INTO journal_events VALUES (?,?,?,?)', (event['seq'], text, event_hash, signature))
    return {'event':event, 'hash':event_hash, 'signature':signature}


def verify(entries, encoded_public, previous_hash=GENESIS, next_seq=1):
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_public, validate=True))
        for entry in entries:
            event = entry['event']
            if event['seq'] != next_seq or event['previous'] != previous_hash or event['version'] != 1:
                raise ValueError('Journal sequence or previous hash mismatch')
            digest = hashlib.sha256(DOMAIN + canonical(event).encode('utf-8')).hexdigest()
            if digest != entry['hash']:
                raise ValueError('Journal hash mismatch')
            key.verify(base64.b64decode(entry['signature'], validate=True), bytes.fromhex(digest))
            previous_hash, next_seq = digest, next_seq + 1
    except Exception as error:
        raise ValueError('Journal verification failed') from error
    return previous_hash, next_seq
