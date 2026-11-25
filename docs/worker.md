# Running the worker

Since the `modular-worker` change, one background process is the only writer to
`ontology.db`. The web app and CLI open the database read-only and hand writes to
the worker as jobs. Without a running worker, paste, **Process**, and reader
corrections queue and never finish.

This page covers the first rollout on the server and day-to-day operation. The
everyday code deploy is in [deploy.md](deploy.md).

## How it fits together

- Adapters submit a job as a small JSON file in the command spool beside the
  database: `/var/lib/stock-ontology/ontology.db.commands/`.
- The worker moves submissions into the `jobs` table, claims due jobs with a
  15-minute lease, runs them, and records the outcome. A restarted worker reclaims
  jobs whose lease expired.
- The worker checks the spool every 2 seconds, so a submitted job starts within
  2 seconds when no other job is running. It rescans the notes folder once per
  `--interval`. It keeps one database connection open for the queue and opens one
  more for each job attempt.
- Corrections run first, then operator commands, then note extraction. A job gets
  3 attempts with backoff starting at 60 seconds. Invalid input and conflicts fail
  at once.
- Consensus refresh is tracked per company in `consensus_refresh`. A failed
  refresh keeps the previous consensus, shown as stale.
- Operator commands (`ingest`, `reembed`, `repair`, `registry-publish`,
  `registry-apply`) also run as jobs. By default the command runs the worker loop
  in its own process until its job finishes, so it works with or without the
  service. `--no-wait` only queues the job for the service.

## Paths on the server

| What | Where |
|---|---|
| Code | `/opt/stock-ontology/current` (symlink to a release) |
| CLI | `/opt/stock-ontology/current/.venv/bin/stock-ontology` |
| Database | `/var/lib/stock-ontology/ontology.db` |
| Command spool | `/var/lib/stock-ontology/ontology.db.commands/` |
| Notes | `/var/lib/stock-ontology/notes` |
| Provider keys and models | `/etc/stock-ontology/app.env` |
| Data paths and registry | `Environment=` lines in the app and worker units |
| Pre-deploy backups | `/var/backups/stock-ontology` |

The app and worker run as `stockontology` from `/var/lib/stock-ontology`.
`app.env` holds only provider settings. The `ONTOLOGY_DB`, `ONTOLOGY_DATA_DIR`, and
`ONTOLOGY_REGISTRY` paths are set in the unit files, so a shell that sources only
`app.env` falls back to `ontology.db` and `data` in its working directory, not the
live data.

To run the CLI by hand with the app's settings, paste this into a root shell on
the server:

```bash
cd /var/lib/stock-ontology && set -a && . /etc/stock-ontology/app.env && set +a
export ONTOLOGY_DB=/var/lib/stock-ontology/ontology.db ONTOLOGY_DATA_DIR=/var/lib/stock-ontology/notes ONTOLOGY_REGISTRY=/opt/stock-ontology/current/ontology_registry.json HOME=/var/lib/stock-ontology
so() { runuser -u stockontology -- /opt/stock-ontology/current/.venv/bin/stock-ontology "$@"; }
```

Then call `so ...` from that shell. It runs as `stockontology`, so any file the
CLI creates beside the database, like `ontology.db-wal`, stays writable by the
app and worker. Running the CLI directly as root can leave root-owned files there
that lock them out.

## First rollout

Run these in order. Each step says how to check it before moving on.

### 1. Check the server

```bash
./deploy.sh --status
```

On the server, check the app's unit. The worker must run as the same user, with
the same environment, paths, and working directory as the app.

```bash
systemctl cat stock-ontology
free -m
```

The unit in step 4 copies the app's unit as of 2026-11-24: `User=stockontology`,
`WorkingDirectory=/var/lib/stock-ontology`, `EnvironmentFile=`, and the
`Environment=ONTOLOGY_*` lines. If `systemctl cat` shows different values, use
those. The box has 894 MB of RAM and 2 GB of swap. The worker is a second Python
process with its own LLM client, so record free memory now to compare later.

