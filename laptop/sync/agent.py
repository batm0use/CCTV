from __future__ import annotations

import logging
import shutil
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CATCHUP_THRESHOLD: int = 50
DEFAULT_TRICKLE_THRESHOLD: int = 5
DEFAULT_BATCH_HARD_LIMIT: int = 20
DISK_SAFETY_FACTOR: float = 0.8
DEFAULT_AVG_SEGMENT_MB: float = 90.0
ROLLING_AVERAGE_WEIGHT: float = 0.2
HTTP_TIMEOUT_SECONDS: float = 30.0
DOWNLOAD_TIMEOUT_SECONDS: float = 300.0


@dataclass
class SyncConfig:
    """Configuration for the laptop sync agent.

    Attributes:
        rpi_base_url: HTTP base URL of the RPi web server.
        local_footage_dir: Local directory where downloaded footage is stored.
        sync_interval_seconds: Sleep duration between sync cycles.
        catchup_threshold: Unsynced count above which catch-up batch is used.
        trickle_threshold: Unsynced count above which trickle batch is used.
        batch_hard_limit: Absolute maximum batch size per cycle.
    """

    rpi_base_url: str
    local_footage_dir: str
    sync_interval_seconds: int = 300
    catchup_threshold: int = DEFAULT_CATCHUP_THRESHOLD
    trickle_threshold: int = DEFAULT_TRICKLE_THRESHOLD
    batch_hard_limit: int = DEFAULT_BATCH_HARD_LIMIT


def load_sync_config(config_path: Path) -> SyncConfig:
    """Load the sync agent configuration from a TOML file.

    Args:
        config_path: Filesystem path to sync.conf.

    Returns:
        Populated SyncConfig instance.

    Raises:
        FileNotFoundError: If config_path does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
        KeyError: If required keys (rpi_base_url, local_footage_dir) are missing.
    """
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    sync_raw = raw["sync"]
    return SyncConfig(
        rpi_base_url=sync_raw["rpi_base_url"],
        local_footage_dir=sync_raw["local_footage_dir"],
        sync_interval_seconds=sync_raw.get("sync_interval_seconds", 300),
        catchup_threshold=sync_raw.get("catchup_threshold", DEFAULT_CATCHUP_THRESHOLD),
        trickle_threshold=sync_raw.get("trickle_threshold", DEFAULT_TRICKLE_THRESHOLD),
        batch_hard_limit=sync_raw.get("batch_hard_limit", DEFAULT_BATCH_HARD_LIMIT),
    )


