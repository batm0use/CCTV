from __future__ import annotations

from shared import runtime_flags
from shared.config import MotionConfig


def get_motion_state(config: MotionConfig) -> dict[str, bool]:
    """
    Return the current motion detection and notification state.

    Args:
        config: MotionConfig loaded from cctv.conf.

    Returns:
        Dict with keys:
        - notifications_enabled: runtime toggle (survives page reloads,
          resets on container restart).
        - motion_enabled: whether motion detection is active per cctv.conf.
        - ntfy_configured: whether an ntfy_topic is set in cctv.conf.
    """
    return {
        "notifications_enabled": runtime_flags.is_notifications_enabled(),
        "motion_enabled": config.enabled,
        "ntfy_configured": bool(config.ntfy_topic),
    }


def set_notifications_enabled(enabled: bool) -> None:
    """
    Toggle push notification delivery on or off at runtime.

    Does not affect motion detection itself — the camera still detects motion
    and logs it; only ntfy.sh delivery is gated. The flag resets to True on
    container restart.

    Args:
        enabled: True to resume notifications, False to suppress them.
    """
    runtime_flags.set_notifications_enabled(enabled)