### 2. Create the spool folder

The web process creates the spool on its first submission. Create it up front,
owned by the app's user:

```bash
install -d -m 750 -o stockontology -g stockontology /var/lib/stock-ontology/ontology.db.commands
```

### 3. Deploy the code

From the Mac:

```bash
./deploy.sh --dry-run
```

```bash
./deploy.sh
```

This tests the commit, backs up the database, switches `current`, and restarts the
web app. The web app now opens the database read-only. Browsing works as before.
Paste, **Process**, and corrections queue but don't run yet.

Check: `./deploy.sh --status` shows the new release and `health: ok`.

### 4. Install and start the worker service

Create `/etc/systemd/system/stock-ontology-worker.service`. This is the unit
installed on the server on 2026-11-24. It mirrors the app's user, paths, and
sandboxing, with a lower memory ceiling:

```ini
[Unit]
Description=Stock Ontology worker (only database writer)
Wants=network-online.target
After=network-online.target

[Service]
User=stockontology
Group=stockontology
WorkingDirectory=/var/lib/stock-ontology
EnvironmentFile=/etc/stock-ontology/app.env
Environment=ONTOLOGY_DB=/var/lib/stock-ontology/ontology.db
Environment=ONTOLOGY_DATA_DIR=/var/lib/stock-ontology/notes
Environment=ONTOLOGY_REGISTRY=/opt/stock-ontology/current/ontology_registry.json
Environment=HOME=/var/lib/stock-ontology
ExecStart=/opt/stock-ontology/current/.venv/bin/stock-ontology watch --interval 60
Restart=always
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=30
MemoryHigh=400M
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=/var/lib/stock-ontology

[Install]
WantedBy=multi-user.target
```

The unit runs `watch`, not `worker`, on purpose. In this release `watch` runs the
worker loop. Every older release also has `watch`, where it runs the old ingest
loop. So the unit keeps working after `./deploy.sh --rollback`.

```bash
systemctl daemon-reload
systemctl enable --now stock-ontology-worker
journalctl -u stock-ontology-worker -n 20 --no-pager
```

On its first start, the worker opens the database for writing and creates the
`jobs` and `consensus_refresh` tables. The change is additive: no existing table
is altered. Check that the tables exist:

```bash
sqlite3 -readonly /var/lib/stock-ontology/ontology.db ".tables" | tr -s ' ' '\n' | grep -E '^(jobs|consensus_refresh)$'
```

Its first scan queues an `ingest` job if any note changed since the last ingest.

### 5. Smoke test

From the CLI shell set up under Paths on the server:

```bash
so note list --json | head -c 600
```

In the web app, open a note and click **Process**. The reader shows the job as
pending, then succeeded. This makes real LLM calls. Then check the job from the
CLI with the `job_id` from the reader's network response:

```bash
so status <job_id> --json
```

Compare `free -m` with step 1. If swap use climbs steadily, see Troubleshooting.

### 6. Optional: refresh stale consensus

Consensus that went stale before this release stays as it was. To rebuild it for
every company, queue it for the service:

```bash
so ingest --rebuild-consensus --no-wait
```

This makes one LLM call per company.

## Day to day

### After every deploy

`deploy.sh` restarts only the web app. Restart the worker so it runs the new code:

```bash
systemctl restart stock-ontology-worker
```

A restart is safe at any time. A job interrupted mid-run is reclaimed when its
lease expires, after at most 15 minutes. Its consensus step is retried without
re-extracting the note.

### Check health and backlog

```bash
systemctl is-active stock-ontology-worker
journalctl -u stock-ontology-worker --since "1 hour ago" --no-pager | tail -40
```

Queued and running work, oldest first:

```bash
sqlite3 -readonly -box /var/lib/stock-ontology/ontology.db \
  "SELECT state, kind, COUNT(*) AS n, MIN(created_at) AS oldest FROM jobs WHERE state IN ('queued','running') GROUP BY state, kind;"
```

Submissions the worker hasn't picked up yet:

