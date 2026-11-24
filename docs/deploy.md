# Deploying

Code moves from your Mac to GitHub to the server. Data stays on the server.

## Setup

Copy `.deploy.env.example` to `.deploy.env` in the main checkout and fill in the
server and SSH key. Save the server's verified host key in `.deploy.known_hosts`
beside it. Both files are git-ignored.

## Everyday flow

```bash
uv run pytest -q
git push origin main
./deploy.sh
```

`deploy.sh` tests the exact commit, uploads it to its own release folder, installs
its locked dependencies, backs up the database, switches `current`, restarts the
app, and checks health. If the check fails, it switches back and exits non-zero.

| Command | What it does |
|---|---|
| `./deploy.sh` | Deploy `origin/main` |
| `./deploy.sh <commit>` | Deploy a commit already on `origin/main` |
| `./deploy.sh --dry-run` | Run the checks and show what would change |
| `./deploy.sh --status` | Show the running release and health |
| `./deploy.sh --rollback` | Switch back to the previous release |

The server keeps the last 5 releases, plus the current and previous ones, and the
last 10 pre-deploy database backups in `/var/backups/stock-ontology`.

## What a deploy does not do

- It does not restart the worker. Run `systemctl restart stock-ontology-worker`
  after each deploy and rollback. The first worker setup is in
  [worker.md](worker.md).
- It never writes to the database or notes. A rollback restores code only.
- It does not adopt registry changes. When it prints a registry notice, review the
  change and run `registry-apply` on the server.
- It does not run ingest or `repair`.
- Its backups stay on the server, so they do not protect against losing the server.
