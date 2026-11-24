---
proposal_id: "modular-worker"
state: ACCEPTED
witness: independent
candidate: "8bef4e5 + a1c1b1d5 (working tree digest) @ main checkout"
---

# Proposal: Service layer, then durable background processing

## Proposal

### Intent

Put every user-facing operation behind one service layer that the CLI, web app, in-app agent, and a future MCP server all call. Each component can then change its internals without touching the others, and outside agents get a stable contract. A background worker is the only database writer. It runs extraction, consensus, corrections, and registry changes as jobs submitted through that layer.

### Tentative primary claim

An agent can save a note, request processing, poll the job, and read the resulting entity overview through CLI commands with `--json` output. It never touches SQLite or the notes folder, and it gets the same results the web app shows, even if the worker restarts mid-job.

### Why now

- The CLI, web app, and agent each go around a shared layer. The web app saves and scans notes itself (`web/note_intake.py`, `web/catalog.py`). The CLI's `inspect` renders straight from `OntologyDB`. Graph query meaning lives in a 76-method storage class that the CLI, pipeline, agent, web app, and audit all call.
- Outside agents are the intended third parties, through the CLI now and possibly MCP later. Without a service layer, each new adapter copies the logic again.
- `/api/notes/process` runs three extraction passes inside one HTTP request, which an outside caller can't wait on.
- Periodic ingestion can leave a company's consensus out of date after an isolated refresh failure.

### Known constraints

- Retain the modular monolith. The worker is a separate process built from the same codebase.
- Preserve user access to the raw notes and the structured ontology.
- Keep approved registry changes operator-controlled and out of agent-facing adapters.
- One shared library. All users see the same notes and graph.
- Data flows one way. The worker is the only process that writes to `ontology.db`. The web app, CLI read commands, agent, and MCP open it read-only and submit commands for writes.
- Scale means more notes and more users first. The design should allow more workers later without changing callers.

### Non-goals

- Authentication and authorization for the web app, CLI, and MCP. This is a later phase, and the service contract should leave room for a caller identity.
- Per-user libraries or multi-tenancy.
- Persistent chat history. It is a later agent feature, and the service layer must not block it.
- An HTTP API, separately deployed services, or replacing SQLite.

### Open choices

- Initial retry limits, backoff delays, and job priorities.
- Whether to ship the MCP server in this proposal or a follow-up once the CLI JSON contract is stable.

### Decided choices

- Third parties are agents, through the CLI now and possibly MCP later.
- Scale targets more notes and more users, in one shared library.
- All database writes go through the worker, including operator commands: `registry-publish`, `registry-apply`, `repair`, `reembed`, and `ingest`.
- A previously published consensus stays visible, shown as stale, until its replacement succeeds.
- Chat history persistence and authentication are deferred.

## Frame

Candidate: `8bef4e5 + uncommitted working tree (accepted note-reader, note-entity-actions, and note-relationship-actions changes) @ main checkout of stock_ontology`

### Verified reality
- `uv run --offline pytest -q` on the candidate: proves 493 passed, 0 failed before this change; limit: offline fake-LLM suites only, run on an uncommitted tree.
- `src/stock_ontology/cli.py:612` `_create_library_app.note_writer`: proves the web app's note actions open a writable `OntologyDB` and run `IngestionPipeline` in the web process; limit: does not show how often web and ingest write at the same time.
- `src/stock_ontology/web/app.py:606` `process_note`: proves **Process** runs `pipeline.process_note` (staged extraction and consensus) synchronously inside the HTTP request; limit: request latency on the deployed server is not measured.
- `src/stock_ontology/web/note_intake.py:59` `save_pasted_note` and `web/catalog.py:388` `_scan_raw_notes`: prove note saving and note listing, including the `ingested`, `modified`, and `not_ingested` status derived from `ingestion_log`, live in the web module; limit: no CLI path saves or lists notes today.
- `src/stock_ontology/db/schema.py:66` `ingestion_log`: proves extraction state is file path, doc ID, content hash, and time only; no job, attempt, lease, or consensus status exists.
- `src/stock_ontology/pipeline.py:1024` `_refresh_consensus` and `:1037` `watch`: prove a consensus failure is logged to the run report and not retried, and `watch` re-runs `run()` on an interval; limit: no persisted record of failed companies.
- `src/stock_ontology/db/storage.py:118` and `:146` `transaction`: prove read-only connections set `PRAGMA query_only = ON`, writers use WAL and `BEGIN IMMEDIATE`, and every write transaction aborts with `FacetSchemaError` when the applied registry revision changed since the connection opened; limit: no `busy_timeout` is set, so a second writer fails fast on a lock instead of waiting.
- `src/stock_ontology/db/storage.py:254` `_migrate_schema` with `schema.init_schema`: proves schema changes are additive `CREATE TABLE IF NOT EXISTS` and column additions run on writable open; limit: no version-numbered migrations.
- `cli.py:139`, `:233`, `:294`, `:931`, `:993`, `:1073`: prove `ingest`, `reembed`, `watch`, `registry-publish`, `registry-apply`, and `repair` each open their own writable connection; only `audit` (`cli.py:836`) supports `--json`.
- `tests/test_architecture.py:35` `ALLOWED`: proves `web` may import `storage`, `llm`, `search`, `agent`, and `governance`, and there is no services layer; limit: it checks imports, not runtime filesystem access.

### Final primary claim
- Using only CLI commands with `--json` against a temporary database and fake LLM, an agent saves a note, requests processing and receives a job reference, polls until the job succeeds, and reads that note's company entity overview with the same facts and citations the web entity page shows. Killing the worker mid-job and starting it again still reaches success, with consensus recovered without a second extraction call.

### Routing
- Witness: `independent`
- Why: it moves every database write, user-facing and operator, onto one job path and adds persisted job state to `ontology.db`, so it crosses the web, CLI, pipeline, and storage boundaries and can break stored graph data.
- Human-owned irreversible action: the schema migration and worker rollout on the production database at `/var/lib/stock-ontology/ontology.db`, plus merge and deploy.

