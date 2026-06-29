from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from shared import db
from shared.config import AppConfig
from shared.state import (
    delete_segment_record,
    fetch_oldest_segments,
    fetch_oldest_synced_segments,
)

logger = logging.getLogger(__name__)

DELETION_BATCH_SIZE: int = 10


class StorageManager:
    """
    Monitors disk usage and deletes the oldest eligible segments when the
    configured threshold is exceeded.

    Runs as a separate Docker service (cctv-storage). Does not push or
    sync footage — that is the responsibility of the laptop sync agent.
    In synced mode (require_synced_for_deletion = True) only deletes
    segments marked is_synced = 1. In standalone mode deletes the oldest
    completed segments regardless of sync status, enabling RPi-only
    deployments without a laptop agent.

    Attributes:
        config: Application configuration loaded from cctv.conf.
    """

    def __init__(self, config: AppConfig) -> None:
        """
        Initialise the storage manager with application config.

        Args:
            config: Application configuration loaded from cctv.conf.
        """
        self.config = config

    def run(self) -> None:
        """
        Start the polling loop. Blocks until KeyboardInterrupt or SIGTERM.

        Wakes every check_interval_seconds and checks disk usage. If usage
        exceeds delete_threshold_pct, deletes the oldest synced segments
        in batches of DELETION_BATCH_SIZE until usage drops below the
        threshold or no more eligible segments exist.
        """
        logger.info(
            "Storage manager started (delete threshold: %d%%)",
            self.config.storage.delete_threshold_pct,
        )

        try:
            while True:
                self._check_and_clean()
                time.sleep(self.config.storage.check_interval_seconds)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Storage manager stopping")
            raise
        finally:
            db.close()

    def _check_and_clean(self) -> None:
        """
        Check disk usage and delete eligible segments if over threshold.
        """
        footage_dir = self.config.recording.footage_dir

        try:
            disk_usage = shutil.disk_usage(footage_dir)
        except OSError:
            logger.exception("Cannot read disk usage for %s", footage_dir)
            return

        used_pct = disk_usage.used / disk_usage.total * 100
        logger.debug("Disk usage: %.1f%%", used_pct)

        if used_pct < self.config.storage.delete_threshold_pct:
            return

        if self.config.storage.require_synced_for_deletion:
            logger.warning(
                "Disk at %.1f%% (threshold: %d%%) — deleting oldest synced segments",
                used_pct,
                self.config.storage.delete_threshold_pct,
            )
        else:
            logger.warning(
                "Disk at %.1f%% (threshold: %d%%) — deleting oldest segments"
                " (standalone mode)",
                used_pct,
                self.config.storage.delete_threshold_pct,
            )
        self._delete_oldest_segments()

    def _delete_oldest_segments(self) -> None:
        """
        Delete the oldest eligible segment files and their DB records.

        In synced mode (require_synced_for_deletion = True) fetches only
        segments marked is_synced = 1. In standalone mode fetches any
        completed segment. Deletes up to DELETION_BATCH_SIZE files older
        than min_segment_age_hours and removes their DB rows. Logs a warning
        if no eligible segments are found.
        """
        if self.config.storage.require_synced_for_deletion:
            all_eligible_segments = fetch_oldest_synced_segments(
                connection=db.get(),
                min_age_hours=self.config.storage.min_segment_age_hours,
                limit=DELETION_BATCH_SIZE,
            )
        else:
            all_eligible_segments = fetch_oldest_segments(
                connection=db.get(),
                min_age_hours=self.config.storage.min_segment_age_hours,
                limit=DELETION_BATCH_SIZE,
            )

        if not all_eligible_segments:
            if self.config.storage.require_synced_for_deletion:
                logger.warning(
                    "Disk over threshold but no synced segments are old enough"
                    " to delete. Ensure the laptop sync agent is running and"
                    " confirming downloads."
                )
            else:
                logger.warning(
                    "Disk over threshold but no segments are old enough to delete. "
                    "Minimum age is %d hours.",
                    self.config.storage.min_segment_age_hours,
                )
            return

        for segment in all_eligible_segments:
            segment_file = Path(segment["path"])
            try:
                if segment_file.exists():
                    segment_file.unlink()
                    logger.info(
                        "Deleted local segment %s (%d bytes)",
                        segment_file.name,
                        segment["size_bytes"] or 0,
                    )
            except OSError:
                logger.exception("Failed to delete %s", segment_file)
                continue

            delete_segment_record(connection=db.get(), segment_id=segment["id"])
