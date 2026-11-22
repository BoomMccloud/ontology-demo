---
proposal_id: "official-edge-facets"
state: ACCEPTED
witness: independent
candidate: "11825e6 + uncommitted working tree @ .claude/worktrees/official-edge-facets (branch proposal/official-edge-facets)"
---

# Proposal: Official edge facets

## Proposal

### Intent

Edges and entities should have some official facets that are part of the
registry. Today we don't distinguish between connections that are "hard" and
"soft", and facets are free-form. Examples named so far: "extracted" vs
"synthesized", and "strong" or "weak", "etc.".

### Tentative primary claim

Edges and entities carry official facets that are part of the registry.

### Why now

A soft connection made it into a hard connection on the theme page
(`/theme/thm_enterprise_ai_monetizati_a323a6`): Microsoft's consensus view,
linked to the theme only because the LLM listed the theme as evidence,
appeared under Research Views and as the path linking Microsoft to the theme.

### Known constraints

- The official facets are part of the registry.
- The registry is the official ontology. Code reflects the registry.

### Non-goals

None stated.

### Open choices

- Which official facets and values, for edges and for entities. Named so far:
  extracted vs synthesized, and strong vs weak, "etc.".
- How this relates to `canonical-vocabulary`, whose approved constraint keeps
  the closed vocabularies in code (`src/stock_ontology/vocab.py`) rather than
  in `ontology_registry.json`. This Proposal overrides that constraint.
- What happens to a facet that isn't official: rejected, dropped, kept but
  flagged.
- What readers (theme pages, company pages, the agent, audit) do with soft
  connections: hide them, label them, or show them only where asked.
- What happens to the ad hoc facets already stored, such as the edge
  `confidence` facet.
- Whether the narrow fix already in the working tree, which hides consensus
  views on theme pages, stays, gets replaced, or ships on its own first.
- Sequence: whether this waits for `canonical-vocabulary` (BUILT, not yet
  audited, with an open Build deviation, in the same working tree) to be
  audited and committed first, or builds on top of it.

## Frame

Candidate: `11825e6 @ .claude/worktrees/official-edge-facets (branch proposal/official-edge-facets)`, clean tree plus this ledger. `11825e6` merges main into `home-page-tables` and contains the ACCEPTED `canonical-vocabulary` (`02aa13c`) and the narrow consensus-on-theme-page fix.

### Verified reality
- `uv run pytest -q` before this change — proves `226 passed`; limit: none.
- `ontology_registry.json` top-level keys `version, relations (11), companies (5), themes (5), facet_aliases (1), suggestions (4)` — proves the registry already holds official schema (relation names, aliases, domain and range) next to data, and has no facet vocabulary section; limit: says nothing about load order.
- `src/stock_ontology/vocab.py:1-27` and `docs/architecture/ontology.md:13-14` — prove the closed vocabularies live in code as `Literal` types and that "`ontology_registry.json` ... does not hold these vocabularies" is a documented rule; limit: none.
- `vocab.py:217` `EDGE_FACET_VOCABS = {"sentiment": SENTIMENT}` and `vocab.py:297` `canonicalize_edge_facets` — prove `sentiment` is the only official edge facet today, and every other edge facet key passes through untouched; limit: none.
- `registry.py:887` `load_registry`, `cli.py:82,89,803,859`, `web/app.py:141`, and `registry.py:714` `create_minimal_registry` (used by `pipeline.py:107` and tests when no registry is passed) — prove the registry is loaded per run from a configurable path, while `models.py` builds extraction schemas from `vocab.py` at import; limit: does not show whether runtime-built schemas would work with the LLM router.
- Edge writes: `pipeline.py:479` (extraction, `source_doc_id=doc_id`) and the `link` helper in `db/storage.py:386` `upsert_consensus_view`, which writes `ABOUT` tagged `consensus_link`, `SUPPORTS`/`CONTRADICTS` tagged `consensus_evidence`, and `SUPERSEDES` with empty facets, all with no source — prove that only two code paths create edges, so `basis` can be set by code with no LLM judgment, and that the `consensus_*` tags alone do not mark every synthesized edge; limit: `repair` writes through `update_edge` and was not traced line by line.
- Live DB edge facet census — `consensus_evidence` on 124, `consensus_link` on 22, `sentiment` on 57, `role` on 9, `confidence` on 7 (all `high`), plus `product_type`, `area`, `transaction_value`. 146 of 504 edges have no source, and all of those are consensus edges; limit: one local DB.
- `db/storage.py:1139` (`include_consensus` defaults to `False` in entity signal reads) and `audit.py:650` — prove the entity page, the agent's signal tool, and the audit already exclude consensus by node type; the theme page and `find_theme_companies` were the gap, now patched at `web/viewmodels.py:742` and `db/storage.py:1405`; limit: not every `get_incident_edges` caller was audited.

