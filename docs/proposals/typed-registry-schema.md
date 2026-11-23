---
proposal_id: "typed-registry-schema"
state: ACCEPTED
witness: independent
candidate: "6bad51a + uncommitted working tree (git diff HEAD sha256 prefix 787daa7e95ede863; witness blob defc8c2) @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/typed-registry-schema)"
---

# Proposal: Typed registry schema for nodes and edges

## Proposal

### Intent

Official facets should be typed, versioned and enforced, and that is the job of
the ontology registry. In the requester's words:

1. The registry has the nodes, properties of the nodes, and facets.
   1. A property of the node is something like metadata, like a type.
   2. Depending on the type, there are sets of required facets.
   3. Facets are enums, numbers, or have some data values.
2. Edges, like nodes, also have metadata and facets.

### Tentative primary claim

The registry defines, for nodes and edges, their properties (metadata like a
type) and, depending on the type, the required facets and each facet's kind
(enum, number, or some data value), and stored nodes and edges are typed,
versioned and enforced against it.

### Why now

Raised while reviewing what the official ontology contains: official facets
today are not typed, versioned or enforced.

### Known constraints

- The registry holds the nodes, their properties, and their facets.
- Edges get the same treatment as nodes: metadata and facets.

### Non-goals

None stated.

### Open choices

- What "enforced" does to a write that breaks the schema: reject it, coerce it,
  or store it and flag it.
- What "versioned" means: the registry carries a version, stored data records
  which version it was written under, or both, and what happens when the
  version changes.
- Which facets are required for each type, and which are optional.
- What "some data values" covers beyond enums and numbers (dates, text, lists,
  or others).
- Which properties count as metadata for nodes and for edges, beyond type.
- What happens to stored nodes and edges that do not meet the schema today.
- Whether facets outside the registry stay allowed.
- Sequence: nodes and edges together or separately, and typing, enforcement
  and versioning together or separately.
- How the schema is expressed and validated. The requester suggested it can be
  expressed and validated using protobufs, and even suggested that protobuf is
  the registry, and it also enforces the code.

## Frame

Candidate: `6bad51a + uncommitted first-Build working tree (diff prefix 23c6a5e2eb28fc27) @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/typed-registry-schema)`

### Human decisions (2026-11-23)
- Schema source: extend the JSON registry. Protobuf is not used.
- A missing required facet is a pipeline issue: regenerate until it passes.
- The required list is minimal and grows later. Views require only `view_type`.
- Versioning: the registry is versioned, `repair` fixes today's rows, and the DB has a migration.
- Facets outside the registry stay allowed. The registry enforces the minimum, not the maximum.
- Nodes and edges, typing, enforcement and versioning ship together.
- After the first Build (2026-11-23): enforcement is on by default, including for an `OntologyDB` opened without an explicit registry. An optional official facet whose value cannot be coerced to its kind is dropped and the note is kept; only required facets trigger regeneration.

### Verified reality
- `uv run pytest -q` at 6bad51a: 276 passed in 7.64s. Proves the suites judging this change were green before it started; limit: offline fakes only, no live ingestion run.
- `src/stock_ontology/models.py:37` `NodeType` Literal and `src/stock_ontology/db/schema.py` `CHECK(node_type IN (...))`. Proves node_type is the only node property enforced by code and DB; limit: edges have only `relation TEXT NOT NULL`.
- `src/stock_ontology/models.py` `Node.facets` and `Edge.facets` are `dict[str, Any]`; `src/stock_ontology/db/storage.py:192` `upsert_node` writes `json.dumps(node.facets)` unchecked. Proves the write boundary accepts any facet dict; limit: repair writes through the same methods (`docs/architecture/governance.md`), but this was not checked for every caller.
- `src/stock_ontology/db/storage.py` write methods `upsert_node`, `upsert_edge`, `update_edge`, `merge_node_into`, `upsert_consensus_view`. Proves a small set of write entry points can carry enforcement; limit: `upsert_consensus_view` sets `view_type` itself.
- `src/stock_ontology/vocab.py:40` `Vocabulary` with members, definitions, aliases and `fallback`, and `models.py` `ExtractedEntity.entity_type` `default="company"`. Proves extraction fills a fallback today when the LLM omits or garbles a subtype, so a required subtype can never be missing at write; limit: no value kind other than enum and no notion of required.
- `src/stock_ontology/pipeline.py` `_process_document` calls `self.llm.extract_document(...)` once, then writes in one transaction; `run()` wraps each note in `try`. Proves a note that raises rolls back with no ingestion log entry and is retried on the next run; limit: no regeneration within a run exists.
- `src/stock_ontology/registry.py:283` `version: int = 1` and `registry.py:298` `_facet_vocabularies_match_code`. Proves the registry version is never read and that `vocab.py` is the source the JSON must match.
- `src/stock_ontology/db/storage.py:146` `_migrate_schema` and `storage.py:531` `db_metadata` helpers. Proves a migrate-on-open hook and a key-value metadata table exist; limit: the hook only rebuilds `node_lookup`, and no registry version is stamped.
- `src/stock_ontology/repair.py:80` `_canonicalize_facets` and `repair.py:101` `_backfill_edge_basis`. Proves repair already rewrites stored facets through `OntologyDB`; limit: it does not coerce value kinds or check required facets.
- `tests/test_vocab.py:245` and `tests/test_official_facets.py:46`. Prove the code-is-source direction is pinned by tests.
- Read-only query of local `ontology.db` this session: all 187 nodes carry their subtype or `stage`; `target_price` is int on 20 views and str on 4. Proves today's rows meet the proposed required set and that kind drift exists in optional facets; limit: one local DB, not a fixture.

