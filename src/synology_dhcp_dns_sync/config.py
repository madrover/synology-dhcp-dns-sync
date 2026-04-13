"""Configuration loading for the sync tool."""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

from .exceptions import ConfigError

DEFAULT_ZONE_ROOT_DIR = Path("/var/packages/DNSServer/target")
DEFAULT_ZONE_DIR = DEFAULT_ZONE_ROOT_DIR / "named" / "etc" / "zone" / "master"
DEFAULT_NAMED_CHECKZONE_PATH = DEFAULT_ZONE_ROOT_DIR / "bin" / "named-checkzone"
DEFAULT_RELOAD_SCRIPT_PATH = DEFAULT_ZONE_ROOT_DIR / "script" / "reload.sh"
DEFAULT_DHCP_FILES = (
    Path("/etc/dhcpd/dhcpd.conf"),
    Path("/etc/dhcpd/dhcpd-leases.log"),
    Path("/etc/dhcpd/dhcpd-static-static.conf"),
    Path("/etc/dhcpd/dhcpd-eth0-static.conf"),
    Path("/etc/dhcpd/dhcpd.conf.leases"),
)


@dataclass(frozen=True)
class SyncConfig:
    """Runtime configuration for the sync tool."""

    domain: str
    forward_zone: str
    reverse_zone: str
    poll_interval_seconds: int = 5
    zone_root_dir: Path = DEFAULT_ZONE_ROOT_DIR
    zone_dir: Path = DEFAULT_ZONE_DIR
    work_dir: Path = Path("work")
    named_checkzone_path: Path = DEFAULT_NAMED_CHECKZONE_PATH
    reload_script_path: Path = DEFAULT_RELOAD_SCRIPT_PATH
    dhcp_files: Tuple[Path, ...] = DEFAULT_DHCP_FILES
    lock_path: Optional[Path] = None

    @property
    def forward_zone_path(self) -> Path:
        return self.zone_dir / self.forward_zone

    @property
    def reverse_zone_path(self) -> Path:
        return self.zone_dir / self.reverse_zone

    @property
    def normalized_domain(self) -> str:
        return self.domain.rstrip(".")

    @property
    def reverse_zone_suffix(self) -> str:
        return f"{self.reverse_zone.rstrip('.') }."

    def existing_dhcp_files(self) -> Tuple[Path, ...]:
        return tuple(path for path in self.dhcp_files if path.is_file())

    @property
    def effective_lock_path(self) -> Path:
        return self.lock_path or (self.work_dir / "sync.lock")


def load_config(path: Union[str, Path]) -> SyncConfig:
    """Load configuration from an INI file."""

    config_path = Path(path)
    parser = ConfigParser()
    if not parser.read(config_path):
        raise ConfigError(f"Could not read config file: {config_path}")

    if not parser.has_section("sync"):
        raise ConfigError("Config file must contain a [sync] section.")

    sync_section = parser["sync"]
    domain = sync_section.get("domain", "").strip().rstrip(".")
    forward_zone = sync_section.get("forward_zone", "").strip().rstrip(".")
    reverse_zone = sync_section.get("reverse_zone", "").strip().rstrip(".")
    poll_interval_seconds = sync_section.getint("poll_interval_seconds", fallback=5)

    if not domain:
        raise ConfigError("sync.domain is required.")
    if not forward_zone:
        raise ConfigError("sync.forward_zone is required.")
    if not reverse_zone:
        raise ConfigError("sync.reverse_zone is required.")
    if poll_interval_seconds <= 0:
        raise ConfigError("sync.poll_interval_seconds must be greater than zero.")

    paths_section = parser["paths"] if parser.has_section("paths") else {}

    zone_root_dir = _optional_path(paths_section.get("zone_root_dir"), DEFAULT_ZONE_ROOT_DIR)
    zone_dir = _optional_path(paths_section.get("zone_dir"), zone_root_dir / "named" / "etc" / "zone" / "master")
    work_dir = _optional_path(paths_section.get("work_dir"), config_path.parent / "work")
    named_checkzone_path = _optional_path(
        paths_section.get("named_checkzone_path"),
        zone_root_dir / "bin" / "named-checkzone",
    )
    reload_script_path = _optional_path(
        paths_section.get("reload_script_path"),
        zone_root_dir / "script" / "reload.sh",
    )
    dhcp_files = _parse_dhcp_files(paths_section.get("dhcp_files"))
    lock_path = _optional_path(paths_section.get("lock_path"), None)

    return SyncConfig(
        domain=domain,
        forward_zone=forward_zone,
        reverse_zone=reverse_zone,
        poll_interval_seconds=poll_interval_seconds,
        zone_root_dir=zone_root_dir,
        zone_dir=zone_dir,
        work_dir=work_dir,
        named_checkzone_path=named_checkzone_path,
        reload_script_path=reload_script_path,
        dhcp_files=dhcp_files,
        lock_path=lock_path,
    )


def _optional_path(value: Optional[str], default: Optional[Path]) -> Optional[Path]:
    if value is None or not value.strip():
        return default
    return Path(value.strip())


def _parse_dhcp_files(value: Optional[str]) -> Tuple[Path, ...]:
    if value is None or not value.strip():
        return DEFAULT_DHCP_FILES
    parsed = []
    for raw_line in value.splitlines():
        cleaned = raw_line.strip().rstrip(",")
        if cleaned:
            parsed.append(Path(cleaned))
    if not parsed:
        raise ConfigError("paths.dhcp_files was provided but no valid entries were found.")
    return tuple(parsed)
