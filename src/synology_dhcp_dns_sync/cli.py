"""Command-line interface for the sync tool."""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional

from .config import load_config
from .exceptions import LockHeldError, SyncError
from .syncer import perform_sync, validate_runtime_environment
from .watcher import watch


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", required=True, help="Path to config INI file.")
    common.add_argument("--verbose", action="store_true", help="Also log runtime checks and unchanged runs.")
    common.add_argument(
        "--log-file",
        help=f"Write to this file, rotated at {LOG_MAX_BYTES // 1_000_000} MB with {LOG_BACKUP_COUNT} old files kept.",
    )

    parser = argparse.ArgumentParser(prog="synology-dhcp-dns-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", parents=[common], help="Perform one DHCP-to-DNS sync.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Render and validate without writing live zones.")
    sync_parser.add_argument("--force", action="store_true", help="Sync even if no input changed since the last run.")

    subparsers.add_parser("validate-config", parents=[common], help="Validate config, paths, and live zone baselines.")
    subparsers.add_parser("watch", parents=[common], help="Poll DHCP sources and sync when they change.")
    return parser


def configure_logging(*, verbose: bool, log_file: Optional[str]) -> None:
    handler: logging.Handler
    if log_file:
        handler = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose, log_file=args.log_file)
    logger = logging.getLogger("synology_dhcp_dns_sync")

    try:
        config = load_config(args.config)
        if args.command == "sync":
            result = perform_sync(config, dry_run=args.dry_run, force=args.force, logger=logger)
            if result.skipped_unchanged:
                return 0
            # Unchanged runs happen every minute; only log them when asked to.
            logger.log(
                logging.INFO if result.changed or result.dry_run else logging.DEBUG,
                "Sync complete: changed=%s managed_records=%s skipped_records=%s",
                result.changed,
                result.managed_records,
                result.skipped_records,
            )
            if result.dry_run:
                logger.info(
                    "Candidates kept: forward=%s reverse=%s",
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
    except Exception:
        # Log the traceback to the log file too, and exit non-zero so DSM's
        # "abnormal termination" email fires.
        logger.exception("Unexpected error.")
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2
