from __future__ import annotations

from datetime import datetime
from pathlib import Path


def segment_path(footage_dir: str, recorded_at: datetime) -> Path:
    """Build the full filesystem path for an MP4 segment file.

    Segments are stored under a YYYY/MM/DD/ hierarchy so that browsing
    and deletion by date are both efficient on the filesystem level.

    Args:
        footage_dir: Root directory for all footage (from config).
        recorded_at: UTC datetime at which the segment recording started.

    Returns:
        Absolute Path where the segment file should be written.
    """
    date_directory = (
        Path(footage_dir)
        / recorded_at.strftime("%Y")
        / recorded_at.strftime("%m")
        / recorded_at.strftime("%d")
    )
    filename = recorded_at.strftime("%Y-%m-%d_%H-%M-%S") + ".mp4"
    return date_directory / filename


def ensure_segment_directory(footage_dir: str, recorded_at: datetime) -> Path:
    """Create the date-based directory for a segment if it does not exist.

    Args:
        footage_dir: Root directory for all footage (from config).
        recorded_at: UTC datetime at which the segment recording started.

    Returns:
        The created (or already-existing) directory Path.

    Raises:
        OSError: If the directory cannot be created due to permissions or
            a non-directory entry already existing at the path.
    """
    directory = segment_path(footage_dir, recorded_at).parent
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def is_path_within_footage_dir(footage_dir: str, candidate: Path) -> bool:
    """Return True if candidate resolves to a path inside footage_dir.

    Used to guard the footage download endpoint against path traversal.

    Args:
        footage_dir: Root directory for all footage (from config).
        candidate: Path to validate, potentially containing '..' components.

    Returns:
        True if candidate is safely inside footage_dir, False otherwise.
    """
    resolved_root = Path(footage_dir).resolve()
    resolved_candidate = candidate.resolve()
    return resolved_candidate.is_relative_to(resolved_root)
