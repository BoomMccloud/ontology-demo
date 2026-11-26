---
proposal_id: "worker-connection-reuse"
state: ACCEPTED
witness: builder
candidate: "195d828 @ worktree/claude/worker-connection-reuse-d48cb4"
---

# Proposal: Fewer database opens in the worker and status polling

## Proposal

### Intent

Each `Worker.open_store()` builds a new writable `OntologyDB`. Every open loads sqlite-vec, runs the schema script and migration check, and parses and hashes the applied registry. An idle `run_once` opens three times, and each job adds a claim open, an execute open, a fail open on error, and the next claim open. Job status polling from the browser (once a second per waiting tab) also opens a read-only database per poll, and the worker only reads the spool once per tick, so with the default 60-second interval a submitted job can wait up to a minute while the tab polls about 60 times.

Benefit: lower CPU and I/O on the server while idle and while jobs run, and faster pickup of submitted jobs, so the Process button and corrections feel responsive instead of waiting for the next scan tick.

### Tentative primary claim

A job submitted from the browser starts within a few seconds, and an idle worker does not reopen the database several times per tick.

### Why now

Found in the 2026-11-24 simplify review. It matters more now that the worker runs as a long-lived service on the production server.

### Known constraints

Only the worker opens `ontology.db` for writing. A registry change must still be detected (today via `RegistryChangedError` on open).

### Non-goals

None stated.

### Open choices

- How quickly a submitted job should start (the spool check cadence) versus how often the notes folder is rescanned.

## Frame

Candidate: `aa1d9f7 @ worktree/claude/worker-connection-reuse-d48cb4`

