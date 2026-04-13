from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest import mock

from synology_dhcp_dns_sync.config import SyncConfig
from synology_dhcp_dns_sync.exceptions import SyncError
from synology_dhcp_dns_sync.watcher import watch


class WatcherTests(unittest.TestCase):
    def test_watcher_survives_sync_error_and_continues_loop(self) -> None:
        config = SyncConfig(
            domain="home.arpa",
            forward_zone="home.arpa",
            reverse_zone="2.0.192.in-addr.arpa",
            dhcp_files=(Path("/tmp/dhcpd.conf"),),
        )

        with mock.patch(
            "synology_dhcp_dns_sync.watcher._collect_snapshot",
            return_value={Path("/tmp/dhcpd.conf"): 1},
        ), mock.patch(
            "synology_dhcp_dns_sync.watcher.perform_sync",
            side_effect=[SyncError("boom"), KeyboardInterrupt()],
        ):
            with self.assertRaises(KeyboardInterrupt):
                watch(config, logger=logging.getLogger("watcher-test"))


if __name__ == "__main__":
    unittest.main()