### Decisive witness
- Layer: integration test in process, with a temporary SQLite database, a temporary notes directory, a fake LLM, and the Typer `CliRunner`; the worker is driven by calling its run entry point, and the crash is simulated by abandoning a claimed job and expiring its lease.
- Permanent owner: a new `tests/test_worker.py`.
- Witness: JSON from `save`, `process`, `status`, and the entity read commands reaches `succeeded` and returns the entity overview; after an injected consensus failure and lease expiry, a second worker run publishes consensus, and the fake LLM records exactly one extraction call for that note revision.

### Guardrail claims
- The web app, CLI read commands, and in-app agent open `ontology.db` only with `PRAGMA query_only = ON`; **Process**, relink, and relationship corrections return a job reference and the note reader shows pending, succeeded, or failed for that job.
- A consensus attempt that read evidence before a newer evidence change commits cannot publish or mark the newer refresh complete, and an attempt whose lease expired cannot commit.
- When a consensus refresh is pending or failed, the entity page and its JSON keep the previous consensus with its original date and citations and mark it stale.

### Supporting obligations
- Additive tables for jobs and per-company consensus refresh, created by `schema.init_schema`, with a test that opens a database created before them.
- Job claim with claim ID and lease, reclaim after expiry, and a commit that checks claim, note revision, and applied registry revision; unit tests in `tests/test_worker.py`.
- The worker treats `FacetSchemaError` from `transaction` as reopen-and-retry, not a terminal failure.
- Consensus refresh rows are written in the same transaction as the extraction or correction commit; a rolled-back write adds none.
- Corrections run ahead of queued extraction; a unit test orders a correction before an earlier extraction job.
- Fixed initial retry policy: three attempts per job revision with exponential backoff starting at 60 seconds; a newer revision resets the budget.
- `NotesService` takes over `save_pasted_note` and `_scan_raw_notes` logic; existing `tests/test_note_intake.py` and web note tests keep passing through it.
- `RegistryService.get_applied()` replaces the `applied_registry() or _load_ingest_registry()` fallback at `cli.py:618`.
- A thin `GraphQueries` service that delegates to the existing `OntologyDB` overview methods, shared by the web entity page and the CLI JSON read.
- CLI commands with `--json` and typed error codes: `note save`, `note list`, `process`, `status`, `retry`, `worker`, and an entity read.
- Operator commands `ingest`, `ingest --rebuild-consensus`, `reembed`, `repair`, `registry-publish`, and `registry-apply` become job kinds. Each CLI command keeps its current flags, preview, and confirmation prompt, then enqueues its job and by default runs the worker loop in its own process until that job finishes, printing the same report; `--no-wait` only enqueues. The registry preview keeps running on a temporary copy, as `cli.py:967` does today. A test per command shows it reaches the database only through a claimed job.
- A guard test fails if any module other than the worker's job executors opens `OntologyDB` with `read_only=False`.
- Extend `tests/test_architecture.py` with a `services` module, and block migrated adapters (web) from importing `storage`.

### Allowed scope
- Reuse: `IngestionPipeline._process_document`, `_refresh_consensus`, and `_rebuild_company_consensus` for the work itself; `watch` as the worker loop; `OntologyDB.transaction(immediate=True)` and its registry-revision check for commit safety; `ingestion_log` hashes for note revisions; existing web note-action tests as the compatibility suite.
- Cheaper alternative: a systemd `watch` service plus a daily `ingest --rebuild-consensus` timer, with no code. Rejected because the claim needs async **Process** with a job reference, a CLI an agent can drive with JSON, and recovery that retries only the failed consensus.
- Include: Phases 1, 2, and 3 of the draft plan (services for notes, registry, and a delegating `GraphQueries`; job store and worker as the only writer, with operator commands as job kinds; agent-facing CLI JSON), plus the stale consensus marker on the entity page and its JSON.
- Exclude/protect: Phase 4 (moving query semantics out of `OntologyDB`), Phase 5 (LLM task split), the MCP server, in-app agent tools moving to services, authentication, persistent chat, and any change to extraction prompts or consensus synthesis rules. Phase 6 runbook writing is allowed; executing migration or rollout is human-owned. Existing protected witnesses from accepted ledgers in `tests/test_pipeline.py`, `tests/test_repair.py`, `tests/test_relationships.py`, and `tests/test_registry_governance.py` must stay green.

### Invariants changed
- `AGENTS.md:14`: today: the query agent, web UI, and `audit` open the DB read-only and only ingestion writes; after: every reader including the web app's note actions is read-only, and only the worker's job executors write; operator CLI commands write by enqueueing and running their own job.
- `docs/architecture/README.md:35`: today: seven layers with the web app importing storage and the CLI as the composition root; after: a `services` layer sits below the web app and CLI, and the web app imports services instead of storage.
- `tests/test_architecture.py:44`: today: `web` may import `storage`, `llm`, `search`, `agent`, `governance`; after: `web` may import `services` and not `storage`.
- `docs/architecture/web.md:46` and `src/stock_ontology/web/app.py:3`: today: `/api/notes/process`, `/relink`, and `/relationship` apply the change before responding; after: they return a job reference and the reader polls status.
- `src/stock_ontology/web/note_intake.py:3`: today: a saved note reaches the ontology through the next `ingest` or `watch` run; after: saving queues a processing job.
- `docs/architecture/cli.md` and `docs/architecture/governance.md`: today: `ingest`, `reembed`, `repair`, `registry-publish`, and `registry-apply` write directly; after: each runs as a worker job, waiting by default.
- `tests/test_web.py:2354` and the note-reader correction tests at `:2677` and `:2728`: today: they assert the graph changed when the request returns; after: they assert a job reference, then the change after a worker run.

### Decisions required
- None.

## Proof

Candidate: `8bef4e5 + uncommitted working tree (accepted note-reader, note-entity-actions, and note-relationship-actions changes) @ main checkout of stock_ontology`

