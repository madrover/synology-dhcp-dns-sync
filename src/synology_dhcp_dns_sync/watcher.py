"""Polling watcher for DHCP source changes."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import SyncConfig
from .exceptions import SyncError
from .syncer import perform_sync


def watch(config: SyncConfig, *, logger: Optional[logging.Logger] = None) -> None:
    """Poll DHCP source files and trigger sync when they change."""

    log = logger or logging.getLogger(__name__)
    previous_snapshot: Optional[Dict[Path, int]] = None

    while True:
        current_snapshot = _collect_snapshot(config.existing_dhcp_files())
        if previous_snapshot is None or current_snapshot != previous_snapshot:
            log.info("Detected DHCP source change; running sync.")
            try:
                perform_sync(config, dry_run=False, logger=log)
            except SyncError:
                log.exception("Sync attempt failed; watcher will continue running.")
            except Exception:
                log.exception("Unexpected watcher error; watcher will continue running.")
            else:
                previous_snapshot = current_snapshot
        time.sleep(config.poll_interval_seconds)


def _collect_snapshot(source_paths: Tuple[Path, ...]) -> Dict[Path, int]:
    return {
        path: path.stat().st_mtime_ns
        for path in source_paths
        if path.exists()
    }
