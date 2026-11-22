---
proposal_id: "exact-entity-merge"
state: FRAMED
witness: independent
candidate: "main @ worktree/proposal-exact-entity-merge"
---

# Proposal: Exact or registry-based entity merging

## Proposal

Status: approved by the human on 2026-11-22: "entity merge should be exact, or
based on ontology registry, we can propose and have humans reject".

### Outcome

Ingestion never merges two entities or themes because their embeddings are
close. A merge happens only on an exact match (existing ID, name, or alias) or
when the official registry says both names are the same company or theme.
Likely duplicates found by `audit` are proposed as pending merge suggestions in
the registry, a human approves or rejects each one, and `repair` applies only
approved merges.

### Motivation

A fresh rebuild of `ontology.db` on 2026-11-22 merged distinct companies:
NVIDIA absorbed AMD, Vertiv absorbed nVent, TSMC absorbed ASML, and Amkor
absorbed ASE. Live probes put AMD at cosine distance 0.114 from NVIDIA and nVent
at 0.106 from Vertiv, inside the 0.15 auto-merge threshold. No threshold
separates competitors from name variants, so similarity cannot decide a merge.

### Constraints

- Exact name, alias, and ID matches keep merging automatically, as do registry
  matches by ticker, name, or alias.
- Merge proposals use the registry `suggestions` workflow; human decisions
  survive later `audit` syncs, and rejected pairs are not proposed again.
- `audit` stays read-only on the DB. `repair` stays deterministic: it applies
  approved suggestions and exact duplicates, nothing else.

### Non-goals

- Splitting entities already merged wrongly in the live DB. The live DB will
  be rebuilt from notes after this lands (human-owned).
- Approving the pending company, theme, or merge suggestions.

### Unresolved choices

- None.

## Frame

Candidate: `main` (`160507a`) + this ledger @ worktree `.claude/worktrees/exact-entity-merge` (branch `proposal/exact-entity-merge`)

### Verified reality
- `uv run pytest -q` at `160507a` in this worktree — 103 passed before the change.
- `src/stock_ontology/pipeline.py:28` `CANONICAL_DISTANCE_THRESHOLD = 0.15` and `_resolve_canonical_node` (`:161`) — when `_find_exact` (`:234`) misses, a probe embedding is matched by `vector_search` and merged under the threshold; `_batch_probe_vectors` (`:247`) exists only to feed that.
- Probe run on `ontology.fresh.db` (scratchpad, 2026-11-22) — AMD→NVIDIA 0.114, nVent→Vertiv 0.106, ASML→TSMC 0.161; the fresh DB's audit lists AMD, nVent, ASML, and ASE as aliases of other companies.
- Setting the threshold to -1 locally fails exactly one test: `tests/test_pipeline.py::test_pipeline_ingest_idempotent_edit_delete_and_resolution` (`:484-495`, "Nvidia Corporation" must merge into NVIDIA). `create_minimal_registry()` lists `Nvidia Corporation` as an alias of NVIDIA, so registry-based resolution satisfies that assertion; only the test's comment ("Vector-distance merge") describes the old mechanism.
- `src/stock_ontology/registry.py:382` `resolve_company(name, ticker=, aliases=)` and `resolve_theme` — resolve against registry entries by ticker, name, or alias; the pipeline never calls them.
- `registry.py:160` `RegistrySuggestions` — `relations`, `companies`, `themes` only; `sync_suggestions` (`:458`) preserves non-pending decisions; `SuggestionStatus` is `pending|approved|aliased|rejected`.
- `src/stock_ontology/audit.py` `run_ontology_audit` — already produces `duplicate_company_candidates` and `near_duplicate_themes` (`NearDuplicatePair`, reasons `vector_similarity`/`shared_ticker`); `cli.py:820` syncs only unmapped relations, companies, and themes.
- `src/stock_ontology/repair.py` — merges exact name/alias duplicates only; it does not read registry suggestions.
- `tests/test_architecture.py` — governance may import only shared, ontology, storage; only `stock_ontology.db` may touch SQL.

