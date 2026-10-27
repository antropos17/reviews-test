"""Small PostgreSQL adapter for the service's fixed parameterized queries."""
import psycopg
from pathlib import Path
from psycopg.rows import dict_row


class PostgresConnection:
    def __init__(self, url):
        self.connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=8,
                                          sslmode='verify-full',
                                          sslrootcert=str(Path(__file__).with_name('supabase-ca.crt')),
                                          prepare_threshold=None)

    def execute(self, query, params=()):
        # SET LOCAL is transaction-scoped and remains safe with a transaction pooler.
        self.connection.execute('SET LOCAL search_path TO feedback_private')
        return self.connection.execute(query.replace('?', '%s'), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()