```bash
ls /var/lib/stock-ontology/ontology.db.commands/ | wc -l
```

A healthy idle worker shows no queued or running rows and an empty spool. A
growing count, or an `oldest` time that keeps getting older, means the worker is
stuck or down.

### Find and retry failures

Recent failed jobs:

```bash
sqlite3 -readonly -box /var/lib/stock-ontology/ontology.db \
  "SELECT job_id, kind, target, attempts, error_code, substr(error,1,80) AS error, updated_at FROM jobs WHERE state='failed' ORDER BY updated_at DESC LIMIT 20;"
```

Companies whose consensus refresh failed or is waiting:

```bash
sqlite3 -readonly -box /var/lib/stock-ontology/ontology.db \
  "SELECT company_id, state, target_revision, completed_revision, substr(error,1,80) AS error FROM consensus_refresh WHERE state != 'current';"
```

Retry one job. This reopens it with a fresh attempt budget:

```bash
so retry <job_id> --json
```

`error_code` tells you what to do:

| `error_code` | Meaning | Action |
|---|---|---|
| `invalid` | Bad input, or a provider or parser `ValueError` | Fix the cause, then retry. A provider hiccup can land here too, so a plain retry is worth one try. |
| `conflict` | The note changed while the job ran | Usually nothing. A newer job for the new revision runs on its own. |
| `unavailable` | Provider or database unavailable after 3 attempts | Check the provider keys and status, then retry. |
| `not_found` | The note or target is gone | Nothing, unless it shouldn't be gone. |

### Operator commands

Run these from the CLI shell set up under Paths on the server. Flags, previews, and
prompts are unchanged.

- Default: the command runs the job in its own process and prints the same report
  as before. The worker service may also pick up other due work at the same time.
  Leases and SQLite's write lock keep them apart.
- `--no-wait`: queue only, and let the service run it. Use this for long jobs like
  `reembed` or `ingest --rebuild-consensus`.

A `reembed` that runs longer than the 15-minute lease can be reclaimed and run a
second time. The writes are idempotent, so the result is the same, but it costs
extra embedding calls. Avoid running two `reembed` jobs at once.

## Rollback

### Code only

```bash
./deploy.sh --rollback
```

```bash
systemctl restart stock-ontology-worker
```

The previous release's web app writes to the database directly again, and its
`watch` runs the old ingest loop. It ignores the `jobs` and `consensus_refresh`
tables and the spool, which stay in place. When you deploy forward again, the
worker picks up whatever is still queued. A job whose note changed in the meantime
is superseded, not run against stale text.

### Restoring the database

Restore a database only if its data is damaged. A code rollback doesn't need it.
This discards every write since the backup.

```bash
systemctl stop stock-ontology-worker stock-ontology
ls -t /var/backups/stock-ontology | head -3
```

```bash
cp /var/lib/stock-ontology/ontology.db /var/lib/stock-ontology/ontology.db.broken
cp /var/backups/stock-ontology/<backup>.db /var/lib/stock-ontology/ontology.db
rm -f /var/lib/stock-ontology/ontology.db-wal /var/lib/stock-ontology/ontology.db-shm
systemctl start stock-ontology stock-ontology-worker
```

## Troubleshooting

- **Paste or Process returns an error right away.** The web process can't write
  the spool. Check the folder's owner against the app's `User=` (step 2).
- **Jobs stay queued.** The worker is down or crash-looping. Check
  `systemctl status stock-ontology-worker` and its journal.
- **The worker restarts in a loop with a registry error.** The applied registry
  changed while it ran. It should reopen and retry on its own. If the loop
  persists, run `registry-apply` from the CLI and check its output.
- **Memory pressure.** Two Python processes share 894 MB. If swap keeps growing,
  stop the worker during heavy browsing, or raise `--interval` to scan less often.
  Queued jobs wait safely until it's back.
- **`database is locked`.** Each connection waits 10 seconds for the write lock. A
  long `repair` or `registry-apply` can exceed that. The other job retries with
  backoff.
