from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from synology_dhcp_dns_sync import cli
from synology_dhcp_dns_sync.exceptions import LockHeldError
from synology_dhcp_dns_sync.models import SyncResult


class CliTests(unittest.TestCase):
    def test_cli_returns_zero_when_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[sync]",
                        "domain = home.arpa",
                        "forward_zone = home.arpa",
                        "reverse_zone = 2.0.192.in-addr.arpa",
                    ]
                )
            )

            with mock.patch(
                "synology_dhcp_dns_sync.cli.perform_sync",
                side_effect=LockHeldError("Another sync process is already running."),
            ):
                exit_code = cli.main(["sync", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)

    def test_log_file_only_records_changed_runs_unless_verbose(self) -> None:
        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level
        self.addCleanup(lambda: (setattr(root, "handlers", saved_handlers), root.setLevel(saved_level)))

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = _write_config(Path(temp_dir))
            log_path = Path(temp_dir) / "sync.log"
            args = ["sync", "--config", str(config_path), "--log-file", str(log_path)]

            for changed, extra in ((False, []), (True, []), (False, ["--verbose"])):
                result = SyncResult(changed=changed, dry_run=False, managed_records=3, skipped_records=0)
                with mock.patch("synology_dhcp_dns_sync.cli.perform_sync", return_value=result):
                    self.assertEqual(cli.main(args + extra), 0)
            for handler in root.handlers:
                handler.close()

            lines = log_path.read_text().splitlines()

        self.assertEqual(len(lines), 2)
        self.assertIn("changed=True", lines[0])
        self.assertIn("DEBUG Sync complete: changed=False", lines[1])


class CliFailureTests(unittest.TestCase):
    def test_unexpected_error_is_logged_and_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = _write_config(Path(temp_dir))
            with mock.patch("synology_dhcp_dns_sync.cli.perform_sync", side_effect=OSError("disk full")):
                with self.assertLogs("synology_dhcp_dns_sync", level="ERROR"):
                    exit_code = cli.main(["sync", "--config", str(config_path)])

        self.assertEqual(exit_code, 1)


def _write_config(root: Path) -> Path:
    config_path = root / "config.ini"
    config_path.write_text(
        "[sync]\ndomain = home.arpa\nforward_zone = home.arpa\nreverse_zone = 2.0.192.in-addr.arpa\n"
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
