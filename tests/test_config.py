from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synology_dhcp_dns_sync.config import load_config


class ConfigTests(unittest.TestCase):
    def test_work_dir_defaults_next_to_config_file(self) -> None:
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

            config = load_config(config_path)

        self.assertEqual(config.work_dir, config_path.parent / "work")
        self.assertEqual(config.dynamic_ttl, 600)

    def test_dhcp_file_patterns_expand_to_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dhcpd.conf").write_text("")
            (root / "dhcpd-ovs_bond0-static.conf").write_text("")
            (root / "dhcpd-eth1-static.conf").write_text("")
            config_path = root / "config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[sync]",
                        "domain = home.arpa",
                        "forward_zone = home.arpa",
                        "reverse_zone = 2.0.192.in-addr.arpa",
                        "dynamic_ttl = 300",
                        "[paths]",
                        "dhcp_files =",
                        f"    {root / 'dhcpd.conf'}",
                        f"    {root / 'dhcpd-*-static.conf'}",
                        f"    {root / 'missing.leases'}",
                    ]
                )
            )

            config = load_config(config_path)
            existing = config.existing_dhcp_files()

        self.assertEqual(config.dynamic_ttl, 300)
        self.assertEqual(
            [path.name for path in existing],
            ["dhcpd.conf", "dhcpd-eth1-static.conf", "dhcpd-ovs_bond0-static.conf"],
        )


if __name__ == "__main__":
    unittest.main()
