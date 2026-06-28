from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from web.services.segment_service import (
    confirm_synced,
    get_segment_batch,
    get_segment_count,
    get_system_status,
)

logger = logging.getLogger(__name__)

HTTP_404_NOT_FOUND: int = 404
DEFAULT_SEGMENT_BATCH_LIMIT: int = 20

router = APIRouter(prefix="/api")


@router.get("/status")
async def get_status(request: Request) -> dict[str, Any]:
    """
    Return a JSON status summary of the system.

    Args:
        request: Incoming HTTP request used to read config and db from app state.

    Returns:
        Dict with keys: unsynced_segment_count, disk_used_bytes,
        disk_total_bytes, disk_used_pct.
    """
    return get_system_status(
        db_connection=request.app.state.db_connection,
        footage_dir=request.app.state.config.recording.footage_dir,
    )


@router.get("/segments/count")
async def get_count(request: Request, is_synced: bool = False) -> dict[str, int]:
    """
    Return the count of segments matching the is_synced filter.

    Used by the laptop sync agent to compute a dynamic batch size
    before fetching the actual segment list.

    Args:
        request: Incoming HTTP request used to read db_connection from app state.
        is_synced: If False (default), count unsynced segments.
                   If True, count synced segments.

    Returns:
        Dict with a single key "count".
    """
    segment_count = get_segment_count(
        db_connection=request.app.state.db_connection,
        is_synced=is_synced,
    )

    return {"count": segment_count}


@router.get("/segments")
async def list_segments(
    request: Request,
    is_synced: bool = False,
    limit: int = DEFAULT_SEGMENT_BATCH_LIMIT,
) -> list[dict[str, Any]]:
    """
    Return a batch of completed segments matching the is_synced filter.

    Ordered oldest-first so the laptop agent downloads in chronological order.

    Args:
        request: Incoming HTTP request used to read db_connection from app state.
        is_synced: Filter to synced (True) or unsynced (False) segments.
        limit: Maximum number of segments to return (default: 20).

    Returns:
        List of segment metadata dicts with keys:
        id, path, start_timestamp, end_timestamp, size_bytes.
    """
    all_segments = get_segment_batch(
        db_connection=request.app.state.db_connection,
        is_synced=is_synced,
        limit=limit,
    )

    return all_segments


@router.post("/segments/{segment_id}/synced", responses={404: {"description": "Segment not found"}})
async def mark_segment_synced(request: Request, segment_id: int) -> dict[str, str]:
    """
    Mark a segment as successfully downloaded by the laptop sync agent.

    Args:
        request: Incoming HTTP request used to read db_connection from app state.
        segment_id: Database row ID of the segment to mark as synced.

    Returns:
        Dict with key "status" set to "ok".

    Raises:
        HTTPException 404: If no segment with segment_id exists.
    """
    try:
        confirm_synced(
            db_connection=request.app.state.db_connection,
            segment_id=segment_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Segment {segment_id} not found",
        )

    logger.info("Segment %d marked as synced", segment_id)

    return {"status": "ok"}
