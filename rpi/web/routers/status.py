from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from web.auth import require_auth
from web.services.motion_service import get_motion_state
from web.services.segment_service import get_system_status

router = APIRouter(dependencies=[Depends(require_auth)])

BYTES_PER_GB: int = 1_073_741_824


@router.get("/status")
async def status_page(request: Request) -> Response:
    """
    Render the system status page.

    Args:
        request: Incoming HTTP request used to read config from app state.

    Returns:
        HTML TemplateResponse for status.html.
    """
    config = request.app.state.config
    system_status = get_system_status(footage_dir=config.recording.footage_dir)
    motion_state = get_motion_state(config.motion)
    notifications_active = (
        motion_state["notifications_enabled"]
        and motion_state["motion_enabled"]
        and motion_state["ntfy_configured"]
    )

    return request.app.state.templates.TemplateResponse(
        request,
        "status.html",
        {
            "active": "status",
            "notifications_active": notifications_active,
            "motion_enabled": motion_state["motion_enabled"],
            "unsynced_segment_count": system_status["unsynced_segment_count"],
            "disk_used_pct": system_status["disk_used_pct"],
            "disk_used_gb": round(system_status["disk_used_bytes"] / BYTES_PER_GB, 1),
            "disk_total_gb": round(
                system_status["disk_total_bytes"] / BYTES_PER_GB, 1
            ),
        },
    )
