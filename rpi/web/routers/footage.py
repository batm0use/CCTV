from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from web.services.footage_service import resolve_segment_file
from web.services.segment_service import list_segments_paginated

logger = logging.getLogger(__name__)

HTTP_400_BAD_REQUEST: int = 400
HTTP_404_NOT_FOUND: int = 404


def build_footage_router(
    config: AppConfig,
    db_connection: sqlite3.Connection,
    templates: Jinja2Templates,
) -> APIRouter:
    """
    Build the router for footage browsing and file download.

    Args:
        config: Application configuration loaded from cctv.conf.
        db_connection: Open SQLite connection for querying segment metadata.
        templates: Jinja2 template engine instance.

    Returns:
        Configured APIRouter with /footage browser and /footage/{path} download routes.
    """
    router = APIRouter()

    @router.get("/footage")
    async def footage_browser(request: Request, page: int = 1):  # noqa: ANN202
        """
        Render the paginated footage browser page.

        Args:
            request: Incoming HTTP request.
            page: 1-based page number (default: 1).

        Returns:
            HTML TemplateResponse for footage.html.
        """
        all_segments, total_count = list_segments_paginated(
            db_connection=db_connection,
            page=page,
            page_size=config.web.footage_page_size,
        )
        total_pages = max(1, (total_count + config.web.footage_page_size - 1) // config.web.footage_page_size)

        return templates.TemplateResponse(
            "footage.html",
            {
                "request": request,
                "all_segments": all_segments,
                "page": page,
                "page_size": config.web.footage_page_size,
                "total_count": total_count,
                "total_pages": total_pages,
            },
        )

    @router.get("/footage/{year}/{month}/{day}/{filename}")
    async def download_segment(
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
                footage_dir=config.recording.footage_dir,
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

    return router