### Final primary claim
- The JSON registry declares, per node type and for edges, the required official facets and each official facet's kind (enum, number, date, text, list), and carries a version. A node or edge written through `OntologyDB`, opened with or without an explicit registry, that lacks a required facet or has a wrong-kind official facet is refused. Ingestion regenerates a note's extraction until its required facets pass, up to a cap, and drops an optional official facet whose value cannot be coerced to its kind while keeping the note. The DB records the registry version, and opening it for writing at an older version migrates the stored rows.

### Routing
- Witness: `independent`
- Why: it changes what the single DB write boundary accepts and rewrites stored facets on migration, so it can break ingestion of every note and alter stored data across registry, vocab, storage, pipeline and repair.
- Human-owned irreversible action: running the migration or `repair` on the live `ontology.db`, and merging to main. No stage executes either.

### Decisive witness
- Layer: component tests against a temp `OntologyDB` and the pipeline with a fake LLM client.
- Permanent owner: `tests/test_official_facets.py`.
- Witness: (a) `upsert_node` with a view missing `view_type`, or with `target_price` as a non-numeric string, raises and writes nothing, also for an `OntologyDB` opened without an explicit registry, while a conforming view with extra free-form facets round-trips unchanged; (b) a fake LLM that omits `view_type` on its first extraction and supplies it on the second ingests the note with two extraction calls; one that never supplies it fails the note after the cap, leaving no rows and no ingestion log entry; (c) a temp DB stamped at an older registry version, opened writable, has its stored `target_price` strings coerced to numbers and its stamp set to the registry's version; (d) a fake LLM whose view carries `view_type` and a `target_price` of `"$650"` ingests the note in one extraction call and stores the view without `target_price`. Witnesses must not depend on the current date.

### Guardrail claims
- Ingesting the shipped `data/` notes with the fake LLM client produces the same nodes and edges as at 6bad51a.
- `audit`, the agent, web and search still open and read a DB stamped at an older version, or with no stamp, read-only and without writing.
- Facets not declared in the registry are stored and read back unchanged.

### Supporting obligations
- Registry facet schema: extend `facet_vocabularies` (or a sibling key) with `kind` and `required` per facet, per node type and for edges; `load_registry` validates it.
- Flip the source: `vocab.py` and the extraction models read from or are checked against the registry, and a unit test fails when they differ.
- Initial required set: entity `entity_type`, event `event_type`, view `view_type`, theme `stage`, edge `basis`. All other current vocabulary facets stay official and optional. Declare `event_date` and `as_of` as dates and `target_price` as a number.
- For required facets, extraction no longer substitutes the fallback; a missing or out-of-vocabulary value fails validation and triggers regeneration. Optional enum facets keep today's fallback rule.
- Regeneration cap: 2 regenerations (3 extraction calls) per note, then the note fails through the existing `run()` failure path.
- Kind coercion where lossless (for example `"630"` to `630`); anything else fails validation at the write boundary. Ingestion and consensus synthesis drop an uncoercible optional official facet before writing.
- The built-in default registry declares the shipped facet schema, so an `OntologyDB` opened without a registry enforces it.
- `db_metadata` key `registry_version`, written by ingestion and repair; `_migrate_schema` runs the facet migration when the stamp is older than the registry, and writes the stamp. Read-only opens never migrate.
- `repair` runs the same migration, so it fixes today's rows.
- Unit tests per kind, per required set, for the cap and for the stamp.

