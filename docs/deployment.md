# Deployment

## Recommended Model

The recommended DSM 7 deployment model is:

- install the project files in a user-owned home directory on a persistent volume
- keep a small local config file next to the project
- run `sync` from DSM Task Scheduler every minute as `root`

This model is preferred because DSM already provides reliable scheduling, visibility, and restart behavior, while the tool itself stays focused on safe one-shot synchronization.

## Suggested Layout

- project directory:
  `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync`
- config file:
  `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/config.ini`
- work directory:
  `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/work`
- log directory:
  `/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs`

This avoids the permission problems that some DSM systems hit when writing directly under `/volume1/scripts/...`.

If you keep `config.ini` next to the project, the default `work_dir` is already `work/` beside that config file. Keep the explicit override only if you want a different location. The tool stages the final atomic file update beside the live zone files automatically, so `work_dir` does not need to be on the same filesystem as the live Synology zones.

Create the runtime directories before the first run:

```bash
mkdir -p /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/work
mkdir -p /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs
```

Example:

```ini
[sync]
domain = home.arpa
forward_zone = home.arpa
reverse_zone = 2.0.192.in-addr.arpa
poll_interval_seconds = 5

[paths]
work_dir = /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/work
lock_path = /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/work/sync.lock
```

## Initial Validation

Synology DSM commonly provides Python 3.8, so this project is kept compatible with Python 3.8+.

Run these manually over SSH before creating the scheduled task:

```bash
cd /volume1/homes/<user>/scripts/synology-dhcp-dns-sync
PYTHONPATH=src python3 -m synology_dhcp_dns_sync validate-config --config config.ini
PYTHONPATH=src python3 -m synology_dhcp_dns_sync sync --config config.ini --dry-run
PYTHONPATH=src python3 -m synology_dhcp_dns_sync sync --config config.ini
```

## DSM Task Scheduler Setup

Create a scheduled task in DSM:

- Control Panel > Task Scheduler
- Create > Scheduled Task > User-defined script
- User: `root`
- Schedule: every 1 minute

Script:

```sh
/volume1/homes/<user>/scripts/synology-dhcp-dns-sync/scripts/run-sync.sh /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/config.ini >> /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs/sync.log 2>&1
```

The wrapper script sets `PYTHONPATH` for the repo layout and invokes the one-shot `sync` command.

## Optional Watcher Mode

If you want faster-than-minute updates, create a boot-up task instead and run:

```sh
cd /volume1/homes/<user>/scripts/synology-dhcp-dns-sync
PYTHONPATH=src /usr/bin/env python3 -m synology_dhcp_dns_sync watch --config /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/config.ini >> /volume1/homes/<user>/scripts/synology-dhcp-dns-sync/logs/watch.log 2>&1
```

Use this mode only if you want lower latency than Task Scheduler provides. The scheduled one-shot sync remains the simpler default.

## Other Models

- `/usr/local/etc/rc.d`
  works, but is no longer the preferred deployment path for this project
- Synology package/SPK
  a good future packaging option if you want install and upgrade lifecycle management
- Container Manager
  not recommended because the tool needs direct host access to Synology zone files and reload commands