### Final primary claim
- During ingestion, an extracted entity or theme reuses an existing node only when its `temp_id` is that node's ID, its name or an alias exactly matches the node's name or an alias, or the registry resolves both to the same official company or theme; a new entity whose embedding is closer to an existing node than the old threshold (for example AMD next to NVIDIA) is stored as its own node.

### Routing
- Witness: independent
- Why: it changes which stored rows ingestion and repair merge in `ontology.db`, and adds a registry suggestion type that `repair` acts on.
- Human-owned irreversible action: rebuilding or repairing the real `ontology.db`, approving merge suggestions in `ontology_registry.json`, and merging the branch into `main`.

### Decisive witness
- Layer: offline pytest integration over temporary DBs with fake LLM embeddings that place a distinct entity within the old threshold of an existing one.
- Permanent owner: `tests/test_pipeline.py` (ingestion), `tests/test_registry_audit.py` (merge suggestions), `tests/test_repair.py` (applying decisions).
- Witness: a near-identical embedding no longer merges AMD into NVIDIA; a registry alias still merges a name variant; audit sync queues a near-duplicate pair as a pending merge suggestion and keeps a human's rejection; repair merges an approved pair and leaves pending and rejected pairs alone.

### Guardrail claims
- `audit --sync` queues each near-duplicate company or theme pair as a pending merge suggestion, preserves approved and rejected decisions on later syncs, and does not re-queue a rejected pair.
- `repair` merges the nodes of every approved merge suggestion that still exist, and never merges a pending or rejected pair.
- A name variant listed in the registry (for example `Nvidia Corporation` for NVIDIA) still resolves to the existing node during ingestion.

### Supporting obligations
- Remove `CANONICAL_DISTANCE_THRESHOLD`, the probe vector path, and `_batch_probe_vectors`; embed new canonical nodes in one batched call per note.
- Add registry resolution to `_find_exact`: `resolve_company` for entities whose `entity_type` is company (passing ticker and aliases), `resolve_theme` for themes; map the matched spec to an existing node by its name or aliases.
- Add `MergeSuggestion` (`id`, `node_type`, `node_a_id/name`, `node_b_id/name`, `reason`, `distance`, `status`, `reviewer_note`, timestamps) and `RegistrySuggestions.merges`; `sync_suggestions` accepts merge candidates (keyword, default empty) keyed by the unordered node-ID pair; pending pairs no longer reported are dropped as resolved, decided ones kept.
- `cli audit` passes `duplicate_company_candidates` and `near_duplicate_themes`; the summary counts pending merges.
- `repair_ontology` applies approved merge suggestions through existing storage calls (`merge_node_into`, `upsert_node`), reporting them in `RepairReport` (`approved_merges_applied`) and in `merged_survivor_ids`.
- Update the stale comment in `test_pipeline_ingest_idempotent_edit_delete_and_resolution`, `docs/architecture/pipeline.md` and `governance.md`, and `README.md` (a constraint entry for exact-or-registry merging).

### Allowed scope
- Reuse: `_find_exact`, `OntologyRegistry.resolve_company/resolve_theme`, `sync_suggestions`, `NearDuplicatePair`, `_merge_cluster`/`merge_node_into`, the CLI `audit` and `repair` commands.
- Cheaper alternative: lower the threshold. Rejected because measured competitor distances (0.106, 0.114) overlap name-variant distances, so no threshold meets the primary claim; dropping similarity without merge suggestions was rejected because the human asked to propose merges for review.
- Include: `src/stock_ontology/pipeline.py`, `src/stock_ontology/registry.py`, `src/stock_ontology/repair.py`, `src/stock_ontology/cli.py`, `tests/test_pipeline.py`, `tests/test_registry_audit.py`, `tests/test_repair.py`, `tests/test_db.py`, `docs/architecture/pipeline.md`, `docs/architecture/governance.md`, `README.md`.
- Exclude/protect: `ontology.db`, `ontology_registry.json`, `data/`; `audit.py` detection logic and read-only behavior; `db/` storage SQL unless a new query is strictly needed; web and i18n files.

### Invariants changed
- `tests/test_pipeline.py:484` — today: comment says the "Nvidia Corporation" merge is a vector-distance merge; after: the same assertion holds through the registry alias, and the comment says so. No assertion changes.

### Decisions required
- None.

## Proof

## Build

## Audit

## Revisions
