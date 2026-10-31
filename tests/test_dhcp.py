from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ipaddress import IPv4Address

from synology_dhcp_dns_sync.dhcp import parse_dhcp_sources, resolve_conflicts, sanitize_hostname
from synology_dhcp_dns_sync.models import LeaseRecord


class DhcpParsingTests(unittest.TestCase):
    def test_sanitize_hostname_matches_shell_cleanup(self) -> None:
        self.assertEqual(sanitize_hostname("--My Host!!--"), "myhost")

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
                ttl=300,
            )

        self.assertEqual(len(leases), 2)
        self.assertEqual(leases[0].fqdn, "laptop.home.arpa.")
        self.assertEqual(str(leases[0].ip), "192.0.2.150")
        self.assertEqual(leases[0].expires, 1728392012)
        self.assertFalse(leases[0].static)
        self.assertEqual(leases[1].fqdn, "officeprinter.home.arpa.")
        self.assertTrue(leases[1].static)
        # The DNS TTL comes from config; the 7200 in dhcp-host is the lease time.
        self.assertEqual(leases[1].ttl, 300)

    def test_unusable_addresses_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "dhcpd.conf.leases"
            source_path.write_text(
                "\n".join(
                    [
                        "1728392012 aa:bb:cc:dd:ee:01 2001:db8::5 v6host * eth0",
                        "1728392012 aa:bb:cc:dd:ee:02 192.0.2.999 badip * eth0",
                        "1728392012 aa:bb:cc:dd:ee:03 192.0.2.10 good * eth0",
                    ]
                )
            )

            with self.assertLogs("synology_dhcp_dns_sync.dhcp", level="WARNING") as logs:
                leases = parse_dhcp_sources((source_path,), domain="home.arpa")

        self.assertEqual([lease.hostname for lease in leases], ["good"])
        self.assertEqual(len(logs.output), 2)

    def test_reservation_and_active_lease_for_same_host_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "dhcpd.conf"
            source_path.write_text(
                "dhcp-host=aa:bb:cc:dd:ee:11,printer,192.0.2.151,86400\n"
                "1728392012 aa:bb:cc:dd:ee:11 192.0.2.151 printer * eth0\n"
            )

            leases = parse_dhcp_sources((source_path,), domain="home.arpa")

        self.assertEqual(len(leases), 1)
        self.assertTrue(leases[0].static)

    def test_resolve_conflicts_prefers_reservation_then_newest_lease(self) -> None:
        reserved = _lease("192.0.2.10", "iphone", static=True)
        older = _lease("192.0.2.20", "iphone", expires=100)
        newer = _lease("192.0.2.30", "mac", expires=200)
        stale = _lease("192.0.2.31", "mac", expires=100)
        same_ip = _lease("192.0.2.30", "other", expires=50)

        kept, dropped = resolve_conflicts([older, reserved, stale, newer, same_ip])

        self.assertEqual(kept, [reserved, newer])
        self.assertCountEqual(dropped, [older, stale, same_ip])


def _lease(ip: str, hostname: str, *, static: bool = False, expires: int = 0) -> LeaseRecord:
    return LeaseRecord(
        ip=IPv4Address(ip),
        hostname=hostname,
        fqdn=f"{hostname}.home.arpa.",
        ttl=600,
        source_path=Path("dhcpd.conf"),
        line_number=1,
        static=static,
        expires=expires,
    )

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
