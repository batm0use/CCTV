from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from shared import frame_buffer
from shared.config import AppConfig

logger = logging.getLogger(__name__)

MJPEG_BOUNDARY: bytes = b"--frame"
MJPEG_CONTENT_TYPE: str = "multipart/x-mixed-replace; boundary=frame"


def build_live_router(
    config: AppConfig,
    templates: Jinja2Templates,
) -> APIRouter:
    """Build the APIRouter for the live view page and MJPEG stream endpoint.

    Args:
        config: Application configuration loaded from cctv.conf.
        templates: Jinja2 template engine instance.

    Returns:
        Configured APIRouter with /live and /stream.mjpeg routes.
    """
    router = APIRouter()
    frame_sleep_seconds: float = 1.0 / config.stream.stream_fps

    @router.get("/")
    async def redirect_to_live(request: Request):  # noqa: ANN202
        """Redirect the root URL to the live view page."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/live")

    @router.get("/live")
    async def live_page(request: Request):  # noqa: ANN202
        """Render the live view HTML page.

        Args:
            request: Incoming HTTP request (required by Jinja2Templates).

        Returns:
            HTML response with the live.html template.
        """
        return templates.TemplateResponse(
            "live.html",
            {"request": request},
        )

    @router.get("/stream.mjpeg")
    async def mjpeg_stream() -> StreamingResponse:
        """Stream JPEG frames as an MJPEG multipart response.

        Reads the latest frame from the shared frame_buffer at stream_fps
        rate. All browser tabs share the same buffer; only one JPEG is
        held in memory at a time regardless of viewer count.

        Returns:
            StreamingResponse with multipart/x-mixed-replace content type.
        """
        async def generate_frames() -> AsyncGenerator[bytes, None]:
            while True:
                latest_frame = frame_buffer.read()
                if latest_frame:
                    yield (
                        MJPEG_BOUNDARY
                        + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                        + latest_frame
                        + b"\r\n"
                    )
                await asyncio.sleep(frame_sleep_seconds)

        return StreamingResponse(
            generate_frames(),
            media_type=MJPEG_CONTENT_TYPE,
        )

    return router
