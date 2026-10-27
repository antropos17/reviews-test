"""Transfer or export feedback without session, CSRF, or OAuth state data."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

TABLES = {
    'users': ('id', 'login', 'created_at'),
    'repositories': ('id', 'full_name'),
    'ratings': ('repo_id', 'user_id', 'rating', 'updated'),
    'reviews': ('repo_id', 'user_id', 'body', 'updated'),
}
BACKUP_TABLES = {
    **TABLES,
    'reports': ('id', 'repo_id', 'author_id', 'revision', 'reporter_id', 'reason', 'created'),
    'moderation_events': ('id', 'report_id', 'repo_id', 'author_id', 'revision', 'moderator_id', 'action', 'reason', 'event_time'),
    'owner_replies': ('repo_id', 'author_id', 'owner_id', 'body', 'updated'),
    'seals': ('repo_id', 'activated_at', 'removed_at', 'removed_rating', 'activated_by'),
    'security_concerns': ('repo_id', 'author_id', 'revision', 'enabled', 'evidence_url'),
}


def rows(connection, sqlite=False, tables=None):
    result = {}
    for table, columns in (tables or TABLES).items():
        prefix = '' if sqlite else 'feedback_private.'
        order = ', '.join(columns[:2] if table in ('ratings', 'reviews') else columns[:1])
        query = f'SELECT {", ".join(columns)} FROM {prefix}{table} ORDER BY {order}'
        result[table] = [dict(row) for row in connection.execute(query).fetchall()]
    return result


def connect():
    url = os.environ.get('DATABASE_URL')
    if not url or not url.startswith(('postgres://', 'postgresql://')):
        raise ValueError('A PostgreSQL DATABASE_URL is required')
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)


def migrate(source_path):
    source = Path(source_path).resolve(strict=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as sqlite:
        sqlite.row_factory = sqlite3.Row
        sqlite.execute('BEGIN')
        original = rows(sqlite, sqlite=True)
        with connect() as target:
            # Refuse to overwrite any existing feedback. The whole import is atomic.
            target.execute('LOCK TABLE feedback_private.users, feedback_private.repositories, feedback_private.ratings, feedback_private.reviews IN ACCESS EXCLUSIVE MODE')
            if any(rows(target)[name] for name in TABLES):
                raise ValueError('Destination is not empty; import aborted without overwriting it')
            for table, columns in TABLES.items():
                query = f'INSERT INTO feedback_private.{table} ({", ".join(columns)}) VALUES ({", ".join(["%s"] * len(columns))})'
                for row in original[table]:
                    target.execute(query, [row[column] for column in columns])
            copied = rows(target)
            if copied != original:
                raise ValueError('Readback did not match the source; import rolled back')
        print('Imported and verified:', ', '.join(f'{name}={len(original[name])}' for name in TABLES))


def backup(destination):
    path = Path(destination)
    with connect() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = {'schema': 2, 'tables': rows(connection, tables=BACKUP_TABLES)}
    # Exclusive creation avoids accidentally replacing a prior backup.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(snapshot, output, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        output.flush()
        os.fsync(output.fileno())
    with path.open(encoding='utf-8') as source:
        if json.load(source) != snapshot:
            raise ValueError('Backup readback failed')
    print('Backup written and verified:', ', '.join(f'{name}={len(snapshot["tables"][name])}' for name in BACKUP_TABLES))


def restore(source):
    with Path(source).open(encoding='utf-8') as file:
        snapshot = json.load(file)
    if snapshot.get('schema') != 2 or set(snapshot.get('tables', {})) != set(BACKUP_TABLES):
        raise ValueError('Unsupported backup format')
    data = snapshot['tables']
    for table, columns in BACKUP_TABLES.items():
        if not isinstance(data[table], list) or any(not isinstance(row, dict) or set(row) != set(columns) for row in data[table]):
            raise ValueError('Invalid backup table: ' + table)
    with connect() as target:
        target.execute('LOCK TABLE ' + ', '.join('feedback_private.' + name for name in BACKUP_TABLES) + ' IN ACCESS EXCLUSIVE MODE')
        if any(rows(target, tables=BACKUP_TABLES)[name] for name in BACKUP_TABLES):
            raise ValueError('Destination is not empty; restore aborted without overwriting it')
        for table, columns in BACKUP_TABLES.items():
            query = f'INSERT INTO feedback_private.{table} ({", ".join(columns)}) VALUES ({", ".join(["%s"] * len(columns))})'
            for row in data[table]:
                target.execute(query, [row[column] for column in columns])
        if rows(target, tables=BACKUP_TABLES) != data:
            raise ValueError('Restore readback did not match; transaction rolled back')
    print('Restored and verified:', ', '.join(f'{name}={len(data[name])}' for name in BACKUP_TABLES))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate').add_argument('sqlite_path')
    commands.add_parser('backup').add_argument('destination')
    commands.add_parser('restore').add_argument('source')
    args = parser.parse_args()
    if args.command == 'migrate':
        migrate(args.sqlite_path)
    elif args.command == 'backup':
        backup(args.destination)
    else:
        restore(args.source)
