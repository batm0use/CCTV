from __future__ import annotations

import io
import logging
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

from recorder.motion import MotionState, detect_motion, send_ntfy_notification
from shared import db, frame_buffer, state
from shared.config import AppConfig
from shared.paths import ensure_segment_directory, segment_path

logger = logging.getLogger(__name__)

SEGMENT_FINALISE_TIMEOUT_SECONDS: int = 30


def _apply_faststart(segment_path: Path) -> None:
    """
    Re-mux an MP4 segment to move the moov atom to the front.

    Required for browser seeking — without faststart the browser cannot
    seek until the entire file is downloaded. Runs ffmpeg copy (no
    transcoding) so it completes in under a second on the RPi.

    Args:
        segment_path: Path to the MP4 file to re-mux in place.
    """
    temp_path = segment_path.with_suffix(".tmp.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(segment_path),
                "-c", "copy", "-movflags", "+faststart",
                str(temp_path),
            ],
            check=True,
            capture_output=True,
        )
        temp_path.rename(segment_path)
    except subprocess.CalledProcessError as ffmpeg_error:
        logger.warning(
            "faststart re-mux failed for %s: %s",
            segment_path.name,
            ffmpeg_error.stderr.decode(errors="replace"),
        )
        if temp_path.exists():
            temp_path.unlink()


