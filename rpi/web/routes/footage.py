from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from shared.paths import is_path_within_footage_dir
from shared.state import open_connection

logger = logging.getLogger(__name__)

HTTP_400_BAD_REQUEST: int = 400
HTTP_404_NOT_FOUND: int = 404


def build_footage_router(
    config: AppConfig,
    db_connection: sqlite3.Connection,
    templates: Jinja2Templates,
) -> APIRouter:
    """Build the APIRouter for footage browsing and file download.

    Args:
        config: Application configuration loaded from cctv.conf.
        db_connection: Open SQLite connection for querying segment metadata.
        templates: Jinja2 template engine instance.

    Returns:
        Configured APIRouter with /footage and /footage/{path} routes.
    """
    router = APIRouter()
    footage_dir = config.recording.footage_dir
    page_size = config.web.footage_page_size

    @router.get("/footage")
    async def footage_browser(request: Request, page: int = 1):  # noqa: ANN202
        """Render the paginated footage browser page.

        Queries the segments table for completed recordings ordered
        most-recent-first and passes them to the footage.html template.

        Args:
            request: Incoming HTTP request.
            page: 1-based page number for pagination (default: 1).

        Returns:
            HTML response with the footage.html template.
        """
        offset = (page - 1) * page_size
        all_segments = db_connection.execute(
            """
            SELECT id, path, start_ts, end_ts, size_bytes, is_synced
              FROM segments
             WHERE end_ts IS NOT NULL
             ORDER BY start_ts DESC
             LIMIT :limit OFFSET :offset
            """,
            {"limit": page_size, "offset": offset},
        ).fetchall()

        total_count = db_connection.execute(
            "SELECT COUNT(*) FROM segments WHERE end_ts IS NOT NULL"
        ).fetchone()[0]

        return templates.TemplateResponse(
            "footage.html",
            {
                "request": request,
                "all_segments": all_segments,
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": max(1, (total_count + page_size - 1) // page_size),
            },
        )

    @router.get("/footage/{year}/{month}/{day}/{filename}")
    async def download_segment(
        year: str,
        month: str,
        day: str,
        filename: str,
    ) -> FileResponse:
        """Serve a recorded MP4 segment with HTTP Range request support.

        Validates that the requested path is within the configured footage
        directory before serving, preventing path traversal attacks.

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
        candidate_path = Path(footage_dir) / year / month / day / filename

        if not is_path_within_footage_dir(footage_dir, candidate_path):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid path",
            )

        if not candidate_path.exists():
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )

        return FileResponse(
            path=str(candidate_path),
            media_type="video/mp4",
            filename=filename,
        )

    return router
