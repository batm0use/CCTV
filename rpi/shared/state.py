from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def open_connection(db_path: str) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection to the state database.

    WAL mode allows one writer and multiple concurrent readers without
    blocking, which is the access pattern used by cctv-main and cctv-storage.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        Open sqlite3.Connection with WAL journal mode and row_factory set
        to sqlite3.Row for column-name-based access.

    Raises:
        sqlite3.OperationalError: If the database file cannot be opened.
    """
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_schema(db_path: str) -> None:
    """Create the segments table if it does not already exist.

    Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).

    Args:
        db_path: Filesystem path to the SQLite database file.

    Raises:
        sqlite3.OperationalError: If the schema cannot be created.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = open_connection(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            path       TEXT    NOT NULL UNIQUE,
            start_ts   TEXT    NOT NULL,
            end_ts     TEXT,
            size_bytes INTEGER,
            is_synced  INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.commit()
    connection.close()


def insert_segment(
    connection: sqlite3.Connection,
    path: str,
    start_ts: datetime,
) -> int:
    """Insert a new segment row when recording begins.

    end_ts and size_bytes are left NULL until the segment is finalised
    by calling finalise_segment().

    Args:
        connection: Open database connection.
        path: Absolute filesystem path of the segment file.
        start_ts: UTC datetime at which recording of this segment started.

    Returns:
        The auto-assigned row ID of the new segment.

    Raises:
        sqlite3.IntegrityError: If a segment with the same path already exists.
    """
    cursor = connection.execute(
        "INSERT INTO segments (path, start_ts) VALUES (:path, :start_ts)",
        {"path": path, "start_ts": start_ts.isoformat()},
    )
    connection.commit()
    return cursor.lastrowid


def finalise_segment(
    connection: sqlite3.Connection,
    segment_id: int,
    end_ts: datetime,
    size_bytes: int,
) -> None:
    """Update a segment row with its end timestamp and file size.

    Called by the recorder immediately after a segment file is closed.

    Args:
        connection: Open database connection.
        segment_id: Row ID returned by insert_segment().
        end_ts: UTC datetime at which recording of this segment ended.
        size_bytes: Size of the completed MP4 file in bytes.

    Raises:
        sqlite3.OperationalError: If the update fails.
    """
    connection.execute(
        """
        UPDATE segments
           SET end_ts     = :end_ts,
               size_bytes = :size_bytes
         WHERE id = :segment_id
        """,
        {
            "end_ts": end_ts.isoformat(),
            "size_bytes": size_bytes,
            "segment_id": segment_id,
        },
    )
    connection.commit()


def mark_segment_synced(
    connection: sqlite3.Connection,
    segment_id: int,
) -> None:
    """Mark a segment as successfully downloaded by the laptop sync agent.

    Args:
        connection: Open database connection.
        segment_id: Row ID of the segment to mark as synced.

    Raises:
        sqlite3.OperationalError: If the update fails.
    """
    connection.execute(
        "UPDATE segments SET is_synced = 1 WHERE id = :segment_id",
        {"segment_id": segment_id},
    )
    connection.commit()


def count_unsynced_segments(connection: sqlite3.Connection) -> int:
    """Return the number of completed segments not yet synced to the laptop.

    Args:
        connection: Open database connection.

    Returns:
        Count of segments where is_synced = 0 and end_ts IS NOT NULL.
    """
    row = connection.execute(
        "SELECT COUNT(*) FROM segments WHERE is_synced = 0 AND end_ts IS NOT NULL"
    ).fetchone()
    return row[0]


def fetch_unsynced_segments(
    connection: sqlite3.Connection,
    limit: int,
) -> list[sqlite3.Row]:
    """Fetch the oldest completed segments that have not been synced.

    Args:
        connection: Open database connection.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by start_ts ascending.
        Each row has columns: id, path, start_ts, end_ts, size_bytes.
    """
    return connection.execute(
        """
        SELECT id, path, start_ts, end_ts, size_bytes
          FROM segments
         WHERE is_synced = 0
           AND end_ts IS NOT NULL
         ORDER BY start_ts ASC
         LIMIT :limit
        """,
        {"limit": limit},
    ).fetchall()


def fetch_oldest_synced_segments(
    connection: sqlite3.Connection,
    min_age_hours: int,
    limit: int,
) -> list[sqlite3.Row]:
    """Fetch the oldest synced segments that are safe to delete locally.

    Only returns segments older than min_age_hours to prevent the storage
    manager from deleting a segment the recorder or sync agent is still using.

    Args:
        connection: Open database connection.
        min_age_hours: Minimum age in hours a segment must have before it
            is eligible for local deletion.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by start_ts ascending.
        Each row has columns: id, path, size_bytes.
    """
    cutoff = datetime.utcnow().replace(
        hour=datetime.utcnow().hour - min_age_hours
        if datetime.utcnow().hour >= min_age_hours
        else 0
    )
    return connection.execute(
        """
        SELECT id, path, size_bytes
          FROM segments
         WHERE is_synced = 1
           AND start_ts < :cutoff
         ORDER BY start_ts ASC
         LIMIT :limit
        """,
        {"cutoff": cutoff.isoformat(), "limit": limit},
    ).fetchall()


def delete_segment_record(
    connection: sqlite3.Connection,
    segment_id: int,
) -> None:
    """Remove a segment row from the database after the file has been deleted.

    Args:
        connection: Open database connection.
        segment_id: Row ID of the segment to remove.

    Raises:
        sqlite3.OperationalError: If the deletion fails.
    """
    connection.execute(
        "DELETE FROM segments WHERE id = :segment_id",
        {"segment_id": segment_id},
    )
    connection.commit()
