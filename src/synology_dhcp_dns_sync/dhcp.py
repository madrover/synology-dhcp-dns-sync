"""DHCP lease parsing helpers."""

from __future__ import annotations

import logging
import re
import subprocess
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import LeaseRecord

TOKEN_SPLIT_RE = re.compile(r"[\t =,]+")
DEFAULT_TTL = 600

log = logging.getLogger(__name__)


def discover_interface_names() -> Set[str]:
    """Return network interface names reported by the host, if available."""

    try:
        completed = subprocess.run(
            ("ip", "-o", "link", "show"),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return _discover_interface_names_with_ifconfig()

    names: Set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.split(": ", maxsplit=2)
        if len(parts) >= 2:
            names.add(parts[1].strip())
    return names


def _discover_interface_names_with_ifconfig() -> Set[str]:
    try:
        completed = subprocess.run(
            ("ifconfig", "-a"),
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return set()

    names: Set[str] = set()
    for line in completed.stdout.splitlines():
        if not line or line[:1].isspace():
            continue
        candidate = line.split(":", maxsplit=1)[0].strip()
        if candidate:
            names.add(candidate)
    return names


def parse_dhcp_sources(
    source_paths: Iterable[Path],
    *,
    domain: str,
    interface_names: Optional[Set[str]] = None,
    ttl: int = DEFAULT_TTL,
) -> List[LeaseRecord]:
    """Parse DSM DHCP sources into normalized lease records.

    Unusable lines (IPv6, malformed addresses) are skipped with a warning so
    that one bad entry does not block DNS updates for every other host.
    """

    interfaces = interface_names or set()
    parsed: Dict[Tuple[IPv4Address, str], LeaseRecord] = {}

    for source_path in source_paths:
        for line_number, line in enumerate(source_path.read_text().splitlines(), start=1):
            lease = _parse_dhcp_line(
                line,
                source_path=source_path,
                line_number=line_number,
                domain=domain,
                interface_names=interfaces,
                ttl=ttl,
            )
            if lease is None:
                continue
            # A reserved host with an active lease appears twice; keep the preferred entry.
            existing = parsed.get((lease.ip, lease.fqdn))
            if existing is None or _preference(lease) > _preference(existing):
                parsed[(lease.ip, lease.fqdn)] = lease

    return sorted(parsed.values(), key=lambda record: int(record.ip))


def resolve_conflicts(leases: List[LeaseRecord]) -> Tuple[List[LeaseRecord], List[LeaseRecord]]:
    """Keep one record per hostname and per IP; return (kept, dropped).

    Generic device names such as "iPhone" collide easily. The winner is the
    static reservation, then the lease that expires last.
    """

    dropped: List[LeaseRecord] = []
    kept = _keep_best(leases, key=lambda lease: lease.fqdn, dropped=dropped)
    kept = _keep_best(kept, key=lambda lease: lease.ip, dropped=dropped)
    return sorted(kept, key=lambda record: int(record.ip)), dropped


def _keep_best(leases, *, key, dropped: List[LeaseRecord]) -> List[LeaseRecord]:
    best: Dict[object, LeaseRecord] = {}
    for lease in leases:
        current = best.get(key(lease))
        if current is None:
            best[key(lease)] = lease
        elif _preference(lease) > _preference(current):
            dropped.append(current)
            best[key(lease)] = lease
        else:
            dropped.append(lease)
    return list(best.values())


def _preference(lease: LeaseRecord) -> Tuple[bool, int]:
    return (lease.static, lease.expires)


def _parse_dhcp_line(
    line: str,
    *,
    source_path: Path,
    line_number: int,
    domain: str,
    interface_names: Set[str],
    ttl: int,
) -> Optional[LeaseRecord]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    tokens = [token for token in TOKEN_SPLIT_RE.split(stripped) if token]
    if not tokens:
        return None

    ip_token: Optional[str] = None
    hostname_token: Optional[str] = None
    static = False
    expires = 0

    if tokens[0] == "dhcp-host" and len(tokens) >= 4:
        hostname_token = tokens[2]
        ip_token = tokens[3]
        static = True
    elif tokens[0][0].isdigit() and len(tokens) >= 4:
        ip_token = tokens[2]
        expires = int(tokens[0]) if tokens[0].isdigit() else 0
        if len(tokens) >= 5:
            hostname_token = tokens[3]
        elif interface_names and tokens[3] not in interface_names:
            hostname_token = tokens[3]
        else:
            return None

    if not ip_token or not hostname_token:
        return None

    hostname = sanitize_hostname(hostname_token)
    if hostname in {"", "*"}:
        return None

    ip = _parse_ipv4(ip_token)
    if ip is None:
        log.warning("Skipping %s:%s: %r is not an IPv4 address.", source_path, line_number, ip_token)
        return None
    fqdn = f"{hostname}.{domain.rstrip('.').lower()}."

    return LeaseRecord(
        ip=ip,
        hostname=hostname,
        fqdn=fqdn,
        ttl=ttl,
        source_path=source_path,
        line_number=line_number,
        static=static,
        expires=expires,
    )


def sanitize_hostname(hostname: str) -> str:
    """Apply RFC 952-ish hostname cleanup; DNS names are case-insensitive, so lowercase."""

    cleaned = re.sub(r"[^A-Za-z0-9-]+", "", hostname.strip())
    return cleaned.strip("-").lower()


def _parse_ipv4(value: str) -> Optional[IPv4Address]:
    try:
        ip = ip_address(value)
    except ValueError:
        return None
    return ip if isinstance(ip, IPv4Address) else None
