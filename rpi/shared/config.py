from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CameraConfig:
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 15
    sensor_mode: int = 0
    awb_mode: str = "auto"


@dataclass
class RecordingConfig:
    segment_duration_minutes: int = 10
    footage_dir: str = "/var/lib/cctv/footage"
    bitrate_bps: int = 200_000
    encoder: str = "h264"


@dataclass
class StreamConfig:
    stream_fps: int = 5
    stream_resolution: tuple[int, int] = (640, 360)
    jpeg_quality: int = 70


@dataclass
class StorageConfig:
    state_db: str = "/var/lib/cctv/state.db"
    delete_threshold_pct: int = 90
    check_interval_seconds: int = 60
    min_segment_age_hours: int = 2
    require_synced_for_deletion: bool = True


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    footage_page_size: int = 50


@dataclass
class MotionConfig:
    enabled: bool = False
    pixel_diff_threshold: int = 25
    motion_ratio_threshold: float = 0.02
    cooldown_seconds: int = 60
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    motion: MotionConfig = field(default_factory=MotionConfig)


def load_config(config_path: Path) -> AppConfig:
    """
    Load and parse the TOML configuration file into an AppConfig instance.

    Args:
        config_path: Filesystem path to cctv.conf.

    Returns:
        Populated AppConfig dataclass tree.

    Raises:
        FileNotFoundError: If config_path does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
        ValueError: If a config value is outside its valid range.
    """
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)

    camera_raw = raw.get("camera", {})
    resolution_raw = camera_raw.get("resolution", [1280, 720])
    camera = CameraConfig(
        resolution=(resolution_raw[0], resolution_raw[1]),
        fps=camera_raw.get("fps", 15),
        sensor_mode=camera_raw.get("sensor_mode", 0),
        awb_mode=camera_raw.get("awb_mode", "auto"),
    )

    recording_raw = raw.get("recording", {})
    encoder_value = recording_raw.get("encoder", "h264")
    if encoder_value not in {"h264", "h265"}:
        raise ValueError(
            f"recording.encoder must be 'h264' or 'h265' (got {encoder_value!r})"
        )
    bitrate_bps = recording_raw.get("bitrate_bps", 200_000)
    if bitrate_bps < 50_000:
        raise ValueError(
            f"recording.bitrate_bps must be >= 50000 (got {bitrate_bps})"
        )
    recording = RecordingConfig(
        segment_duration_minutes=recording_raw.get("segment_duration_minutes", 10),
        footage_dir=recording_raw.get("footage_dir", "/var/lib/cctv/footage"),
        bitrate_bps=bitrate_bps,
        encoder=encoder_value,
    )

    stream_raw = raw.get("stream", {})
    stream_resolution_raw = stream_raw.get("stream_resolution", [640, 360])
    jpeg_quality = stream_raw.get("jpeg_quality", 70)
    if not 1 <= jpeg_quality <= 95:
        raise ValueError(f"stream.jpeg_quality must be 1–95 (got {jpeg_quality})")

    stream = StreamConfig(
        stream_fps=stream_raw.get("stream_fps", 5),
        stream_resolution=(stream_resolution_raw[0], stream_resolution_raw[1]),
        jpeg_quality=jpeg_quality,
    )

    storage_raw = raw.get("storage", {})
    delete_threshold_pct = storage_raw.get("delete_threshold_pct", 90)
    if not 1 <= delete_threshold_pct <= 99:
        raise ValueError(
            f"storage.delete_threshold_pct must be 1–99 (got {delete_threshold_pct})"
        )
    storage = StorageConfig(
        state_db=storage_raw.get("state_db", "/var/lib/cctv/state.db"),
        delete_threshold_pct=delete_threshold_pct,
        check_interval_seconds=storage_raw.get("check_interval_seconds", 60),
        min_segment_age_hours=storage_raw.get("min_segment_age_hours", 2),
        require_synced_for_deletion=storage_raw.get(
            "require_synced_for_deletion", True
        ),
    )

    web_raw = raw.get("web", {})
    web = WebConfig(
        host=web_raw.get("host", "0.0.0.0"),
        port=web_raw.get("port", 8080),
        footage_page_size=web_raw.get("footage_page_size", 50),
    )

    motion_raw = raw.get("motion", {})
    motion = MotionConfig(
        enabled=motion_raw.get("enabled", False),
        pixel_diff_threshold=motion_raw.get("pixel_diff_threshold", 25),
        motion_ratio_threshold=motion_raw.get("motion_ratio_threshold", 0.02),
        cooldown_seconds=motion_raw.get("cooldown_seconds", 60),
        ntfy_topic=motion_raw.get("ntfy_topic", ""),
        ntfy_server=motion_raw.get("ntfy_server", "https://ntfy.sh"),
    )

    return AppConfig(
        camera=camera,
        recording=recording,
        stream=stream,
        storage=storage,
        web=web,
        motion=motion,
    )