**Protected witness**
- Primary claim: using only CLI JSON commands against a temporary database and a fake LLM, an agent saves a note, gets a job reference, the job reaches success even though the worker dies mid-job, consensus is recovered without a second extraction, and the entity read matches the web entity page. Test: `tests/test_worker.py` / `test_agent_journey_through_cli_json_survives_worker_kill`
  - Defect and boundary: no CLI command saves a note, queues processing, runs a worker, reports job status, or returns an entity overview as JSON, and no job state is stored, so a worker killed mid-job cannot resume. The boundary runs from the CLI adapter through the notes folder, the job store in `ontology.db`, and the extraction and consensus pipeline, to the web entity page.
  - Assertion: `note save ... --json` returns `file` and the note exists under `ONTOLOGY_DATA_DIR`. Proves: an agent saves a note without touching the notes folder. Limit: it does not prove the web save route uses the same service.
  - Assertion: `process <file> --json` returns a non-empty `job_id`. Proves: processing returns a job reference instead of doing the work inline. Limit: it does not cover duplicate requests sharing a job or web **Process**.
  - Assertion: the first `worker --once --lease-seconds 2` run is killed by a `BaseException` raised in the first consensus call. After the lease expires, a second `worker --once` run exits 0, `status <job_id> --json` reports `state == "succeeded"`, the fake LLM records exactly one extraction call for the note, and it records two consensus calls. Proves: a restarted worker reclaims the expired claim and publishes consensus without re-extracting. Limit: one worker, one note, a kill only inside consensus; it does not cover a kill during the extraction commit, retry backoff, a provider failure that raises an ordinary `Exception`, or a late result racing newer evidence.
  - Assertion: `entity "Acme Robotics" --json` returns that entity, `consensus.summary` equal to the fake synthesis, `consensus.stale is False`, and events equal to exactly `{(event name, saved note file)}`. The web `/entity/{id}` page for the same id contains that consensus summary, event name, and note file. Proves: the CLI read shows the same facts and citations as the web entity page. Limit: it compares only the consensus summary, the event name, and the citation file. It does not compare views, themes, related entities, or the stale-marker rendering.
  - Assertion: provider API key variables are blanked, and the LLM comes from the existing `stock_ontology.cli.create_llm_client` seam. Proves: the witness can only reach the fake LLM. Limit: it binds every new CLI command, `worker` included, to that seam.
  - CLI contract fixed by this witness: `note save --title --text --json` → `{"file": ...}`; `process FILE --json` → `{"job_id": ...}`; `worker --once --lease-seconds N` runs due work and exits; `status JOB_ID --json` → `{"state": ...}`; `entity NAME --json` → `{"entity": {"id", "name"}, "consensus": {"summary", "stale"}, "events": [{"name", "source": {"file"}}]}`. Paths come from `ONTOLOGY_DB`, `ONTOLOGY_DATA_DIR`, and `ONTOLOGY_REGISTRY`; the registry path points at a missing file, so the minimal built-in registry is used.
- Protected paths: `tests/test_worker.py` (the whole file, including `_JourneyLLM`, `_WorkerKilled`, and `test_agent_journey_through_cli_json_survives_worker_kill`). Build may add new tests to this file for the supporting obligations below but must not change the protected test or its helpers.
- Protected revision: `tests/test_worker.py` untracked on the candidate, git blob `88cec11a6737c7509e0823ede2a73b61fca4f896`, sha256 `a08922fb1c76fde9e61ef18547569f279d604ac6bd1c1fef500dc6ece13545c6`.

**Red evidence**
- `uv run --offline pytest tests/test_worker.py -v` → 1 failed: `note save` exits 2 with "No such command 'note'" (missing agent-facing CLI and worker behavior); log: `work/proof/modular-worker-red.log`.
- Feasibility check, not proof: on the candidate, a scratch run of today's `IngestionPipeline` with the same fake, with the kill skipped, put the consensus summary, the event name, and the saved file `_general/2026-11-24_acme_q3_check.md` on `/entity/{id}` with no ingest errors. The web-page assertions are satisfiable, and only the CLI and worker behavior is missing.
- Guardrail claims have no proof yet. The read-only openings, the job reference from web **Process**, relink, and relationship corrections, and the note-reader job status; late or expired attempts that cannot publish; and the stale previous consensus on the entity page and its JSON have no independent RED witness in this Proof. Build must add each as a new test in its named owner and show it RED before implementing. Audit should treat them as builder-owned evidence, not protected proof.
- The primary claim has no proof until `uv run --offline pytest tests/test_worker.py -v` is observed RED and then GREEN against the built candidate with the protected revision unchanged.

**Supporting test plan**
- Additive job and consensus refresh tables open on a database created before them → Build: `tests/test_db.py`; catches a migration that fails or drops data on an existing `ontology.db`.
- Claim with claim ID and lease, reclaim after expiry, and a commit that checks claim, note revision, and registry revision → Build: `tests/test_worker.py` (new tests); catches an expired or stale attempt committing.
- `FacetSchemaError` from `transaction` is reopen-and-retry, not terminal → Build: `tests/test_worker.py`; catches a registry apply permanently failing queued jobs.
- Consensus refresh rows are written in the extraction or correction transaction, and a rollback adds none → Build: `tests/test_worker.py`; catches orphan refresh rows after a failed commit.
- Corrections run ahead of an earlier queued extraction → Build: `tests/test_worker.py`; catches priority inversion.
- Three attempts per job revision with exponential backoff from 60 seconds, and a newer revision resets the budget → Build: `tests/test_worker.py`; catches unbounded retries or a stuck budget.
- `NotesService` serves save and list, and existing note tests pass through it → Build: `tests/test_note_intake.py`, `tests/test_web.py`; catches regressions when note logic moves out of `web/`.
- `RegistryService.get_applied()` replaces the JSON fallback at `cli.py:618` → Build: `tests/test_registry_governance.py`; catches reads that ignore the applied registry.
- Web **Process**, relink, and relationship routes return a job reference and apply after a worker run → Build: `tests/test_web.py` (amend `:2354`, `:2677`, `:2728` as the Frame records); catches synchronous writes left in the web process.
- Stale previous consensus kept with its date and citations on the entity page and JSON → Build: `tests/test_web.py` and `tests/test_worker.py`; catches the consensus disappearing or a stale one shown as current.
- Each operator command (`ingest`, `ingest --rebuild-consensus`, `reembed`, `repair`, `registry-publish`, `registry-apply`) writes only through a claimed job and keeps its flags, preview, and prompt → Build: `tests/test_worker.py` and the existing command owners in `tests/test_db.py`, `tests/test_repair.py`, `tests/test_registry_governance.py`; catches direct writable opens.
- Guard test that no module except the worker's job executors opens `OntologyDB(read_only=False)`, plus a `services` layer in `tests/test_architecture.py` with `web` blocked from `storage` → Build: `tests/test_architecture.py`; catches new writers and adapter imports that go around the services layer.

