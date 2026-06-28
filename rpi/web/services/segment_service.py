from __future__ import annotations

import shutil
import sqlite3
from typing import Any

from shared.state import (
    count_unsynced_segments,
    fetch_unsynced_segments,
    mark_segment_synced,
)


def get_system_status(
    db_connection: sqlite3.Connection,
    footage_dir: str,
) -> dict[str, Any]:
    """
    Return a status snapshot of the system for the /api/status endpoint.

    Args:
        db_connection: Open database connection.
        footage_dir: Footage root directory used to compute disk usage.

    Returns:
        Dict with keys: unsynced_segment_count, disk_used_bytes,
        disk_total_bytes, disk_used_pct.
    """
    disk_usage = shutil.disk_usage(footage_dir)
    unsynced_count = count_unsynced_segments(db_connection)

    return {
        "unsynced_segment_count": unsynced_count,
        "disk_used_bytes": disk_usage.used,
        "disk_total_bytes": disk_usage.total,
        "disk_used_pct": round(disk_usage.used / disk_usage.total * 100, 1),
    }


def get_segment_count(
    db_connection: sqlite3.Connection,
    is_synced: bool,
) -> int:
    """
    Return the count of completed segments matching the is_synced filter.

    Args:
        db_connection: Open database connection.
        is_synced: If False, count unsynced segments. If True, count synced.

    Returns:
        Integer count of matching segments.
    """
    if not is_synced:
        return count_unsynced_segments(db_connection)

    row = db_connection.execute(
        "SELECT COUNT(*) FROM segments WHERE is_synced = 1 AND end_timestamp IS NOT NULL"
    ).fetchone()

    return row[0]


def get_segment_batch(
    db_connection: sqlite3.Connection,
    is_synced: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Return a batch of completed segments matching the is_synced filter.

    Ordered oldest-first so the laptop agent downloads in chronological order.

    Args:
        db_connection: Open database connection.
        is_synced: If False, fetch unsynced segments. If True, fetch synced.
        limit: Maximum number of segments to return.

    Returns:
        List of segment metadata dicts, each with keys:
        id, path, start_timestamp, end_timestamp, size_bytes.
    """
    if not is_synced:
        all_rows = fetch_unsynced_segments(connection=db_connection, limit=limit)
    else:
        all_rows = db_connection.execute(
            """
            SELECT id, path, start_timestamp, end_timestamp, size_bytes
              FROM segments
             WHERE is_synced = 1 AND end_timestamp IS NOT NULL
             ORDER BY start_timestamp ASC
             LIMIT :limit
            """,
            {"limit": limit},
        ).fetchall()

    return [dict(row) for row in all_rows]


def confirm_synced(
    db_connection: sqlite3.Connection,
    segment_id: int,
) -> None:
    """
    Mark a segment as synced, or raise ValueError if it does not exist.

    Args:
        db_connection: Open database connection.
        segment_id: Database row ID of the segment to mark as synced.

    Raises:
        ValueError: If no segment with segment_id exists in the database.
        sqlite3.OperationalError: If the update fails.
    """
    existing_segment = db_connection.execute(
        "SELECT id FROM segments WHERE id = :segment_id",
        {"segment_id": segment_id},
    ).fetchone()

    if existing_segment is None:
        raise ValueError(f"Segment {segment_id} not found")

    mark_segment_synced(connection=db_connection, segment_id=segment_id)


def list_all_segments_paginated(
    db_connection: sqlite3.Connection,
    page: int,
    page_size: int,
) -> tuple[list[sqlite3.Row], int]:
    """
    Return one page of completed segments for the footage browser, newest first.

    Args:
        db_connection: Open database connection.
        page: 1-based page number.
        page_size: Number of rows per page.

    Returns:
        Tuple of (all_segments, total_count) where all_segments is the
        current page of sqlite3.Row objects and total_count is the total
        number of completed segments across all pages.
    """
    offset = (page - 1) * page_size
    all_segments = db_connection.execute(
        """
        SELECT id, path, start_timestamp, end_timestamp, size_bytes, is_synced
          FROM segments
         WHERE end_timestamp IS NOT NULL
         ORDER BY start_timestamp DESC
         LIMIT :limit OFFSET :offset
        """,
        {"limit": page_size, "offset": offset},
    ).fetchall()

    total_count = db_connection.execute(
        "SELECT COUNT(*) FROM segments WHERE end_timestamp IS NOT NULL"
    ).fetchone()[0]

    return all_segments, total_count
