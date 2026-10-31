"""Zone parsing, rendering, and validation."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .exceptions import ZoneValidationError
from .models import LeaseRecord

MANAGED_COMMENT_MARKER = "managed-by:synology-dhcp-dns-sync"
KNOWN_RECORD_TYPES = {"A", "PTR", "NS", "SOA", "AAAA", "CNAME", "MX", "TXT", "SRV"}
KNOWN_DNS_CLASSES = {"IN", "CH", "HS"}
SERIAL_RE = re.compile(r"^(\s*)(\d+)(\s*(?:;.*)?)$")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedZoneLine:
    owner: str
    record_type: str
    value: Optional[str]


def read_zone_text(path: Path) -> str:
    return path.read_text()


def validate_zone_baseline(zone_name: str, zone_text: str) -> None:
    lines = zone_text.splitlines(keepends=True)
    if not any(_is_soa_line(line) for line in lines):
        raise ZoneValidationError(f"Zone {zone_name} does not contain an SOA record.")
    if not any(_is_record_type(line, "NS") for line in lines):
        raise ZoneValidationError(f"Zone {zone_name} does not contain an NS record.")


def strip_managed_records(zone_text: str, *, zone_name: str) -> Tuple[str, List[ParsedZoneLine]]:
    preserved_lines: List[str] = []
    static_records: List[ParsedZoneLine] = []
    current_owner: Optional[str] = None

    for line in zone_text.splitlines(keepends=True):
        parsed, current_owner = parse_zone_line_with_state(
            line,
            origin=zone_name,
            current_owner=current_owner,
        )
        if parsed is not None and _is_managed_dynamic_line(line, parsed.record_type):
            continue
        preserved_lines.append(line)
        if parsed is not None:
            static_records.append(parsed)

    preserved_text = "".join(preserved_lines)
    validate_zone_baseline(zone_name, preserved_text)
    return preserved_text, static_records


def managed_forward_records(zone_text: str, *, zone_name: str) -> Dict[str, str]:
    """Return the A records this tool manages, as lowercase FQDN -> IP."""

    records: Dict[str, str] = {}
    current_owner: Optional[str] = None
    for line in zone_text.splitlines():
        parsed, current_owner = parse_zone_line_with_state(line, origin=zone_name, current_owner=current_owner)
        if parsed is not None and parsed.record_type == "A" and _is_managed_dynamic_line(line, "A"):
            records[parsed.owner.lower()] = parsed.value or ""
    return records


def parse_zone_line(line: str, *, origin: str) -> Optional[ParsedZoneLine]:
    parsed, _ = parse_zone_line_with_state(line, origin=origin, current_owner=None)
    return parsed


def parse_zone_line_with_state(
    line: str,
    *,
    origin: str,
    current_owner: Optional[str],
) -> Tuple[Optional[ParsedZoneLine], Optional[str]]:
    pre_comment = line.split(";", maxsplit=1)[0].strip()
    if not pre_comment:
        return None, current_owner

    tokens = pre_comment.split()
    record_type_index = -1
    for index, token in enumerate(tokens):
        if token.upper() in KNOWN_RECORD_TYPES:
            record_type_index = index
            break

    if record_type_index < 0:
        return None, current_owner

    owner = _resolve_owner(tokens[:record_type_index], origin=origin, current_owner=current_owner)
    if owner is None:
        return None, current_owner
    record_type = tokens[record_type_index].upper()
    value = tokens[record_type_index + 1] if len(tokens) > record_type_index + 1 else None
    return ParsedZoneLine(owner=owner, record_type=record_type, value=value), owner


def normalize_owner(owner: str, origin: str) -> str:
    if owner == "@":
        return f"{origin.rstrip('.') }."
    if owner.endswith("."):
        return owner
    return f"{owner}.{origin.rstrip('.') }."


def _resolve_owner(
    prefix_tokens: List[str],
    *,
    origin: str,
    current_owner: Optional[str],
) -> Optional[str]:
    if not prefix_tokens:
        return current_owner

    first_token = prefix_tokens[0]
    if _is_dns_class(first_token) or _is_ttl_token(first_token):
        return current_owner

    return normalize_owner(first_token, origin)


def collect_static_claims(
    static_forward_records: List[ParsedZoneLine],
    static_reverse_records: List[ParsedZoneLine],
) -> Tuple[Set[str], Set[str]]:
    # A CNAME owner can't hold any other record, so a lease with that name would break the zone.
    static_forward_owners = {
        record.owner.lower()
        for record in static_forward_records
        if record.record_type in {"A", "CNAME"}
    }
    static_reverse_owners = {
        record.owner.lower()
        for record in static_reverse_records
        if record.record_type == "PTR"
    }
    return static_forward_owners, static_reverse_owners


def filter_leases_for_static_claims(
    leases: List[LeaseRecord],
    *,
    reverse_zone: str,
    static_forward_owners: Set[str],
    static_reverse_owners: Set[str],
) -> Tuple[List[LeaseRecord], int]:
    kept: List[LeaseRecord] = []
    skipped = 0
    suffix = f"{reverse_zone.rstrip('.') }."

    for lease in leases:
        reverse_owner = f"{lease.ip.reverse_pointer}."
        if not reverse_owner.endswith(suffix):
            log.warning("Skipping %s (%s): outside reverse zone %s.", lease.fqdn, lease.ip, reverse_zone)
            skipped += 1
            continue
        if lease.fqdn in static_forward_owners or reverse_owner in static_reverse_owners:
            skipped += 1
            continue
        kept.append(lease)

    return kept, skipped


def validate_managed_leases(leases: List[LeaseRecord]) -> None:
    fqdn_to_ip: Dict[str, str] = {}
    ip_to_fqdn: Dict[str, str] = {}

    for lease in leases:
        ip_text = str(lease.ip)
        existing_ip = fqdn_to_ip.get(lease.fqdn)
        if existing_ip is not None and existing_ip != ip_text:
            raise ZoneValidationError(
                f"Conflicting IPs for hostname {lease.fqdn}: {existing_ip} vs {ip_text}"
            )
        fqdn_to_ip[lease.fqdn] = ip_text

        existing_fqdn = ip_to_fqdn.get(ip_text)
        if existing_fqdn is not None and existing_fqdn != lease.fqdn:
            raise ZoneValidationError(
                f"Conflicting hostnames for IP {ip_text}: {existing_fqdn} vs {lease.fqdn}"
            )
        ip_to_fqdn[ip_text] = lease.fqdn


def build_forward_zone(zone_text: str, leases: List[LeaseRecord], *, bump_serial: bool = True) -> str:
    base = increment_soa_serial(zone_text) if bump_serial else zone_text
    body = base.rstrip("\n")
    dynamic_lines = [
        f"{lease.fqdn}\t{lease.ttl}\tA\t{lease.ip}\t;dynamic {MANAGED_COMMENT_MARKER}"
        for lease in leases
    ]
    if dynamic_lines:
        joined_dynamic_lines = "\n".join(dynamic_lines)
        body = f"{body}\n" if body else body
        body = f"{body}{joined_dynamic_lines}\n"
    else:
        body = f"{body}\n"
    validate_zone_baseline("candidate-forward", body)
    return body


def build_reverse_zone(zone_text: str, leases: List[LeaseRecord], *, bump_serial: bool = True) -> str:
    base = increment_soa_serial(zone_text) if bump_serial else zone_text
    body = base.rstrip("\n")
    dynamic_lines = [
        (
            f"{lease.ip.reverse_pointer}.\t{lease.ttl}\tPTR\t{lease.fqdn}\t"
            f";dynamic {MANAGED_COMMENT_MARKER}"
        )
        for lease in leases
    ]
    if dynamic_lines:
        joined_dynamic_lines = "\n".join(dynamic_lines)
        body = f"{body}\n" if body else body
        body = f"{body}{joined_dynamic_lines}\n"
    else:
        body = f"{body}\n"
    validate_zone_baseline("candidate-reverse", body)
    return body


def increment_soa_serial(zone_text: str) -> str:
    lines = zone_text.splitlines(keepends=True)
    soa_index = next((index for index, line in enumerate(lines) if _is_soa_line(line)), None)
    if soa_index is None:
        raise ZoneValidationError("Zone does not contain an SOA record.")

    for index in range(soa_index + 1, len(lines)):
        match = SERIAL_RE.match(lines[index].rstrip("\n"))
        if match is None:
            continue
        prefix, serial, suffix = match.groups()
        lines[index] = f"{prefix}{int(serial) + 1}{suffix}\n"
        return "".join(lines)

    raise ZoneValidationError("Could not locate the SOA serial line to increment.")


def run_named_checkzone(command_path: Path, zone_name: str, candidate_path: Path) -> str:
    if not command_path.exists():
        return f"Skipping named-checkzone for {zone_name}; command not found at {command_path}."

    completed = subprocess.run(
        (str(command_path), zone_name, str(candidate_path)),
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    if completed.returncode != 0:
        raise ZoneValidationError(
            f"named-checkzone failed for {zone_name}: {combined_output or 'unknown error'}"
        )
    return combined_output or f"named-checkzone passed for {zone_name}."


def _is_soa_line(line: str) -> bool:
    return _is_record_type(line, "SOA")


def _is_record_type(line: str, record_type: str) -> bool:
    parsed = parse_zone_line(line, origin="placeholder.local")
    return parsed is not None and parsed.record_type == record_type


def _is_managed_dynamic_line(line: str, record_type: str) -> bool:
    if record_type not in {"A", "PTR"}:
        return False
    return ";dynamic" in line or MANAGED_COMMENT_MARKER in line


def _is_dns_class(token: str) -> bool:
    return token.upper() in KNOWN_DNS_CLASSES


def _is_ttl_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+[WDHMSwdhms]*", token))
