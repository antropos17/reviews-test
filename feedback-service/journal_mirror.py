"""Verify and retain a separate local copy of a signed journal."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import requests
from journal import GENESIS, verify, digest_value


def load(path, public_key):
    if not path.exists():
        return [], GENESIS, 1
    with path.open(encoding='utf-8') as stream:
        header = json.loads(stream.readline())
        if header != {'format':1, 'public_key':public_key}:
            raise ValueError('Pinned key or mirror format changed')
        entries = [json.loads(line) for line in stream if line.strip()]
    head, next_seq = verify(entries, public_key)
    return entries, head, next_seq


def sync(url, path, public_key):
    origin = urlsplit(url)
    if origin.path not in ('', '/') or origin.query or origin.fragment or not origin.netloc or (origin.scheme != 'https' and origin.hostname not in ('localhost', '127.0.0.1')):
        raise ValueError('Use an HTTPS origin or localhost')
    entries, head, next_seq = load(path, public_key)
    while True:
        response = requests.get(url.rstrip('/') + '/api/journal', params={'after':next_seq-1}, timeout=20, allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if data.get('public_key') != public_key:
            raise ValueError('Remote public key differs from pinned key')
        remote_head = data.get('head')
        if remote_head:
            event = remote_head['event']
            verify([remote_head], public_key, event['previous'], event['seq'])
        if next_seq > 1 and (not remote_head or remote_head['event']['seq'] < next_seq - 1):
            raise ValueError('Remote journal is shorter than the local mirror')
        if remote_head and remote_head['event']['seq'] == next_seq - 1 and remote_head['hash'] != head:
            raise ValueError('Remote journal disagrees with the local mirror')
        batch = data['entries']
        if not batch:
            if remote_head and remote_head['event']['seq'] >= next_seq:
                raise ValueError('Remote journal withheld entries')
            break
        head, next_seq = verify(batch, public_key, head, next_seq)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(json.dumps({'format':1, 'public_key':public_key}, sort_keys=True) + '\n')
                stream.flush(); os.fsync(stream.fileno())
        with path.open('a', encoding='utf-8') as stream:
            for entry in batch:
                stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        entries.extend(batch)
    print('Verified mirrored events:', len(entries), 'head:', head)


def check_receipt(path, public_key, receipt_path, value_file=None):
    entries, _, _ = load(path, public_key)
    with Path(receipt_path).open(encoding='utf-8') as stream:
        receipt = json.load(stream)
    if receipt.get('public_key') != public_key:
        raise ValueError('Receipt key differs from pinned key')
    event = receipt['event']
    verify([receipt], public_key, event['previous'], event['seq'])
    index = event['seq'] - 1
    if index < 0 or index >= len(entries) or entries[index]['hash'] != receipt['hash']:
        raise ValueError('Receipt is not in the locally mirrored chain')
    if value_file:
        with Path(value_file).open(encoding='utf-8') as stream:
            value = json.load(stream)
        expected = event['details'].get('value_hash') or event['details'].get('body_hash')
        if not expected or digest_value(value, receipt['salt']) != expected:
            raise ValueError('Provided value does not match the receipt')
        print('Value commitment verified.')
    print('Receipt signature and local inclusion verified for event', event['seq'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('sync')
    download.add_argument('origin'); download.add_argument('mirror'); download.add_argument('public_key')
    check = commands.add_parser('verify-receipt')
    check.add_argument('mirror'); check.add_argument('public_key'); check.add_argument('receipt')
    check.add_argument('--value-file')
    args = parser.parse_args()
    if args.command == 'sync':
        sync(args.origin, Path(args.mirror), args.public_key)
    else:
        check_receipt(Path(args.mirror), args.public_key, args.receipt, args.value_file)
