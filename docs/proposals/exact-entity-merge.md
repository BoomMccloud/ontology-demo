---
proposal_id: "exact-entity-merge"
state: ACCEPTED
witness: independent
candidate: "8365c00 @ worktree/proposal-exact-entity-merge"
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

Candidate: `proposal/exact-entity-merge` @ `3a73dc035eb618a7511b5dcece14527fc4dc1a90` (worktree `.claude/worktrees/exact-entity-merge`; production source unchanged from `a09be2b`, which is `160507a` plus the ledger)

**Protected witness**
- Ingestion never merges a distinct entity by embedding distance. Witness: `tests/test_pipeline.py` / `test_pipeline_does_not_merge_distinct_company_by_embedding_distance`
  - Defect and boundary: `_resolve_canonical_node` falls back to `vector_search` and merges under `CANONICAL_DISTANCE_THRESHOLD = 0.15`. The boundary is extracted note → `IngestionPipeline.run()` → stored `ontology.db` nodes.
  - Assertion: the fake LLM `_ExactMergeFakeLLM` embeds AMD at cosine distance ~0.042 from NVIDIA. After `nvda.md` and then `amd.md` are ingested in separate runs, exactly one node is named `AMD`, its ID differs from NVIDIA's, and `AMD` is not among NVIDIA's aliases. This proves the primary claim. Limit: it covers a company entity only. A theme near-miss is not witnessed separately, and the test does not prove the probe path was removed.
- A name listed in the registry still resolves to the existing node. Witness: `tests/test_pipeline.py` / `test_pipeline_merges_registry_alias_without_embedding_similarity`
  - Defect and boundary: `_find_exact` never calls `OntologyRegistry.resolve_company/resolve_theme`. Today `Nvidia Corporation` merges only because its embedding sits near NVIDIA. The boundary is ingestion → stored nodes, using the default `create_minimal_registry()`.
  - Assertion: `Nvidia Corporation` is embedded orthogonal to NVIDIA. After ingestion no node is named `Nvidia Corporation`, and NVIDIA's aliases contain it. This proves registry-alias resolution without any help from similarity. Limit: it covers a company alias with no ticker. It does not cover ticker-only resolution or theme registry resolution.
- `audit --sync` queues each near-duplicate company or theme pair as a pending merge suggestion, keeps human decisions, and does not re-queue a rejected pair. Witness: `tests/test_registry_audit.py` / `test_cli_audit_queues_merge_suggestions_and_keeps_human_decisions`
  - Defect and boundary: `RegistrySuggestions` has no `merges`, and `cli audit` syncs only relations, companies, and themes. The boundary is the read-only DB → CLI `audit` → registry JSON file.
  - Assertion: the first `audit` writes `suggestions.merges` with the theme pair `{thm_div, thm_hedge}` (vector similarity) and the company pair `{ent_nvda, ent_nvda_dup}` (shared ticker), both `pending`. The test then edits the registry file as a human would, marking the theme pair `rejected` with a note and the company pair `approved`. A second `audit` keeps exactly one entry per pair, with the same statuses and reviewer note, and DB `get_stats()` is unchanged. Proves the audit guardrail. Limit: it does not check the summary count of pending merges, or that pending pairs no longer reported are dropped.
- `repair` merges every approved pair that still exists and never merges a pending or rejected pair. Witness: `tests/test_repair.py` / `test_repair_applies_only_approved_merge_suggestions`
  - Defect and boundary: `repair_ontology` merges exact name and alias duplicates only and never reads registry suggestions. The boundary is registry `suggestions.merges` → `repair_ontology` → stored nodes and edges.
  - Assertion: with a registry built by `OntologyRegistry.model_validate` holding three merge suggestions with the Frame's `MergeSuggestion` fields, the approved pair (Omega) leaves exactly one node; the loser's vector is gone; the survivor carries both names and `OGS`, and both event edges point to it; the survivor is in `merged_survivor_ids` and `approved_merges_applied == 1`. Pending (Sigma) and rejected (Tau) nodes all still exist. A second run leaves the DB snapshot unchanged. Proves the repair guardrail. Limit: company pairs only, not theme pairs; library call, not CLI `repair --json` output.
