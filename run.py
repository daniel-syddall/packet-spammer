"""Packet Spammer — entry point.

Usage:
    python run.py [--config path/to/config.toml]
"""

import argparse
import asyncio
import logging
from pathlib import Path

from base.config import load_config
from app.models.config import ProjectConfig
from app.host.runtime import HostRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("spammer")

DEFAULT_CONFIG = Path(__file__).parent / "config" / "config.toml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Packet Spammer")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to config.toml  (default: config/config.toml)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.config.exists():
        logger.error("Config file not found: %s", args.config)
        raise SystemExit(1)

    config = load_config(args.config, ProjectConfig)
    logger.info(
        "Starting — api=%s:%d  tasks=%d",
        config.api.host,
        config.api.port,
        len(config.tasks),
    )

    runtime = HostRuntime(config, config_path=args.config)
    asyncio.run(runtime.run())


if __name__ == "__main__":
    main()
