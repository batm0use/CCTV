from __future__ import annotations

import logging
import shutil
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

CATCHUP_THRESHOLD: int = 50
TRICKLE_THRESHOLD: int = 5
DISK_SAFETY_FACTOR: float = 0.8
AVG_SEGMENT_MB: float = 90.0


@dataclass
class SyncConfig:
    rpi_base_url: str
    local_footage_dir: str
    sync_interval_seconds: int
    catchup_threshold: int
    trickle_threshold: int
    batch_hard_limit: int


def load_sync_config(config_path: Path) -> SyncConfig:
    """
    Load and parse the TOML sync configuration file.

    Args:
        config_path: Path to sync.conf.

    Returns:
        Populated SyncConfig instance.
    """
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    sync_raw = raw.get("sync", {})

    return SyncConfig(
        rpi_base_url=sync_raw["rpi_base_url"].rstrip("/"),
        local_footage_dir=sync_raw["local_footage_dir"],
        sync_interval_seconds=sync_raw.get("sync_interval_seconds", 300),
        catchup_threshold=sync_raw.get("catchup_threshold", CATCHUP_THRESHOLD),
        trickle_threshold=sync_raw.get("trickle_threshold", TRICKLE_THRESHOLD),
        batch_hard_limit=sync_raw.get("batch_hard_limit", 20),
    )


class SyncAgent:
    """
    Polls the RPi API, downloads unsynced segments, and confirms receipt.

    Uses a dynamic batch size based on how far behind sync is and how
    much free disk space is available on the laptop.

    Attributes:
        config: Sync configuration loaded from sync.conf.
    """

    def __init__(self, config: SyncConfig) -> None:
        """
        Initialise the sync agent.

        Args:
            config: Sync configuration loaded from sync.conf.
        """
        self.config = config
        self._avg_segment_mb: float = AVG_SEGMENT_MB

    def run(self) -> None:
        """
        Start the polling loop. Blocks until KeyboardInterrupt or SIGTERM.

        Creates the local footage directory if it does not exist, then
        enters the sync loop.
        """
        logger.info(
            "Sync agent started — RPi: %s, local: %s",
            self.config.rpi_base_url,
            self.config.local_footage_dir,
        )
        Path(self.config.local_footage_dir).mkdir(parents=True, exist_ok=True)

        try:
            while True:
                self._sync_cycle()
                time.sleep(self.config.sync_interval_seconds)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Sync agent stopping")
            raise

    def _sync_cycle(self) -> None:
        """
        Run one sync cycle: compute batch size, fetch, download, confirm.
        """
        try:
            unsynced_count = self._fetch_unsynced_count()
        except httpx.HTTPError:
            logger.exception("Cannot reach RPi")
            return

        if unsynced_count == 0:
            logger.debug("Nothing to sync")
            return

        batch_size = self._compute_batch_size(unsynced_count)
        logger.info(
            "Unsynced: %d — downloading batch of %d", unsynced_count, batch_size
        )

        try:
            all_segments = self._fetch_segment_list(batch_size)
        except httpx.HTTPError:
            logger.exception("Failed to fetch segment list")
            return

        for segment in all_segments:
            self._download_and_confirm(segment)

    def _fetch_unsynced_count(self) -> int:
        """
        Query the RPi for the number of unsynced segments.

        Returns:
            Integer count of unsynced segments.

        Raises:
            httpx.HTTPError: If the request fails or returns a non-2xx status.
        """
        url = f"{self.config.rpi_base_url}/api/all_segment/count"
        response = httpx.get(url, params={"is_synced": "false"}, timeout=10)
        response.raise_for_status()

        return int(response.json()["count"])

    def _fetch_segment_list(self, limit: int) -> list[dict[str, Any]]:
        """
        Fetch a batch of unsynced segment metadata from the RPi.

        Args:
            limit: Maximum number of segments to request.

        Returns:
            List of segment metadata dicts with keys:
            id, path, start_timestamp, end_timestamp, size_bytes.

        Raises:
            httpx.HTTPError: If the request fails or returns a non-2xx status.
        """
        url = f"{self.config.rpi_base_url}/api/all_segment"
        response = httpx.get(
            url,
            params={"is_synced": "false", "limit": limit},
            timeout=10,
        )
        response.raise_for_status()

        return cast(list[dict[str, Any]], response.json())

    def _download_and_confirm(self, segment: dict[str, Any]) -> None:
        """
        Download one segment file and confirm receipt to the RPi.

        Skips download if the file already exists locally with the same size.
        On successful download, updates the rolling average segment size and
        POSTs to the RPi to mark the segment as synced.

        Args:
            segment: Segment metadata dict from the RPi API.
        """
        segment_id: int = segment["id"]
        remote_path: str = segment["path"]

        parts = remote_path.replace("\\", "/").split("/")
        if len(parts) < 4:
            logger.warning("Unexpected segment path format: %s", remote_path)
            return

        year, month, day, filename = parts[-4], parts[-3], parts[-2], parts[-1]
        local_dir = Path(self.config.local_footage_dir) / year / month / day
        local_file = local_dir / filename

        if local_file.exists() and segment.get("size_bytes"):
            if local_file.stat().st_size == segment["size_bytes"]:
                logger.debug("Already have %s — confirming only", filename)
                self._confirm_synced(segment_id)
                return

        local_dir.mkdir(parents=True, exist_ok=True)
        download_url = (
            f"{self.config.rpi_base_url}/footage/{year}/{month}/{day}/{filename}"
        )

        try:
            logger.info("Downloading %s", filename)
            with httpx.stream("GET", download_url, timeout=120) as stream_response:
                stream_response.raise_for_status()
                with local_file.open("wb") as output_file:
                    for chunk in stream_response.iter_bytes(chunk_size=65536):
                        output_file.write(chunk)
        except httpx.HTTPError:
            logger.exception("Failed to download %s", filename)
            if local_file.exists():
                local_file.unlink()
            return

        downloaded_mb = local_file.stat().st_size / 1_048_576
        self._avg_segment_mb = self._avg_segment_mb * 0.8 + downloaded_mb * 0.2
        logger.info("Saved %s (%.1f MB)", filename, downloaded_mb)

        self._confirm_synced(segment_id)

    def _confirm_synced(self, segment_id: int) -> None:
        """
        Notify the RPi that a segment has been successfully downloaded.

        Args:
            segment_id: Database row ID of the confirmed segment.
        """
        url = f"{self.config.rpi_base_url}/api/all_segment/{segment_id}/synced"
        try:
            response = httpx.post(url, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to confirm segment %d", segment_id)

    def _compute_batch_size(self, unsynced_count: int) -> int:
        """
        Compute how many segments to download this cycle.

        Combines disk-aware cap with catch-up/trickle/steady-state switching:
        - catch-up mode (unsynced > catchup_threshold): up to batch_hard_limit
        - trickle mode (unsynced > trickle_threshold): up to batch_hard_limit // 4
        - steady-state (caught up): 1 per cycle

        Args:
            unsynced_count: Number of segments currently unsynced on the RPi.

        Returns:
            Number of segments to request in this cycle.
        """
        available_mb = shutil.disk_usage(self.config.local_footage_dir).free / 1_048_576
        max_by_disk = int((available_mb * DISK_SAFETY_FACTOR) / self._avg_segment_mb)
        max_by_disk = max(1, max_by_disk)

        if unsynced_count > self.config.catchup_threshold:
            target = self.config.batch_hard_limit
        elif unsynced_count > self.config.trickle_threshold:
            target = max(1, self.config.batch_hard_limit // 4)
        else:
            target = 1

        return min(target, max_by_disk)