### Allowed scope
- Reuse: `Vocabulary` in `vocab.py`, the registry's `facet_vocabularies`, `db_metadata` and `_migrate_schema`, the `OntologyDB` write methods, repair's `_canonicalize_facets`, and the pipeline's existing per-note failure path.
- Cheaper alternative: report violations in `audit` without enforcing them. Rejected because the Proposal asks for enforcement. Also rejected: enforcing only in the pipeline, since repair and consensus writes would bypass it.
- Include: `ontology_registry.json`, `src/stock_ontology/registry.py`, `vocab.py`, `models.py`, `pipeline.py`, `db/storage.py`, `db/schema.py` only if a column is needed (expected: none), `repair.py`, `audit.py` only to report the new violations, `llm/prompts.py` only if generated text changes, the tests named above, `docs/architecture/ontology.md`, `docs/architecture/storage.md`, `docs/architecture/governance.md`, `README.md`.
- Exclude/protect: the live `ontology.db`, LLM provider calls, web and agent read paths beyond keeping them working, the suggestion queue, protobuf or any new dependency.

### Invariants changed
- `docs/architecture/ontology.md:21-22` — today: `Node` and `Edge` have open `facets`; after: official facets are typed and their required set enforced, and other facets stay open.
- `README.md:31` — today: `facet_vocabularies` are mirrored from `vocab.py`, and `load_registry` fails if they differ; after: the registry is the source, and code is checked against it.
- `tests/test_official_facets.py:46` — today: a registry without `facet_vocabularies` gets code's copy; after: the registry is the source and cannot fall back to code's copy.
- `tests/test_vocab.py:245` — today: registry and code declare identical vocabularies; after: kept as the drift check, extended to kinds and required sets.
- `docs/architecture/ontology.md` Vocabularies section, "Ingest stores the member or the fallback" — today: every enum facet falls back at ingest; after: required facets regenerate instead, and optional ones keep the fallback.

### Decisions required
- None.

## Proof

**Approved witness correction (third Proof pass, 2026-11-23)**
- One line in `tests/test_official_facets.py` / `test_ingest_drops_uncoercible_optional_facet_and_keeps_note`: the assertion `[path for path, _ in report.errors] == []` became `[path for path, _ in report.errors if not path.startswith("consensus:")] == []`. The fake inherits a `synthesize_consensus` that raises, so a `consensus:Omega Corp` error is unavoidable and not under test. The test still requires no error for the note itself, exactly 1 extraction call, a logged note, and one stored view without `target_price`.
- Protected revision now: git blob `defc8c2bff0ab377d066575128a227e2389629ae` (`tests/test_official_facets.py`) and `b458c0f3562d294e429900ac323ac34482170de2` (fixture).
- On the current Build candidate after this correction: `uv run pytest -q` → 339 passed. `uv run pytest tests/test_official_facets.py -q` → 20 passed.

Candidate: `6bad51a2d94fc1d751ddbfa0da47ef6176841eeb + uncommitted first-Build working tree, branch proposal/typed-registry-schema (/Users/jasonbxu/Documents/GitHub/stock_ontology)`. I hashed the tree two ways. `git diff HEAD -- src ontology_registry.json | shasum` gives prefix `2521e6de0a46c3da`. `git diff HEAD -- . ':!tests/test_official_facets.py' | shasum` gives `e197af5af027ee47`, the same before and after this rerun, so the Build tree didn't change underneath me. Untracked: `.claude/launch.json`, the ledger and `tests/fixtures/typed_registry_baseline_graph.json`. This rerun edited only `tests/test_official_facets.py`. Nothing under `src/` was touched and nothing was committed.

**Protected witness**
- New RED: enforcement is on by default. `tests/test_official_facets.py` / `test_default_db_without_registry_refuses_missing_required_or_wrong_kind_facet[missing-view_type]`, `[non-numeric-target_price]`
  - Defect and boundary: `create_minimal_registry()` declares no `facet_schema`, so an `OntologyDB` opened without a registry enforces nothing. The boundary is the `OntologyDB` write path at its built-in default.
  - Assertion: `OntologyDB(path, embedding_dim=8)` with no registry raises `ValueError` from `upsert_node` for a view without `view_type` and for one with `target_price: "about six hundred"`, and stores 0 nodes. Proves witness (a) for a DB opened without an explicit registry. Limit: edges and the other write methods aren't covered on the default registry.
