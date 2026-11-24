# Stock Ontology agent instructions

See `README.md` for architecture, setup, and CLI usage.

## Commands

- Install dependencies: `uv sync`
- Offline test suite: `uv run pytest -v`
- Focused tests: `uv run pytest tests/test_pipeline.py -v` (or another `tests/test_*.py`)

## Invariants

- Data flows one way: notes under `ONTOLOGY_DATA_DIR` are ingested into
  `ontology.db`. Only the worker's job executors (`src/stock_ontology/worker.py`)
  open it for writing. The web app (Process and note corrections included), CLI
  read commands, the query agent, and `audit` open it read-only
  (`PRAGMA query_only = ON`) and submit writes as jobs through
  `services.ProcessingService`. Operator commands (`ingest`, `reembed`,
  `repair`, `registry-publish`, `registry-apply`) queue their job and run the
  worker in their own process until it finishes.
- Tests run offline with fake LLM clients. Never call a live LLM provider from
  a test.
- Never commit `.env`, `ontology.db`, or other files listed in `.gitignore`.

## Change process: proposal pipeline

This repository opts into the checked-in proposal pipeline under
`.codex/skills/`. Use `proposal-pipeline` for daily changes that need a durable
process. It maintains one ledger in `docs/proposals/<proposal_id>.md` and runs
`proposal-intake` → `proposal-frame` → optional independent `proposal-prove` →
`proposal-build` → independent `proposal-audit`.

No stage merges, pushes, deploys, migrates live data, or performs another
irreversible action without separate human authorization. The pipeline's required
stages are the repository-specific exception to the global delegation budget; do
not add another prove, audit, or review chain unless the human requests it. The
exception still has a limit: after two `REVISE` reruns, the pipeline stops and
waits for the human.

`kiss`, `first-principle`, and `test-strategy` are human-invoked diagnostics for
investigating a suboptimal pipeline outcome. They are not automatic pipeline
stages and do not modify the ledger or candidate unless the human separately
authorizes a follow-up change.
