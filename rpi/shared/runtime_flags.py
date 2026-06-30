from __future__ import annotations

import threading

_lock = threading.Lock()
_notifications_enabled: bool = True


def is_notifications_enabled() -> bool:
    """
    Return whether ntfy push notifications are currently enabled.

    Thread-safe. Defaults to True on startup; resets to True on container
    restart since the flag is held in memory.

    Returns:
        True if notifications should be sent, False if they are suppressed.
    """
    with _lock:
        return _notifications_enabled


def set_notifications_enabled(value: bool) -> None:
    """
    Set the runtime notifications toggle.

    Called by PATCH /api/motion. Does not affect motion detection itself —
    only controls whether detected motion triggers an ntfy.sh POST.

    Args:
        value: True to enable notifications, False to suppress them.
    """
    global _notifications_enabled
    with _lock:
        _notifications_enabled = value
