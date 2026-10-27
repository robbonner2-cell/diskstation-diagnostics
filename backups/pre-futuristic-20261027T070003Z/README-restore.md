# Pre-futuristic production snapshot

Exact original files, with SHA-256 hashes in manifest.json. Open index.html for the archived old production view.

To restore: acquire the existing /tmp/.ds-refresh.lock with flock, verify manifest.json hashes, then copy build_site.py, index.html, refresh.py, README.md, data/data.json and data/whatbox.json from this directory to the repository root, preserving relative paths. Do not run archived refresh.py from this directory. No credentials or cron configuration are archived or changed.
