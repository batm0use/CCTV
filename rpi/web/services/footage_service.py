from __future__ import annotations

from pathlib import Path

from shared.paths import is_path_within_footage_dir


def resolve_segment_file(
    footage_dir: str,
    year: str,
    month: str,
    day: str,
    filename: str,
) -> Path:
    """
    Validate and resolve the path for a requested segment file.

    Checks that the resolved path stays within footage_dir to prevent
    path traversal. Returns the resolved Path if valid and the file exists.

    Args:
        footage_dir: Root footage directory from config.
        year: Four-digit year path component supplied by the HTTP request.
        month: Two-digit month path component supplied by the HTTP request.
        day: Two-digit day path component supplied by the HTTP request.
        filename: Segment filename including .mp4 extension.

    Returns:
        Resolved absolute Path to the segment file.

    Raises:
        ValueError: If the resolved path escapes footage_dir (traversal attempt).
        FileNotFoundError: If the segment file does not exist on disk.
    """
    if not filename.endswith(".mp4"):
        raise ValueError(f"Filename {filename!r} is not an MP4 file")

    candidate = Path(footage_dir) / year / month / day / filename

    if not is_path_within_footage_dir(footage_dir, candidate):
        raise ValueError(f"Path {filename!r} escapes footage directory")

    if not candidate.exists():
        raise FileNotFoundError(f"Segment file not found: {candidate}")

    return candidate
