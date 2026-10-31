"""Shared dataclasses used by the sync tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class LeaseRecord:
    """Normalized DHCP lease or reservation."""

    ip: IPv4Address
    hostname: str
    fqdn: str
    ttl: int
    source_path: Path
    line_number: int


@dataclass(frozen=True)
class ZoneCandidate:
    """Rendered zone candidate plus the temp file path."""

    zone_name: str
    live_path: Path
    candidate_path: Path
    backup_path: Path
    content: str


@dataclass
class SyncResult:
    """Outcome of a sync execution."""

    changed: bool
    dry_run: bool
    managed_records: int
    skipped_records: int
    # Only set for dry runs, the one case where candidate files are kept for inspection.
    forward_candidate_path: Optional[Path] = None
    reverse_candidate_path: Optional[Path] = None
    validation_messages: List[str] = field(default_factory=list)
