from __future__ import annotations

import logging
import stat
import tempfile
import unittest
from pathlib import Path

from synology_dhcp_dns_sync.config import SyncConfig
from synology_dhcp_dns_sync.exceptions import LockHeldError, ReloadError
from synology_dhcp_dns_sync.locking import acquire_process_lock
from synology_dhcp_dns_sync.syncer import perform_sync, validate_runtime_environment

FORWARD_ZONE_TEXT = """$TTL 3600
@ IN SOA ns.home.arpa. admin.home.arpa. (
    2026040801 ; serial
    3600 ; refresh
    900 ; retry
    604800 ; expire
    86400 ; minimum
)
@ IN NS ns.home.arpa.
router IN A 192.0.2.2
oldhost.home.arpa.\t86400\tA\t192.0.2.150\t;dynamic
"""

REVERSE_ZONE_TEXT = """$TTL 3600
@ IN SOA ns.home.arpa. admin.home.arpa. (
    2026040801 ; serial
    3600 ; refresh
    900 ; retry
    604800 ; expire
    86400 ; minimum
)
@ IN NS ns.home.arpa.
2 PTR router.home.arpa.
150.2.0.192.in-addr.arpa.\t86400\tPTR\toldhost.home.arpa.\t;dynamic
"""


class SyncerTests(unittest.TestCase):
    def test_perform_sync_updates_live_zone_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._build_config(Path(temp_dir), reload_exit_code=0)
            result = perform_sync(config, logger=self._logger())

            self.assertTrue(result.changed)
            self.assertEqual(result.managed_records, 1)
            self.assertEqual(result.skipped_records, 0)

            forward_live = config.forward_zone_path.read_text()
            reverse_live = config.reverse_zone_path.read_text()
            self.assertIn("newhost.home.arpa.", forward_live)
            self.assertNotIn("oldhost.home.arpa.", forward_live)
            self.assertIn("newhost.home.arpa.", reverse_live)
            self.assertNotIn("oldhost.home.arpa.", reverse_live)

    def test_reload_failure_rolls_back_live_zone_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._build_config(Path(temp_dir), reload_exit_code=1)
            original_forward = config.forward_zone_path.read_text()
            original_reverse = config.reverse_zone_path.read_text()

            with self.assertRaises(ReloadError):
                perform_sync(config, logger=self._logger())

            self.assertEqual(config.forward_zone_path.read_text(), original_forward)
            self.assertEqual(config.reverse_zone_path.read_text(), original_reverse)

    def test_lock_prevents_overlapping_sync_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._build_config(Path(temp_dir), reload_exit_code=0)
            with acquire_process_lock(config.effective_lock_path):
                with self.assertRaises(LockHeldError):
                    perform_sync(config, logger=self._logger())

    def test_validate_runtime_environment_rejects_broken_zone_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._build_config(Path(temp_dir), reload_exit_code=0)
            config.forward_zone_path.write_text("router IN A 192.0.2.2\n")

            with self.assertRaisesRegex(Exception, "SOA record"):
                validate_runtime_environment(config)

    def test_validate_runtime_environment_requires_reload_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._build_config(Path(temp_dir), reload_exit_code=0)
            config.reload_script_path.unlink()

            with self.assertRaisesRegex(Exception, "Reload script does not exist"):
                validate_runtime_environment(config)

    def _build_config(self, root: Path, *, reload_exit_code: int) -> SyncConfig:
        zone_dir = root / "zones"
        work_dir = root / "work"
        dhcp_dir = root / "dhcp"
        zone_dir.mkdir()
        work_dir.mkdir()
        dhcp_dir.mkdir()

        forward_zone_path = zone_dir / "home.arpa"
        reverse_zone_path = zone_dir / "2.0.192.in-addr.arpa"
        forward_zone_path.write_text(FORWARD_ZONE_TEXT)
        reverse_zone_path.write_text(REVERSE_ZONE_TEXT)

        dhcp_source = dhcp_dir / "dhcpd.conf"
        dhcp_source.write_text("1728392012 aa:bb:cc:dd:ee:ff 192.0.2.150 newhost eth0\n")

        named_checkzone = root / "named-checkzone"
        self._write_script(named_checkzone, "#!/bin/sh\nexit 0\n")

        reload_script = root / "reload.sh"
        self._write_script(reload_script, f"#!/bin/sh\nexit {reload_exit_code}\n")

        return SyncConfig(
            domain="home.arpa",
            forward_zone="home.arpa",
            reverse_zone="2.0.192.in-addr.arpa",
            zone_dir=zone_dir,
            work_dir=work_dir,
            named_checkzone_path=named_checkzone,
            reload_script_path=reload_script,
            dhcp_files=(dhcp_source,),
        )

    def _write_script(self, path: Path, content: str) -> None:
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _logger(self) -> logging.Logger:
        logger = logging.getLogger(f"test-syncer-{id(self)}")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        return logger


if __name__ == "__main__":
    unittest.main()