- Protected paths: `tests/test_pipeline.py`, `tests/test_registry_audit.py`, `tests/test_repair.py`. The witnesses are in the sections labeled "Proof witnesses: exact-entity-merge". Build may change only the stale comment the Frame names at `tests/test_pipeline.py:484` outside those sections.
- Protected revision: `3a73dc035eb618a7511b5dcece14527fc4dc1a90` (commit "Proof witnesses: exact-entity-merge").

**Red evidence**
- `uv run pytest -v tests/test_pipeline.py::test_pipeline_does_not_merge_distinct_company_by_embedding_distance` → `AssertionError: AMD was merged into an existing node because its embedding is near NVIDIA` (`0 == 1` AMD nodes); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove3/red_pipeline_amd.log`.
- `uv run pytest -v tests/test_pipeline.py::test_pipeline_merges_registry_alias_without_embedding_similarity` → `AssertionError: 'Nvidia Corporation' is a registry alias of NVIDIA but was stored as its own node`; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove3/red_pipeline_registry_alias.log`.
- `uv run pytest -v tests/test_registry_audit.py::test_cli_audit_queues_merge_suggestions_and_keeps_human_decisions` → `AssertionError: audit --sync-suggestions wrote no suggestions.merges list to the registry`; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove3/red_audit_merge_suggestions.log`.
- `uv run pytest -v tests/test_repair.py::test_repair_applies_only_approved_merge_suggestions` → `AssertionError: repair did not merge the nodes of an approved merge suggestion` (`2 == 1`); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove3/red_repair_approved_merges.log`.
- `uv run pytest -q` → 4 failed (the four witnesses), 103 passed; no other regression; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/prove3/full_suite.log`. `ruff check` on the three files passes.
- Each claim was observed RED above; none counts as proven until its witness turns GREEN on the Build candidate with the protected sections unchanged.

**Supporting test plan**
- `sync_suggestions` merge keyword: a pending pair no longer reported is dropped as resolved, a decided pair is kept, and the summary counts pending merges → Build: `tests/test_registry_audit.py`; catches stale pending merges and a wrong pending count.
- Registry resolution by ticker during ingestion, plus a theme resolved through a `ThemeSpec` alias → Build: `tests/test_pipeline.py`; catches `_find_exact` handling only company names and aliases, or calling `resolve_company` for non-company entities.
- Batched embedding of new canonical nodes: one `embed_texts` call per note → Build: `tests/test_pipeline.py`; catches a regression to one call per node after `_batch_probe_vectors` is removed.

## Build

Candidate: `8365c00 @ worktree/proposal-exact-entity-merge` (branch `proposal/exact-entity-merge`). Later commits touch only this ledger.

### Files changed

- `src/stock_ontology/pipeline.py` — removed `CANONICAL_DISTANCE_THRESHOLD`, the probe-vector path, `_batch_probe_vectors`, and `_probe_text`; `_find_exact` falls back to new `_find_by_registry` (`resolve_company` with ticker and aliases for company entities only, `resolve_theme` for themes, mapped to the stored node carrying any official label); `_resolve_canonical_node` no longer embeds; new and changed canonical nodes are embedded in one `embed_texts` call per note via `replace_node_embeddings`.
- `src/stock_ontology/registry.py` — `MergeSuggestion` and `RegistrySuggestions.merges`; `sync_suggestions(..., merge_candidates=...)` keyed by the unordered node-ID pair, keeps decided pairs, drops pending pairs no longer reported; `SuggestionSyncSummary.pending_merges`.
- `src/stock_ontology/repair.py` — `_apply_approved_merges` merges the nodes of `approved` merge suggestions through `_merge_cluster` (existing `merge_node_into`/`upsert_node`), skipping missing or mixed-type pairs; `RepairReport.approved_merges_applied`.
- `src/stock_ontology/cli.py` — `audit` passes `duplicate_company_candidates` and `near_duplicate_themes` as merge candidates; the sync line shows pending merges.
- `tests/test_pipeline.py` — only the stale comment at the "Nvidia Corporation" step (Frame's `Invariants changed`).
- `tests/test_db.py` — supporting tests: merge-suggestion sync drops stale pending pairs and counts pending merges; registry resolves a company by ticker and a theme by alias, and never resolves a person through the company registry. The existing `test_probe_embeddings_are_batched_per_note` still passes (one embed call per note).
- `docs/architecture/pipeline.md`, `docs/architecture/governance.md` — resolution and merge-suggestion workflow.
- `README.md` — merge-suggestion usage note; Ingestion Constraints entry (exact or registry merging only), **Why** naming the 2026-11-22 rebuild, **Guarded by** the AMD witness.

### Unit evidence

- `uv run pytest -q tests/test_db.py` — GREEN: 22 passed; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/unit_db.log`. The two new supporting tests were written after the implementation, so no RED was observed for them.