### Final primary claim
- After ingest or `repair`, every stored edge carries `basis`, `extracted` for edges written from a note and `synthesized` for edges written by consensus synthesis, and every node or edge facet whose key is official is stored at ingest as a member of that key's vocabulary in `ontology_registry.json` (`repair` keeps `canonical-vocabulary`'s rule for unknown legacy values). The official facet vocabularies in `ontology_registry.json` and in code are identical, and loading a registry whose vocabularies differ from code fails with an error naming the difference. The theme page and `find_theme_companies` skip `synthesized` edges.

### Routing
- Witness: `independent`
- Why: it changes what ingestion writes to stored rows, the registry file's schema, and `repair` over existing data, across the ontology, pipeline and storage layers.
- Human-owned irreversible action: running `repair` against the real `ontology.db` to backfill `basis` on the 504 existing edges, and committing the registry schema change.

### Decisive witness
- Layer: unit and integration tests over the public boundaries: `load_registry`/`OntologyRegistry`, `IngestionPipeline.run` with fake LLM clients, `repair_ontology`, and `build_theme_context`/`find_theme_companies`.
- Permanent owner: `tests/test_vocab.py` (registry and code parity), `tests/test_registry_audit.py` (registry load and `audit --sync` round trip), `tests/test_pipeline.py` (`basis` at ingest), `tests/test_repair.py` (`basis` backfill), `tests/test_web.py` (theme page).
- Witness: (1) the shipped `ontology_registry.json` and `create_minimal_registry()` declare the same facet vocabularies as `vocab.py`, member for member, with the same aliases and fallbacks; (2) loading a registry with a missing or extra member raises; (3) after ingest of a fake note, every extracted edge has `basis: extracted` and every consensus edge has `basis: synthesized`, including when the LLM output supplies its own `basis`; (4) `repair` on a DB with edges lacking `basis` sets `synthesized` on every edge touching a consensus view, including `SUPERSEDES`, and `extracted` on the rest, and a second run changes nothing; (5) a theme linked to a consensus view only by a `synthesized` edge shows no consensus view and no company path through it.

### Guardrail claims
- `ontology_registry.json` written by `audit --sync` keeps the facet vocabulary section byte-for-byte unchanged.
- Consensus views still show on company pages with their pillars, and non-official edge facets (`rationale`, `role`, `confidence`, `product_type`) are still stored and read as before.

### Supporting obligations
- Add a facet vocabulary section to `OntologyRegistry`, `ontology_registry.json` and `create_minimal_registry`: per key, the members with definitions, aliases and fallback, split into node and edge groups. Validate on load that every alias and fallback is a member and that the section equals `vocab.py`.
- Add an `EDGE_BASIS` vocabulary (`extracted | synthesized`, no fallback) to `vocab.py` and `EDGE_FACET_VOCABS`.
- Set `basis` in `pipeline.py` at the extraction edge write, overriding any LLM-supplied value, and in the `upsert_consensus_view` `link` helper, so all four consensus relations get it.
- `repair` backfills a missing `basis`: `synthesized` when either endpoint is a `consensus` view, else `extracted`. It adds a counter to `total_changes`.
- `audit` reports non-official edge facet keys as counts by key, without failing.
- Replace the node-type skips at `web/viewmodels.py:742` and `db/storage.py:1405` with a `basis == "synthesized"` edge skip. An edge without `basis` counts as `extracted`.

