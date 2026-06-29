from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def open_connection(db_path: str) -> sqlite3.Connection:
    """
    Open a WAL-mode SQLite connection to the state database.

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
    """
    Create the segments table if it does not already exist.

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
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            path              TEXT    NOT NULL UNIQUE,
            start_timestamp   TEXT    NOT NULL,
            end_timestamp     TEXT,
            size_bytes        INTEGER,
            is_synced         INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.commit()
    connection.close()


def insert_segment(
    connection: sqlite3.Connection,
    path: str,
    start_timestamp: datetime,
) -> int:
    """
    Insert a new segment row when recording begins.

    end_timestamp and size_bytes are left NULL until the segment is finalised
    by calling finalise_segment().

    Args:
        connection: Open database connection.
        path: Absolute filesystem path of the segment file.
        start_timestamp: UTC datetime at which recording of this segment started.

    Returns:
        The auto-assigned row ID of the new segment.

    Raises:
        sqlite3.IntegrityError: If a segment with the same path already exists.
    """
    cursor = connection.execute(
        "INSERT INTO segments (path, start_timestamp) VALUES (:path, :start_timestamp)",
        {"path": path, "start_timestamp": start_timestamp.isoformat()},
    )
    connection.commit()

    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("INSERT did not return a row ID")

    return row_id


def finalise_segment(
    connection: sqlite3.Connection,
    segment_id: int,
    end_timestamp: datetime,
    size_bytes: int,
) -> None:
    """
    Update a segment row with its end timestamp and file size.

    Called by the recorder immediately after a segment file is closed.

    Args:
        connection: Open database connection.
        segment_id: Row ID returned by insert_segment().
        end_timestamp: UTC datetime at which recording of this segment ended.
        size_bytes: Size of the completed MP4 file in bytes.

    Raises:
        sqlite3.OperationalError: If the update fails.
    """
    connection.execute(
        """
        UPDATE segments
           SET end_timestamp = :end_timestamp,
               size_bytes    = :size_bytes
         WHERE id = :segment_id
        """,
        {
            "end_timestamp": end_timestamp.isoformat(),
            "size_bytes": size_bytes,
            "segment_id": segment_id,
        },
    )
    connection.commit()


def mark_segment_synced(
    connection: sqlite3.Connection,
    segment_id: int,
) -> None:
    """
    Mark a segment as successfully downloaded by the laptop sync agent.

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
    """
    Return the number of completed segments not yet synced to the laptop.

    Args:
        connection: Open database connection.

    Returns:
        Count of segments where is_synced = 0 and end_timestamp IS NOT NULL.
    """
    row = connection.execute(
        "SELECT COUNT(*) FROM segments"
        " WHERE is_synced = 0 AND end_timestamp IS NOT NULL"
    ).fetchone()

    return int(row[0])


def fetch_unsynced_segments(
    connection: sqlite3.Connection,
    limit: int,
) -> list[sqlite3.Row]:
    """
    Fetch the oldest completed segments that have not been synced.

    Args:
        connection: Open database connection.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by start_timestamp ascending.
        Each row has columns: id, path, start_timestamp, end_timestamp, size_bytes.
    """
    return connection.execute(
        """
        SELECT id, path, start_timestamp, end_timestamp, size_bytes
          FROM segments
         WHERE is_synced = 0
           AND end_timestamp IS NOT NULL
         ORDER BY start_timestamp ASC
         LIMIT :limit
        """,
        {"limit": limit},
    ).fetchall()


def fetch_oldest_synced_segments(
    connection: sqlite3.Connection,
    min_age_hours: int,
    limit: int,
) -> list[sqlite3.Row]:
    """
    Fetch the oldest synced segments that are safe to delete locally.

    Only returns segments older than min_age_hours to prevent the storage
    manager from deleting a segment the recorder or sync agent is still using.

    Args:
        connection: Open database connection.
        min_age_hours: Minimum age in hours a segment must have before it
            is eligible for local deletion.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by start_timestamp ascending.
        Each row has columns: id, path, size_bytes.
    """
    cutoff = (datetime.now(tz=UTC) - timedelta(hours=min_age_hours)).isoformat()

    return connection.execute(
        """
        SELECT id, path, size_bytes
          FROM segments
         WHERE is_synced = 1
           AND start_timestamp < :cutoff
         ORDER BY start_timestamp ASC
         LIMIT :limit
        """,
        {"cutoff": cutoff, "limit": limit},
    ).fetchall()


def fetch_oldest_segments(
    connection: sqlite3.Connection,
    min_age_hours: int,
    limit: int,
) -> list[sqlite3.Row]:
    """
    Fetch the oldest completed segments eligible for deletion, regardless of
    sync status.

    Used in standalone mode (require_synced_for_deletion = False) where the
    laptop sync agent is not running and is_synced will always remain 0.
    The end_timestamp IS NOT NULL guard prevents deleting the segment the
    recorder is currently writing.

    Args:
        connection: Open database connection.
        min_age_hours: Minimum age in hours a segment must have before it
            is eligible for local deletion.
        limit: Maximum number of rows to return.

    Returns:
        List of sqlite3.Row objects ordered by start_timestamp ascending.
        Each row has columns: id, path, size_bytes.
    """
    cutoff = (datetime.now(tz=UTC) - timedelta(hours=min_age_hours)).isoformat()

    return connection.execute(
        """
        SELECT id, path, size_bytes
          FROM segments
         WHERE end_timestamp IS NOT NULL
           AND start_timestamp < :cutoff
         ORDER BY start_timestamp ASC
         LIMIT :limit
        """,
        {"cutoff": cutoff, "limit": limit},
    ).fetchall()


def fetch_incomplete_segments(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """
    Return all segment rows that were never finalised.

    A segment is incomplete when end_timestamp IS NULL, meaning the process
    was killed before _finalise_current_segment() could run. These rows
    have a corresponding file on disk that is corrupt or truncated.

    Args:
        connection: Open database connection.

    Returns:
        List of sqlite3.Row objects with columns: id, path.
    """
    return connection.execute(
        "SELECT id, path FROM segments WHERE end_timestamp IS NULL"
    ).fetchall()


def delete_segment_record(
    connection: sqlite3.Connection,
    segment_id: int,
) -> None:
    """
    Remove a segment row from the database after the file has been deleted.

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