## Build

Candidate: `8bef4e5 + a1c1b1d5e360d43b8db0ca2a4b3c8584a244ed8bde3a55df3bd8957b46d1aeba @ main checkout`. The digest is the sha256 of `git diff --binary HEAD` followed by, for each untracked file under `src/` and `tests/` in sorted order, a `== <path>` line and the file's bytes: `(git diff --binary HEAD; for f in $(git ls-files --others --exclude-standard src tests | sort); do printf '== %s\n' "$f"; cat "$f"; done) | shasum -a 256`. Built on top of the accepted note-reader working tree. Nothing is committed or staged.

### Files changed
- `src/stock_ontology/db/schema.py`: adds the `jobs` and `consensus_refresh` tables to `init_schema` with `CREATE TABLE IF NOT EXISTS`. Satisfies the additive tables obligation.
- `src/stock_ontology/db/jobs.py` (new): `JobStore` and `Job`. Claim with a claim ID and a lease, reclaim after expiry, `check_claim` (refuses a lost or expired claim and extends the lease), finish, fail with a retry time, supersede, reopen, record a result, and consensus refresh revisions (`mark_consensus_pending`, `complete_consensus`, `fail_consensus`). Reads work on read-only databases and on databases created before these tables. Satisfies the claim, lease, and commit check obligation.
- `src/stock_ontology/db/storage.py`, `src/stock_ontology/db/__init__.py`: `OntologyDB.jobs`, a 10 s `busy_timeout` on every connection, and `RegistryChangedError` (a `FacetSchemaError`) when the applied registry changed after the connection opened. Satisfies the reopen-and-retry obligation.
- `src/stock_ontology/pipeline.py`: `commit_check` hook and `_evidence_changed`, so every evidence transaction (extraction, deletions, rebuild, corrections) writes its consensus refresh rows in that same transaction. Consensus synthesis and embedding run outside the write transaction and publish only if the refresh revision is unchanged, otherwise `StaleConsensusError`. A failed refresh marks the row `failed` and keeps the previous consensus. `RegistryChangedError` and `LeaseLostError` are re-raised instead of counted as per-note errors. Satisfies guardrails 2 and 3 and the same-transaction obligation.
- `src/stock_ontology/services/` (new): `errors.py` (`ServiceError`, `EXIT_CODES`: not_found 3, conflict 4, invalid 5, unavailable 6); `notes.py` (`NotesService`, taking over note saving, which then queues processing, plus the note scan with status and `has_changes`); `processing.py` (`ProcessingService`: submissions to the command spool `<db>.commands/`, job IDs derived from note path and revision so duplicates share a job, status, retry, priorities of corrections 0, operator commands 10, extraction 20, and 3 attempts with backoff from 60 s); `registry.py` (`RegistryService.get_applied`); `graph.py` (`GraphQueries` delegating the entity overview and adding consensus status and stale flag, read-only `open_graph`, and a `GraphStore` type re-export so `web` needs no storage import).
- `src/stock_ontology/worker.py` (new): `Worker` with spool intake, claim and drain, `run_once`, `run_until`, `run_forever`, and the ingest scan. Invalid input and conflicts fail at once; other failures retry with backoff; a registry change reopens and retries. The `process` executor supersedes a job when the note changed and resumes at consensus without re-extracting. Executors for the six note corrections, `ingest`, `reembed`, `repair`, `registry.apply`, and `registry.publish`; repair, apply, and publish finish their job inside the write transaction that applies the change. `plan_rollout` (preview on a temporary copy), `load_suggestions`, and `load_repair_registry` moved here from `cli.py`.
- `src/stock_ontology/cli.py`: new `note save`, `note list`, `process`, `status`, `retry`, and `entity`, all with `--json` and typed errors, and `worker` with `--once`, `--lease-seconds`, `--interval`, `--scan/--no-scan`. `watch` runs the worker loop. `ingest`, `ingest --rebuild-consensus`, `reembed`, `repair`, `registry-publish`, and `registry-apply` keep their flags, diff or preview, and prompt, then queue their job and wait by default; `--no-wait` only queues. No writable `OntologyDB` open remains in this file.
- `src/stock_ontology/web/app.py`: imports services instead of storage and opens the database read-only. Paste saves through `NotesService.save` with queuing on and returns 201 `{file, job_id}`. **Process**, relink, entity add and delete, and relationship correct, add, and delete return 202 `{file, job_id, state}`. New `GET /api/jobs/{job_id}`. The entity page gets `consensus_stale`. `note_writer` is replaced by `note_actions`. Satisfies guardrail 1 and the `note_intake` invariant.
- `src/stock_ontology/web/catalog.py`, `src/stock_ontology/web/viewmodels.py`: storage imports replaced by services; note scanning goes through `services.notes.scan_notes`; new `NoteExtraction.job_state`.
- `src/stock_ontology/web/note_intake.py`: deleted; its code moved to `services/notes.py`.
- Web templates, static files, and locales: `note_reader.html` shows `data-job-state`, `note_reader.js` polls the job, `facet_consensus_card.html` shows the stale marker `data-consensus-stale`, `library.css` styles both, and each of the six locales gains six strings.
- `tests/test_worker.py`: 11 tests appended after the unchanged protected prefix, covering claim and lease, an expired lease that cannot commit extraction, a consensus attempt whose lease expired during synthesis that cannot publish (`test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish`, added in audit rerun 1), a late consensus that cannot publish, registry-change reopen, refresh rows rolling back with their extraction, corrections ahead of extraction, the retry policy, stale consensus keeping its date and citations, every operator command (publish included) writing only through a claimed job, and CLI reads being read-only with typed errors.
- `tests/test_architecture.py`: adds `services` and `worker` layers, blocks `web` from importing `storage`, and adds `test_only_worker_job_executors_open_a_writable_database`.
- `tests/test_db.py`: new `test_job_tables_are_added_to_a_database_created_before_them`.
- `tests/test_registry_governance.py`: new `test_registry_service_reads_the_applied_registry_not_the_published_file`. Amended accepted witness `test_publish_and_apply_require_separate_interactive_decisions` (human-authorized): after a confirmed publish and the declined apply that follows, a new `_graph_state` helper checks graph rows, applied registry revision, and facet stamp are unchanged instead of whole-file byte identity, and one `registry.publish` job succeeded. The declined-publish byte check is unchanged.
- `tests/test_web.py`: new `_note_action` helper (a note action returns 202, one worker run applies it, and the job outcome maps to 200, 404, 409, 422, or 500). Amended `test_note_reader_extraction_workflow` (which, since audit rerun 1, also asserts `data-job-state="failed"` after a failed correction), `test_note_reader_can_correct_both_relationship_endpoints`, `test_note_reader_adds_and_deletes_relationships`, and `test_note_reader_adds_and_deletes_entities` (the last two human-approved as built). Amended accepted test `test_paste_note_hostile_title_stays_a_visible_file_in_general` (human-authorized) to allow writes under `<db>.commands/` and to assert a `job_id`; every other assertion is unchanged. New `test_web_note_actions_return_job_references_and_open_the_db_read_only`.
- `tests/test_note_intake.py`: imports from `stock_ontology.services.notes`.
- Docs: `AGENTS.md` invariants now name the worker as the only writer with every operator command, publish included, running as a job. `docs/architecture/README.md` has twelve modules, the new data flow and layers, a services and worker section, and a durable constraint entry guarded by `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database` and `tests/test_worker.py::test_operator_commands_write_only_through_claimed_jobs`. `docs/architecture/cli.md`, `web.md`, `governance.md`, `pipeline.md`, `storage.md`, and `README.md` describe the new flows.

