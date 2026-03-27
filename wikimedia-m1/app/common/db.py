from contextlib import contextmanager
from typing import Iterator

import psycopg


@contextmanager
def db_connection(database_url: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()