- New RED: an uncoercible optional facet is dropped and the note kept (witness d). `tests/test_official_facets.py` / `test_ingest_drops_uncoercible_optional_facet_and_keeps_note`
  - Defect and boundary: a wrong-kind optional facet raises `FacetSchemaError`, which triggers regeneration and fails the note. The boundary runs from the fake LLM's `ExtractionResult.model_validate` payload through `IngestionPipeline.run` to the DB.
  - Assertion: a view with `view_type: analyst_report` and facets `target_price: "$650"` and `author: "Desk"` ingests with exactly 1 extraction call and no errors, and the note is logged. The one stored view has no `target_price` and keeps `view_type` and `author`. Proves optional official facets are dropped, not regenerated. Limit: it only covers the number kind and only covers ingestion, not consensus synthesis.
- New RED: the registry is the source with no fallback to code's copy (replaces `test_registry_without_facet_vocabularies_gets_codes_copy`). `tests/test_official_facets.py` / `test_registry_without_facet_vocabularies_is_refused_not_filled_from_code`
  - Defect and boundary: `OntologyRegistry.facet_vocabularies` still has `default_factory=facet_vocabularies_spec`. The boundary is `load_registry` reading a registry JSON file.
  - Assertion: loading the shipped registry with `facet_vocabularies` removed raises `ValueError` naming `facet_vocabularies`. Proves the changed invariant at `tests/test_official_facets.py:46`. Limit: it doesn't require a missing `facet_schema` to be refused.
- GREEN on this candidate (already satisfied, kept protected):
  - `test_upsert_node_refuses_missing_required_or_wrong_kind_facet[missing-view_type]` and `[non-numeric-target_price]`: shipped registry, write refused.
  - `test_upsert_edge_refuses_edge_without_basis`: edge without `basis` refused.
  - `test_ingest_regenerates_extraction_missing_required_view_type`: 2 calls.
  - `test_ingest_fails_note_after_regeneration_cap`: 3 calls, then the note fails with no rows and no log entry.
  - `test_writable_open_migrates_rows_and_stamps_older_registry_version`: `"630"` becomes 630 and the stamp is set to `registry.version`.
  - Guardrails: `test_conforming_view_with_free_form_facets_round_trips`, `test_read_only_open_of_old_or_unstamped_db_reads_without_writing` and `test_shipped_fixture_ingest_matches_baseline_graph`.
  - The earlier tests (`test_load_registry_rejects_*`, `test_audit_reports_non_official_edge_facet_keys_without_failing`, `test_repair_counts_basis_backfill_in_total_changes`) stay protected.
- The three defects Build reported in my witnesses are fixed:
  - Date dependence: `test_shipped_fixture_ingest_matches_baseline_graph` now monkeypatches `stock_ontology.pipeline.datetime`, so `now()` returns 2026-11-23T12:00Z, the date the baseline was captured at 6bad51a. The fixture is unchanged and the test no longer depends on today's date.
  - The `_seed` edge now carries `basis: "extracted"`. The audit and repair witnesses still pass: the audit reports only `confidence` and `role`, and repair backfills after a raw-SQL `json_remove`.
  - Witnesses (a) without a registry and (d) were added, as listed above.
- Protected paths: `tests/test_official_facets.py`, `tests/fixtures/typed_registry_baseline_graph.json`.
- Protected revision (second pass, superseded by the correction above): git blob `c9dad9b12460166cee026a74fb9b0682dcd4f01f` (`tests/test_official_facets.py`) and `b458c0f3562d294e429900ac323ac34482170de2` (`tests/fixtures/typed_registry_baseline_graph.json`), both uncommitted. Compare with `git hash-object`.

**Red evidence**
- `uv run pytest tests/test_official_facets.py -v` → 4 failed, 16 passed.
  - `test_registry_without_facet_vocabularies_is_refused_not_filled_from_code`: `DID NOT RAISE ValueError`.
  - Both `test_default_db_without_registry_...` cases: `DID NOT RAISE ValueError`.
  - `test_ingest_drops_uncoercible_optional_facet_and_keeps_note`: `extract_calls` holds 3 entries where 1 was expected, because the wrong-kind optional facet triggered regeneration.
- `uv run pytest -q` → 4 failed, 332 passed. The 4 failures are exactly the RED witnesses above. `ruff check tests/test_official_facets.py` is clean.
- Enforcement on the default registry, the drop rule for optional facets, and the registry-as-source rule have no proof until these 4 tests turn GREEN.

