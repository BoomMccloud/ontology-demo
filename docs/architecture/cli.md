# CLI

The `stock-ontology` command (Typer), wired up as `stock_ontology.cli:app`. It
builds settings and the LLM client, then hands off to the services and the
worker. It opens `ontology.db` only read-only and should hold no business logic
of its own.

## Files

- `src/stock_ontology/cli.py`

## Commands

| Command | Module it drives | Writes to DB |
| --- | --- | --- |
| `ingest` (`--force`, `--rebuild-consensus`) | worker `ingest` job | through the job |
| `reembed` | worker `reembed` job | through the job |
| `repair` (`--reembed`) | preview on a copy, then worker `repair` job | through the job |
| `registry-apply` | preview on a copy, then worker `registry.apply` job | through the job |
| `registry-publish` | diff and prompt, then worker `registry.publish` job | job rows only (writes the registry file) |
| `watch`, `worker` | the worker loop | yes, as the worker |
| `note save`, `note list` | `NotesService` | no (`save` writes a note and queues a job) |
| `process`, `status`, `retry` | `ProcessingService` | no (submits to the spool) |
| `entity` | `GraphQueries` | no |
| `audit` | governance | no (may update the registry file) |
| `inspect` | storage | no |
| `ask`, `chat` | agent | no |
| `serve` | web app | no |

Each operator job command keeps its flags, preview, and confirmation prompt,
then queues its job and by default runs the worker in its own process until the
job finishes, printing the same report. `--no-wait` only queues the job (with
`--json`, `ingest --no-wait` prints `{"job_id", "state"}`); a running `worker`
or `watch` applies it.

Agent-facing commands take `--json` and print one JSON object on stdout:
`note save --title T --text X` gives `{"file", "job_id"}`, `process FILE`
gives `{"job_id", "state"}`, `status JOB_ID` gives the job's `state`,
`attempts`, `next_attempt_at`, `error_code`, and `error`, and `entity NAME`
gives `{"entity", "consensus" (with `stale` and `as_of`), "events"
(each with `source.file`), "views", "themes", "related_entities"}`. A
rejected request prints `{"error": {"code", "message"}}` and exits with the
code's number from `services.EXIT_CODES`.

`worker` takes `--once` (drain due work and exit), `--lease-seconds`,
`--interval`, and `--scan/--no-scan` (queue an ingest scan when notes changed or
a consensus refresh is still pending). `watch --interval` runs the same loop.

Most commands take `--lang` / `-l`.

## Depends on

Every other module. It's the composition root.

## Tests

CLI cases live in `tests/test_db.py`, `tests/test_registry_audit.py`,
`tests/test_i18n.py`, `tests/test_relationships.py`, and `tests/test_worker.py`
(the agent JSON journey and the job path of every operator command).