### Allowed scope
- Reuse: `vocab.Vocabulary` (members, definitions, aliases, fallback, coerce), `EDGE_FACET_VOCABS`/`canonicalize_edge_facets`, `OntologyRegistry` and its existing `facet_aliases` field, `repair_ontology`, and `audit` out-of-vocabulary reporting.
- Cheaper alternative: add `basis` and `strength` to `EDGE_FACET_VOCABS` in code only. Rejected because the Proposal requires the registry to be the official ontology.
- Include: `vocab.py`, `registry.py`, `ontology_registry.json`, `pipeline.py` (edge write), `db/storage.py` (`upsert_consensus_view`, `find_theme_companies`), `repair.py`, `audit.py` (non-official key report), `web/viewmodels.py` (`build_theme_context`), and the docs listed under Invariants changed.
- Exclude/protect: a `strength` facet (held by the human, decision 3), runtime-built schemas (decision 2), relation vocabulary handling (already registry-owned), `/search` options (`search-ontology`), sentiment precedence in `resolve_item_sentiment`, and the `canonical-vocabulary` witness `tests/test_canonical_vocabulary.py`. Don't run `repair` against the real `ontology.db`.

### Invariants changed
- `docs/architecture/ontology.md:13-14` — today: the registry is the data registry, and vocabularies live in `vocab.py`; after: the registry is the official ontology, including facet vocabularies, and code reflects it.
- `src/stock_ontology/vocab.py:4-6` module docstring — today: "`ontology_registry.json` ... does not hold these vocabularies"; after: it does.
- `README.md:31` — today: the registry holds relations, companies, themes and facet aliases; after: it also holds the official facet vocabularies.
- `canonical-vocabulary` Proposal constraint "the closed enum vocabularies live in code" — overridden by this Proposal's approved constraint. That ledger is not edited.

### Decisions required
- None. The human decided on 2026-11-22:
  - 1. Sequence: finish `canonical-vocabulary` first (correct its disputed Proof assertion, Audit, commit), and build this on the accepted result.
  - 2. Registry declares every official facet vocabulary; code keeps typed copies; a load-time check and test fail if they differ.
  - 3. Edges: `basis` (`extracted | synthesized`, set by code only) and `sentiment` as today. Hold off on `strength`. Nodes: the ten node vocabularies `canonical-vocabulary` built, across all node types.
  - 4. Non-official facets stay open and free-form, reported by `audit`, never filtered on. `confidence` stays as is.
  - 5. The theme page and `find_theme_companies` skip `synthesized` edges, replacing the node-type patch; the company consensus panel keeps them; no other reader changes.

## Proof

Candidate: `11825e6 @ .claude/worktrees/official-edge-facets (branch proposal/official-edge-facets)`, with this ledger untracked and the witness edits below uncommitted in `tests/`. No production code changed.

**Protected witness**
- Registry and code parity, claim (1): `tests/test_vocab.py` / `test_registry_and_code_declare_the_same_official_facet_vocabularies`
  - Defect and boundary: the registry has no facet vocabulary section, and `basis` is not an official edge vocabulary. The boundary is the `ontology_registry.json` / `create_minimal_registry()` schema against `vocab.py`.
  - Assertion: for every vocabulary in `vocab.NODE_FACET_VOCABS` (per node type) and `vocab.EDGE_FACET_VOCABS`, the shipped `ontology_registry.json` and `create_minimal_registry().model_dump(mode="json")` each contain a container listing exactly its members, plus every definition string, every alias pair and the fallback. Both load, and the minimal registry survives save/load unchanged. Code has `EDGE_FACET_VOCABS["basis"]` with members `("extracted", "synthesized")`, no fallback, and `sentiment` is still `SENTIMENT`.
  - Proves: the registry declares the same official vocabularies as code, member for member, including `basis`.
  - Limit: the match is shape-agnostic. Members can be dict keys, strings, or dicts keyed by `name/value/member/id/key`. Alias and fallback pairs are matched anywhere in the tree, not tied to their own vocabulary. It doesn't fix the section's key name or layout, and it doesn't reject extra registry-only vocabularies. Witness (2) covers that through the load check.
- Load-time check, claim (2): `tests/test_registry_audit.py` / `test_load_registry_rejects_facet_vocabulary_that_differs_from_code[node-missing-member|node-extra-member|edge-missing-member|edge-extra-member]`
  - Defect and boundary: `load_registry` doesn't compare the registry vocabularies with code. The boundary is the registry file to `load_registry`.
  - Assertion: the shipped registry is mutated in its vocabulary section. The cases drop `region` from `entity_type`, add `spaceship`, drop `synthesized` from `basis`, and add `inferred`. In each case `load_registry` raises `ValueError` (pydantic `ValidationError` qualifies), and the message names the differing member.
  - Proves: a registry whose vocabularies differ from code fails with an error naming the difference.
  - Limit: it only covers member drift on two vocabularies. Alias, fallback and definition drift aren't mutated.
