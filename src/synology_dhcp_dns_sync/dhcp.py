"""DHCP lease parsing helpers."""

from __future__ import annotations

import re
import subprocess
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .exceptions import SyncError
from .models import LeaseRecord

TOKEN_SPLIT_RE = re.compile(r"[\t =,]+")


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
) -> List[LeaseRecord]:
    """Parse DSM DHCP sources into normalized lease records."""

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
            )
            if lease is not None:
                parsed[(lease.ip, lease.fqdn)] = lease

    return sorted(parsed.values(), key=lambda record: int(record.ip))


def _parse_dhcp_line(
    line: str,
    *,
    source_path: Path,
    line_number: int,
    domain: str,
    interface_names: Set[str],
) -> Optional[LeaseRecord]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    tokens = [token for token in TOKEN_SPLIT_RE.split(stripped) if token]
    if not tokens:
        return None

    ip_token: Optional[str] = None
    hostname_token: Optional[str] = None
    ttl = 86400

    if tokens[0] == "dhcp-host" and len(tokens) >= 4:
        hostname_token = tokens[2]
        ip_token = tokens[3]
        ttl = _parse_ttl(tokens[4]) if len(tokens) >= 5 else 86400
    elif tokens[0][0].isdigit() and len(tokens) >= 4:
        ip_token = tokens[2]
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
    fqdn = f"{hostname}.{domain.rstrip('.') }."

    return LeaseRecord(
        ip=ip,
        hostname=hostname,
        fqdn=fqdn,
        ttl=ttl,
        source_path=source_path,
        line_number=line_number,
    )


def sanitize_hostname(hostname: str) -> str:
    """Apply RFC 952-ish hostname cleanup."""

    cleaned = re.sub(r"[^A-Za-z0-9-]+", "", hostname.strip())
    return cleaned.strip("-")


def _parse_ipv4(value: str) -> IPv4Address:
    ip = ip_address(value)
    if not isinstance(ip, IPv4Address):
        raise SyncError(f"IPv6 address is not supported for DHCP to DNS sync: {value}")
    return ip


def _parse_ttl(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return 86400
    return parsed if parsed > 0 else 86400
