"""Core sync workflow."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .config import SyncConfig
from .dhcp import discover_interface_names, parse_dhcp_sources, resolve_conflicts
from .exceptions import ReloadError, SyncError
from .locking import acquire_process_lock
from .models import LeaseRecord, SyncResult, ZoneCandidate
from .zone import (
    build_forward_zone,
    build_reverse_zone,
    collect_static_claims,
    filter_leases_for_static_claims,
    increment_soa_serial,
    managed_forward_records,
    read_zone_text,
    run_named_checkzone,
    strip_managed_records,
    validate_managed_leases,
    validate_zone_baseline,
)

# Live-zone backups kept per zone in work_dir; each changed sync adds one.
BACKUPS_TO_KEEP = 20
# Fingerprint of the last successful run's inputs; delete it to force a full sync.
STATE_FILE_NAME = "sync-state.json"


def validate_runtime_environment(config: SyncConfig) -> List[str]:
    """Validate that required files and directories exist."""

    messages: List[str] = []
    if not config.forward_zone_path.is_file():
        raise SyncError(f"Forward zone file does not exist: {config.forward_zone_path}")
    if not config.reverse_zone_path.is_file():
        raise SyncError(f"Reverse zone file does not exist: {config.reverse_zone_path}")

    dhcp_files = config.existing_dhcp_files()
    if not dhcp_files:
        raise SyncError("No configured DHCP source files exist.")
    messages.append(f"Using DHCP sources: {', '.join(str(path) for path in dhcp_files)}")

    if config.named_checkzone_path.exists():
        if not os.access(config.named_checkzone_path, os.X_OK):
            raise SyncError(f"named-checkzone is not executable: {config.named_checkzone_path}")
        messages.append(f"Using named-checkzone: {config.named_checkzone_path}")
    else:
        messages.append(f"named-checkzone not found at {config.named_checkzone_path}; external validation will be skipped.")

    if not config.reload_script_path.exists():
        raise SyncError(f"Reload script does not exist: {config.reload_script_path}")
    if not os.access(config.reload_script_path, os.X_OK):
        raise SyncError(f"Reload script is not executable: {config.reload_script_path}")
    messages.append(f"Using reload script: {config.reload_script_path}")
    messages.append(f"Using sync lock: {config.effective_lock_path}")

    validate_zone_baseline(config.forward_zone, read_zone_text(config.forward_zone_path))
    validate_zone_baseline(config.reverse_zone, read_zone_text(config.reverse_zone_path))
    messages.append("Forward and reverse zone baselines are structurally valid.")

    return messages


def perform_sync(
    config: SyncConfig,
    *,
    dry_run: bool = False,
    force: bool = False,
    logger: Optional[logging.Logger] = None,
) -> SyncResult:
    """Perform a full DHCP to DNS sync.

    Unless forced, a run whose inputs (DHCP sources, live zones, config) are
    unchanged since the last successful run returns early without parsing.
    """

    log = logger or logging.getLogger(__name__)
    with acquire_process_lock(config.effective_lock_path):
        if not dry_run and not force and _read_state(config) == _input_state(config):
            log.debug("DHCP sources, zones and config unchanged since the last sync; skipping.")
            return SyncResult(changed=False, dry_run=False, managed_records=0, skipped_records=0, skipped_unchanged=True)
        result = _sync_locked(config, dry_run=dry_run, log=log)
        if not dry_run:
            _write_state(config)
        return result


def _sync_locked(config: SyncConfig, *, dry_run: bool, log: logging.Logger) -> SyncResult:
    validation_messages = validate_runtime_environment(config)
    for message in validation_messages:
        log.debug(message)

    config.work_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    forward_live_text = read_zone_text(config.forward_zone_path)
    reverse_live_text = read_zone_text(config.reverse_zone_path)
    validate_zone_baseline(config.forward_zone, forward_live_text)
    validate_zone_baseline(config.reverse_zone, reverse_live_text)

    forward_static_text, forward_static_records = strip_managed_records(
        forward_live_text,
        zone_name=config.forward_zone,
    )
    reverse_static_text, reverse_static_records = strip_managed_records(
        reverse_live_text,
        zone_name=config.reverse_zone,
    )
    static_forward_owners, static_reverse_owners = collect_static_claims(
        forward_static_records,
        reverse_static_records,
    )

    leases = parse_dhcp_sources(
        config.existing_dhcp_files(),
        domain=config.normalized_domain,
        interface_names=discover_interface_names(),
        ttl=config.dynamic_ttl,
    )
    managed_leases, skipped_records = filter_leases_for_static_claims(
        leases,
        reverse_zone=config.reverse_zone,
        static_forward_owners=static_forward_owners,
        static_reverse_owners=static_reverse_owners,
    )
    managed_leases, conflicting = resolve_conflicts(managed_leases)
    for lease in conflicting:
        log.warning(
            "Skipping %s (%s) from %s:%s: hostname or IP already taken by a preferred entry.",
            lease.fqdn,
            lease.ip,
            lease.source_path,
            lease.line_number,
        )
    skipped_records += len(conflicting)
    validate_managed_leases(managed_leases)

    # Compare with the serial untouched: bumping first would make every run look like a change.
    forward_candidate_text = build_forward_zone(forward_static_text, managed_leases, bump_serial=False)
    reverse_candidate_text = build_reverse_zone(reverse_static_text, managed_leases, bump_serial=False)
    changed = (
        forward_candidate_text != forward_live_text
        or reverse_candidate_text != reverse_live_text
    )

    if changed:
        log.info(
            "Zone changes: %s",
            _describe_changes(
                managed_forward_records(forward_live_text, zone_name=config.forward_zone),
                managed_leases,
            ),
        )

    if not changed and not dry_run:
        _prune_work_dir(config)
        log.debug("No zone changes detected; skipping zone update and reload.")
        return SyncResult(
            changed=False,
            dry_run=False,
            managed_records=len(managed_leases),
            skipped_records=skipped_records,
            validation_messages=validation_messages,
        )

    if changed:
        forward_candidate_text = increment_soa_serial(forward_candidate_text)
        reverse_candidate_text = increment_soa_serial(reverse_candidate_text)

    forward_candidate = _write_candidate(
        config.forward_zone_path,
        config.work_dir,
        timestamp,
        "forward",
        forward_candidate_text,
    )
    reverse_candidate = _write_candidate(
        config.reverse_zone_path,
        config.work_dir,
        timestamp,
        "reverse",
        reverse_candidate_text,
    )

    validation_messages.append(
        run_named_checkzone(config.named_checkzone_path, config.forward_zone, forward_candidate.candidate_path)
    )
    validation_messages.append(
        run_named_checkzone(config.named_checkzone_path, config.reverse_zone, reverse_candidate.candidate_path)
    )

    if dry_run:
        log.info("Dry-run complete; live zones were not modified.")
        return SyncResult(
            changed=changed,
            dry_run=dry_run,
            managed_records=len(managed_leases),
            skipped_records=skipped_records,
            forward_candidate_path=forward_candidate.candidate_path,
            reverse_candidate_path=reverse_candidate.candidate_path,
            validation_messages=validation_messages,
        )

    _backup_live_zone(config.forward_zone_path, forward_candidate.backup_path)
    _backup_live_zone(config.reverse_zone_path, reverse_candidate.backup_path)

    replaced_forward = False
    replaced_reverse = False
    try:
        _replace_candidate(forward_candidate)
        replaced_forward = True
        _replace_candidate(reverse_candidate)
        replaced_reverse = True
        _reload_dns(config.reload_script_path)
    except Exception:
        log.exception("Sync failed after candidate generation; attempting rollback.")
        if replaced_forward:
            _restore_backup(config.forward_zone_path, forward_candidate.backup_path)
        if replaced_reverse:
            _restore_backup(config.reverse_zone_path, reverse_candidate.backup_path)
        if replaced_forward or replaced_reverse:
            try:
                _reload_dns(config.reload_script_path)
            except Exception:
                log.exception("Rollback reload also failed.")
        raise

    _prune_work_dir(config)
    return SyncResult(
        changed=True,
        dry_run=False,
        managed_records=len(managed_leases),
        skipped_records=skipped_records,
        validation_messages=validation_messages,
    )


def _state_path(config: SyncConfig) -> Path:
    return config.work_dir / STATE_FILE_NAME


def _input_state(config: SyncConfig) -> Dict[str, object]:
    """Everything a sync result depends on: code version, config and input file mtimes."""

    inputs = [*config.existing_dhcp_files(), config.forward_zone_path, config.reverse_zone_path]
    return {
        "version": __version__,
        "config": repr(config),
        "mtimes": {str(path): path.stat().st_mtime_ns for path in inputs if path.exists()},
    }


def _read_state(config: SyncConfig) -> Optional[Dict[str, object]]:
    try:
        return json.loads(_state_path(config).read_text())
    except (OSError, ValueError):
        return None


def _write_state(config: SyncConfig) -> None:
    # Taken after the run, so the zone mtimes include this run's own writes.
    _state_path(config).write_text(json.dumps(_input_state(config), sort_keys=True))


def _describe_changes(previous: Dict[str, str], leases: List[LeaseRecord]) -> str:
    current = {lease.fqdn: str(lease.ip) for lease in leases}
    parts = []
    added = [f"{name} {current[name]}" for name in sorted(current) if name not in previous]
    removed = [f"{name} {previous[name]}" for name in sorted(previous) if name not in current]
    moved = [
        f"{name} {previous[name]} -> {current[name]}"
        for name in sorted(current)
        if name in previous and previous[name] != current[name]
    ]
    if added:
        parts.append("added " + ", ".join(added))
    if removed:
        parts.append("removed " + ", ".join(removed))
    if moved:
        parts.append("moved " + ", ".join(moved))
    # Same hosts and addresses, different text: TTL, case or record formatting.
    return "; ".join(parts) or "records rewritten (TTL or formatting)"


def _prune_work_dir(config: SyncConfig) -> None:
    """Delete candidate files and all but the newest backups of each zone.

    Candidates are only kept by dry runs, for inspection; the next scheduled
    run removes them. Timestamps in the file names sort chronologically.
    """

    for zone_path, label in ((config.forward_zone_path, "forward"), (config.reverse_zone_path, "reverse")):
        for candidate_path in config.work_dir.glob(f"{zone_path.name}.*.{label}.candidate"):
            candidate_path.unlink()
        backups = sorted(config.work_dir.glob(f"{zone_path.name}.*.{label}.bak"))
        for backup_path in backups[:-BACKUPS_TO_KEEP]:
            backup_path.unlink()


def _write_candidate(
    live_path: Path,
    work_dir: Path,
    timestamp: str,
    label: str,
    content: str,
) -> ZoneCandidate:
    candidate_path = work_dir / f"{live_path.name}.{timestamp}.{label}.candidate"
    backup_path = work_dir / f"{live_path.name}.{timestamp}.{label}.bak"
    candidate_path.write_text(content)
    return ZoneCandidate(
        zone_name=live_path.name,
        live_path=live_path,
        candidate_path=candidate_path,
        backup_path=backup_path,
        content=content,
    )


def _backup_live_zone(live_path: Path, backup_path: Path) -> None:
    shutil.copy2(live_path, backup_path)


def _replace_candidate(candidate: ZoneCandidate) -> None:
    staged_path = _stage_for_atomic_replace(candidate.candidate_path, candidate.live_path)
    os.replace(staged_path, candidate.live_path)


def _restore_backup(live_path: Path, backup_path: Path) -> None:
    restore_path = _stage_for_atomic_replace(backup_path, live_path)
    os.replace(restore_path, live_path)


def _stage_for_atomic_replace(source_path: Path, live_path: Path) -> Path:
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{live_path.name}.",
        suffix=".tmp",
        dir=str(live_path.parent),
        delete=False,
    )
    temp_handle.close()
    staged_path = Path(temp_handle.name)
    try:
        shutil.copy2(source_path, staged_path)
        _copy_live_metadata(live_path, staged_path)
        return staged_path
    except Exception:
        try:
            staged_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _copy_live_metadata(live_path: Path, staged_path: Path) -> None:
    live_stat = live_path.stat()
    os.chmod(staged_path, live_stat.st_mode)
    try:
        os.chown(staged_path, live_stat.st_uid, live_stat.st_gid)
    except PermissionError:
        # If the sync is not running with enough privileges, the replace step
        # would fail shortly afterwards anyway.
        pass


def _reload_dns(reload_script_path: Path) -> None:
    if not reload_script_path.exists():
        raise ReloadError(f"Reload script does not exist: {reload_script_path}")

    completed = subprocess.run(
        (str(reload_script_path),),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        combined_output = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        raise ReloadError(f"DNS reload failed: {combined_output or 'unknown error'}")
