from __future__ import annotations

import shutil
import sqlite3
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from shared.config import AppConfig
from shared.state import (
    count_unsynced_segments,
    fetch_unsynced_segments,
    mark_segment_synced,
)

logger = logging.getLogger(__name__)

HTTP_404_NOT_FOUND: int = 404
DEFAULT_SEGMENT_BATCH_LIMIT: int = 20


def build_api_router(
    config: AppConfig,
    db_connection: sqlite3.Connection,
) -> APIRouter:
    """Build the APIRouter for the JSON API used by the laptop sync agent.

    Args:
        config: Application configuration loaded from cctv.conf.
        db_connection: Open SQLite connection shared with the recorder thread.

    Returns:
        Configured APIRouter with /api/* routes.
    """
    router = APIRouter(prefix="/api")

    @router.get("/status")
    async def get_status() -> dict[str, Any]:
        """Return a JSON status summary of the system.

        Returns:
            Dict with keys: unsynced_segment_count, disk_used_bytes,
            disk_total_bytes, disk_used_pct.
        """
        disk_usage = shutil.disk_usage(config.recording.footage_dir)
        unsynced_count = count_unsynced_segments(db_connection)
        return {
            "unsynced_segment_count": unsynced_count,
            "disk_used_bytes": disk_usage.used,
            "disk_total_bytes": disk_usage.total,
            "disk_used_pct": round(disk_usage.used / disk_usage.total * 100, 1),
        }

    @router.get("/segments/count")
    async def get_segment_count(is_synced: bool = False) -> dict[str, int]:
        """Return the count of segments matching the is_synced filter.

        Used by the laptop sync agent to compute a dynamic batch size
        before fetching the actual segment list.

        Args:
            is_synced: If False (default), count unsynced segments only.
                       If True, count synced segments.

        Returns:
            Dict with a single key "count".
        """
        if not is_synced:
            segment_count = count_unsynced_segments(db_connection)
        else:
            segment_count = db_connection.execute(
                "SELECT COUNT(*) FROM segments WHERE is_synced = 1 AND end_ts IS NOT NULL"
            ).fetchone()[0]
        return {"count": segment_count}

    @router.get("/segments")
    async def list_segments(
        is_synced: bool = False,
        limit: int = DEFAULT_SEGMENT_BATCH_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return a batch of completed segments matching the is_synced filter.

        Used by the laptop sync agent to discover which segments to download.
        Returns segments ordered oldest-first so the agent downloads in
        chronological order.

        Args:
            is_synced: Filter to synced (True) or unsynced (False) segments.
            limit: Maximum number of segments to return (default: 20).

        Returns:
            List of segment metadata dicts, each with keys:
            id, path, start_ts, end_ts, size_bytes.
        """
        if not is_synced:
            all_rows = fetch_unsynced_segments(
                connection=db_connection,
                limit=limit,
            )
        else:
            all_rows = db_connection.execute(
                """
                SELECT id, path, start_ts, end_ts, size_bytes
                  FROM segments
                 WHERE is_synced = 1 AND end_ts IS NOT NULL
                 ORDER BY start_ts ASC
                 LIMIT :limit
                """,
                {"limit": limit},
            ).fetchall()

        return [dict(row) for row in all_rows]

    @router.post("/segments/{segment_id}/synced")
    async def confirm_segment_synced(segment_id: int) -> dict[str, str]:
        """Mark a segment as successfully downloaded by the laptop sync agent.

        Called by the laptop after a segment file has been downloaded and
        verified on the laptop side. The RPi storage manager will only
        delete segments that have been marked synced.

        Args:
            segment_id: Database row ID of the segment to mark as synced.

        Returns:
            Dict with key "status" set to "ok".

        Raises:
            HTTPException 404: If no segment with segment_id exists.
        """
        existing_row = db_connection.execute(
            "SELECT id FROM segments WHERE id = :segment_id",
            {"segment_id": segment_id},
        ).fetchone()

        if existing_row is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Segment {segment_id} not found",
            )

        mark_segment_synced(
            connection=db_connection,
            segment_id=segment_id,
        )
        logger.info("Segment %d marked as synced", segment_id)
        return {"status": "ok"}

    return router