**Supporting test plan**
- The built-in default registry declares the shipped `facet_schema` and stays equal to the loaded registry's schema → Build: `tests/test_vocab.py`. Catches the default registry and `ontology_registry.json` drifting apart.
- Consensus synthesis drops an uncoercible optional facet before `upsert_consensus_view` → Build: `tests/test_pipeline.py`. Catches a consensus write failing on a bad optional value.
- Edge enforcement and `update_edge`, `merge_node_into` and `upsert_consensus_view` on the default registry → Build: `tests/test_db.py`. Catches a write path that bypasses the check.
- Other test files that seed through a DB with no registry (for example `tests/test_web.py`, `tests/test_agent.py`, `tests/test_search.py`) may need conforming fixtures once enforcement is on by default. They aren't protected and may be updated.

## Build

Candidate: `6bad51a2d94fc1d751ddbfa0da47ef6176841eeb` plus the uncommitted working tree on `proposal/typed-registry-schema`. `git diff HEAD | shasum -a 256` prefix is `c2b941ff7122f341`. That covers 23 files and doesn't include the untracked fixture `tests/fixtures/typed_registry_baseline_graph.json`. Nothing is committed. The protected witnesses are unchanged: `git hash-object` gives `c9dad9b12460166cee026a74fb9b0682dcd4f01f` for `tests/test_official_facets.py` and `b458c0f3562d294e429900ac323ac34482170de2` for the fixture.

Status: 3 of the 4 Proof RED witnesses are now GREEN. `test_ingest_drops_uncoercible_optional_facet_and_keeps_note` still fails, because of a defect in the witness itself (first deviation below).

### Files changed

- `ontology_registry.json`:
  - Adds a `facet_schema` sibling key, per node type and for edges, with `kind` and `required` for each official facet.
  - Bumps `version` to 2.
  - Required facets: entity `entity_type`, event `event_type`, view `view_type`, theme `stage`, edge `basis`.
  - Kinds: `event_date` and `as_of` are `date`, `target_price` is `number`.
- `src/stock_ontology/vocab.py`: code's copy of the schema (`FacetSpec`, `NODE_FACET_SCHEMA`, `EDGE_FACET_SCHEMA`), `facet_schema_spec`, the drift check `facet_schema_differences`, the lossless `coerce_facet_value`, and a shared `coerce_member`. The docstring now says the registry is the source.
- `src/stock_ontology/registry.py`:
  - `FacetSchemaError` (a `ValueError`).
  - `facet_vocabularies` is now a required field, so a registry without it is refused and code's copy is never filled in.
  - `facet_schema` is validated against code when present.
  - New methods `required_facets`, `check_facets`, `migrate_facets`, and `drop_uncoercible_optional` (the ingest drop rule).
  - `create_minimal_registry()` now declares the shipped `facet_vocabularies` and `facet_schema`. It stays at `version=1`, because existing tests expect `v1` for the starter registry.
- `src/stock_ontology/db/storage.py`:
  - `upsert_node`, `upsert_edge` (insert and merge paths) and `update_edge` check facets through `registry.check_facets`, including on the default registry.
  - `REGISTRY_VERSION_KEY`, `use_registry` and `migrate_facets(registry=None)`.
  - A writable open migrates and stamps only when it's given an explicit registry. The protected read-only guardrail requires this: it reopens writable without a registry and expects `"630"` to stay a string.
- `src/stock_ontology/models.py`: the required subtypes become `Literal | None`. An out-of-vocabulary value becomes None. The default still applies when the field is omitted.
- `src/stock_ontology/pipeline.py`:
  - `MAX_EXTRACTION_ATTEMPTS = 3`, with regeneration on `FacetSchemaError`.
  - `_required_subtype` doesn't substitute a fallback for a required facet.
  - `IngestionPipeline(registry=...)` calls `db.use_registry`.
  - `drop_uncoercible_optional` runs on entity, theme, event, view, edge and consensus facets before they're written.
- `src/stock_ontology/repair.py`:
  - `RepairReport.facets_migrated`, counted in `total_changes`.
  - `repair_ontology` ends with `db.migrate_facets(registry)`.
  - `_backfill_edge_basis` now runs before `_canonicalize_facets`, so every edge rewrite carries the required `basis`.
  - Consensus detection uses `VIEW_TYPE.coerce`.
