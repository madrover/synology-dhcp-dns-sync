from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synology_dhcp_dns_sync.dhcp import parse_dhcp_sources, sanitize_hostname


class DhcpParsingTests(unittest.TestCase):
    def test_sanitize_hostname_matches_shell_cleanup(self) -> None:
        self.assertEqual(sanitize_hostname("--My Host!!--"), "MyHost")

    def test_parse_dynamic_and_static_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "dhcpd.conf"
            source_path.write_text(
                "\n".join(
                    [
                        "1728392012 aa:bb:cc:dd:ee:ff 192.0.2.150 laptop eth0",
                        "dhcp-host=aa:bb:cc:dd:ee:11,Office_Printer!,192.0.2.151,7200",
                        "1728392012 aa:bb:cc:dd:ee:22 192.0.2.152 eth0",
                    ]
                )
            )

            leases = parse_dhcp_sources(
                (source_path,),
                domain="home.arpa",
                interface_names={"eth0"},
            )

        self.assertEqual(len(leases), 2)
        self.assertEqual(leases[0].fqdn, "laptop.home.arpa.")
        self.assertEqual(str(leases[0].ip), "192.0.2.150")
        self.assertEqual(leases[1].fqdn, "OfficePrinter.home.arpa.")
        self.assertEqual(leases[1].ttl, 7200)

    def test_parse_ambiguous_four_column_line_is_skipped_without_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "dhcpd.conf"
            source_path.write_text("1728392012 aa:bb:cc:dd:ee:22 192.0.2.152 eth0\n")

            leases = parse_dhcp_sources(
                (source_path,),
                domain="home.arpa",
                interface_names=set(),
            )

        self.assertEqual(leases, [])


if __name__ == "__main__":
    unittest.main()