### Unit evidence
- `uv run --offline pytest tests/test_worker.py -q`: RED before implementation, collection ImportError for `LeaseLostError` and the missing worker and services modules; log `work/build/red-worker.log`.
- `uv run --offline pytest tests/test_architecture.py tests/test_registry_governance.py tests/test_db.py::test_job_tables_are_added_to_a_database_created_before_them -q`: RED, 4 failed (layer violations, writable opens outside the worker, `stock_ontology.services` missing, `no such table: jobs`); log `work/build/red-supporting.log`.
- `uv run --offline pytest tests/test_web.py -q -k "note_reader or job_references"`: RED, 5 failed (note actions returned 200, `/api/jobs` missing); log `work/build/red-web.log`.
- Repair pass, against the earlier candidate before code changes: `uv run --offline pytest "tests/test_registry_governance.py::test_publish_and_apply_require_separate_interactive_decisions" "tests/test_web.py::test_paste_note_hostile_title_stays_a_visible_file_in_general" tests/test_worker.py::test_operator_commands_write_only_through_claimed_jobs -q`: RED, 8 failed (no publish job recorded; 6 hostile-title cases with `KeyError: 'job_id'`; no `registry.publish` job in the operator test); log `work/build/red-repair.log`.
- `uv run --offline pytest tests/test_registry_governance.py tests/test_web.py tests/test_worker.py tests/test_db.py tests/test_note_intake.py tests/test_architecture.py tests/test_relation_facets.py -q`: GREEN, 152 passed; log `work/build/green-repair.log`.
- Audit rerun 1: `uv run --offline pytest tests/test_worker.py::test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish -q` with `self._check_commit({})` temporarily removed from `_rebuild_company_consensus.publish` in `src/stock_ontology/pipeline.py`: RED, 1 failed ("the expired attempt published its consensus"); log `work/build/red-r1.log`. Same command with `pipeline.py` restored (`cmp` identical to the candidate): GREEN, 1 passed; log `work/build/green-r1.log`. No production code changed in this rerun.

### Green evidence
- Decisive witness: `uv run --offline pytest "tests/test_worker.py::test_agent_journey_through_cli_json_survives_worker_kill" -q`: pass; log `work/build/witness-green.log`. The first 5,423 bytes of `tests/test_worker.py` are byte-identical to `work/build/test_worker.protected.py` and hash to git blob `88cec11a6737c7509e0823ede2a73b61fca4f896`, matching the Proof. The orchestrator rechecked the hash and the candidate digest.
- Gate: `uv run --offline pytest -q`: 509 passed (493 baseline, the protected witness, 15 new tests); log `work/build/gate.log`. The orchestrator reran it on this candidate with the same result.
- `uv run --offline ruff check --select F,E9` on `worker.py`, `cli.py`, `web/app.py`, and `services/`: clean.
- No test opened the repo-root `ontology.db` or created a spool in the repo root. No production server or live database was touched.

### Intervention record
- The repository has no intervention ledger.
- Human-authorized amendments to accepted tests in the repair pass: `tests/test_registry_governance.py::test_publish_and_apply_require_separate_interactive_decisions` (graph rows and applied registry revision unchanged, instead of whole-file byte identity) and `tests/test_web.py::test_paste_note_hostile_title_stays_a_visible_file_in_general` (writes under `<db>.commands/` allowed).
- Human-approved as built: the two additional amended note-reader tests, the `<db>.commands/` spool so adapters never write `ontology.db`, and validation errors returned through 202 and the job outcome.

