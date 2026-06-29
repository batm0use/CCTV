from __future__ import annotations

import threading

_lock: threading.Lock = threading.Lock()
_latest_frame: bytes = b""


def write(frame: bytes) -> None:
    """
    Replace the latest JPEG frame in the shared buffer.

    Called from the recorder thread every 1/stream_fps seconds.
    Only the most recent frame is retained; older frames are discarded.

    Args:
        frame: Raw JPEG-encoded bytes of the latest preview frame.
    """
    global _latest_frame
    with _lock:
        _latest_frame = frame


def read() -> bytes:
    """
    Return the latest JPEG frame from the shared buffer.

    Returns an empty bytes object if no frame has been written yet.
    Safe to call from any thread, including the async web handler.

    Returns:
        Raw JPEG-encoded bytes of the most recent preview frame,
        or b"" if the recorder has not yet produced a frame.
    """
    with _lock:
        return _latest_frame