- `audit --sync` guardrail: `tests/test_registry_audit.py` / `test_cli_audit_sync_keeps_facet_vocabulary_section_unchanged`
  - Defect and boundary: sync rewrites the whole registry through `save_registry`. The boundary is the CLI `audit` writing the registry file.
  - Assertion: on a copy of the shipped registry, after `audit --db ... --registry ...` exits 0 and changes `suggestions`, every top-level key holding the vocabulary section serializes identically (`json.dumps(indent=2)`, key order included) before and after.
  - Proves: sync keeps the facet vocabulary section unchanged.
  - Limit: it compares the section's JSON value, not the raw file bytes, because `save_registry` reformats the whole file.
- `basis` at ingest, claim (3): `tests/test_pipeline.py` / `test_pipeline_sets_edge_basis_by_code_not_by_llm`
  - Defect and boundary: `pipeline.py` edge writes and `upsert_consensus_view` `link` store no `basis`, and pass an LLM-supplied `basis` through raw. The boundary is `IngestionPipeline.run` with a fake LLM to stored `edges` rows.
  - Assertion: one note is ingested, then edited so a new consensus supersedes the old one. The LLM supplies `basis: synthesized` / `Synthesized` on two extracted edges. Every stored edge touching a `consensus` view (at least `ABOUT`, `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES` are present) has `basis == "synthesized"`, and every other edge has `"extracted"`. The guardrail part checks that `role`, `confidence` and `product_type` are still stored on the extracted edge.
  - Proves: code sets `basis` at both write paths and overrides the LLM.
  - Limit: one fake note, the minimal registry, and the consensus path via the base `FakePipelineLLM.synthesize_consensus`.
- `basis` backfill by `repair`, claim (4): `tests/test_repair.py` / `test_repair_backfills_edge_basis_and_is_idempotent`
  - Defect and boundary: `repair_ontology` doesn't backfill `basis`. The boundary is `repair_ontology` over a temp DB.
  - Assertion: the temp DB is seeded with extracted edges, a non-consensus view, and two consensus views via `upsert_consensus_view` (`ABOUT`, `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES`). Then `basis` is stripped from every edge with SQL. After `repair`, every edge touching a consensus view has `synthesized` and every other edge has `extracted`. Free-form `role`/`confidence` survive. A second run reports `total_changes == 0` and leaves the snapshot unchanged.
  - Proves: the backfill rule, and that repair is idempotent.
  - Limit: temp DB only, and it doesn't assert the new counter's name. The real `ontology.db` was not touched.
- Theme page skip, claim (5): `tests/test_web.py` / `test_theme_readers_skip_synthesized_edges`
  - Defect and boundary: `build_theme_context` skips by node type (`view_type == consensus`), not by edge `basis`. The boundary is the DB to the theme view model.
  - Assertion: a guardrail part checks that `build_entity_context("ent_msft")["consensus"].pillars == ("Copilot seat growth",)` (green before the change). The theme lists views linked by `basis: extracted` and by an edge with no `basis`. It doesn't list the consensus view, or a non-consensus view linked only by a `basis: synthesized` edge. Oracle is an affected company, and Microsoft isn't.
  - Proves: the theme page skips `synthesized` edges and treats a missing `basis` as `extracted`.
  - Limit: it doesn't assert that a consensus view linked by an extracted edge would now show.
- `find_theme_companies` skip, claim (5): `tests/test_web.py` / `test_find_theme_companies_skips_synthesized_edges`
  - Defect and boundary: the same node-type skip in `db/storage.py` `find_theme_companies`. The boundary is the storage public read.
  - Assertion: same seed. `via_node_id` includes `vw_extracted` and `vw_legacy`, and excludes `vw_cons_msft` and `vw_soft`. The affected companies are exactly `{"Oracle"}`.
  - Proves: the storage reader skips `synthesized` edges.
  - Limit: same seed limit as above.
- Protected paths: `tests/test_vocab.py`, `tests/test_registry_audit.py`, `tests/test_pipeline.py`, `tests/test_repair.py`, `tests/test_web.py`.
- Protected revision (`git hash-object`, uncommitted working-tree blobs on base `11825e60d671ef850580d287f9d88e6c64372064`):
  - `tests/test_vocab.py` `4eaacab39f91432de9a75b2f46b28d0c1eff8ff2`
  - `tests/test_registry_audit.py` `3a39ad1da0c0e8e238df348afc88ffd1defd4a41`
  - `tests/test_pipeline.py` `45729539f1dadeb1365f5cf465b473b5fe2a3bff`
  - `tests/test_repair.py` `56e69502ccddb2e1772ad511b26291ca3e34e1c3`
  - `tests/test_web.py` `91e68b83bc0584e6fcc887c0566154225b3132ea`

