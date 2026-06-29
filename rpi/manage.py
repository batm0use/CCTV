from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.config import AppConfig

DEFAULT_CONFIG_PATH: Path = Path("/app/cctv.conf")
LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging(level: str = "INFO") -> None:
    """
    Configure root logger to write to stdout.

    Args:
        level: Logging level name (e.g. "INFO", "DEBUG", "WARNING").
    """
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
    )


def _load_config(config_path: Path) -> AppConfig:
    """
    Load AppConfig from disk, printing a helpful message on failure.

    Args:
        config_path: Path to cctv.conf.

    Returns:
        AppConfig instance.
    """
    from shared.config import load_config

    if not config_path.exists():
        print(
            f"ERROR: config file not found at {config_path}\n"
            "Copy cctv.conf.example to cctv.conf and edit it before starting.",
            file=sys.stderr,
        )
        sys.exit(1)

    return load_config(config_path)


def cmd_init_db(args: argparse.Namespace) -> None:
    """
    Create the SQLite state database schema.

    Safe to run multiple times; existing data is not modified.

    Args:
        args: Parsed CLI arguments (expects args.config).
    """
    config = _load_config(args.config)
    from shared.state import init_schema

    init_schema(config.storage.state_db)
    print(f"Database initialised at {config.storage.state_db}")


def _purge_incomplete_segments() -> None:
    """
    Delete files and DB records for any segment not finalised before last exit.

    Runs once at startup after db.init(). Targets rows where end_timestamp IS
    NULL — these were being recorded when the process was killed and the
    corresponding MP4 files are corrupt or truncated.
    """
    from shared import db, state

    logger = logging.getLogger(__name__)
    all_incomplete = state.fetch_incomplete_segments(db.get())

    if not all_incomplete:
        return

    for row in all_incomplete:
        segment_file = Path(row["path"])
        try:
            segment_file.unlink(missing_ok=True)
        except OSError as delete_error:
            logger.warning(
                "Could not delete incomplete segment %s: %s",
                segment_file,
                delete_error,
            )
        state.delete_segment_record(db.get(), row["id"])
        logger.info("Purged incomplete segment %s", segment_file.name)


def cmd_run_main(args: argparse.Namespace) -> None:
    """
    Start the recorder thread and the web server (Uvicorn/FastAPI).

    Blocks until SIGTERM or KeyboardInterrupt. On shutdown, signals the
    recorder to finish the current segment before exiting.

    Args:
        args: Parsed CLI arguments (expects args.config).
    """
    _setup_logging()
    config = _load_config(args.config)

    from recorder.recorder import Recorder
    from shared import db

    db.init(config.storage.state_db)
    _purge_incomplete_segments()
    recorder = Recorder(config=config)

    stop_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        recorder.stop()
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    recorder_thread = threading.Thread(
        target=recorder.start, daemon=False, name="recorder"
    )
    recorder_thread.start()

    import uvicorn

    from web.app import build_app

    application = build_app(config=config)

    server_config = uvicorn.Config(
        app=application,
        host=config.web.host,
        port=config.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config=server_config)
    server.install_signal_handlers = lambda: None

    server.run()

    stop_event.wait()
    recorder_thread.join(timeout=60)
    db.close()


def cmd_run_storage(args: argparse.Namespace) -> None:
    """
    Start the storage manager loop.

    Runs until SIGTERM or KeyboardInterrupt.

    Args:
        args: Parsed CLI arguments (expects args.config).
    """
    _setup_logging()
    config = _load_config(args.config)

    from shared import db
    from storage.manager import StorageManager

    db.init(config.storage.state_db)
    manager = StorageManager(config=config)
    manager.run()


def cmd_status(args: argparse.Namespace) -> None:
    """
    Print a brief status summary from the database.

    Args:
        args: Parsed CLI arguments (expects args.config).
    """
    import shutil

    config = _load_config(args.config)
    from shared import db
    from shared.state import count_unsynced_segments

    db.init(config.storage.state_db)
    unsynced_count = count_unsynced_segments(db.get())
    db.close()

    disk_usage = shutil.disk_usage(config.recording.footage_dir)
    used_pct = disk_usage.used / disk_usage.total * 100

    print(f"Unsynced segments : {unsynced_count}")
    print(
        f"Disk usage        : {disk_usage.used // 1_073_741_824} GB / "
        f"{disk_usage.total // 1_073_741_824} GB ({used_pct:.1f}%)"
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    """
    Build the top-level CLI argument parser with subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="manage.py", description="CCTV management CLI"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to cctv.conf (default: /app/cctv.conf)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Initialise the SQLite state database")
    subparsers.add_parser("run-main", help="Start recorder + web server")
    subparsers.add_parser("run-storage", help="Start storage manager")
    subparsers.add_parser("status", help="Print status summary")

    return parser


if __name__ == "__main__":
    argument_parser = _build_argument_parser()
    parsed_args = argument_parser.parse_args()

    command_handlers = {
        "init-db": cmd_init_db,
        "run-main": cmd_run_main,
        "run-storage": cmd_run_storage,
        "status": cmd_status,
    }
    command_handlers[parsed_args.command](parsed_args)
