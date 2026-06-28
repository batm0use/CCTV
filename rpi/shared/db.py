from __future__ import annotations

import sqlite3

from shared.state import init_schema, open_connection

_connection: sqlite3.Connection | None = None


def init(db_path: str) -> None:
    """
    Open the singleton database connection and ensure the schema exists.

    Must be called once at process startup before any call to get().
    Safe to call from manage.py for both cctv-main and cctv-storage.

    Args:
        db_path: Filesystem path to the SQLite state database.
    """
    global _connection
    init_schema(db_path)
    _connection = open_connection(db_path)


def get() -> sqlite3.Connection:
    """
    Return the process-wide SQLite connection.

    Returns:
        The open sqlite3.Connection initialised by init().

    Raises:
        RuntimeError: If init() has not been called yet.
    """
    if _connection is None:
        raise RuntimeError("Database not initialised — call db.init() first")

    return _connection


def close() -> None:
    """
    Close the singleton connection on graceful shutdown.

    Safe to call even if init() was never called.
    """
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
