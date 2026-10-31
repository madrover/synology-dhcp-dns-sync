from __future__ import annotations

import unittest
from ipaddress import IPv4Address
from pathlib import Path

from synology_dhcp_dns_sync.models import LeaseRecord
from synology_dhcp_dns_sync.zone import (
    build_forward_zone,
    build_reverse_zone,
    collect_static_claims,
    filter_leases_for_static_claims,
    strip_managed_records,
)

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

FORWARD_ZONE_WITH_INHERITED_OWNER = """$TTL 3600
@ IN SOA ns.home.arpa. admin.home.arpa. (
    2026040801 ; serial
    3600 ; refresh
    900 ; retry
    604800 ; expire
    86400 ; minimum
)
@ IN NS ns.home.arpa.
router IN AAAA 2001:db8::2
    3600 IN A 192.0.2.2
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


def _lease(ip_text: str, hostname: str) -> LeaseRecord:
    return LeaseRecord(
        ip=IPv4Address(ip_text),
        hostname=hostname,
        fqdn=f"{hostname}.home.arpa.",
        ttl=86400,
        source_path=Path("/tmp/dhcpd.conf"),
        line_number=1,
    )


class ZoneRenderingTests(unittest.TestCase):
    def test_strip_and_rebuild_zone_files(self) -> None:
        forward_static, forward_records = strip_managed_records(
            FORWARD_ZONE_TEXT,
            zone_name="home.arpa",
        )
        reverse_static, reverse_records = strip_managed_records(
            REVERSE_ZONE_TEXT,
            zone_name="2.0.192.in-addr.arpa",
        )

        static_forward_owners, static_reverse_owners = collect_static_claims(
            forward_records,
            reverse_records,
        )
        leases, skipped = filter_leases_for_static_claims(
            [_lease("192.0.2.150", "newhost"), _lease("192.0.2.2", "router")],
            reverse_zone="2.0.192.in-addr.arpa",
            static_forward_owners=static_forward_owners,
            static_reverse_owners=static_reverse_owners,
        )

        self.assertEqual(skipped, 1)

        rebuilt_forward = build_forward_zone(forward_static, leases)
        rebuilt_reverse = build_reverse_zone(reverse_static, leases)

        self.assertNotIn("oldhost.home.arpa.", rebuilt_forward)
        self.assertIn("newhost.home.arpa.\t86400\tA\t192.0.2.150", rebuilt_forward)
        self.assertIn("2026040802 ; serial", rebuilt_forward)

        self.assertNotIn("oldhost.home.arpa.", rebuilt_reverse)
        self.assertIn(
            "150.2.0.192.in-addr.arpa.\t86400\tPTR\tnewhost.home.arpa.",
            rebuilt_reverse,
        )
        self.assertIn("2026040802 ; serial", rebuilt_reverse)

    def test_static_claim_detection_supports_inherited_owner_lines(self) -> None:
        forward_static, forward_records = strip_managed_records(
            FORWARD_ZONE_WITH_INHERITED_OWNER,
            zone_name="home.arpa",
        )
        static_forward_owners, static_reverse_owners = collect_static_claims(
            forward_records,
            [],
        )

        leases, skipped = filter_leases_for_static_claims(
            [_lease("192.0.2.2", "router")],
            reverse_zone="2.0.192.in-addr.arpa",
            static_forward_owners=static_forward_owners,
            static_reverse_owners=static_reverse_owners,
        )

        self.assertEqual(forward_static, FORWARD_ZONE_WITH_INHERITED_OWNER)
        self.assertEqual(skipped, 1)
        self.assertEqual(leases, [])

    def test_static_cname_and_mixed_case_owners_claim_the_name(self) -> None:
        zone_text = FORWARD_ZONE_TEXT + "tv IN CNAME router\nNAS IN A 192.0.2.5\n"
        _, forward_records = strip_managed_records(zone_text, zone_name="home.arpa")
        static_forward_owners, static_reverse_owners = collect_static_claims(forward_records, [])

        leases, skipped = filter_leases_for_static_claims(
            [_lease("192.0.2.40", "tv"), _lease("192.0.2.41", "nas"), _lease("192.0.2.42", "laptop")],
            reverse_zone="2.0.192.in-addr.arpa",
            static_forward_owners=static_forward_owners,
            static_reverse_owners=static_reverse_owners,
        )

        self.assertEqual([lease.hostname for lease in leases], ["laptop"])
        self.assertEqual(skipped, 2)

    def test_lease_outside_reverse_zone_is_skipped_not_fatal(self) -> None:
        with self.assertLogs("synology_dhcp_dns_sync.zone", level="WARNING"):
            leases, skipped = filter_leases_for_static_claims(
                [_lease("198.51.100.7", "guest"), _lease("192.0.2.42", "laptop")],
                reverse_zone="2.0.192.in-addr.arpa",
                static_forward_owners=set(),
                static_reverse_owners=set(),
            )

        self.assertEqual([lease.hostname for lease in leases], ["laptop"])
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