### Green evidence

- Decisive witness: `uv run pytest -q tests/test_pipeline.py -k "does_not_merge_distinct or registry_alias_without"` — pass (2 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/witness_pipeline.log`.
- Decisive witness: `uv run pytest -q tests/test_registry_audit.py -k queues_merge` — pass; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/witness_audit.log`.
- Decisive witness: `uv run pytest -q tests/test_repair.py -k approved_merge` — pass; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/witness_repair.log`.
- Gate: `uv run pytest -q` — pass (109 passed); log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/full_suite.log`.
- Gate: `uv run ruff check src/stock_ontology/pipeline.py src/stock_ontology/registry.py src/stock_ontology/repair.py src/stock_ontology/cli.py tests/test_db.py` — pass; log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/build3/ruff.log`.
- Protected witnesses: `git diff 3a73dc0 -- tests/test_registry_audit.py tests/test_repair.py` is empty; `tests/test_pipeline.py` differs only by the one comment line Proof allowed.

### Intervention record

- None. No intervention ledger exists; the outcome is measured by the rebuild audit after merge.

### Deviations

- Test home: Proof's supporting plan named `tests/test_registry_audit.py` and `tests/test_pipeline.py` for the sync and registry-resolution unit tests. They are in `tests/test_db.py` because Proof protects those files whole; no behavior or scope change.

## Audit

Candidate: `8365c00` on branch `proposal/exact-entity-merge`, in worktree `.claude/worktrees/exact-entity-merge`. The branch tip `c62d43b` differs from `8365c00` only in `docs/proposals/exact-entity-merge.md` (`git diff --quiet 8365c00 HEAD -- src tests README.md docs/architecture`).

Independence: fresh-context. Before this audit the auditor had seen only the ledger, the proposal-audit skill, the candidate and Proof diffs (`3a73dc0..8365c00`, `a09be2b..3a73dc0`), and the repository source. It took no part in Frame, Proof, or Build.

Primary-claim verdict: PROVED
- Evidence: `tests/test_pipeline.py::test_pipeline_does_not_merge_distinct_company_by_embedding_distance` passes on the candidate (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/witnesses.log`); Proof recorded it RED at `3a73dc0`. `git diff 3a73dc0 8365c00 -- tests/` shows only the one-line comment at `tests/test_pipeline.py:484` that Frame lists under `Invariants changed`. `pipeline.py` no longer calls `vector_search`; `CANONICAL_DISTANCE_THRESHOLD`, `_probe_text`, `_batch_probe_vectors`, and `probe_vec` no longer appear in src, tests, docs, or README. `_find_exact` falls back only to the registry's exact ticker, name, and alias matching. A temp-DB probe stored a theme with an identical embedding as its own node (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/probe_theme.py`, `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/probe_theme.log`: "PROBE OK").
- Limit: the decisive witness covers a company only; theme coverage rests on the probe and code reading.