**Red evidence**
- `uv run pytest tests/test_vocab.py::test_registry_and_code_declare_the_same_official_facet_vocabularies tests/test_registry_audit.py::test_load_registry_rejects_facet_vocabulary_that_differs_from_code tests/test_registry_audit.py::test_cli_audit_sync_keeps_facet_vocabulary_section_unchanged tests/test_pipeline.py::test_pipeline_sets_edge_basis_by_code_not_by_llm tests/test_repair.py::test_repair_backfills_edge_basis_and_is_idempotent tests/test_web.py::test_theme_readers_skip_synthesized_edges tests/test_web.py::test_find_theme_companies_skips_synthesized_edges -v` → `10 failed`, all `AssertionError`s from the missing behavior, none from imports or setup:
  - parity: "ontology_registry.json: no vocabulary lists exactly the entity.entity_type members"
  - all four load cases: "the registry has no facet vocabulary section listing ..."
  - sync: "the shipped registry has no facet vocabulary section"
  - ingest: edges with wrong or missing basis, including `('ABOUT', False, 'synthesized')` and `('ABOUT', False, 'Synthesized')` passed through from the LLM, and `None` on `ABOUT`/`SUPPORTS`/`CONTRADICTS`/`SUPERSEDES` consensus edges
  - repair: all 10 edges have `basis` `None` after repair
  - theme: "a view linked to the theme only by a synthesized edge is listed"
  - storage: "find_theme_companies links a company through a synthesized edge"
- `uv run pytest -q` → `10 failed, 226 passed`. The failures are exactly the 10 new witnesses, and the 226 tests that passed before this change still pass. Orchestrator re-ran it and confirmed the hashes above.
- The company-page consensus guardrail inside `test_theme_readers_skip_synthesized_edges` already passed before the change. It is a regression guard, not RED proof.

**Supporting test plan**
- `audit` reports non-official edge facet keys as counts by key, without failing → Build: `tests/test_vocab.py` (next to `test_audit_counts_and_lists_out_of_vocabulary_stored_values`). Catches the report dropping or failing on `role`, `confidence` or `product_type`.
- Load validation also rejects an alias or fallback that isn't a member, and definition drift → Build: `tests/test_registry_audit.py`. Catches a check that only compares member names.
- The `repair` `basis` counter adds to `total_changes` → Build: `tests/test_repair.py`. Catches a backfill that isn't counted.

## Build

Candidate: `11825e6 + uncommitted working tree @ .claude/worktrees/official-edge-facets (branch proposal/official-edge-facets)`: the production and doc edits below, Proof's unchanged witness edits in `tests/`, new untracked `tests/test_official_facets.py`, and this ledger. Nothing committed.

### Files changed

