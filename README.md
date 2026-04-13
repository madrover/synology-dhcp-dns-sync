# synology-dhcp-dns-sync

It is designed for DSM 7 systems where Synology DHCP and Synology DNS are both enabled, but DHCP leases are not automatically reflected in the authoritative DNS zone. The tool reads the DHCP lease and reservation files, builds the managed A/PTR records for a single forward and reverse zone pair, validates the result, and then atomically updates the live zone files before reloading Synology DNS.

## What It Does

- Uses whole-file zone regeneration for both managed zones.
- Preserves static DNS records already present in the live zone files.
- Removes only DHCP-managed dynamic A/PTR records.
- Rebuilds forward and reverse records from DHCP data.
- Bumps the SOA serial automatically.
- Validates candidate zones before any live write.
- Rolls back zone file changes if reload fails.
- Supports both scheduled one-shot sync runs and an optional long-running watcher.
- Validates the live zone baselines and required reload path before reporting the environment as usable.

## Assumptions

- DSM 7 only.
- Python 3.8 or newer.
- One forward zone and one reverse zone.
- Synology DNS zones are stored under `/var/packages/DNSServer/target/named/etc/zone/master`.
- Synology reload script is `/var/packages/DNSServer/target/script/reload.sh`.
- `named-checkzone` is available at `/var/packages/DNSServer/target/bin/named-checkzone`.

## Config

The required config is intentionally small:

```ini
[sync]
domain = home.arpa
forward_zone = home.arpa
reverse_zone = 2.0.192.in-addr.arpa
poll_interval_seconds = 5
```

By default, candidate files, backups, and the lock file are written to a `work/` directory beside the config file.

See [config.example.ini](config.example.ini) for the optional advanced path overrides.

## Commands

Run directly from the repo:

```bash
PYTHONPATH=src python3 -m synology_dhcp_dns_sync validate-config --config config.example.ini
PYTHONPATH=src python3 -m synology_dhcp_dns_sync sync --config config.example.ini --dry-run
PYTHONPATH=src python3 -m synology_dhcp_dns_sync watch --config config.example.ini
```

Or install it as a package and use the console script:

```bash
python3 -m pip install .
synology-dhcp-dns-sync sync --config /path/to/config.ini
```

## Deployment On DSM 7

Recommended deployment is DSM `Task Scheduler` running `sync` every minute as `root`.

Suggested layout on the NAS:

- project: `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync`
- config: `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/config.ini`
- work files: `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/work`
- logs: `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs`

This user-owned home path is the recommended default because it avoids the permission issues that some DSM setups hit under `/volume1/scripts/...`.

Make sure the `work` and `logs` directories exist before the first scheduled run.

Recommended task:

- Control Panel > Task Scheduler
- Create > Scheduled Task > User-defined script
- User: `root`
- Schedule: every 1 minute
- Script:

```sh
/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/scripts/run-sync.sh /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/config.ini >> /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs/sync.log 2>&1
```

Why this is the default:

- one-shot `sync` is easy to reason about and easy to debug
- overlapping scheduled runs are serialized with a lock file
- candidate files can live on the data volume while final atomic updates are staged beside the live zone files
- DSM already provides scheduling, restart behavior, and logging hooks

Optional low-latency mode:

- use a boot-up task to launch `watch` if you want sub-minute updates
- keep it as an advanced option rather than the default deployment path

Other deployment models:

- Synology package/SPK is a good future packaging option, but not required for a personal deployment
- Container Manager is not a great fit because this tool needs direct host access to zone files and the DNS reload script
- `/usr/local/etc/rc.d` remains possible, but Task Scheduler is the recommended DSM-native approach here

See [deployment.md](docs/deployment.md) for the full deployment walkthrough.

## Verification

1. Run `validate-config`.
2. Run `sync --dry-run` and confirm candidate files are generated under the work directory.
3. Run `sync`.
4. Renew or create a DHCP lease.
5. Confirm the forward and reverse zone files contain the expected managed records.
6. Confirm `named-checkzone` passes.
7. Confirm `nslookup <host>.<domain> <nas_ip>` resolves correctly.

## Design Docs

- [design.md](docs/design.md)
- [deployment.md](docs/deployment.md)

## Acknowledgements

- Inspired by [`gclayburg/synology-diskstation-scripts`](https://github.com/gclayburg/synology-diskstation-scripts).
