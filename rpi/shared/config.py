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


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    footage_page_size: int = 50


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)


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
    recording = RecordingConfig(
        segment_duration_minutes=recording_raw.get("segment_duration_minutes", 10),
        footage_dir=recording_raw.get("footage_dir", "/var/lib/cctv/footage"),
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
    storage = StorageConfig(
        state_db=storage_raw.get("state_db", "/var/lib/cctv/state.db"),
        delete_threshold_pct=storage_raw.get("delete_threshold_pct", 90),
        check_interval_seconds=storage_raw.get("check_interval_seconds", 60),
        min_segment_age_hours=storage_raw.get("min_segment_age_hours", 2),
    )

    web_raw = raw.get("web", {})
    web = WebConfig(
        host=web_raw.get("host", "0.0.0.0"),
        port=web_raw.get("port", 8080),
        footage_page_size=web_raw.get("footage_page_size", 50),
    )

    return AppConfig(
        camera=camera,
        recording=recording,
        stream=stream,
        storage=storage,
        web=web,
    )