- `src/stock_ontology/vocab.py` — `EDGE_BASIS` vocabulary (`extracted | synthesized`, no fallback) added to `EDGE_FACET_VOCABS`; `facet_vocabularies_spec()` (the registry shape: `node.<node_type>.<key>` and `edge.<key>`, each `{members: {member: definition}, aliases, fallback}`); `facet_vocabulary_differences()` naming each missing or extra vocabulary, member, definition, alias map and fallback; `is_synthesized_edge()` (missing `basis` counts as extracted); module docstring per Invariants changed. Claims (1), (2), (5).
- `src/stock_ontology/registry.py` — `OntologyRegistry.facet_vocabularies`, defaulting to code's spec, with a field validator that raises `ValueError` listing every difference from `vocab.py`. `create_minimal_registry()` gets it through the default. Claims (1), (2).
- `ontology_registry.json` — adds the `facet_vocabularies` section after `facet_aliases` (157 added lines, no other line changed). Claim (1).
- `src/stock_ontology/pipeline.py` — the extraction edge write sets `basis: extracted`, overriding any LLM value. Claim (3).
- `src/stock_ontology/db/storage.py` — the `upsert_consensus_view` `link` helper adds `basis: synthesized` to `ABOUT`, `SUPERSEDES`, `SUPPORTS` and `CONTRADICTS`; `find_theme_companies` skips `synthesized` theme edges and `synthesized` view-to-company edges, replacing the node-type skip. Claims (3), (5).
- `src/stock_ontology/web/viewmodels.py` — `build_theme_context` skips `synthesized` edges, replacing the node-type skip. Claim (5).
- `src/stock_ontology/repair.py` — `_backfill_edge_basis` runs last, after duplicate and self-loop removal, so only surviving edges count. Sets `synthesized` when either endpoint is a consensus view, else `extracted`. New `edge_basis_backfilled` counter in `total_changes`. Claim (4).
- `src/stock_ontology/audit.py` — `non_official_edge_facet_keys` (key and count) and `summary.non_official_edge_facet_key_count`; reported, never a failure. Supporting obligation.
- `docs/architecture/ontology.md`, `README.md:31` — per Invariants changed.
- `README.md` — one constraint entry: set edge `basis` in code at each write and have theme readers skip `synthesized` edges, with Why and Guarded by.
- `tests/test_official_facets.py` (new, builder-owned) — Proof's supporting test plan named `test_vocab.py`, `test_registry_audit.py` and `test_repair.py`, but Proof protects those whole files, so the unit tests live here: alias, fallback, definition and shape drift rejected on load; a registry missing the section gets code's copy; audit key report; repair counter.

### Unit evidence

- `uv run pytest -q tests/test_official_facets.py` — GREEN: 8 passed. RED was not observed for these. They were written after the behavior they cover, so they guard it without proving it.
- `uv run pytest -q` after the repair step was first added — RED: `tests/test_repair.py::test_repair_counts_self_loops_and_lists_merged_survivors` expected `total_changes == 2` and got 3, because the backfill counted the self-loop edge that repair then deletes. Fixed by running the backfill last, with no witness edited.

### Green evidence

- Decisive witness: `uv run pytest tests/test_vocab.py::test_registry_and_code_declare_the_same_official_facet_vocabularies tests/test_registry_audit.py::test_load_registry_rejects_facet_vocabulary_that_differs_from_code tests/test_registry_audit.py::test_cli_audit_sync_keeps_facet_vocabulary_section_unchanged tests/test_pipeline.py::test_pipeline_sets_edge_basis_by_code_not_by_llm tests/test_repair.py::test_repair_backfills_edge_basis_and_is_idempotent tests/test_web.py::test_theme_readers_skip_synthesized_edges tests/test_web.py::test_find_theme_companies_skips_synthesized_edges -v` — pass, all 10.
- Gate: `uv run pytest -q` — `244 passed`.
- Protected witness blobs match Proof: `git hash-object` of the five protected test files returns `4eaacab3…`, `3a39ad1d…`, `45729539…`, `56e69502…`, `91e68b83…`.
- `uv run ruff check` over the changed source files and `tests/test_official_facets.py` — clean. Repository-wide ruff reports 42 errors in other files, not checked against the base.
- Not checked: the live web page against the real `ontology.db`. The worktree sandbox refused to load the main checkout's `.env`.

### Intervention record

- None. The repository has no intervention ledger, and the user-facing outcome is the theme page, covered by the witnesses.

### Deviations

- None blocking. For Audit and the human: existing rows in the real `ontology.db` have no `basis` until `repair` runs, and a missing `basis` counts as `extracted`. So between deploying this candidate and running `repair`, the Enterprise AI Monetization theme page shows Microsoft's consensus view again, which the narrow node-type fix had hidden. Running `repair` on the real DB is human-owned.

## Audit

Candidate: `11825e6 + uncommitted working tree @ .claude/worktrees/official-edge-facets (branch proposal/official-edge-facets)`, with the five protected test blobs at Proof's hashes and untracked `tests/test_official_facets.py` and ledger.

Independence: fresh-context. The auditing context had seen only the task message, the ledger, the candidate diff, the test files and its own command output. It did not author or see the Frame, Proof or Build work in progress.