class Recorder:
    """
    Manages continuous H.264 recording and low-res JPEG preview capture.

    Owns the sole Picamera2 instance for the process. Segments are written
    as MP4 files, rotated on wall-clock boundaries (e.g. every 10 minutes
    at :00, :10, :20 ...). A low-resolution JPEG stream is captured
    concurrently and written into the shared frame_buffer for MJPEG streaming.

    Attributes:
        config: Application configuration loaded from cctv.conf.
    """

    def __init__(self, config: AppConfig) -> None:
        """
        Initialise the recorder with application config.

        Args:
            config: Application configuration loaded from cctv.conf.
        """
        self.config = config
        self._stop_event = threading.Event()
        self._camera: Picamera2 | None = None
        self._current_segment_id: int | None = None
        self._current_segment_path: Path | None = None
        self._current_segment_start: datetime | None = None
        self._encoder: H264Encoder | None = None
        self._motion_state: MotionState = MotionState()

    def start(self) -> None:
        """
        Open the camera, configure streams, and begin recording.

        Configures two simultaneous streams:
        - main: full-resolution H.264 video written to MP4 segment files
        - lores: low-resolution preview for JPEG capture into frame_buffer

        Raises:
            RuntimeError: If the camera cannot be opened or configured.
        """
        self._camera = Picamera2()

        main_stream_config = {
            "size": self.config.camera.resolution,
            "format": "YUV420",
        }
        lores_stream_config = {
            "size": self.config.stream.stream_resolution,
            "format": "YUV420",
        }
        video_config = self._camera.create_video_configuration(
            main=main_stream_config,
            lores=lores_stream_config,
        )
        self._camera.configure(video_config)
        self._camera.start()

        time.sleep(2)
        logger.info("Camera started at %s", self.config.camera.resolution)

        self._begin_new_segment()
        self._run_loop()

    def stop(self) -> None:
        """
        Signal the recording loop to stop after the current segment.

        Thread-safe. Can be called from any thread.
        """
        logger.info("Stop requested; finishing current segment")
        self._stop_event.set()

    def _run_loop(self) -> None:
        """
        Main recording loop: rotate segments and capture preview frames.

        Runs until stop() is called. On each iteration checks whether the
        current segment has reached its configured duration, and if so
        rotates to a new segment file. Also captures a low-res JPEG frame
        for the MJPEG stream at the configured stream_fps rate.
        """
        frame_interval_seconds: float = 1.0 / self.config.stream.stream_fps
        last_frame_capture_time: float = 0.0

        while not self._stop_event.is_set():
            current_time = time.monotonic()

            if self._should_rotate_segment():
                self._rotate_segment()

            if current_time - last_frame_capture_time >= frame_interval_seconds:
                self._capture_preview_frame()
                last_frame_capture_time = current_time

            time.sleep(0.1)

        self._finalise_current_segment()
        if self._camera is not None:
            self._camera.stop()
            self._camera.close()
            logger.info("Camera closed")

    def _should_rotate_segment(self) -> bool:
        """
        Return True if the current segment has exceeded its configured duration.

        Returns:
            True if recording has run longer than segment_duration_minutes,
            False otherwise or if no segment is currently active.
        """
        if self._current_segment_start is None:
            return False

        elapsed_minutes = (
            datetime.now(tz=UTC) - self._current_segment_start
        ).total_seconds() / 60.0

        return elapsed_minutes >= self.config.recording.segment_duration_minutes

    def _begin_new_segment(self) -> None:
        """
        Start recording a new segment file.

        Creates the date-based output directory, inserts a DB row, and
        starts the H264Encoder writing to the new file.

        Raises:
            OSError: If the output directory or file cannot be created.
            sqlite3.OperationalError: If the DB insert fails.
        """
        segment_start_time = datetime.now(tz=UTC)
        new_segment_path = segment_path(
            self.config.recording.footage_dir,
            segment_start_time,
        )
        ensure_segment_directory(
            self.config.recording.footage_dir,
            segment_start_time,
        )

        self._current_segment_id = state.insert_segment(
            connection=db.get(),
            path=str(new_segment_path),
            start_timestamp=segment_start_time,
        )
        self._current_segment_path = new_segment_path
        self._current_segment_start = segment_start_time

        if self._camera is None:
            raise RuntimeError("Camera not initialised")
        bitrate = self.config.recording.bitrate_bps
        if self.config.recording.encoder == "h265":
            from picamera2.encoders import H265Encoder  # noqa: PLC0415
            self._encoder = H265Encoder(bitrate=bitrate)
        else:
            self._encoder = H264Encoder(bitrate=bitrate)
        output = FfmpegOutput(str(new_segment_path))
        self._camera.start_recording(self._encoder, output)

        logger.info("Started segment %s", new_segment_path.name)

    def _rotate_segment(self) -> None:
        """
        Stop the current segment, finalise its DB record, and start a new one.

        Raises:
            sqlite3.OperationalError: If the DB finalise update fails.
            OSError: If the new segment file cannot be created.
        """
        self._finalise_current_segment()
        self._begin_new_segment()

    def _finalise_current_segment(self) -> None:
        """
        Stop encoding the current segment and write its metadata to the DB.

        Raises:
            sqlite3.OperationalError: If the DB update fails.
        """
        if self._current_segment_id is None or self._current_segment_path is None:
            return

        if self._camera is None:
            raise RuntimeError("Camera not initialised")
        self._camera.stop_recording()
        _apply_faststart(self._current_segment_path)
        segment_end_time = datetime.now(tz=UTC)
        segment_file_size = (
            self._current_segment_path.stat().st_size
            if self._current_segment_path.exists()
            else 0
        )

        state.finalise_segment(
            connection=db.get(),
            segment_id=self._current_segment_id,
            end_timestamp=segment_end_time,
            size_bytes=segment_file_size,
        )
        logger.info(
            "Finalised segment %s (%d bytes)",
            self._current_segment_path.name,
            segment_file_size,
        )

        self._current_segment_id = None
        self._current_segment_path = None
        self._current_segment_start = None
        self._encoder = None

    def _capture_preview_frame(self) -> None:
        """
        Capture one JPEG frame from the lores stream into frame_buffer.

        When motion detection is enabled, also captures the raw lores array and
        runs frame differencing on the Y-plane. Sends an ntfy notification if
        motion is detected and the cooldown has elapsed. Silently skips if the
        camera is not ready or capture fails, so preview errors never interrupt
        the recording loop.
        """
        if self._camera is None:
            return

        try:
            jpeg_buffer = io.BytesIO()
            self._camera.capture_file(jpeg_buffer, name="lores", format="jpeg")
            frame_buffer.write(jpeg_buffer.getvalue())

            if self.config.motion.enabled:
                raw_array: npt.NDArray[np.uint8] = self._camera.capture_array("lores")
                stream_h = self.config.stream.stream_resolution[1]
                y_plane = raw_array[:stream_h, :]
                if detect_motion(y_plane, self._motion_state, self.config.motion):
                    send_ntfy_notification(self.config.motion, self._motion_state)
        except Exception as capture_error:
            logger.warning("Preview frame capture failed: %s", capture_error)
