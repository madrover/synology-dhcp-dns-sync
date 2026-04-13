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


if __name__ == "__main__":
    unittest.main()