Guardrail verdicts:
- `audit --sync` queues near-duplicate pairs as pending, keeps decisions, does not re-queue a rejected pair: PROVED. Evidence: `tests/test_registry_audit.py::test_cli_audit_queues_merge_suggestions_and_keeps_human_decisions` passes; the file is byte-identical to `3a73dc0`; Proof recorded it RED. The CLI passes `duplicate_company_candidates` and `near_duplicate_themes` to `sync_suggestions(merge_candidates=...)`. Limit: the summary count and stale-pending drop rest on `tests/test_db.py::test_sync_merge_suggestions_drops_stale_pending_and_counts`, written after the implementation and never RED.
- `repair` merges approved pairs and never pending or rejected ones: PROVED. Evidence: `tests/test_repair.py::test_repair_applies_only_approved_merge_suggestions` passes; file identical to `3a73dc0`; Proof recorded it RED. `_apply_approved_merges` skips non-approved, missing, and mixed-type pairs; CLI `repair` emits `approved_merges_applied`. Limit: company pairs only, library call; CLI `repair --json` not run end to end.
- A registry name variant still resolves to the existing node: PROVED. Evidence: `tests/test_pipeline.py::test_pipeline_merges_registry_alias_without_embedding_similarity` passes, unchanged since `3a73dc0`; `test_pipeline_ingest_idempotent_edit_delete_and_resolution` passes with assertions unchanged. Limit: ticker-only and theme-alias resolution rest on `tests/test_db.py::test_registry_resolves_company_by_ticker_and_theme_by_alias`, never RED, which asserts nothing about the person entity it adds.

Scope and duty verdict: scope HELD; duties HELD.
- Every changed file except the ledger is on Frame's Include list; nothing on the Exclude list was touched (`audit.py`, `db/`, web, i18n, `ontology.db`, the registry JSON, `data/`). The work reuses what Frame named; no unclaimed feature work. The embedding batch runs inside the per-note `db.transaction()`; `replace_node_embeddings` nests, so the per-note transaction invariant holds. `README.md` has a new Ingestion Constraints entry with **Why** and **Guarded by** naming an existing passing test. Frame's only listed invariant change was made with no assertion changed.
- Limit: Build disclosed the test-home deviation; `tests/test_db.py` is in allowed scope and already holds pipeline wiring tests, so scope is held.

Test homes:
- `tests/test_db.py` adds `test_sync_merge_suggestions_drops_stale_pending_and_counts` and `test_registry_resolves_company_by_ticker_and_theme_by_alias`; it is their home because Proof protects `tests/test_pipeline.py` and `tests/test_registry_audit.py` whole.
- `tests/test_pipeline.py` changed by one comment line only, as Frame allows.

Full gates: PASS
- `uv run pytest -q`: 109 passed (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/full_suite.log`). The four decisive witnesses plus the amended resolution test: 5 passed (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/witnesses.log`). `uv run ruff check` on all changed files: pass (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/ruff_changed.log`).
- Limit: repo-wide `uv run ruff check src tests` reports 39 pre-existing errors in untouched files (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/21c6d27a-a6c6-400c-b4bd-4ebdc671ca5f/scratchpad/audit3/ruff.log`).

Residual risks:
- No supporting test was observed RED (ticker resolution, theme-alias resolution, stale-pending drop, pending-merge count).
- The person-entity case in the registry-resolution test has no assertion; company-only lookup rests on code reading.
- A theme near-miss is proved by an audit-time probe, not a permanent witness.
- CLI `repair` was not run end to end against a temp registry.
- The live `ontology.db` still holds the wrong merges; splitting them is a non-goal and depends on the human-owned rebuild.

Recommendation: ACCEPT

Packet: none required. Merging the branch, rebuilding the real `ontology.db`, and approving merge suggestions in `ontology_registry.json` stay with the human.

## Revisions
