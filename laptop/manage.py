from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

DEFAULT_CONFIG_PATH: Path = Path("/app/sync.conf")
LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging() -> None:
    """Configure root logger to write to stdout at INFO level."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format=LOG_FORMAT,
    )


def cmd_run_sync(args: argparse.Namespace) -> None:
    """Start the footage sync polling loop.

    Args:
        args: Parsed CLI arguments (expects args.config).
    """
    _setup_logging()

    if not args.config.exists():
        print(
            f"ERROR: config file not found at {args.config}\n"
            "Copy sync.conf.example to sync.conf"
            " and fill in rpi_base_url and local_footage_dir.",
            file=sys.stderr,
        )
        sys.exit(1)

    from sync.agent import SyncAgent, load_sync_config

    sync_config = load_sync_config(args.config)
    agent = SyncAgent(config=sync_config)
    agent.run()


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="CCTV laptop sync agent CLI",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to sync.conf (default: /app/sync.conf)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-sync", help="Start the footage sync agent")

    return parser


if __name__ == "__main__":
    argument_parser = _build_argument_parser()
    parsed_args = argument_parser.parse_args()

    if parsed_args.command == "run-sync":
        cmd_run_sync(parsed_args)
