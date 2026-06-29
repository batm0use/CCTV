from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from web.services.segment_service import (
    confirm_synced,
    get_segment_batch,
    get_segment_count,
    get_system_status,
    purge_all_footage,
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
        request: Incoming HTTP request used to read footage_dir from app state.

    Returns:
        Dict with keys: unsynced_segment_count, disk_used_bytes,
        disk_total_bytes, disk_used_pct.
    """
    return get_system_status(footage_dir=request.app.state.config.recording.footage_dir)


@router.get("/all_segment/count")
async def get_count(is_synced: bool = False) -> dict[str, int]:
    """
    Return the count of segments matching the is_synced filter.

    Used by the laptop sync agent to compute a dynamic batch size
    before fetching the actual segment list.

    Args:
        is_synced: If False (default), count unsynced segments.
                   If True, count synced segments.

    Returns:
        Dict with a single key "count".
    """
    return {"count": get_segment_count(is_synced=is_synced)}


@router.get("/all_segment")
async def list_all_segment(
    is_synced: bool = False,
    limit: int = DEFAULT_SEGMENT_BATCH_LIMIT,
) -> list[dict[str, Any]]:
    """
    Return a batch of completed segments matching the is_synced filter.

    Ordered oldest-first so the laptop agent downloads in chronological order.

    Args:
        is_synced: Filter to synced (True) or unsynced (False) segments.
        limit: Maximum number of segments to return (default: 20).

    Returns:
        List of segment metadata dicts with keys:
        id, path, start_timestamp, end_timestamp, size_bytes.
    """
    return get_segment_batch(is_synced=is_synced, limit=limit)


@router.post(
    "/all_segment/{segment_id}/synced",
    responses={404: {"description": "Segment not found"}},
)
async def mark_segment_synced(segment_id: int) -> dict[str, str]:
    """
    Mark a segment as successfully downloaded by the laptop sync agent.

    Args:
        segment_id: Database row ID of the segment to mark as synced.

    Returns:
        Dict with key "status" set to "ok".

    Raises:
        HTTPException 404: If no segment with segment_id exists.
    """
    try:
        confirm_synced(segment_id=segment_id)
    except ValueError as not_found_error:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Segment {segment_id} not found",
        ) from not_found_error

    logger.info("Segment %d marked as synced", segment_id)

    return {"status": "ok"}


@router.delete("/footage")
async def delete_all_footage() -> dict[str, int]:
    """
    Delete all completed segment recordings from the RPi.

    Removes every segment file whose recording has finished
    (end_timestamp IS NOT NULL) and purges their database records.
    The segment currently being recorded is not touched.

    Videos already downloaded to the laptop are not affected — the laptop
    stores its own copy and the sync API returns an empty list once no
    unsynced segments remain.

    Returns:
        Dict with key "deleted" containing the number of segments removed.
    """
    deleted = purge_all_footage()
    logger.warning("Purged %d segment(s) from RPi via web UI", deleted)
    return {"deleted": deleted}
