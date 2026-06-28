from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from shared import frame_buffer

logger = logging.getLogger(__name__)

MJPEG_BOUNDARY: bytes = b"--frame"
MJPEG_CONTENT_TYPE: str = "multipart/x-mixed-replace; boundary=frame"

router = APIRouter()


@router.get("/")
async def redirect_to_live() -> RedirectResponse:
    """
    Redirect the root URL to the live view page.

    Returns:
        RedirectResponse targeting /live.
    """
    return RedirectResponse(url="/live")


@router.get("/live")
async def live_page(request: Request):  # noqa: ANN202
    """
    Render the live view HTML page.

    Args:
        request: Incoming HTTP request (required by Jinja2Templates).

    Returns:
        HTML TemplateResponse for live.html.
    """
    return request.app.state.templates.TemplateResponse("live.html", {"request": request})


@router.get("/stream.mjpeg")
async def mjpeg_stream(request: Request) -> StreamingResponse:
    """
    Stream JPEG frames as an MJPEG multipart response.

    Reads the latest frame from the shared frame_buffer at stream_fps rate.
    All browser tabs share the same buffer; only one JPEG is held in memory
    at a time regardless of viewer count.

    Args:
        request: Incoming HTTP request used to read stream_fps from app state.

    Returns:
        StreamingResponse with multipart/x-mixed-replace content type.
    """
    frame_sleep_seconds: float = 1.0 / request.app.state.config.stream.stream_fps

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

    return StreamingResponse(generate_frames(), media_type=MJPEG_CONTENT_TYPE)
