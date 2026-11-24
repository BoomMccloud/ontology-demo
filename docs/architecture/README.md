# Architecture

The app is twelve modules. Each has its own page, except services and the
worker, which are described below.

| Module | Files | Page |
| --- | --- | --- |
| Ontology | `models.py`, `registry.py`, `vocab.py` | [ontology.md](ontology.md) |
| Storage | `db/schema.py`, `db/storage.py` | [storage.md](storage.md) |
| Data pipeline | `pipeline.py`, `llm/prompts.py` | [pipeline.md](pipeline.md) |
| LLM layer | `llm/` | [llm.md](llm.md) |
| Search | `search.py` | [search.md](search.md) |
| Agent | `agent.py`, `llm/pydantic_ai_model.py` | [agent.md](agent.md) |
| Web app | `web/` | [web.md](web.md) |
| Governance | `audit.py`, `repair.py` | [governance.md](governance.md) |
| Services | `services/` | [Services and worker](#services-and-worker) |
| Worker | `worker.py` | [Services and worker](#services-and-worker) |
| CLI | `cli.py` | [cli.md](cli.md) |
| Shared | `config.py`, `i18n.py`, `locales/` | [shared.md](shared.md) |

## Data flow

```text
web app, CLI ──submit──► <db>.commands/ (spool) ──► worker ──writes──► ontology.db
                                                     │ pipeline, repair
data/**/*.md|.txt ───────────────────────────────────┘
ontology.db ──PRAGMA query_only = ON──► agent, web app, audit, CLI reads
```

## Dependency layers

Each layer may import from layers above it, never below.

```text
1. shared         config, i18n
2. ontology       models, registry, vocab
3. storage, llm   db/, llm/          (independent of each other)
4. search         search.py          (shared by agent and web app)
5. pipeline, agent, governance        (independent of each other)
6. services       services/          (notes, processing, registry, graph queries)
7. worker, web app                    (the worker is the only DB writer)
8. CLI            composition root, imports everything
```

The web app imports services, never storage. Services import storage and
search, never the pipeline or the LLM layer.

## Isolation

Editing a module's internals should stay inside that module. Changing its
interface touches its callers, and that's expected.

`tests/test_architecture.py` enforces this offline:

- Every source file maps to one module above.
- Imports follow the layers. The web app may not import the pipeline, and
  storage may not import governance, for example.
- Only `stock_ontology.db` touches SQLite (`.conn`, `sqlite3`, `sqlite_vec`),
  so a schema change can't silently break another module.
- Only `worker.py` (and storage itself) calls `OntologyDB(...)` without
  `read_only=True`.

The web-to-agent contract (`chat()` and `ChatTurn` only) is enforced by
`tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat` and
`tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract`.

## Services and worker

`services/` is the contract the CLI and web app call. `NotesService` saves,
resolves, and lists notes and derives each note's status from the extraction
log. `ProcessingService` submits jobs as JSON files in the command spool next
to the database (`<db>.commands/`), reports job status, and reopens a failed
job. A note's processing job ID comes from its path and content revision, so
duplicate requests share a job. `RegistryService.get_applied(db)` is the one
registry read for graph writes. `GraphQueries` delegates to the `OntologyDB`
overview methods and adds the consensus status (`current`, `pending`,
`failed`, `unavailable`). Errors are `ServiceError` with a code from
`EXIT_CODES` (`not_found` 3, `conflict` 4, `invalid` 5, `unavailable` 6).

`worker.py` moves spooled submissions into the `jobs` table, claims the most
urgent due job under a lease (corrections, then operator jobs, then note
extraction), and runs it. Every graph commit for a job calls
`IngestionPipeline.commit_check`, which refuses a lost or expired claim and
records the consensus revisions the commit queued. A job that committed its
write and then died resumes at the consensus stage without re-extracting. A
change of the applied registry (`RegistryChangedError`) reopens the connection
and retries without using an attempt. Invalid input, conflicts, and missing
notes fail at once; other failures retry three times per job revision, 60 then
120 seconds apart. `watch` and `worker` run the loop; `worker --once` drains
due work and exits. It also holds the registry rollout preview, which writes a
disposable copy.

- Open `ontology.db` for writing only from `worker.py`. Adapters submit a job
  through `services.ProcessingService` instead, and operator commands run the
  worker in their own process.
  **Why:** the web app wrote through its own ingestion writer inside HTTP
  requests and operator commands opened their own writers, so writes raced and
  a killed request could not resume (proposal `modular-worker`, 2026-11-24).
  **Guarded by:** `tests/test_architecture.py::test_only_worker_job_executors_open_a_writable_database`
  and `tests/test_worker.py::test_operator_commands_write_only_through_claimed_jobs`.

If the test fails on a dependency you actually want, update `ALLOWED` in the
test and the layer list here together.

These couplings remain and the test does not catch them:

1. `LLMClient` has `extract_document` and `synthesize_consensus`, which are
   pipeline tasks, and `llm/` holds the pipeline's prompts and the agent's
   Pydantic AI adapter. So pipeline prompt changes and agent loop changes both
   land in `llm/`. A generic structured-output call would let the pipeline own
   its prompts and schemas.
2. `OntologyDB` is one wide class shared by the pipeline, agent, web app, and
   governance. The graph queries (`get_entity_overview`,
   `find_theme_companies`, `traverse_bfs`) serve both the agent and the web
   app, so tuning one for the UI changes the agent's tool output too.