### Deviations
- Each amended accepted test gained one assertion beyond the authorized relaxation, so it fails without the new behavior: a succeeded `registry.publish` job, and a `job_id` in the paste response.
- For confirmation, not blocking: `watch` keeps its name for the existing systemd unit but runs the worker loop; `IngestionPipeline.watch` stays but the CLI no longer calls it; in production the web process needs write permission on `/var/lib/stock-ontology/ontology.db.commands/`.
- No Phase 6 runbook was written. Migration and worker rollout on the production database stay human-owned.

## Audit

Candidate: `8bef4e5 + a1c1b1d5e360d43b8db0ca2a4b3c8584a244ed8bde3a55df3bd8957b46d1aeba @ main checkout`. Digest recomputed with the Build's command before and after the gate, matching both times. The first 5,423 bytes of `tests/test_worker.py` hash to `88cec11a6737c7509e0823ede2a73b61fca4f896`, matching Proof. A scratch copy with only the new test `test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish` and the `data-job-state="failed"` assertion at `tests/test_web.py:2464` removed reproduces the previous audited digest `f53cd039d1628d18545821daf248b9ff490b35d19d05c038f66630778d392472`, so the rerun changed only those two test lines and production code is byte-identical to the previously audited candidate.

Independence: fresh-context: the auditor had not seen Frame, Proof, Build, or the rerun being written; it read the ledger, candidate source and tests, and `work/build/` logs, and ran mutation probes on a scratch copy of `src/` and `tests/` without editing the repo.

Primary-claim verdict: PROVED: evidence: `uv run --offline pytest -q -p no:cacheprovider` passes `tests/test_worker.py::test_agent_journey_through_cli_json_survives_worker_kill` with its protected prefix byte-identical to Proof; RED recorded in `work/proof/modular-worker-red.log`; disabling the resume branch in `Worker._finish_consensus` on the scratch copy made it fail; limit: one worker and one note with a kill inside consensus only; the web comparison covers consensus summary, event name, and citation file only.

Guardrail verdicts:
- Readers open read-only, note actions return a job reference, and the reader shows job state: PROVED: evidence: `tests/test_web.py::test_web_note_actions_return_job_references_and_open_the_db_read_only`, `tests/test_worker.py::test_cli_reads_are_read_only_and_errors_are_typed`, `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database`, and the `_note_action` note-reader tests; setting `read_only=False` in `services/graph.open_graph` failed two web and architecture tests; `tests/test_web.py:2464` asserts `data-job-state="failed"` after a failed correction; limit: the runtime read-only check covers the Process route, relink and relationship routes rely on the static guard, and the new failed-state assertion was not mutation-probed.
- A late consensus attempt cannot publish over newer evidence, and an expired-lease attempt cannot commit: PROVED: evidence: removing `self._check_commit({})` from `_rebuild_company_consensus.publish` (`src/stock_ontology/pipeline.py:733`) on a scratch copy made `tests/test_worker.py::test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish` fail with "the expired attempt published its consensus", and it passes with the line restored, matching `work/build/red-r1.log` and `work/build/green-r1.log`; the test asserts the late summary is never published, the refresh is `(1, 1, "current")` from the reclaiming attempt, exactly one extraction call happened, and the job succeeded on attempt 2; `test_late_consensus_attempt_cannot_publish_over_newer_evidence` and `test_attempt_whose_lease_expired_cannot_commit_extraction` are unchanged and failed under their mutations in the prior audit; limit: single worker with a simulated clock; a lease expiring between the claim check and the commit inside one transaction is not modeled, and `BEGIN IMMEDIATE` serializes that case.
- Stale previous consensus keeps its date and citations on the entity page and JSON: PROVED: evidence: forcing `"stale": False` in `services/graph.py:48` made `tests/test_worker.py::test_stale_consensus_keeps_its_date_and_citations_until_replaced` fail; limit: covers the `failed` refresh state, not `pending`.

Scope and duty verdict: scope HELD; duties HELD: evidence: the rerun added one test in the Frame-named owner after the protected prefix and one assertion in an already-amended, human-approved note-reader test, and the digest reconstruction shows no other change; earlier scope findings hold because the source is identical: changes map to Frame's Include, Phase 4, Phase 5, MCP, and in-app agent tools are untouched, amended accepted tests match the human-authorized Intervention record, and the README constraint entry names guard tests that exist and pass; limit: the git diff still mixes in the earlier accepted note-reader work, so attribution relies on the Build's file list and the prior audit's per-file read.

Test homes: `tests/test_worker.py` (worker, job store, lease, CLI contract, including the new expired-during-synthesis test), `tests/test_architecture.py` (layer and writer guards), `tests/test_db.py` (schema migration on a pre-existing database), `tests/test_registry_governance.py` (publish, apply, `RegistryService`), `tests/test_web.py` (web note actions, job-state assertion, paste), `tests/test_note_intake.py` (import path only).

Full gates: PASS: `uv run --offline pytest -q -p no:cacheprovider`: 509 passed; `uv run --offline ruff check --select F,E9` on `worker.py`, `cli.py`, `web/app.py`, `services/`, `tests/test_worker.py`, and `tests/test_web.py`: all checks passed; limit: offline fake-LLM only; the repo-root `ontology.db` mtime was unchanged, no repo-root spool was created, and no production server or live database was touched.

Residual risks:
- `Worker._run_reembed` checks the claim once and then writes every embedding without extending the lease; the reembed after an apply and `fail_consensus` also write outside a claim check. A reembed longer than the 900 s lease could be reclaimed and run twice at once. The writes are idempotent, but ownership is not strict.
- If a process job's note changes during consensus, the job hits `NoteConflictError` inside `commit_check` and the company refresh is briefly marked `failed` until a later attempt publishes.
- `ValueError` from a provider or parser is treated as terminal `invalid`, not retryable.
- The production web process needs write access to `/var/lib/stock-ontology/ontology.db.commands/`. Migration and worker rollout stay human-owned, and no Phase 6 runbook was written.