- Tests, as allowed by Proof's supporting test plan and the fixture rule:
  - `tests/test_vocab.py`:
    - The default registry declares the shipped schema and vocabularies.
    - A registry that declares no schema enforces nothing.
    - Drop rule unit tests.
    - The out-of-vocabulary audit seed is written under a schema-less "legacy" registry.
  - `tests/test_db.py`: a DB with no registry enforces on `upsert_node`, `upsert_edge`, `update_edge` and `upsert_consensus_view`, `merge_node_into` is covered, and the DB is never stamped.
  - `tests/test_pipeline.py`:
    - An unknown subtype regenerates, and a bad optional date is dropped.
    - The fallback applies only under a schema-less registry.
    - New: `test_consensus_synthesis_drops_uncoercible_optional_facet`.
  - `tests/test_repair.py`: event fixtures carry `event_type`.
  - Conforming-fixture updates, all through a registry-less DB:
    - `tests/test_canonical_vocabulary.py`: required subtypes are members, and legacy seeds start conforming before the raw-SQL overwrite.
    - `tests/test_search_ontology_options.py`: the legacy `webinar` row is seeded under a schema-less registry.
    - `tests/test_web.py`: the legacy no-`basis` edges are stripped by raw SQL.
    - `tests/test_search.py`, `tests/test_agent.py`, `tests/test_registry_audit.py` and `tests/test_relationships.py`.
    - Most of these were added mechanically: `basis: "extracted"` on literal `Edge(...)`, the default subtype on literal `Node(...)`, and the previous default made explicit on `Extracted*(...)` calls.
- Docs:
  - `docs/architecture/ontology.md`: typed facets, the Facet schema section, the default registry enforcing, the drop rule, and the fallback for optional facets only.
  - `docs/architecture/storage.md`: default enforcement, and that only an explicit registry migrates and stamps.
  - `docs/architecture/governance.md`: the repair order, the migration, and that a legacy required-facet row stops the run.
  - `README.md`: the line-31 invariant now says the registry is the source with no fallback to code's copy, and that the default DB enforces. There is one Ingestion Constraints entry covering the no-fallback rule for required facets, regeneration, and the drop rule for optional facets. **Why:** proposal `typed-registry-schema`, 2026-11-23. **Guarded by:** the official-facets witnesses and `tests/test_pipeline.py::test_consensus_synthesis_drops_uncoercible_optional_facet`.

### Unit evidence

- Proof's protected RED: `uv run pytest -q` showed 4 failed and 332 passed, as recorded in Proof.
- Post-hoc RED: I wrote the repair-pass unit tests after the code. I then ran them with `src/` and `ontology_registry.json` stashed back to 6bad51a: `uv run pytest -q tests/test_vocab.py tests/test_db.py tests/test_pipeline.py tests/test_repair.py -k "default_registry_declares or drop_uncoercible or consensus_synthesis_drops or default_schema_but_never or registry_declaring_no or regenerates_out_of_vocabulary or repair_migrates"` gave RED, 7 failed.
- GREEN: `uv run pytest -q tests/test_vocab.py tests/test_db.py tests/test_repair.py tests/test_pipeline.py tests/test_canonical_vocabulary.py tests/test_search_ontology_options.py` → 181 passed.

### Green evidence

- Decisive witness: `uv run pytest -q tests/test_official_facets.py -v` → 19 passed, 1 failed. The failure is `test_ingest_drops_uncoercible_optional_facet_and_keeps_note` (first deviation).
- Gate: `uv run pytest -q` → 338 passed, 1 failed (the same test).
- Gate: `uv run ruff check` on every changed `.py` file outside the protected witness → 3 findings: `tests/test_search.py:45` and `tests/test_web.py:1891` and `:1894`. The baseline shows the same count of 3, so none are new.
- I didn't touch the live `ontology.db`, `.env` or any ignored file. I ran no ingestion or repair against the live DB.

### Intervention record

- None. The repository has no intervention ledger. The outcome becomes measurable only after a human runs ingest or `repair` on the live DB.

### Deviations

- **Blocking: witness defect in `test_ingest_drops_uncoercible_optional_facet_and_keeps_note`.**
  - The test's fake inherits `_RegeneratingFakeLLM.synthesize_consensus`, which raises `RuntimeError("consensus not under test")`.
  - The ingested view is `ABOUT` the company `Omega Corp`, so the pipeline's existing consensus step runs, catches the error, and records `report.errors == [("consensus:Omega Corp", ...)]`.
  - The test asserts `[path for path, _ in report.errors] == []`.
  - No implementation can pass that line without skipping consensus synthesis for an affected company. That would be the kind of reconciliation the Build rules forbid.
  - Every other assertion in the test passes. I checked this with a scratch copy that comments out only that line: 1 passed. The protected file is unchanged.
  - Proof should fix the witness: the fake returns a synthesis, or the assertion filters out `consensus:` entries.