def compute_batch_size(
    unsynced_count: int,
    local_footage_dir: str,
    avg_segment_mb: float,
    catchup_threshold: int,
    trickle_threshold: int,
    batch_hard_limit: int,
) -> int:
    """Compute the number of segments to fetch in the next sync cycle.

    Uses a hybrid algorithm: disk-aware cap combined with mode switching
    based on how many unsynced segments remain on the RPi.

    Modes:
    - catch-up (unsynced > catchup_threshold): max batch, download fast
    - trickle  (unsynced > trickle_threshold): medium batch
    - steady   (unsynced <= trickle_threshold): small batch, conserve disk

    The disk-aware cap ensures that downloading the batch will not exceed
    DISK_SAFETY_FACTOR of available free space on the local drive.

    Args:
        unsynced_count: Number of segments on the RPi not yet synced.
        local_footage_dir: Local directory to check for free disk space.
        avg_segment_mb: Rolling average of observed segment sizes in MB.
        catchup_threshold: Unsynced count above which catch-up batch applies.
        trickle_threshold: Unsynced count above which trickle batch applies.
        batch_hard_limit: Absolute maximum batch size regardless of other limits.

    Returns:
        Computed batch size, always at least 1.
    """
    try:
        available_mb = shutil.disk_usage(local_footage_dir).free / 1_048_576
    except OSError as disk_error:
        logger.error("Cannot check local disk usage: %s", disk_error)
        return 1

    max_by_disk = int((available_mb * DISK_SAFETY_FACTOR) / avg_segment_mb)
    max_by_disk = max(1, max_by_disk)

    if unsynced_count > catchup_threshold:
        desired_batch = batch_hard_limit
    elif unsynced_count > trickle_threshold:
        desired_batch = max(1, batch_hard_limit // 4)
    else:
        desired_batch = 1

    return min(desired_batch, max_by_disk, batch_hard_limit)


class SyncAgent:
    """Downloads new footage segments from the RPi and confirms receipt.

    Runs a polling loop that:
    1. Checks unsynced count on RPi and computes dynamic batch size
    2. Fetches a batch of unsynced segment metadata
    3. Downloads each segment to the local footage directory
    4. Confirms each successful download to the RPi API

    Attributes:
        config: Sync agent configuration loaded from sync.conf.
        avg_segment_mb: Rolling average of observed segment sizes, updated
            after each successful download.
    """

    def __init__(self, config: SyncConfig) -> None:
        """Initialise the sync agent with its configuration.

        Args:
            config: Sync agent configuration loaded from sync.conf.
        """
        self.config = config
        self.avg_segment_mb: float = DEFAULT_AVG_SEGMENT_MB

    def run(self) -> None:
        """Start the sync polling loop. Blocks until interrupted.

        Runs until KeyboardInterrupt or SIGTERM. Errors in individual
        cycles are logged and do not stop the loop.
        """
        logger.info(
            "Sync agent started — RPi: %s, local: %s",
            self.config.rpi_base_url,
            self.config.local_footage_dir,
        )
        Path(self.config.local_footage_dir).mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http_client:
            try:
                while True:
                    self._run_one_cycle(http_client)
                    time.sleep(self.config.sync_interval_seconds)
            except (KeyboardInterrupt, SystemExit):
                logger.info("Sync agent stopping")

    def _run_one_cycle(self, http_client: httpx.Client) -> None:
        """Execute one sync cycle: count → batch → download → confirm.

        Args:
            http_client: Shared httpx client for all requests in this cycle.
        """
        try:
            unsynced_count = self._fetch_unsynced_count(http_client)
        except httpx.HTTPError as network_error:
            logger.error("Cannot reach RPi: %s", network_error)
            return

        if unsynced_count == 0:
            logger.debug("No new segments to sync")
            return

        batch_size = compute_batch_size(
            unsynced_count=unsynced_count,
            local_footage_dir=self.config.local_footage_dir,
            avg_segment_mb=self.avg_segment_mb,
            catchup_threshold=self.config.catchup_threshold,
            trickle_threshold=self.config.trickle_threshold,
            batch_hard_limit=self.config.batch_hard_limit,
        )
        logger.info(
            "%d unsynced segments — fetching batch of %d", unsynced_count, batch_size
        )

        try:
            all_pending_segments = self._fetch_segment_list(
                http_client, batch_size=batch_size
            )
        except httpx.HTTPError as network_error:
            logger.error("Failed to fetch segment list: %s", network_error)
            return

        for segment in all_pending_segments:
            self._sync_one_segment(http_client, segment)

    def _fetch_unsynced_count(self, http_client: httpx.Client) -> int:
        """Query the RPi for the count of unsynced segments.

        Args:
            http_client: Shared httpx client.

        Returns:
            Integer count of unsynced completed segments on the RPi.

        Raises:
            httpx.HTTPError: On network or non-2xx response.
        """
        url = urljoin(self.config.rpi_base_url, "/api/segments/count?is_synced=false")
        response = http_client.get(url)
        response.raise_for_status()
        return int(response.json()["count"])

    def _fetch_segment_list(
        self,
        http_client: httpx.Client,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Fetch a batch of unsynced segment metadata from the RPi.

        Args:
            http_client: Shared httpx client.
            batch_size: Maximum number of segments to fetch.

        Returns:
            List of segment metadata dicts (id, path, start_ts, end_ts, size_bytes).

        Raises:
            httpx.HTTPError: On network or non-2xx response.
        """
        url = urljoin(
            self.config.rpi_base_url,
            f"/api/segments?is_synced=false&limit={batch_size}",
        )
        response = http_client.get(url)
        response.raise_for_status()
        return response.json()

    def _sync_one_segment(
        self,
        http_client: httpx.Client,
        segment: dict[str, Any],
    ) -> None:
        """Download one segment and confirm it to the RPi on success.

        Builds the local destination path mirroring the RPi's directory
        structure (YYYY/MM/DD/filename.mp4). Skips download if the file
        already exists locally with a non-zero size.

        Args:
            http_client: Shared httpx client.
            segment: Segment metadata dict from the RPi API.
        """
        segment_id = segment["id"]
        rpi_path = segment["path"]

        # rpi_path is an absolute path like /var/lib/cctv/footage/YYYY/MM/DD/file.mp4
        # Extract the relative part starting from the date directory
        path_parts = Path(rpi_path).parts
        try:
            footage_index = next(
                index for index, part in enumerate(path_parts) if part == "footage"
            )
            relative_path = Path(*path_parts[footage_index + 1:])
        except StopIteration:
            logger.error(
                "Segment %d has unexpected path format: %s", segment_id, rpi_path
            )
            return

        local_path = Path(self.config.local_footage_dir) / relative_path

        if local_path.exists() and local_path.stat().st_size > 0:
            logger.debug("Segment %d already exists locally, confirming", segment_id)
            self._confirm_synced(http_client, segment_id)
            return

        local_path.parent.mkdir(parents=True, exist_ok=True)
        download_url = urljoin(
            self.config.rpi_base_url,
            f"/footage/{relative_path.parts[0]}/{relative_path.parts[1]}"
            f"/{relative_path.parts[2]}/{relative_path.name}",
        )

        try:
            with http_client.stream(
                "GET",
                download_url,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            ) as download_response:
                download_response.raise_for_status()
                with local_path.open("wb") as output_file:
                    for chunk in download_response.iter_bytes(chunk_size=65_536):
                        output_file.write(chunk)
        except httpx.HTTPError as download_error:
            logger.error(
                "Failed to download segment %d (%s): %s",
                segment_id,
                relative_path.name,
                download_error,
            )
            if local_path.exists():
                local_path.unlink()
            return
        except OSError as file_error:
            logger.error(
                "Cannot write segment %d to %s: %s",
                segment_id,
                local_path,
                file_error,
            )
            return

        downloaded_mb = local_path.stat().st_size / 1_048_576
        self.avg_segment_mb = (
            ROLLING_AVERAGE_WEIGHT * downloaded_mb
            + (1 - ROLLING_AVERAGE_WEIGHT) * self.avg_segment_mb
        )
        logger.info(
            "Downloaded segment %d: %s (%.1f MB)",
            segment_id,
            relative_path.name,
            downloaded_mb,
        )
        self._confirm_synced(http_client, segment_id)

    def _confirm_synced(self, http_client: httpx.Client, segment_id: int) -> None:
        """Notify the RPi that a segment has been successfully downloaded.

        Args:
            http_client: Shared httpx client.
            segment_id: Database row ID of the downloaded segment.
        """
        confirm_url = urljoin(
            self.config.rpi_base_url,
            f"/api/segments/{segment_id}/synced",
        )
        try:
            confirm_response = http_client.post(confirm_url)
            confirm_response.raise_for_status()
            logger.debug("Confirmed segment %d as synced", segment_id)
        except httpx.HTTPError as confirm_error:
            logger.error(
                "Failed to confirm segment %d as synced: %s",
                segment_id,
                confirm_error,
            )