Recommendation: ACCEPT
Packet: none for the candidate. ACCEPT does not authorize commit, merge, deploy, the schema migration, or the worker rollout on `/var/lib/stock-ontology/ontology.db`; each needs a separate human decision. Before rollout, confirm the `watch` systemd unit behavior and the spool directory permissions.

## Revisions

### R1: 2026-11-24: a consensus attempt whose lease expired cannot publish
- Verdict: REVISE: removing `self._check_commit({})` from the consensus publish transaction in `src/stock_ontology/pipeline.py` left every `tests/test_worker.py` test green, so the expired-lease half of guardrail 2 had no evidence.
- Changed: `tests/test_worker.py` adds `test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish`, RED without the check and GREEN with it; `tests/test_web.py:2464` asserts `data-job-state="failed"` after a failed correction. No production code changed.
- Re-audit: ACCEPT: all claims PROVED, scope and duties HELD, 509 passed; candidate `8bef4e5 + a1c1b1d5e360d43b8db0ca2a4b3c8584a244ed8bde3a55df3bd8957b46d1aeba @ main checkout`.

## Draft execution plan

This plan proposes implementation and verification steps for review. The phase boundaries let us deliver and check each change separately. The formal Frame will verify the approved scope and record the decisive witness before implementation.

### Background

The [architecture map](../architecture/README.md) describes the current layers and the import test that enforces them. It also lists two known couplings: task logic inside `LLMClient`, and the wide `OntologyDB` shared by every reader. [Pipeline](../architecture/pipeline.md) documents the extraction stages and polling loop. [Governance](../architecture/governance.md) documents registry adoption and repair. The abandoned [consensus retry proposal](consensus-retry.md) records the original stale-consensus case. That case was handled operationally with `ingest --rebuild-consensus`. This proposal replaces that workaround as part of the worker, not as a standalone fix.

### Layers

A new `services` layer sits between storage and LLM below, and the adapters above.

```text
1. shared         config, i18n
2. ontology       models, registry, vocab
3. storage, llm   db/, llm/
4. domain         search, pipeline (extraction), consensus, governance
5. services       NotesService, GraphQueries, ProcessingService, RegistryService
6. adapters       web app, CLI, in-app agent tools, worker entry point, future MCP
```

Adapters import services and never `db`, the notes folder, or `llm` task calls directly. `tests/test_architecture.py` enforces this for each caller once it is migrated.

### Service contracts

Method names are illustrative. Inputs and results are typed objects that carry no SQLite rows and no display formatting. Errors are typed (not found, conflict, invalid input, unavailable), so the CLI can map them to stable exit codes and JSON.

| Service | Owns | Operations |
| --- | --- | --- |
| `NotesService` | Raw text, note identity and content revision, safe access to the notes directory, discovery. Note saving and listing move here from `web/`. | `save(title, text) → NoteRef`, `read(note_id) → NoteSnapshot`, `list() → NoteSummaries`, `search(query) → NotePassages`, `discover_changes() → NoteChanges`. Saving is a file write followed by `request_processing`. It does not touch the DB. |
| `GraphQueries` | Graph query meaning: entity overview, theme companies, search, traversal. Storage only fetches rows. | `get_entity_overview`, `get_theme_overview`, `search_graph`, `traverse`. The web app, CLI `inspect`, and agent tools each map the results for their own display. |
| `ProcessingService` | Job lifecycle, status, retry, and the command queue. Job rows are the single source of processing status. `ingestion_log` becomes the extraction record only. | `request_processing(note_ref) → JobRef`, `submit_correction(command) → JobRef`, `get_status(job_ref or note_id) → ProcessingStatus`, `retry(job_ref) → JobRef`, `run_due_work() → WorkReport` (worker only). |
| `RegistryService` | Reading the applied registry, and preview, publish, and apply for operators. | `get_applied() → RegistrySnapshot` is the only registry read path. The JSON-file fallback in read paths is removed. Publish and apply stay operator CLI commands and are not exposed to agent adapters. |

Extraction and consensus stay domain code that the worker calls: `extract(note_snapshot, registry_snapshot, catalog) → ExtractionResult` and `build_consensus(company_evidence, registry_snapshot) → ConsensusResult`. Consensus code, not storage, decides which companies an evidence change affects.

The LLM layer keeps provider selection, transport, fallback, and embeddings. It gains a generic structured-output call so extraction and consensus can own their prompts and result schemas.

### Processing behavior

#### One writer

Every database write is a job the worker runs: extraction, consensus refresh, note corrections, relinks, and deletions. Registry publish and apply also become jobs, unless Frame decides they run only while the worker is stopped. Corrections run ahead of extraction, so a quick fix isn't stuck behind a three-pass extraction. The web app returns a job reference and polls status for every write.

#### Extraction is versioned by note

1. Saving publishes a complete raw note and queues processing. The worker also discovers new and changed files using the existing reconciliation logic. Duplicate requests for the same revision share a job. An explicit retry reopens a failed job.
2. The worker claims due work, loads the note and applied registry snapshots, and runs staged extraction. A note edit makes the old job obsolete. Moves keep the existing document ID when the match is unambiguous. Deletions use the current reconciliation behavior.
3. The commit checks the note revision, the claim, and the applied registry revision. It replaces records for that note, records extraction success, and writes consensus refresh rows for the companies affected by the old or new evidence, all in one transaction. A changed source or registry makes the result stale and queues processing of the current input. A failed commit leaves previously published graph data intact.

#### Consensus is versioned by company evidence

