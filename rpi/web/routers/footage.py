from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from web.services.footage_service import resolve_segment_file
from web.services.segment_service import list_all_segments_paginated

logger = logging.getLogger(__name__)

HTTP_400_BAD_REQUEST: int = 400
HTTP_404_NOT_FOUND: int = 404

router = APIRouter(prefix="/footage")


@router.get("")
async def footage_browser(request: Request, page: int = 1):  # noqa: ANN202
    """
    Render the paginated footage browser page.

    Args:
        request: Incoming HTTP request.
        page: 1-based page number (default: 1).

    Returns:
        HTML TemplateResponse for footage.html.
    """
    config = request.app.state.config
    all_segments, total_count = list_all_segments_paginated(
        page=page,
        page_size=config.web.footage_page_size,
    )
    total_pages = max(1, (total_count + config.web.footage_page_size - 1) // config.web.footage_page_size)

    return request.app.state.templates.TemplateResponse(
        request,
        "footage.html",
        {
            "all_segments": all_segments,
            "page": page,
            "page_size": config.web.footage_page_size,
            "total_count": total_count,
            "total_pages": total_pages,
        },
    )


@router.get(
    "/{year}/{month}/{day}/{filename}",
    responses={
        400: {"description": "Path escapes footage directory"},
        404: {"description": "Segment file not found"},
    },
)
async def download_segment(
    request: Request,
    year: str,
    month: str,
    day: str,
    filename: str,
) -> FileResponse:
    """
    Serve a recorded MP4 segment with HTTP Range request support.

    Delegates path validation to footage_service.resolve_segment_file(),
    which guards against path traversal attacks.

    Args:
        request: Incoming HTTP request used to read footage_dir from app state.
        year: Four-digit year component of the segment path.
        month: Two-digit month component of the segment path.
        day: Two-digit day component of the segment path.
        filename: Segment filename including .mp4 extension.

    Returns:
        FileResponse with Range support for in-browser seeking.

    Raises:
        HTTPException 400: If the resolved path escapes footage_dir.
        HTTPException 404: If the segment file does not exist on disk.
    """
    try:
        segment_file = resolve_segment_file(
            footage_dir=request.app.state.config.recording.footage_dir,
            year=year,
            month=month,
            day=day,
            filename=filename,
        )
    except ValueError:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Invalid path")
    except FileNotFoundError:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Segment not found")

    return FileResponse(path=str(segment_file), media_type="video/mp4", filename=filename)