Primary-claim verdict: PROVED. Evidence: `git hash-object` on `tests/test_vocab.py`, `tests/test_registry_audit.py`, `tests/test_pipeline.py`, `tests/test_repair.py` and `tests/test_web.py` returns `4eaacab3…`, `3a39ad1d…`, `45729539…`, `56e69502…`, `91e68b83…`, which match Proof's protected revision. `git diff HEAD -- tests` holds only additions (606 lines, no removed lines), so no pre-existing test was weakened. Proof records all 10 decisive cases RED for the missing behavior. The seven named witnesses (10 cases) were re-run and pass: parity between registry and code, the load-time rejection of member drift, `basis` set by code at both write paths with the LLM value overridden, the repair backfill being idempotent, and both theme readers skipping `synthesized` edges. `grep` over `src` confirms the only `upsert_edge(Edge(...))` writers are `pipeline.py:481` and `db/storage.py:413`, and both now set `basis`. Node-facet membership at ingest is `canonical-vocabulary`'s existing behavior, now tied to the registry through the parity check. Limit: the witnesses use fake LLMs, the minimal registry and temp DBs. The parity witness doesn't fix the section's layout. The load witness mutates members only. A registry file with no `facet_vocabularies` section loads silently with code's copy (`registry.py` `default_factory`). That is a guarded design choice, not a load failure.

Guardrail verdicts:
- `audit --sync` keeps the facet vocabulary section unchanged: PROVED. Evidence: `tests/test_registry_audit.py::test_cli_audit_sync_keeps_facet_vocabulary_section_unchanged` passes and is protected. Limit: it compares the section's JSON value, not the raw file bytes.
- Consensus views still show on company pages with their pillars, and non-official edge facets are still stored and read: PROVED. Evidence: the guardrail part of `tests/test_web.py::test_theme_readers_skip_synthesized_edges` checks `build_entity_context("ent_msft")["consensus"].pillars`. `test_pipeline_sets_edge_basis_by_code_not_by_llm` and `test_repair_backfills_edge_basis_and_is_idempotent` check that `role`, `confidence` and `product_type` survive. Limit: the pillars check was already green before the change, so it is a regression guard and not RED proof.

Scope and duty verdict: scope HELD; duties HELD. Evidence: the changed files are exactly Frame's Include list plus the docs and the new test file. `ontology_registry.json` only gains the `facet_vocabularies` section. `tests/test_canonical_vocabulary.py` is unchanged. No `strength` facet, runtime schema or relation handling was added. All supporting obligations are present: the `EDGE_BASIS` vocabulary, the registry section with its validator, `basis` at both writers, the repair backfill with its `edge_basis_backfilled` counter in `total_changes`, the audit `non_official_edge_facet_keys` report, and both node-type skips replaced. The three Invariants-changed edits are made: `docs/architecture/ontology.md`, the `vocab.py` docstring and `README.md:31`. The constraint-capture entry under the README's constraint list has a Why and names three Guarded-by tests, all of which exist and pass. Limit: `find_theme_companies` also skips `synthesized` view-to-company second-hop edges, and no witness covers that. It counts within decision 5 ("skip synthesized edges"), not as expansion.

Test homes:
- `tests/test_vocab.py`, `tests/test_registry_audit.py`, `tests/test_pipeline.py`, `tests/test_repair.py`, `tests/test_web.py`: Proof's protected witnesses, each in the permanent owner Frame named.
- `tests/test_official_facets.py` (new): holds the supporting tests for alias, fallback, definition and shape drift, the audit key report and the repair counter. They went into a feature file because Proof protected the files its plan named. That is acceptable, but they were written GREEN without a RED run, so they guard the behavior without proving it.

Full gates: PASS.
- `uv run pytest -q`: `244 passed`.
- The decisive-witness command plus `tests/test_official_facets.py` and `tests/test_canonical_vocabulary.py`: `25 passed`.
- `uv run ruff check` on the seven changed source files and `tests/test_official_facets.py`: clean.

Limit: ruff wasn't run repo-wide. The live web page wasn't checked against the real `ontology.db`.

Residual risks:
- Existing rows in the real `ontology.db` have no `basis` until a human runs `repair`, and a missing `basis` counts as `extracted`. Until then the Enterprise AI Monetization theme page shows Microsoft's consensus view again, which the narrow node-type fix had hidden. Run `repair` before or together with deploying.
- A registry without a `facet_vocabularies` section loads using code's copy rather than failing. A stale registry file elsewhere wouldn't be flagged until `audit --sync` rewrites it.
- The second-hop synthesized-edge skip in `find_theme_companies` has no witness.

Recommendation: ACCEPT
Packet: no re-audit needed. Two next actions are human-owned: committing the candidate, and running `repair` against the real `ontology.db` to backfill `basis` before the theme page fix takes effect live.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
