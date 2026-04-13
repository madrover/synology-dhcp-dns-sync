from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from synology_dhcp_dns_sync import cli
from synology_dhcp_dns_sync.exceptions import LockHeldError


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


if __name__ == "__main__":
    unittest.main()