- **Non-blocking: migration on open needs an explicit registry.** Enforcement is on by default. Migrating and stamping on a writable open happen only with an explicit registry, `use_registry`, or `repair`. The protected `test_read_only_open_of_old_or_unstamped_db_reads_without_writing` reopens writable without a registry and expects `"630"` to remain a string. CLI ingest still stamps through `IngestionPipeline` → `use_registry`, and CLI `repair` stamps through `migrate_facets(registry)`.
- **Non-blocking: version mismatch.** `create_minimal_registry()` declares the shipped schema but stays at `version=1`, while `ontology_registry.json` is at 2. Existing tests display and assert `v1` for the starter registry.
- **Residual risk for Audit:**
  - Repair's own writes are checked. A live node whose required subtype is outside the vocabulary would stop `repair` with `FacetSchemaError`, and the transaction rolls back. Frame confirmed that all 187 local nodes carry a subtype, but it didn't check that each one is a vocabulary member.
  - Optional facets that can't be coerced, such as `as_of: "Q3 2026"` or `target_price: "$650"`, are now dropped at ingest. They are not stored.

## Audit

Candidate: `6bad51a + uncommitted working tree on proposal/typed-registry-schema; git diff HEAD | shasum -a 256 = 787daa7e95ede863ae15f159955618002af72fb7511dea223e6bf39e5f30ea4e; protected blobs tests/test_official_facets.py = defc8c2bff0ab377d066575128a227e2389629ae, tests/fixtures/typed_registry_baseline_graph.json = b458c0f3562d294e429900ac323ac34482170de2 (both confirmed with git hash-object). Untracked .claude/launch.json and docs/proposals/registry-schema-v2.md are not part of this candidate.`

Independence: fresh-context. This context saw only the ledger, the candidate tree, and its own commands. It did not frame, prove or build.

Primary-claim verdict: PROVED. Evidence: `uv run pytest tests/test_official_facets.py -v` gives 20 passed. I ran the protected witness file and fixture against a `git archive 6bad51a` extract in the scratchpad, using the repo venv with PYTHONPATH set to the extract. That gave 10 failed and 10 passed, and each primary witness failed for the claimed reason:
- (a) `test_upsert_node_refuses_*` and `test_default_db_without_registry_refuses_*` both raised `DID NOT RAISE ValueError`.
- `test_upsert_edge_refuses_edge_without_basis` also raised `DID NOT RAISE`.
- (b) Both regenerate/cap tests failed because the logged note was present.
- (c) The migrate/stamp test asserted False.
- (d) `test_ingest_drops_uncoercible_optional_facet_and_keeps_note` failed because `'target_price': '$650'` was stored.
- `test_registry_without_facet_vocabularies_is_refused_not_filled_from_code` raised `DID NOT RAISE`.

The code matches these witnesses:
- `registry.check_facets` runs in `upsert_node`, `upsert_edge` (insert and merge) and `update_edge`.
- `create_minimal_registry()` declares `facet_schema`.
- `MAX_EXTRACTION_ATTEMPTS = 3`, and only `FacetSchemaError` triggers regeneration.
- `drop_uncoercible_optional` runs before entity, theme, event, view, edge and consensus writes.
- `migrate_facets` writes the `registry_version` stamp.

Limits:
- Migrate-on-writable-open happens only with an explicit registry or `use_registry`. A registry-less writable open enforces but does not migrate. The protected read-only guardrail requires that, and CLI ingest and repair both pass the loaded registry, but it is narrower than a literal reading of "opening it for writing".
- Optional enum facets are checked only for being a string, not for vocabulary membership. Frame chose that ("optional keep today's rule").
- `merge_node_into` writes no facets, so it needs no check.

On the orchestrator note: the Proof correction is acceptable. It came from the witness owner with human approval, and it only filters `consensus:` errors that the inherited fake `synthesize_consensus` produces. Every claim-bearing assertion is unchanged: 1 extraction call, the note logged, one view without `target_price` that keeps `view_type` and `author`. It is still RED at 6bad51a on the `target_price` assertion. Keeping Build without a rerun is fine because no src change was needed. The limit is that I could not reproduce Build's recorded hash `c2b941ff7122f341` by reverting that one line in the diff text, so "src unchanged since Build" rests on the ledger, not my check. Build's status text (19/1, "Blocking" deviation) is now stale.