1. Keep one refresh record per company. Each relevant evidence change advances its target revision. Several changes can merge into one refresh of the latest snapshot. Corrections, deletions, and governance writes follow the same rule.
2. Read a consistent evidence snapshot, including the applied registry revision. Run synthesis and embeddings outside the write transaction. Publish only if the claim, evidence revision, and registry revision still match. Publishing or retiring consensus and recording the completed revision happen in one transaction.
3. A provider or validation failure leaves extraction complete and the company refresh pending or failed. A retry uses the company's current evidence without rerunning extraction. A late result cannot overwrite a newer consensus or clear a newer refresh.
4. The previous consensus stays visible with its original date and citations, marked stale, until its replacement publishes. The UI and JSON output distinguish current, stale, and unavailable consensus.

#### Recovery and status

- Persist job kind, target and revision, priority, state, attempt count, next attempt time, lease expiry, and a short error. Give each claim an identifier. Reclaim expired work after a restart, and check the claim at commit so an expired attempt cannot publish later. This keeps the design correct when more workers are added.
- Keep the existing bounded regeneration of malformed extraction results within an attempt. At the job level, use bounded backoff for transient provider, network, or database failures. A terminal failure stays visible for retry. A newer note or evidence revision starts a fresh attempt budget.
- Show extraction status for the current note revision separately from each affected company's consensus, so an extracted note can show **Consensus pending** or **Consensus refresh failed**. Monitoring should distinguish an idle worker from a backlog that is growing or repeatedly failing.
- The worker runs continuously under systemd, using the existing `watch` entry point and its interval as the default. On startup it recovers pending rows already in SQLite before scanning for new files.

### Agent-facing contract

- Every CLI command an agent uses supports `--json`, returning the service's result or a typed error with a stable exit code. Today only `audit` does.
- Commands that call an LLM return a job reference. Agents poll `status` for the result.
- The in-app `OntologyAgent` gets its tools from the same services, so the internal agent and outside agents share one contract.
- A future MCP server is a thin adapter over the same services. Registry publish and apply are excluded.
- Service inputs leave room for a caller identity, so authentication can be added later without changing operation shapes.

### Execution phases

| Phase | Deliverables | Exit evidence |
| --- | --- | --- |
| **0. Frame** | Settle the remaining open choices. Commit the in-progress note-reader work and record a fresh baseline. Inventory every current DB write path (ingest, corrections, relink, repair, registry apply) so each maps to a job kind. Approve the upgrade path for existing SQLite databases. | Recorded baseline with any failure accounted for. The approved Frame names the decisive witness and the first phase's scope. |
| **1. Services for notes and registry** | Add the `services` layer. Move note saving, listing, reading, and search from `web/` into `NotesService`. Make `RegistryService.get_applied()` the only registry read path. Migrate the web app and CLI callers. | Existing web and CLI tests pass through the services. The architecture test blocks migrated callers from importing `db` or reading the notes folder. |
| **2. Processing service and worker** | Additive migration for job and company refresh tables. `ProcessingService` with job references and status. The worker becomes the only writer. Process, corrections, and relinks return job references, and the reader polls status. Stale consensus marker. Run the worker under systemd. Keep one-shot `ingest` for operators through the same job path. | Headless fake-LLM journey: save, queue, kill the worker, restart, recover, browse. Consensus is retried without re-extracting. A late attempt can't publish over newer evidence. Duplicate requests share a job. Corrections run ahead of queued extraction. Rolled-back writes add no jobs. The web app opens the DB read-only. |
| **3. Agent-facing CLI** | `--json` and typed errors for save, process, status, retry, read, search, and entity overview. In-app agent tools call the services. | Contract tests run the primary-claim journey through CLI JSON. Agent suites keep tool behavior. |
| **4. Graph queries** | Move query meaning out of `OntologyDB` into `GraphQueries`, one use case at a time, starting with entity overview and search. The web app, agent, and CLI `inspect` map the results themselves. | Web and agent suites keep search ordering, citations, source links, and tool behavior. Contract tests run the web app and agent against a substitute with no SQLite. |
| **5. LLM task split** | Add a generic structured-output call. Extraction and consensus own their prompts and schemas. | Fallback, validation, and diagnostics tests are unchanged. The architecture README's coupling note on `LLMClient` is removed. |
| **6. Roll out and verify** | Rehearse the migration on a copy of the production database. Write a worker runbook: start, stop, inspect backlog and terminal errors, retry, and roll back with queued work. Decide whether to queue a consensus refresh on deployment. | In a test environment, systemd restarts a killed worker and the backlog drains while the web app keeps serving notes, graph results, and chat. Live rollout needs separate approval. |

Later phases outside this proposal: authentication for the web app, CLI, and MCP; an MCP server if not shipped here; persistent chat history.

### Verification and acceptance

- **Baseline.** An earlier draft ran `uv run --offline pytest -q tests/test_architecture.py tests/test_pipeline.py tests/test_db.py tests/test_web.py tests/test_agent.py tests/test_registry_governance.py` with 147 passing, on a working tree with uncommitted note-reader changes. Record a fresh baseline against the candidate selected in Phase 0.
- **Decisive witness.** A test with a temporary SQLite database and a fake LLM runs the primary-claim journey using only service calls and CLI JSON. It kills the worker mid-job and confirms recovery without re-extraction. The permanent owner is the worker integration suite.
- **Concurrency guardrail.** Pause a fake synthesis after taking a snapshot. Commit newer evidence and a new refresh request. Release the older attempt and assert that it cannot publish or acknowledge the newer revision. Run the equivalent check for edited note revisions and an expired lease.
- **Single-writer guardrail.** Assert that the web app, CLI read commands, and agent open the database with `PRAGMA query_only = ON`, and that every write path in the Phase 0 inventory runs as a worker job.
- **Compatibility guardrail.** Exercise the registry preview and apply sequence, the note reader's corrections, and a database created before the new tables.
- **Checks by phase.** Use `uv run pytest -q tests/test_pipeline.py tests/test_db.py` for the worker changes. Add the focused web, agent, and CLI suites for later phases, and `tests/test_architecture.py` for dependency enforcement. Run `uv run pytest -v` offline against the stable candidate before audit.
