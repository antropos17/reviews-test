"""Create and validate a minimal journal checkpoint for external witnessing."""
import argparse
import json
from pathlib import Path
from journal import GENESIS
from journal_mirror import load


def create(path, checkpoint, key):
    if not path.exists():
        path.write_text(json.dumps({'format':1, 'public_key':key}, sort_keys=True) + '\n', encoding='utf-8')
    entries, head, _ = load(path, key)
    data = {'format':1, 'public_key':key, 'sequence':len(entries), 'head':head}
    checkpoint.write_text(json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')


def check(path, checkpoint, key):
    entries, head, _ = load(path, key)
    data = json.loads(checkpoint.read_text(encoding='utf-8'))
    if data != {'format':1, 'public_key':key, 'sequence':len(entries), 'head':head}:
        raise ValueError('Checkpoint does not match the verified journal')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['create','verify'])
    parser.add_argument('journal', type=Path); parser.add_argument('checkpoint', type=Path); parser.add_argument('public_key')
    args = parser.parse_args()
    (create if args.operation == 'create' else check)(args.journal,args.checkpoint,args.public_key)