Guardrail verdicts:
- Shipped `data/` ingest with the fake LLM matches 6bad51a: PROVED. Evidence: `test_shipped_fixture_ingest_matches_baseline_graph` passes on the candidate and on the 6bad51a extract, and the clock is pinned by monkeypatch. Limit: fake LLM only, and the guardrail is not RED-capable by design.
- audit, agent, web and search read an old-stamped or unstamped DB read-only without writing: PROVED for audit, with the rest by inspection. Evidence: `test_read_only_open_of_old_or_unstamped_db_reads_without_writing` passes and checks the file bytes are unchanged after `run_ontology_audit`. `_init_schema`, and with it the migration, is skipped when `read_only`. `tests/test_web.py`, `test_agent.py` and `test_search.py` pass. Limit: agent, web and search are not exercised against an old-stamped DB specifically.
- Facets not declared in the registry round-trip unchanged: PROVED. Evidence: `test_conforming_view_with_free_form_facets_round_trips` passes, and `check_facets` passes through undeclared keys. Limit: covers nodes, not edges.

Scope and duty verdict: scope HELD; duties HELD.
- Scope: every changed file is in Frame's Include list. `db/schema.py`, `audit.py` and `llm/prompts.py` are untouched, and there is no new dependency.
- The edits to tests that Proof did not author are conforming-fixture updates that Proof's supporting test plan allowed. The one changed assertion is in `tests/test_vocab.py`: `event_type` for "Gossip" goes from "fact" to None. It matches the listed invariant "required facets regenerate instead, optional keep fallback".
- The README line-31 change matches its listed invariant.
- Constraint capture: `README.md` Ingestion Constraints has an entry with **Why:** and **Guarded by:**, and every named test exists and passes.
- Limit: `docs/architecture/storage.md` alone records the rule that only an explicit registry migrates and stamps. That is acceptable because it is not a bug-paid constraint.

Test homes:
- `tests/test_official_facets.py`: the Proof-owned decisive witness, its permanent owner per Frame.
- `tests/test_vocab.py`: default-registry schema and drop-rule unit tests, which are the registry/vocab drift owner.
- `tests/test_db.py`: write-path enforcement on the default registry, the storage owner.
- `tests/test_pipeline.py`: regeneration, the schema-less fallback and the consensus drop, the pipeline owner.
- `tests/test_repair.py`: repair fixtures.
- `tests/test_canonical_vocabulary.py`, `tests/test_search_ontology_options.py`, `tests/test_web.py`, `tests/test_search.py`, `tests/test_agent.py`, `tests/test_registry_audit.py`, `tests/test_relationships.py`: conforming fixture updates in their existing owners.

Full gates: PASS.
- `uv run pytest -q`: 339 passed in 8.06s.
- `uv run pytest tests/test_official_facets.py -v`: 20 passed.
- `uv run ruff check` on all 18 changed `.py` files: 3 findings (`tests/test_search.py:45`, `tests/test_web.py:1891` and `:1894`). The same files at 6bad51a also give 3, so none are new.
- Limit: offline fakes only. No live ingest, no live migration and no live repair were run.

Residual risks:
- A loaded registry without `facet_schema` validates and silently disables enforcement, because `use_registry` replaces the enforcing default. `tests/test_vocab.py` pins this behavior. The shipped registry declares the schema, but deleting the key turns enforcement off without error. That is worth a follow-up given "the registry is the source".
- On the live DB, a canonical entity or theme whose stored required subtype is outside the vocabulary would make every note that touches it fail after 3 extraction calls, since `_resolve_canonical_node` keeps the stored value. `repair` would also abort and roll back on `FacetSchemaError`. Frame checked presence on 187 nodes, not membership. Before the human runs ingest or repair live, check membership read-only.
- Uncoercible optional values such as `target_price: "$650"` or `as_of: "Q3 2026"` are now dropped at ingest, not stored. Migration leaves existing uncoercible values in place.
- `create_minimal_registry()` is `version=1` while `ontology_registry.json` is 2. That is harmless now because the default never stamps, but it is a drift point.
- The Build section's candidate hash, the 19/1 green evidence and the "Blocking" deviation are stale after the Proof correction. The ledger should note this for the record.

Recommendation: ACCEPT
Packet: No re-audit is needed. The merge and any live ingest, migration or `repair` stay with the human. Run a read-only check of required-subtype vocabulary membership on the live `ontology.db` before running them. Optionally, the orchestrator can note that Build's evidence was superseded by the Proof correction and that the result is now 339/339.

Orchestrator note (2026-11-23): the read-only membership check Audit asks for was run on the live `ontology.db` before Audit (all 187 nodes' required subtype or `stage` checked against `vocab.py` members): no non-members. Build's 19/1 result and its blocking deviation are superseded by the Proof correction; the candidate is 339/339.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
