"""Command-line interface for the sync tool."""

from __future__ import annotations

import argparse
import logging
from typing import List, Optional

from .config import load_config
from .exceptions import LockHeldError, SyncError
from .syncer import perform_sync, validate_runtime_environment
from .watcher import watch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synology-dhcp-dns-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Perform one DHCP-to-DNS sync.")
    sync_parser.add_argument("--config", required=True, help="Path to config INI file.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Render and validate without writing live zones.")

    validate_parser = subparsers.add_parser("validate-config", help="Validate config, paths, and live zone baselines.")
    validate_parser.add_argument("--config", required=True, help="Path to config INI file.")

    watch_parser = subparsers.add_parser("watch", help="Poll DHCP sources and sync when they change.")
    watch_parser.add_argument("--config", required=True, help="Path to config INI file.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("synology_dhcp_dns_sync")

    try:
        config = load_config(args.config)
        if args.command == "sync":
            result = perform_sync(config, dry_run=args.dry_run, logger=logger)
            logger.info(
                "Sync complete: changed=%s managed_records=%s skipped_records=%s forward_candidate=%s reverse_candidate=%s",
                result.changed,
                result.managed_records,
                result.skipped_records,
                result.forward_candidate_path,
                result.reverse_candidate_path,
            )
            return 0

        if args.command == "validate-config":
            for message in validate_runtime_environment(config):
                logger.info(message)
            logger.info("Config and runtime environment look usable.")
            return 0

        if args.command == "watch":
            watch(config, logger=logger)
            return 0
    except LockHeldError as exc:
        logger.info(str(exc))
        return 0
    except SyncError as exc:
        logger.error(str(exc))
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2