### Verified reality
- `uv run pytest -q` at `aa1d9f7` — proves the suite was green before the change (551 passed in 24.6 s); limit: no test measures database opens or pickup latency today.
- `src/stock_ontology/worker.py:253` `Worker.open_store` — proves every call constructs a new writable `OntologyDB`; limit: says nothing about cost per open.
- `src/stock_ontology/db/storage.py:92` `OntologyDB.__init__` — proves each open loads sqlite-vec, runs `_init_schema` (schema script and migration check) on writable opens, and parses the applied registry JSON on every open; limit: absolute cost not measured.
- `src/stock_ontology/worker.py:282` `run_once`, `:316` `_drain`, `:326` `_queue_scan` — proves an idle `run_once(scan=True)` opens three times (intake, claim, scan check) and each job adds a claim open, an execute open, a fail open on error, and the next claim open; limit: none.
- `src/stock_ontology/worker.py:307` `run_forever` — proves the spool is read only inside `run_once`, once per `interval_seconds` (default 60, `cli.py:294` and `:324`); limit: none.
- `src/stock_ontology/db/storage.py:160` `OntologyDB.transaction` — proves registry-change detection happens at transaction start on writable connections (`APPLIED_REVISION_KEY` against the connection's `_active_revision`, raising `RegistryChangedError`), so a long-lived connection still detects a change, on its next write; limit: reads outside a transaction are not checked.
- `src/stock_ontology/db/jobs.py:166` `JobStore.claim`, `:141` `insert`, `:155` `reopen`, `fail` — proves queue operations touch only `jobs` and `consensus_refresh` and run inside `transaction()`, so they never use `db.registry`; limit: none.
- `src/stock_ontology/pipeline.py:124` `db.use_registry(registry)` — proves an executor can change a connection's `registry` for the rest of its life, so sharing one connection across job executions would carry state between jobs; limit: only matters on a database with no applied registry, but it is why execution keeps its own connection.
- `src/stock_ontology/worker.py:631` `_run_rollout` opens a second `open_store()` while the attempt's connection is open, to see the newly adopted registry; limit: none.
- `src/stock_ontology/services/processing.py:179` `ProcessingService._open` / `_job` — proves each status read constructs a full read-only `OntologyDB` (sqlite-vec load and registry JSON parse) only to read one `jobs` row; `web/app.py:60` serves it at `/api/jobs/{job_id}`; limit: none.
- `src/stock_ontology/web/static/note_reader.js:112`, `ontology_edit.js:200` — proves each waiting tab polls once a second; limit: owned by the parallel `shared-editor-script` session, not changed here.
- `tests/test_architecture.py:98` `test_only_storage_touches_sqlite` — proves SQL and `sqlite3` imports must stay inside the `db` package, so a light job reader belongs in `src/stock_ontology/db/jobs.py`, not in `services/processing.py`; limit: none.
- `tests/test_worker.py:332` `test_registry_change_during_a_job_reopens_and_retries`, `:805` `test_run_forever_continues_after_a_tick_raises` — proves existing permanent owners for registry reopen and tick resilience; limit: neither covers a registry change between ticks on a reused connection.

### Final primary claim
- With the worker service running (`run_forever`, default `--interval 60`), a job submitted to the spool while the worker is idle is claimed within 2 seconds, and an idle worker opens `ontology.db` once for the life of the loop instead of three times per tick. Each job attempt still opens one connection to execute. Notes are still rescanned once per `--interval`. A job submitted while another job runs waits for it, as today.

### Routing
- Witness: `builder`
- Why: the change alters connection lifetimes and loop timing inside the worker process and one read path in the web process; it changes no schema, job contract, stored data, or API response, and reverts with a code rollback.
- Human-owned irreversible action: deploying the candidate to the production server and restarting `stock-ontology-worker`. No stage executes it.

### Decisive witness
- Layer: unit test of `Worker.run_forever` with a fake monotonic clock and sleep, counting `OntologyDB` constructions in `stock_ontology.worker`.
- Permanent owner: `tests/test_worker.py`
- Witness: over several idle 2-second spool checks and one notes scan, the worker opens `OntologyDB` once for queue work; a job spooled at fake time T is claimed and finished by fake time T + 2 s, before the next 60-second scan; the job's execution adds exactly one open.

### Guardrail claims
- Registry change is still detected: when another process adopts a new registry between ticks, the reused queue connection raises `RegistryChangedError` on its next transaction, the worker reopens and retries that queue operation once, and the next job succeeds against the adopted registry without a failed tick or a consumed attempt.
- Writes stay worker-only: the job-status read path opens its connection with `PRAGMA query_only = ON`, and the web app, CLI reads and `audit` stay read-only.
- `/api/jobs/{job_id}` returns the same status payload as before for spooled, recorded, failed-with-spooled-retry, and missing jobs, without constructing an `OntologyDB` (no sqlite-vec load, no registry parse).

### Supporting obligations
- Add a worker-owned queue connection used by `intake`, `claim`, `_queue_scan`, `_fail` and `run_until`'s status read, opened lazily and held for one session: the whole `run_forever` loop, or one `run_once` / `run_until` call. Close it when the session ends; drop it on any exception so the next use reopens. Unit candidate: a nested `run_once` inside `run_forever` reuses the session.
- Retry a queue operation once on `RegistryChangedError` after reopening. Unit candidate: adopt a registry from another connection between two `run_once` calls inside one session; the next job succeeds with `attempts == 1`.
- Keep `open_store()` as a fresh connection per job attempt, unchanged, so `_run`, executors and `_run_rollout`'s nested open keep their semantics.
- `run_forever`: rescan notes every `interval_seconds`; between scans, every `SPOOL_SECONDS = 2` (module constant), check whether the spool holds a submission (a directory listing, no database open) and if so run `run_once(scan=False)`. Keep catching and logging a failed tick. Add `ProcessingService.has_submissions()` beside `read_spool`.
- Add `read_jobs(db_path)` in `src/stock_ontology/db/jobs.py`: a context manager yielding a `JobStore` on a plain `sqlite3` connection with `query_only`, `busy_timeout` and `sqlite3.Row`, or None when the database does not exist. `ProcessingService` status reads (`_job`, `latest_for_note`) use it instead of a full `OntologyDB`.
- Update `docs/worker.md` (how it fits together) and the `watch --interval` help text to say the interval is the notes rescan and the spool is checked every 2 seconds.

### Allowed scope
- Reuse: extends `Worker` in `src/stock_ontology/worker.py` (`run_once`, `run_until`, `run_forever`, `_drain`, `_queue_scan`, `_fail`, `intake` callers), `JobStore` in `src/stock_ontology/db/jobs.py` as-is, and `ProcessingService` in `src/stock_ontology/services/processing.py`; tests extend `tests/test_worker.py` and the existing status tests.
- Cheaper alternative: lowering `--interval` on the service to a few seconds (an operational change, no code). Rejected: it would rescan the notes folder and open the database three times every few seconds, the opposite of the idle-cost half of the claim. A second rejected option is reusing one connection for job execution too: it would carry `use_registry` state between jobs (`pipeline.py:124`) and break `_run_rollout`'s nested fresh open, for one saved open per job.
- Include: `read_jobs` in `src/stock_ontology/db/jobs.py` (export from `db/__init__.py`); the queue-connection session and once-retry in `worker.py`; the two-cadence `run_forever` loop with `SPOOL_SECONDS`; `ProcessingService.has_submissions()` and the light status connection; doc and help-text updates; tests in `tests/test_worker.py` (and a status test where the existing status tests live).
- Exclude/protect: `_run`, `_run_correction`, `_run_ontology_correction` in `worker.py` and all of `pipeline.py` (owned by the parallel `pipeline-correction-api` session); all web JS, including the 1-second poll interval (owned by `shared-editor-script`); `OntologyDB` and existing `JobStore` behavior; job state rules, retry budget and backoff; CLI flags other than help text; the production service.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

- Witness deferred to Build (builder route). Decisive witness owner: `tests/test_worker.py`; Build must show it RED on `aa1d9f7` behavior and GREEN on the candidate.

<!-- Replaced only by proposal-prove, or by the orchestrator with the builder-route
deferred-witness status. Reference native witness path, exact command, concise RED
result, and candidate identity. -->

## Build

Candidate: `195d828 @ worktree/claude/worker-connection-reuse-d48cb4`

### Files changed

- `src/stock_ontology/worker.py` — `SPOOL_SECONDS = 2.0`; a session-scoped queue connection (`_session`, `_queue`, `_close_queue`) used by intake, claim, scan check, `_fail` and `run_until`'s status read, reopened once on `RegistryChangedError` and dropped on any other exception; `run_forever` rescans notes every `interval_seconds` and between scans runs `run_once(scan=False)` when the spool has a submission. `open_store()` is unchanged, so each job attempt still opens its own connection. `_run`, `_run_correction`, `_run_ontology_correction` untouched. Satisfies the primary claim and the registry guardrail.
- `src/stock_ontology/services/processing.py` — `has_submissions()`; `_job` and `latest_for_note` read through `read_jobs` instead of a full read-only `OntologyDB`. Satisfies the status-poll guardrail.
- `src/stock_ontology/db/jobs.py`, `src/stock_ontology/db/__init__.py` — `read_jobs(db_path)`: a `JobStore` on a plain `query_only` connection, or None when the database is missing. Satisfies the read-only and status-poll guardrails.
- `src/stock_ontology/cli.py` — `--interval` help text for `watch` and `worker` now says it is the note-scan interval and queued jobs start within 2 seconds.
- `docs/worker.md` — one bullet on the 2-second spool check, the notes rescan interval, and connection use.
- `README.md` — one Ingestion Constraints entry: run each job attempt on its own `open_store()` connection; the queue connection serves only queue work. Guarded by the two new worker tests.
- `tests/test_worker.py` — decisive witness `test_idle_worker_opens_once_and_starts_a_spooled_job_within_two_seconds`, guardrail tests `test_reused_worker_connection_detects_a_registry_change_between_ticks` and `test_job_status_reads_skip_the_full_store_and_stay_read_only`, fake-time helper `_LoopTime` and `_run_service`.

### Unit evidence

- Builder-owned decisive witness: `uv run pytest tests/test_worker.py -q -k "opens_once or registry_change_between or status_reads_skip"` on `aa1d9f7` source — RED, 3 failed: idle opens `[0.0, 0.0, 0.0]` instead of `[0]`; no job started before the stop at fake 30 s (the 60 s sleep skipped the submission window); status read constructed a full `OntologyDB`; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-worker-connection-reuse-d48cb4/c87b9c70-1a49-4345-8d52-ee0d5a520fc2/scratchpad/red.log`.
- Same command on the candidate — GREEN, 3 passed (part of the full run below).
- `uv run pytest tests/test_worker.py -q -W error::ResourceWarning` — GREEN, 22 passed; no leaked connections from sessions.

### Green evidence

- Decisive witness: `uv run pytest tests/test_worker.py -q` — pass, 22 passed.
- Gate: `uv run pytest -v` — pass, 554 passed in 22.7 s; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology--claude-worktrees-worker-connection-reuse-d48cb4/c87b9c70-1a49-4345-8d52-ee0d5a520fc2/scratchpad/green.log`.
- Gate: `uv run ruff check src tests` — pass.

### Intervention record

- None. The repository keeps no intervention ledger; the user-facing outcome (job pickup within 2 s) is measured by the decisive witness.

### Deviations

- None open. The first full run failed `tests/test_architecture.py::test_only_storage_touches_sqlite` because the light reader sat in `services/processing.py`. Frame was rerun to add `src/stock_ontology/db/jobs.py` to allowed scope before this Build section was written; the reader now lives there.

## Audit

Candidate: `195d828 @ worktree/claude/worker-connection-reuse-d48cb4` (source tree audited at 195d828; HEAD 481b1b5 differs only in the ledger's Build section)

Independence: fresh-context. Before this audit, the auditing context had seen only the orchestrator's brief, the ledger, AGENTS.md, and the proposal-audit skill. It had not seen the build session.

Primary-claim verdict: PROVED. Evidence: `tests/test_worker.py::test_idle_worker_opens_once_and_starts_a_spooled_job_within_two_seconds` runs `Worker.run_forever(60)` on fake monotonic time and sleep, and counts `OntologyDB` constructions in `stock_ontology.worker`. It asserts one open before the submission at t=10 (that window covers the t=0 notes scan and four idle 2-second spool checks), a job start between t=10 and t=12, exactly one more open for the attempt, and a final state of `succeeded`. I verified RED by running the test against aa1d9f7 `src/` in a scratch copy: the opens were `[0.0, 0.0, 0.0]` instead of `[0]`, and no job started before the stop at fake t=30. It is GREEN on the candidate. In code, `run_forever` sets `next_scan = monotonic() + interval_seconds` and sleeps `min(SPOOL_SECONDS, next_scan - now)`. `open_store()` is unchanged, so each attempt still opens its own connection. Limit: the hook fires on a 2-second boundary, so the test proves pickup on the next spool check but not the worst case of a submission landing just after a check (bounded by 2 s by construction). The test stops at t=30, so "notes are still rescanned once per `--interval`" is proved by code reading only, with no witness of a second scan at t=60. The test does not exercise the claim that a job submitted during another job waits for it.

Guardrail verdicts:
- Registry change is still detected on the reused queue connection: PROVED. Evidence: `test_reused_worker_connection_detects_a_registry_change_between_ticks` adopts a new registry from another connection at t=4, then submits at t=10. It asserts no "Worker tick failed" log, a start between t=10 and t=12, exactly two opens at t>=10 (queue reopen plus attempt), `attempts == 1`, and the adopted revision in place. Detection still comes from `OntologyDB.transaction` (`storage.py:159-168`, BEGIN IMMEDIATE plus the `APPLIED_REVISION_KEY` check), and every queue operation goes through `Worker._queue`, which reopens and retries once: intake, claim, `_queue_scan`, `_fail`, and `run_until`'s get. A mutation in a scratch copy that removed the retry (`for reopened in (True,)`) made the test fail on the caplog assertion, so the witness is sensitive to the retry. Limit: on aa1d9f7 this test was RED for the timing reason only, because fresh connections trivially see a new registry, so its RED does not isolate detection. The mutation run supplies that evidence instead. Reads outside a transaction (`get_ingestion_log` and `jobs.get` in `run_until`) are not registry-checked, but they never use `db.registry`.
- Writes stay worker-only: PROVED. Evidence: `read_jobs` in `src/stock_ontology/db/jobs.py` sets `PRAGMA query_only = ON` before yielding. The status test asserts `DELETE FROM jobs` raises `sqlite3.OperationalError` matching "readonly". The diff adds no write path outside `worker.py`. The web app, CLI reads, and `audit` are untouched, and the queue connection lives only in `Worker`. Limit: only the new status read path was re-witnessed. The other read-only paths are unchanged and rely on existing tests.
- `/api/jobs/{job_id}` payload unchanged, with no `OntologyDB` construction: PROVED. Evidence: `test_job_status_reads_skip_the_full_store_and_stay_read_only` patches `OntologyDB.__init__` to raise and re-reads recorded, spooled, `latest_for_note`, and missing-job statuses. For behavioral RED, I removed the test's `read_jobs` import and final block in a scratch copy and ran it against aa1d9f7 `src/`. It failed with "a status read must not open a full OntologyDB". Payload equivalence with the old code rests on the unchanged existing tests, which all pass on the candidate: `tests/test_worker.py` around lines 420-490 (failed with a spooled retry, pending retry shown as fresh), `tests/test_web_notes.py:1002-1010` (queued, missing 404, succeeded) and `tests/test_web_ontology.py:448,576`. Limit: the new test's `expected` dict is computed on the candidate itself, so on its own it shows only self-consistency. The Build's RED note for this test is inaccurate: on aa1d9f7 it fails first with `ImportError` for `read_jobs`, not on the full-store assertion. I had to establish the behavioral RED myself.

Scope and duty verdict: scope HELD; duties HELD. Evidence: `git diff aa1d9f7 195d828` touches only `worker.py` (session, `_queue`, `run_once`, `run_until`, `run_forever`, `_drain`, `_queue_scan`, `_fail`), `db/jobs.py` and `db/__init__.py` (`read_jobs`), `services/processing.py` (`has_submissions`, status reads), `cli.py` (help text only), `docs/worker.md`, `README.md`, `tests/test_worker.py`, and the ledger. `_run`, `_run_correction`, `_run_ontology_correction`, `pipeline.py`, all web JS, `OntologyDB`, existing `JobStore` methods, job state rules, the retry budget, and CLI flags are untouched. No existing test was edited. The one new `README.md` Ingestion Constraints entry (one connection per job attempt, a queue-only connection that reopens once on `RegistryChangedError`) is the constraint-capture entry step 7 requires. It has a `**Why:**` and two `**Guarded by:**` tests, and both exist and pass. Every supporting obligation is present, including `SPOOL_SECONDS = 2.0` and the doc and help-text updates. Limit: scope was judged against the re-run Frame, which added `src/stock_ontology/db/jobs.py` to allowed scope.

Test homes: `tests/test_worker.py`. It is the Frame-named permanent owner for worker loop, registry reopen, and job-status behavior. It also holds the new status-read test, because the existing status assertions already live there alongside `test_web_notes.py`.

Full gates: PASS. `uv run pytest -v` (run as `-q`): 554 passed in 22.1 s. `uv run ruff check src tests`: all checks passed. `uv run pytest tests/test_worker.py -q -W error::ResourceWarning`: 22 passed, with no leaked queue connections. Decisive witnesses: RED on aa1d9f7 source in a scratch copy (3 failed), GREEN on the candidate. The worktree was left clean (`git status --short` empty) and the scratch copy was removed. Limit: all evidence comes from offline tests on fake time. No run against the production service.

Residual risks:
- `has_submissions()` matches any `*.json` in the spool, but `read_spool` silently skips unparseable files and never deletes them. A corrupt or half-written submission therefore makes the loop run `run_once(scan=False)` every 2 seconds indefinitely: one intake plus one BEGIN IMMEDIATE claim on the reused connection, with no error. That costs little, but it is a quiet idle-cost regression that has no test.
- A persistent intake or claim failure is now logged every 2 seconds instead of every 60, and each failure drops and reopens the queue connection. Log volume and reopen cost go up in that failure mode.
- Backed-off retries and expired leases are still picked up only at the notes-scan cadence (`--interval`) or when a new submission arrives, not within 2 seconds. This matches the old behavior and the claim, but operators may expect otherwise.
- The production rollout (deploy and restart `stock-ontology-worker`) stays human-owned and unverified.

Recommendation: ACCEPT
Packet: No re-audit is needed. Optional follow-ups for the human, outside this proposal: make `has_submissions` ignore or quarantine unparseable spool files, and correct the Build's RED note for the status test (on aa1d9f7 it fails first with `ImportError`, not on the full-store assertion). Deploying to the production server and restarting the worker still needs separate human authorization.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
