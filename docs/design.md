# Design

## Runtime Model

The tool operates in three layers:

- config loading from a small INI file
- DHCP source parsing into normalized lease records
- zone regeneration and swap orchestration

The watcher is intentionally thin and simply reuses the same sync path as manual runs.

The primary deployment target is a one-shot `sync` command invoked by DSM Task Scheduler. The watcher remains available when lower latency is needed.

## DHCP Parsing

The parser reads the DSM DHCP inputs used by this workflow:

- `/etc/dhcpd/dhcpd.conf`
- `/etc/dhcpd/dhcpd-leases.log`
- `/etc/dhcpd/dhcpd-static-static.conf`
- `/etc/dhcpd/dhcpd-eth0-static.conf`
- `/etc/dhcpd/dhcpd.conf.leases`

Each matching line is normalized into:

- IPv4 address
- sanitized hostname
- FQDN
- TTL
- source file and line number

Hostname cleanup removes non-alphanumeric and non-hyphen characters, then trims leading and trailing hyphens.

## Managed Record Contract

The tool owns only records that are clearly marked as managed dynamic entries.

- Existing `;dynamic` records are recognized as managed records.
- Records emitted by this tool use `;dynamic managed-by:synology-dhcp-dns-sync`.

This keeps the managed record contract explicit while remaining understandable to operators inspecting the zone files manually.

## Zone Rendering

Zone updates are whole-file renders, not in-place line edits.

For each zone:

1. Read the live zone file.
2. Preserve every non-managed line in order.
3. Reject the file if the preserved baseline no longer contains SOA or NS records.
4. Normalize static A/PTR owners so relative names, inherited owners, and owner lines with leading TTL or class tokens still count as static claims.
5. Generate a deterministic set of managed records from the DHCP lease model.
6. Increment the SOA serial by updating the first numeric line after the SOA declaration.
7. Write the candidate zone to the work directory.

The output format stays simple and easy to inspect directly on the NAS.

## Locking

Every sync run acquires a non-blocking process lock before it inspects or updates the zone files.

- the default lock file lives at `work_dir/sync.lock`
- an explicit `paths.lock_path` override is available when needed
- if another process already holds the lock, the new invocation logs the condition and exits cleanly

This makes periodic DSM scheduled runs safe even when one execution takes longer than the scheduling interval.

## Validation

Validation happens in layers:

- baseline validation for live zones
- internal validation for generated leases and candidate zones
- external validation through `named-checkzone` when available

The `validate-config` command also checks that the live forward and reverse zones contain usable SOA and NS records and that the configured reload script is executable before reporting success.

The tool rejects a run if:

- the live zone baseline is malformed
- a lease falls outside the configured reverse zone
- conflicting hostname/IP mappings remain after normalization
- `named-checkzone` rejects a candidate

## Atomic Replace And Rollback

Candidate files are written into the configured work directory first. When `paths.work_dir` is omitted, it defaults to a `work/` directory beside the config file.

Before updating live zones:

- live zones are copied to backup files in the work directory

The final live file update is staged beside the live zone file and then applied with `os.replace`, so each file swap remains atomic even when the configured work directory lives on a different filesystem such as `/volume1`.

If any step after the file update fails, especially DNS reload, the tool restores the backups back to the live paths and attempts one more reload to get the server back to a known-good state.

## Watcher

The watcher compares DHCP file mtimes on a polling interval.

- the first pass always triggers a sync
- later passes sync only when the snapshot changes

The watcher uses the same sync path and therefore the same locking behavior as manual or scheduled sync runs. If one sync attempt fails, the watcher logs the failure and keeps running.
