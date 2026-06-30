from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt

from shared import runtime_flags
from shared.config import MotionConfig

logger = logging.getLogger(__name__)


@dataclass
class MotionState:
    """
    Mutable detection state threaded through successive calls to detect_motion.

    Attributes:
        previous_frame: Y-plane of the last processed frame, or None on first call.
        last_notification_time: Monotonic timestamp of the last successful ntfy
            send, or 0.0 if no notification has been sent yet.
    """

    previous_frame: npt.NDArray[np.uint8] | None = field(default=None)
    last_notification_time: float = field(default=0.0)


def detect_motion(
    y_plane: npt.NDArray[np.uint8],
    state: MotionState,
    config: MotionConfig,
) -> bool:
    """
    Compare the current Y-plane against the previous frame.

    Updates state.previous_frame in-place on every call. Returns False on the
    first call (no previous frame to compare against).

    Args:
        y_plane: 2-D uint8 numpy array of shape (height, width) containing
            the luminance plane of the current lores frame.
        state: Mutable motion state shared across calls. previous_frame is
            updated to the current frame before returning.
        config: Motion detection thresholds from MotionConfig.

    Returns:
        True if the fraction of pixels whose absolute luminance difference
        from the previous frame exceeds pixel_diff_threshold is greater than
        or equal to motion_ratio_threshold. False on the first call or when
        motion is below the threshold.
    """
    if state.previous_frame is None:
        state.previous_frame = y_plane.copy()
        return False

    diff = np.abs(
        y_plane.astype(np.int16) - state.previous_frame.astype(np.int16)
    ).astype(np.uint8)
    motion_ratio = int(np.sum(diff > config.pixel_diff_threshold)) / y_plane.size
    state.previous_frame = y_plane.copy()

    return motion_ratio >= config.motion_ratio_threshold


def send_ntfy_notification(config: MotionConfig, state: MotionState) -> None:
    """
    Send a push notification via ntfy.sh if cooldown has elapsed.

    No-ops silently when ntfy_topic is empty or when cooldown_seconds have
    not elapsed since the last successful send. Uses stdlib urllib — no
    external HTTP dependency.

    Args:
        config: Motion configuration supplying ntfy_topic, ntfy_server, and
            cooldown_seconds.
        state: Mutable motion state; last_notification_time is updated on a
            successful send.
    """
    if not config.ntfy_topic:
        return
    if not runtime_flags.is_notifications_enabled():
        return

    now = time.monotonic()
    if now - state.last_notification_time < config.cooldown_seconds:
        return

    timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S UTC")
    message = f"Motion detected at {timestamp}".encode()
    url = f"{config.ntfy_server.rstrip('/')}/{config.ntfy_topic}"

    try:
        req = urllib.request.Request(url, data=message, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                logger.warning(
                    "ntfy returned HTTP %d for topic %r",
                    resp.status,
                    config.ntfy_topic,
                )
    except urllib.error.URLError as ntfy_error:
        logger.warning("ntfy notification failed: %s", ntfy_error)
    except OSError as ntfy_error:
        logger.warning("ntfy notification error: %s", ntfy_error)
    else:
        state.last_notification_time = now
        logger.info(
            "Motion notification sent to %r at %s",
            config.ntfy_topic,
            timestamp,
        )
