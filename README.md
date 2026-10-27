# DiskStation fleet — scheduled diagnostics

**Production:** https://robbonner2-cell.github.io/diskstation-diagnostics/

Four Synology boxes, eight volumes, 95 physical drives. This is a scheduled
snapshot, **not live telemetry**. Existing laptop cron captures every 30 minutes;
if collection or validation fails, the last good page remains published.

## Futuristic production renderer

`build_site.py` renders the actual collector model, not a frozen preview. All CSS
(including enlarged capacity visuals) is embedded from `assets/futuristic.css`;
there are no external assets or scripts. Details expand natively in the browser.
Status comes from current volume status, array membership and high/critical findings.
Full sanitized records, previous readings, source findings and measurement notes
are retained. Original measurement notes are safely embedded in the generator,
with the check count supplied by each current model (no archive dependency).

```bash
python3 build_site.py path/to/model.json
# Optional staged Whatbox input, used by refresh.py:
python3 build_site.py path/to/model.json path/to/whatbox.json
python3 -m unittest discover -s tests -v
```

The generator validates all inputs before writing, stages files beside their
targets, fsyncs, and atomically replaces each output: `index.html`, `data/data.json`,
and sanitized `data/whatbox.json`. Multi-file replacement is not a filesystem-wide
transaction; validation failures leave all three untouched. Required invariants:
four unique box IDs, eight volumes, 95 drive markers, matching drive/capacity sums,
valid ranges, unique drive flags, and all collector self-checks passing.

`refresh.py` retains its existing CLI and publishing behavior. It now stages model
and Whatbox inputs in a unique repository directory, so failed generation cannot
overwrite last-good Whatbox data. The existing external refresh flock remains
`/tmp/.ds-refresh.lock`; no cron configuration changed. This renderer makes no
network requests and requires no files outside the repository.

## Measurement scope and privacy

DSM endpoints: `SYNO.Storage.CGI.Storage`, `SYNO.Core.System`, `SYNO.Backup.Task`.
Uptime is DSM `up_time` (H:MM:SS). DSM SMART flags are not on-box smartctl verdicts;
backup states are not proof of successful backups. Missing Hyper Backup tasks do
not rule out Snapshot Replication, Cloud Sync, rsync or other backups.

Whatbox CPU is average slot cores divided by actual host cores, not a core count;
CPU-cap language reflects the reported cgroup value (or unknown). Memory/disk are
slot measurements. Network is host-wide, not slot traffic; no link-speed
percentage is inferred. Limits and full sanitized sample provenance are included.

Private IPs, sensitive fields and credentials are removed from embedded records
and exported JSON. The final HTML is checked for private-data leakage, local home
paths, scripts and external dependencies before any artifact changes.

## Previous production and restoration

[Compare archived old production snapshot](backups/pre-futuristic-20261027T070003Z/index.html).
`backups/pre-futuristic-20261027T070003Z/` contains the exact six original artifacts (with the two JSON files under
`data/`), SHA-256 `manifest.json`, and `README-restore.md` restoration instructions.
`build_legacy.py` preserves the previous generator byte-for-byte for reference.
Do not run the legacy generator in production unless intentionally restoring.

The production data used during promotion is the existing repository capture,
not an invented sample. Test variations of that capture are isolated in temporary
sandboxes. No credentials, host configuration, cron, commits or pushes are changed
by the promotion itself.

MIT — see [LICENSE](./LICENSE).
