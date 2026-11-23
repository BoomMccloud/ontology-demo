---
proposal_id: "registry-schema-v2"
state: ACCEPTED
witness: independent
candidate: "c835acc + uncommitted working tree (git diff c835acc sha256 39e68be0c92f36a4; witness blob 470b147) @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/registry-schema-v2)"
---

# Proposal: Registry schema v2: one pattern for all data

## Proposal

### Intent

Follow-up to `typed-registry-schema` (accepted, commit `c835acc`). All data
follows one pattern, in the requester's words:

> [object, node or edge][object metadata][typed facets][optional facets]
> where type is an object metadata
> typed facets follow from type

The requester chose the simplest design that keeps the same or better
coverage, verification and implementation:

1. Type means an entity of a given entity type must have certain fields,
   generalized to every entity type, not only companies. Type is `node_type`
   plus the subtype facet (`entity_type`) that `typed-registry-schema` already
   requires, so each entity type (for example `entity:company`,
   `entity:person`) declares facets on top of `entity`.
2. Metadata stays limited to the metadata already in the database (node `id`,
   `node_type`, `name`, `summary`, `aliases`, `source_doc_id`, timestamps; edge
   `id`, `from_id`, `to_id`, `relation`, `source_doc_id`, `created_at`). Text
   metadata gets a max length.
3. Fix what the review of the initial design found:
   - Per-type facet specs live only in the registry, not also in code.
   - A registry without `facet_schema` fails to load instead of silently
     turning enforcement off.
   - Optional enum facets are verified for vocabulary membership, not only for
     being text.
   - The stored version cannot drift from the schema it was written under.
   - Edges are typed and have the same protection: an unmapped relation is not
     written.
4. Typed and optional facets keep sharing one store. No separate storage.

`target_price` should always be a number and a currency, so no `$650`, and
`as_of` should be a date, not `Q3 2026`; these wait until a type needs them,
along with per-relation facets.

### Tentative primary claim

Every entity must have the fields the registry declares for its entity type,
edges with an unmapped relation are not written, and every check comes from the
official registry alone.

### Why now

Reviewing `typed-registry-schema` showed it enforces one required facet per
node type only, keeps a second copy of the schema in code, can be switched off
by a missing registry key, accepts any text for optional enums, relies on a
hand-bumped version, and writes edges with unmapped relations.

### Known constraints

- Builds on `typed-registry-schema`.
- The registry is the official ontology, and the system verifies against it.
- Type is object metadata. Typed facets follow from type.
- Metadata is limited to the existing database metadata.
- Optional facets stay allowed. The registry enforces the minimum, not the
  maximum.
- Additional facets or nodes require management to promote them to official.
- No separate storage for typed and optional facets.

### Non-goals

- Moving the subtype into its own column.
- Separate storage for typed and optional facets.
- A number-and-currency kind, and per-relation facet specs, until a type needs
  them.

### Open choices

- Which fields each entity type requires (company, person, product,
  institution, sector, region); an entity type may declare none.
- The max length for `name` and `summary`.

The requester ruled the remaining questions implementation details for Frame.

## Frame

Candidate: `c835acc @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/registry-schema-v2, cut from proposal/typed-registry-schema), clean except untracked .claude/launch.json and this ledger`

### Verified reality
- `uv run pytest -q` at c835acc: 339 passed in 8.26s. Proves the suites judging this change were green before it started; limit: offline fakes only.
- `src/stock_ontology/registry.py:329` `_facet_specs(node_type)` returns `facet_schema["node"][node_type]` or `facet_schema["edge"]`. Proves specs are keyed by node type only, with no subtype layer; limit: none.
- `src/stock_ontology/registry.py:319` `_facet_schema_matches_code` with `vocab.py:474` `facet_schema_differences` comparing against `vocab.py:436` `NODE_FACET_SCHEMA` and `EDGE_FACET_SCHEMA`. Proves the registry's schema must equal a second copy in code, so a new per-type spec needs a code edit; limit: `NODE_FACET_SCHEMA` is otherwise used only by `facet_schema_spec`, which feeds `create_minimal_registry()` (`registry.py:838`).
- `src/stock_ontology/registry.py:306` `facet_schema: dict = Field(default_factory=dict)` and `_facet_specs` returning `{}` when empty; `tests/test_vocab.py:430` `test_registry_declaring_no_facet_schema_enforces_nothing`. Proves a registry without `facet_schema` loads and enforces nothing, and a test pins it.
- `src/stock_ontology/vocab.py:521-525` `coerce_facet_value`: an optional enum only has to be a string. Proves optional enums are not checked for membership.
- `src/stock_ontology/db/storage.py:55` `REGISTRY_VERSION_KEY` and `storage.py:169-170` comparing the stamp as an integer against `registry.version`; `registry.py:296` `version: int = 1` set by hand in `ontology_registry.json`. Proves the stamp tracks a hand-bumped integer, so a schema edit without a bump never migrates; limit: `registry.version` is also shown in the web UI (`web/viewmodels.py:1258`, `web/app.py:547`).
- `src/stock_ontology/registry.py:229` `CanonicalEdgeResult.matched` and the pipeline writing every canonicalized edge. Proves the pipeline knows when a relation is unmapped but writes it anyway; `upsert_edge` and `update_edge` only normalize the name.
- `src/stock_ontology/db/storage.py` `upsert_node` stores `name` and `summary` unchecked. Proves no metadata length limit exists.
- Read-only queries of local `ontology.db` this session: 0 of 504 edges have an unmapped relation; 0 nodes have an out-of-vocabulary optional enum; 0 edges fail today's check; longest `name` 78 and `summary` 783 characters; no `registry_version` stamp yet. Entity facet coverage: company 31 (`sector` 31, `ticker` 19), person 22 (`role` 22, `organization` 22), product 9, institution 18 (`sector` 16), sector 1. Proves the narrowed rules break no stored row if limits are set at or above these values; limit: one local DB.

### Final primary claim
- An entity is refused on write when it lacks a facet the registry declares as required for its entity type (`entity:<entity_type>`, layered on `entity`), or breaks that facet's kind; adding such a declaration is a registry edit with no code change. An edge whose relation the registry does not map is not written to `edges`; it is held in `pending_edges`, which `audit` turns into a relation suggestion, and `repair` promotes it into `edges` once the registry maps the relation. A registry without `facet_schema` fails to load. Optional enum facets must be vocabulary members. `name` and `summary` have a registry-declared max length. The DB's stamp changes whenever the schema changes, so a changed schema always migrates.

### Routing
- Witness: `independent`
- Why: it narrows what the single DB write boundary accepts, changes which extracted edges are stored, and rewrites the version stamp and migration trigger, so it can break ingestion and alter stored data.
- Human-owned irreversible action: merging, and running ingest or `repair` on the live `ontology.db`. No stage executes either.

### Decisive witness
- Layer: component tests against a temp `OntologyDB` and the pipeline with a fake LLM client.
- Permanent owner: `tests/test_official_facets.py` (its `typed-registry-schema` protection ended at that run's Audit).
- Witness: (a) with a registry JSON whose only change from the shipped one is an `entity:person` entry requiring `organization`, `upsert_node` refuses a person entity without it, accepts one with it, and accepts a company entity without it; no source edit is involved. (b) `upsert_edge` refuses a relation the registry does not map, and ingesting an extraction with one mapped and one unmapped edge stores only the mapped edge and keeps the note. (c) `load_registry` on the shipped registry with `facet_schema` removed raises. (d) `upsert_node` refuses a view with `stance: "maybe"`, and ingest drops it and keeps the note. (e) `upsert_node` refuses a `name` longer than the declared max. (g) ingesting an unmapped `FROBNICATES` edge stores no edge and one `pending_edges` row; a read-only `audit` lists `FROBNICATES` as an unmapped relation suggestion; after the registry gains a `FROBNICATES` relation, `repair` moves the row into `edges` with `basis` set and deletes the pending row; deleting the source note removes its pending rows. (f) a DB stamped under the shipped schema, opened writable with a registry whose schema differs but whose `version` integer is unchanged, migrates and restamps.

### Guardrail claims
- Ingesting the fixture notes with the fake LLM client produces the same graph as at c835acc.
- Read-only opens (audit, agent, web, search) of a DB stamped under an older schema, or unstamped, still read without writing.
- Facets not declared in the registry are stored and read back unchanged, on nodes and on edges.

### Supporting obligations
- `_facet_specs` merges `facet_schema["node"][node_type]` with `facet_schema["node"]["entity:<entity_type>"]` when present. Only `entity` subtypes are layered for now.
- Code keeps no copy of per-type specs. The drift check becomes: the registry's schema declares at least the required subtype facets code depends on (`entity_type`, `event_type`, `view_type`, `stage`, edge `basis`). `facet_vocabularies` stay checked as today, since the extraction models need them as `Literal`s.
- `create_minimal_registry()` keeps a built-in base schema for a DB opened without a registry. It is a minimum, not required to equal the shipped file.
- `facet_schema` becomes a required registry field.
- Optional enums are coerced to a member or refused at the write boundary; ingest's drop rule then removes them. Repair's existing lowercase-and-keep rule for unknown optional enums changes to drop, matching ingest.
- `name` and `summary` max lengths live in the registry, set to 200 and 1,000, which fit every stored row. Over-length metadata is refused at write, and ingest regenerates as for a required facet.
- Unmapped relations: the pipeline writes the edge to a new `pending_edges` table (from_id, to_id, raw relation, facets, source_doc_id, created_at) instead of `edges`, keeps the note, and counts it in `IngestReport`. `upsert_edge` and `update_edge` refuse them. `audit` reads `pending_edges` read-only alongside `edges` for relation suggestions. `repair` promotes pending rows whose relation now resolves, through `upsert_edge`, and deletes them. Pending rows are cleared with their note (`delete_document_artifacts`, `_clear_prior_artifacts`) and cascade with their endpoint nodes. `repair` does not move legacy unmapped edges out of `edges`; it may abort on one, as the human accepted.
- Version stamp: a hash of the canonical JSON of `facet_vocabularies`, `facet_schema` and the metadata limits. Migration runs when the stamp differs. `registry.version` stays as the human-facing label.
- Initial entity-type declarations in `ontology_registry.json`: `entity:person` requires `role` and `organization`; `entity:company` requires `sector` (all `text`). Ingest regenerates when they are missing, like any required facet.
- Unit tests per merge rule, per refusal, for the skip count and for the hash.

### Allowed scope
- Reuse: `OntologyRegistry._facet_specs`, `check_facets`, `drop_uncoercible_optional`, `migrate_facets`, `CanonicalEdgeResult.matched`, `resolve_relation`, `db_metadata`, and the pipeline's regeneration loop from `typed-registry-schema`.
- Cheaper alternative: add `entity:<type>` keys alone and leave the other review fixes for later. Rejected because the approved Proposal includes them. Also rejected: moving the subtype to a column, and separate facet storage, both non-goals.
- Include: `ontology_registry.json`, `src/stock_ontology/registry.py`, `vocab.py`, `db/storage.py`, `db/schema.py` (the `pending_edges` table only), `pipeline.py`, `repair.py`, `audit.py` (reading `pending_edges`), the tests that seed schema-less or nonconforming data, `docs/architecture/ontology.md`, `storage.md`, `governance.md`, `README.md`.
- Exclude/protect: the live `ontology.db`, LLM provider calls, any `db/schema.py` change beyond `pending_edges`, web and agent read paths beyond keeping them working, any new dependency, money and per-relation specs.

### Invariants changed
- `README.md:31` — today: `facet_schema` is optional, `vocab.py` is checked for equality, the DB records `version`; after: `facet_schema` is required, code is checked only for the subtype minimum, the DB records a schema hash.
- `README.md:144` — today: an optional official facet that cannot be coerced to its kind is dropped; after: that also covers optional enums outside their vocabulary and over-length text, and unmapped edges are skipped.
- `docs/architecture/ontology.md:17` and `:93-95` — today: loading fails if `facet_schema` differs from `vocab.py`, and a registry without `facet_schema` enforces nothing; after: `facet_schema` is required and holds per-type specs code does not copy.
- `docs/architecture/storage.md:49-56` — today: `registry_version` stores the registry's integer version and migrates when older; after: it stores the schema hash and migrates when different.
- `docs/architecture/governance.md` repair rule "an unknown value is lowercased and kept" for enum facets — after: for optional enums, an unknown value is dropped.
- c835acc `README.md:138` (relation vocabulary, queuing unknown relations via `audit --sync`) and its guard `tests/test_relationships.py::test_write_side_normalization_oov_queueing_and_catalog_signatures` — today: ingest stores an unknown relation in `edges` and audit queues it; after: ingest holds it in `pending_edges`, audit still queues it from there, and the guard reasserts the queueing. Approved by the human in R1.
- c835acc `README.md:147` ("Keep `upsert_edge` accepting raw strings") — today: `upsert_edge` accepts any relation name; after: `upsert_edge` and `update_edge` refuse unmapped relations, and tests seed legacy rows through raw SQL. Approved by the human in R1.
- Optional enum aliases are canonicalized on every write, not only at extraction — reflected in the stance assertions of `tests/test_agent.py`, `tests/test_web.py` and `tests/test_web_navigation.py` (`buy` shown as `bullish`, `cautious` as `bearish`, `hold` as `neutral`). Approved by the human in R1; canonical only, no raw value kept.
- `tests/test_vocab.py:430` `test_registry_declaring_no_facet_schema_enforces_nothing` — today: pins that a schema-less registry enforces nothing; after: a schema-less registry fails to load.

### Decisions required
- None. Human decisions (2026-11-23, R1 after Audit REVISE): the ontology must evolve through recommendations, so unmapped relations are held in a `pending_edges` table that `audit` turns into relation suggestions and `repair` promotes once the registry maps them; `repair` stays strict and may abort on a legacy unmapped edge; optional enum aliases are stored canonical only (no raw value kept); the three unlisted rule changes below are approved. Human decision (2026-11-23, after Proof): the shipped registry declares `entity:person` requiring `role` and `organization`, and `entity:company` requiring `sector`, all `text`; every stored row already has them. The requester ruled the rest implementation detail. Frame took these defaults, each changeable in the registry later: `name` max 200 and `summary` max 1,000; unmapped edges are not regenerated (since R1 they are held in `pending_edges`, not skipped).

## Proof

Candidate: `c835acc27569005872af67ec0abe7449fc7ede4b` plus Build's uncommitted working tree on branch `proposal/registry-schema-v2` in `/Users/jasonbxu/Documents/GitHub/stock_ontology`. The coordinator gave `git diff c835acc | sha256sum` as prefix `be5d1fdddd251067`, with the test file at blob `4c28db2`. Since then, the only change is the witness (g) block appended to `tests/test_official_facets.py`. The full diff prefix is now `cf2a313444c59f19`. The diff excluding that file is `cd7c432c31873297`. I made no src/ change.

**Protected witness**

All tests are in the permanent owner `tests/test_official_facets.py`, under the `registry-schema-v2` and `R1` banner comments. Two human-approved test-only data corrections were applied earlier:
1. Witness entities conform to the shipped `entity:person` (`role`, `organization`) and `entity:company` (`sector`) declarations, through `_CONFORMING` in `_entity` and a `sector` facet on `_OMEGA`. Witness (a) now declares `entity:product` requiring `process_node`.
2. `sector` was added to the companies in `test_upsert_edge_refuses_edge_without_basis`, `test_ingest_regenerates_extraction_missing_required_view_type` and `test_ingest_drops_uncoercible_optional_facet_and_keeps_note`.

Build changed, as anticipated, the final stamp assertion of `test_writable_open_migrates_rows_and_stamps_older_registry_version` to `reg.schema_stamp()`.

- (a) An entity-type required facet comes from a registry edit. Test: `test_entity_type_required_facet_is_a_registry_edit_enforced_on_write`
  - Defect and boundary: specs were keyed by `node_type` only, and load required `facet_schema` to equal `vocab.py`. The boundary is registry JSON to `load_registry` to `upsert_node`.
  - Assertion: the shipped JSON, plus only `entity:product.process_node` (text, required), loads. A product without it is refused and nothing is stored. A product with it is stored, and so is a conforming company.
  - Proves: per-entity-type specs with no source edit.
  - Limit: one entity type and one text facet. It doesn't cover kind errors on subtype facets.
- (b1) Test: `test_upsert_edge_refuses_relation_the_registry_does_not_map`
  - Defect and boundary: `upsert_edge` only normalized the name. The boundary is the DB write.
  - Assertion: `FROBNICATES` is refused and 0 edges are stored.
  - Limit: `update_edge` is left to Build.
- (b2) Test: `test_ingest_skips_unmapped_edge_keeps_mapped_edge_and_note`
  - Defect and boundary: the pipeline wrote edges with `matched=False`. The boundary is the pipeline with a fake LLM, writing to the DB.
  - Assertion: there's no note error, the note is ingested, and the relations in `edges` are exactly `["ABOUT"]`.
  - It still holds under R1 unchanged, since it asserts only on `edges`. Pending storage is witnessed by (g).
- (c) Test: `test_load_registry_refuses_registry_without_facet_schema`
  - Assertion: the shipped JSON minus `facet_schema` raises `ValueError` naming it.
  - Limit: it covers the missing key only.
- (d1) Test: `test_upsert_node_refuses_optional_enum_outside_vocabulary`
  - Assertion: a view with `stance: "maybe"` is refused and 0 nodes are stored.
  - Limit: one enum.
- (d2) Test: `test_ingest_drops_optional_enum_outside_vocabulary_and_keeps_note`
  - Assertion: view `status: "maybe"` is dropped, `author` is kept, and the note is ingested. It uses `status` because the extraction model coerces `stance`.
  - Limit: repair isn't covered.
- (e) Test: `test_upsert_node_refuses_metadata_over_declared_max_length[name-200]` and `[summary-1000]`
  - Assertion: a value at the limit is stored, and limit+1 is refused.
  - Limit: it doesn't prove the limit is read from the registry rather than code.
- (f) Test: `test_schema_change_without_version_bump_migrates_and_restamps`
  - Assertion: a registry adding only optional `view.horizon`, with the same `version`, migrates a raw `target_price: "630"` to int 630, and the stamp differs from before.
  - Limit: it doesn't pin the stamp's format, and it doesn't check that an identical schema skips migration.
- (g1) Unmapped relations are held, suggested and promoted. Test: `test_unmapped_edge_is_held_pending_suggested_by_audit_and_promoted_by_repair`
  - Defect and boundary: after Build's first pass, an unmapped relation is skipped and only counted. It reaches neither `edges` nor any audit or human surface. The boundary is pipeline to DB, then the read-only audit, then registry JSON to repair.
  - Assertion, in order:
    - Ingest of a view with only a `FROBNICATES` edge has no note error and logs the note, with `edges` = 0 and `pending_edges` = 1.
    - A read-only open plus `run_ontology_audit` lists `FROBNICATES` in `unmapped_relations`, and the DB bytes are unchanged.
    - With a registry JSON that only adds a `FROBNICATES` relation (view to entity), `repair_ontology` leaves `edges` = [`FROBNICATES`] with `basis == "extracted"`, and `pending_edges` = 0.
  - Proves: the R1 recommendation loop end to end.
  - Limit: it doesn't check pending columns beyond count, cascade on endpoint deletion, or repair aborting on legacy unmapped edges.
- (g2) Test: `test_pending_edges_are_cleared_with_their_note`
  - Assertion: re-ingesting the changed note leaves `pending_edges` = 1, not 2. After the note is deleted and the pipeline rerun, `files_deleted == 1` and `pending_edges` = 0.
  - Proves: pending rows are cleared with their note.
  - Limit: the endpoint-node cascade is left to Build.
- Guardrails, passing now:
  - `test_undeclared_edge_facets_round_trip`
  - `test_shipped_fixture_ingest_matches_baseline_graph`
  - `test_read_only_open_of_old_or_unstamped_db_reads_without_writing`
  - `test_conforming_view_with_free_form_facets_round_trips`
- Protected paths: all tests and helpers named above in `tests/test_official_facets.py`, plus `tests/fixtures/typed_registry_baseline_graph.json` and `tests/fixtures/sample_data/`. Build may not change them without a separately approved test-only correction.
- Protected revision: blob `470b147f68653cee0426c2fd94509be4a4693112` (`git hash-object tests/test_official_facets.py`). The fixtures are unchanged from c835acc.

**Red evidence**

- `uv run pytest tests/test_official_facets.py -q` on the candidate gives 2 failed, 30 passed.
  - (g1) and (g2) both fail with `sqlite3.OperationalError: no such table: pending_edges`, raised after the ingest assertions pass (no note error, 0 edges). The pending store is missing.
  - All earlier witnesses (a) through (f) and all guardrails are GREEN.
- The table error stops (g1) before its audit step, so I probed that step separately. On the candidate, ingest gives `edges 0`, `unmapped_relations_skipped {'FROBNICATES': 1}`, and audit's unmapped names are `[]`. So the relation reaches no suggestion surface.
- Earlier RED for (a) through (f) was observed against a `git archive` export of c835acc. With this blob it gives 12 failed, 20 passed: the 9 primary witnesses, (g1), (g2), and Build's amended stamp test.
- Orchestrator check: `uv run pytest -q` → 2 failed (g1, g2), 376 passed.
- (g) has no proof until this command is observed GREEN after Build, with the witness blob unchanged.

**Supporting test plan**

- `pending_edges` schema (from_id, to_id, raw relation, facets, source_doc_id, created_at). Rows cascade when an endpoint node is deleted or merged. Build owner: `tests/test_db.py`. Catches orphaned pending rows.
- `delete_document_artifacts` and `_clear_prior_artifacts` clear pending rows for their doc only. Build owner: `tests/test_db.py` and `tests/test_pipeline.py`. Catches cross-note deletion.
- `IngestReport` counts pending (unmapped) relations by name. Build owner: `tests/test_pipeline.py`. Catches the count not matching pending rows.
- Audit merges `pending_edges` with `edges` for `unmapped_relations`, covering counts, signatures and samples, and `audit --sync` queues them. Build owner: `tests/test_registry_audit.py`. Also reassert `tests/test_relationships.py::test_write_side_normalization_oov_queueing_and_catalog_signatures` per the R1 invariant. Catches suggestions that lose pending data.
- Repair promotes through `upsert_edge`, including alias and inverse resolution that flips direction, and still-unmapped rows stay pending. It stays strict on legacy unmapped edges in `edges` and may abort, per the human decision. Build owner: `tests/test_repair.py`. Catches wrong direction or premature deletion.
- `update_edge` refuses an unmapped relation. Build owner: `tests/test_db.py`.
- From the earlier plan, carried forward:
  - `_facet_specs` entity-subtype merge, and the drift check reduced to the subtype minimum. Owner: `tests/test_vocab.py`.
  - The `test_vocab.py:430` refusal and `create_minimal_registry()` enforcement. Owner: `tests/test_vocab.py`.
  - Repair drops unknown optional enums, and optional enum aliases are stored canonical. Owner: `tests/test_repair.py`.
  - Over-length metadata triggers regeneration, and the limits are read from the registry. Owner: `tests/test_pipeline.py`.
  - Schema hash stability and inputs, and an identical schema skips migration. Owner: `tests/test_db.py`.
  - Integer-stamp assertions updated. Owners: `tests/test_db.py`, `tests/test_pipeline.py`, `tests/test_repair.py`.

## Build

Candidate: `c835acc + uncommitted working tree @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/registry-schema-v2). Identity: sha256 of "git diff c835acc" starts 39e68be0c92f36a4. Protected witness tests/test_official_facets.py is at blob 470b147f68653cee0426c2fd94509be4a4693112, unchanged by Build in this pass. tests/fixtures/ is unchanged from c835acc. Nothing committed. Untracked: .claude/launch.json and the ledger.`

### Files changed

**Registry data**
- `ontology_registry.json`
  - Adds `metadata_max_length` (`name` 200, `summary` 1000).
  - Adds `facet_schema.node["entity:person"]` requiring `role` and `organization`, and `facet_schema.node["entity:company"]` requiring `sector`, all `text` (the human's scope decision).

**Source**
- `src/stock_ontology/registry.py`
  - `facet_schema` and `metadata_max_length` are required fields.
  - Loading checks only the code minimum (`facet_schema_problems`) and refuses an enum facet that has no vocabulary.
  - `_facet_specs(node_type, entity_type)` layers `entity:<entity_type>` on `entity`. A layer key overrides the base. Only entity subtypes are layered.
  - New methods:
    - `schema_stamp()`: sha256 of the canonical JSON of `facet_vocabularies`, `facet_schema` and `metadata_max_length`.
    - `check_metadata`
    - `check_relation`
  - `drop_uncoercible_optional` gains a `kinds=` filter.
  - `create_minimal_registry()` carries the built-in limits.
- `src/stock_ontology/vocab.py`
  - `facet_schema_problems` replaces `facet_schema_differences`. It checks shape and kinds, node keys, that a layer does not redeclare `entity_type`, and that the subtype facets and edge `basis` are required enums.
  - `NODE_FACET_SCHEMA` and `EDGE_FACET_SCHEMA` are now only the built-in base schema.
  - Adds `METADATA_MAX_LENGTH`.
  - `coerce_facet_value` requires vocabulary membership for every enum. Its `required` parameter is removed.
- `src/stock_ontology/db/schema.py`: R1 adds the `pending_edges` table only, with indexes. Columns are id, from_id, to_id, raw relation, facets_json, source_doc_id, created_at. FK `ON DELETE CASCADE` on both endpoints.
- `src/stock_ontology/db/storage.py`
  - Earlier pass:
    - `upsert_node` calls `check_metadata`.
    - `upsert_edge` and `update_edge` call `check_relation`.
    - The stamp is `schema_stamp()`, and migration runs whenever the stamp is missing or differs.
  - R1:
    - `insert_pending_edge` and `delete_pending_edges`.
    - `list_pending_edges_with_endpoints`, which returns empty on an older read-only DB that lacks the table. `list_edges_with_endpoints` shares the same query and now also returns `created_at`.
    - `delete_document_artifacts` clears that note's pending rows.
    - `list_artifact_doc_ids` includes pending rows.
- `src/stock_ontology/pipeline.py`
  - Over-length metadata goes through the existing regeneration loop.
  - R1: an unmapped extracted edge goes to `pending_edges` with its raw relation, and its facets get the same processing as a mapped edge (`basis: extracted`, sentiment normalized, uncoercible optional facets dropped). The note is kept.
  - It is counted by name in `IngestReport.unmapped_relations_pending`, which renames the earlier `unmapped_relations_skipped`. Only the kept extraction attempt is counted.
  - Pending rows are cleared with the note through `_clear_prior_artifacts` and `delete_document_artifacts`.
- `src/stock_ontology/audit.py`: R1 adds read-only reads of `pending_edges`.
  - Pending rows that are still unmapped add to `unmapped_relations` counts, signatures and samples, so `audit --sync` queues them.
  - A new `AuditSummary.pending_edges` counts them. `total_edges` and `unmapped_edges` still count only `edges`.
  - A pending row the registry already maps is left for repair.
- `src/stock_ontology/repair.py`
  - Earlier pass: unknown optional enums on nodes and edges are dropped.
  - R1: `_promote_pending_edges` runs after `_canonicalize_relations`. Each pending row whose relation now resolves goes through `canonicalize_edge` (alias, inverse direction and alias facets) and then `upsert_edge`, and is then deleted from pending.
  - Promotions are counted in `RepairReport.pending_edges_promoted`, which is part of `total_changes`. Unmapped rows stay pending.
  - Legacy unmapped rows in `edges` are untouched, so a run that must rewrite one aborts and rolls back.

**Docs**
- `README.md`
  - Official Registry paragraph updated.
  - Relation-vocabulary constraint: unknown relations are held in pending, suggested by audit and promoted by repair. Its Why now cites registry-schema-v2 R1, and its guard list adds witness (g1).
  - Typed-registry constraint covers over-length text, out-of-vocabulary optional enums and pending edges.
  - The "raw strings" constraint now says `upsert_edge` and `update_edge` refuse unmapped relations, and tests seed legacy rows through `tests/test_db.py::insert_legacy_edge`.
  - New schema-stamp constraint entry.
- `docs/architecture/ontology.md`, `storage.md`, `governance.md`: updated per Frame's Invariants changed. They now cover the required `facet_schema`, entity-type layers and the shipped person and company declarations, the code minimum, enum membership, metadata limits, `check_relation`, the `pending_edges` table and methods, the hash stamp, audit reading pending, repair promotion and strictness, and repair dropping unknown optional enums.

**Tests (Build-owned)**
- `tests/test_vocab.py`
  - The `:430` schema-less test is replaced by load refusal plus a check that the built-in registry still enforces.
  - Drift checks are split into "code minimum refused" and "beyond the minimum is the registry's call".
  - New coverage: layer merge and override, and no leak to other node types; enum without a vocabulary is refused; optional enum is stored as its member or refused; metadata-limit validation; the shipped person and company declarations.
- `tests/test_db.py`
  - Hash-stamp tests: skip when matching, migrate when different, stable across key order and `version`, changes with each input.
  - `update_edge` refuses an unmapped relation.
  - Shared `insert_legacy_edge` helper.
  - R1: pending schema and cascade on delete and merge; `delete_document_artifacts` clears only its doc's pending rows; read-only DB without the table.
  - `_typed_db` companies get `sector`.
- `tests/test_pipeline.py`
  - Pending count is per kept extraction and matches the pending rows (raw relation, doc id, basis).
  - Over-length name regenerates under a registry-declared limit but not under the shipped one.
  - Over-length summary hits the cap.
  - R1: re-ingesting one note clears only its own pending rows.
  - Fixture companies get `sector`.
- `tests/test_repair.py`
  - Unknown optional enum drop.
  - R1: promotion through an inverse alias flips direction, and an unmapped row stays pending; a legacy unmapped edge that must be rewritten aborts and rolls back.
  - Stamp assertion updated.
- `tests/test_registry_audit.py`
  - R1: audit merges pending rows into counts, signatures and samples, and skips mapped pending rows; `audit` CLI sync queues relations held only in pending.
  - Legacy PRODUCES is seeded by raw SQL.
- `tests/test_relationships.py`: `test_write_side_normalization_oov_queueing_and_catalog_signatures` is reasserted per R1. PARTNERS_WITH is held in `pending_edges`, counted, queued by audit and sync, and pending in suggestions. Legacy unmapped seeds use raw SQL.
- `tests/test_canonical_vocabulary.py`: repair drops an unknown optional enum instead of keeping it, and the seed relation is now mapped.
- `tests/test_search_ontology_options.py`, `tests/test_web.py`: legacy unmapped edges are seeded via `insert_legacy_edge`.
- `tests/test_agent.py`, `tests/test_web.py`, `tests/test_web_navigation.py`: stance assertions are canonical (`bullish`, `bearish`, `neutral`), per the R1 approval.

### Unit evidence

- Earlier pass, RED against c835acc source (`src/` and `ontology_registry.json` stashed): 25 failed, 10 passed. The 10 that passed are refusals the old equality check already made.
- R1, RED against c835acc source: 10 failed.
- The pre-R1 candidate RED for pending storage is Proof's (g1) and (g2) observation, so it was not repeated here.
- These tests were written after the implementation, not test-first. RED was observed by reverting the source.
- GREEN, both lists together: 44 passed.

### Green evidence

- Decisive witness: `uv run pytest tests/test_official_facets.py -v` at blob 470b147 gave 32 passed, including (g1), (g2) and the baseline-graph guardrail.
- Gate: `uv run pytest -q` gave 386 passed.
- Gate: `uv run ruff check` on the changed src and test files found 2 errors, both `raise-vanilla-args` in `tests/test_web.py` at the `EmbeddingAndAgentDownWebLLM` fakes. They exist identically at c835acc, so none are new.
- The live `ontology.db`, `.env` and LLM providers were never touched. No ingest or repair was run on the live DB.

### Intervention record

- None. The repository has no intervention ledger, and this change has no user-facing outcome to measure.

### Deviations

- Protected witness: Build's only edit to `tests/test_official_facets.py` was the anticipated final stamp assertion in `test_writable_open_migrates_rows_and_stamps_older_registry_version` (`== reg.schema_stamp()`). Every later blob (4c28db2, then 470b147) came from Proof's human-approved test-only corrections. Build did not edit the file in this pass.
- None otherwise. All paths are within Frame's Allowed scope, with `db/schema.py` limited to `pending_edges` and `audit.py` limited to reading it. The R1 test and README changes are those listed in Invariants changed.
- Residual notes for Audit:
  1. The extraction prompt (`llm/prompts.py:31`) still asks for `role`, `organization` and `sector` only "when discernible", so live ingest may regenerate or fail notes that omit them. This file is out of scope.
  2. `cli.py` does not print `IngestReport.unmapped_relations_pending`. Audit is the human surface for those relations.
  3. Pending rows on a merge loser are deleted with it (FK cascade), as Frame specifies, rather than repointed to the survivor.
  4. Repair aborts on a legacy unmapped edge in `edges` that it must rewrite, as the human accepted. Frame measured 0 such edges in the live DB.

## Audit

Candidate: `c835acc + uncommitted working tree @ /Users/jasonbxu/Documents/GitHub/stock_ontology (branch proposal/registry-schema-v2)`. I rechecked the identity: `git diff c835acc | shasum -a 256` gives prefix 39e68be0c92f36a4, `git hash-object tests/test_official_facets.py` gives 470b147f68653cee0426c2fd94509be4a4693112, and `git diff c835acc -- tests/fixtures` is empty.

Independence: fresh-context. This context did not frame, prove or build the candidate. It wrote the superseded R1 audit (REVISE) of the earlier candidate be5d1fdddd251067, so it came to this re-audit already knowing that candidate's diff and its scope findings.

R1 answer check: R1 cited two things. First, scope was EXPANDED by unlisted changes to c835acc `README.md:138`, `README.md:147` and the stance assertions. Frame's `Invariants changed` now lists all three, each "Approved by the human in R1", and the diff matches them. Second, unmapped relations reached no human surface. That is answered with code and witnesses: `pending_edges` in `src/stock_ontology/db/schema.py`, reads in `src/stock_ontology/audit.py`, `_promote_pending_edges` in `src/stock_ontology/repair.py`, witnesses (g1) and (g2), and the reasserted queueing in `tests/test_relationships.py::test_write_side_normalization_oov_queueing_and_catalog_signatures`. The R1 entry is answered by changed evidence, not restated.

Primary-claim verdict: PROVED.
- Evidence:
  - `uv run pytest tests/test_official_facets.py -q` on the candidate: 32 passed.
  - I re-ran RED myself on a `git archive c835acc` export with the 470b147 file overlaid: 12 failed, 20 passed. That is witnesses (a), (b1), (b2), (c), (d1), (d2), (e)[name], (e)[summary], (f), (g1) and (g2), plus the anticipated stamp test. Proof's earlier RED on the pre-R1 candidate (g1 and g2 failing with `no such table: pending_edges`) is consistent with that.
  - `diff` of the retrievable blob 4c28db2 against 470b147 deletes 0 lines and appends only the R1 block. So witnesses (a) to (f) and their helpers are byte-identical to the version accepted as protected in the prior round.
  - Proof's stated limits are covered by Build-owned tests that pass:
    - `tests/test_pipeline.py::test_over_length_name_regenerates_under_the_registry_declared_limit` shows the limits are read from the registry.
    - `tests/test_db.py::test_update_edge_refuses_relation_the_registry_does_not_map`.
    - `test_schema_stamp_is_stable_for_identical_content_and_key_order`, `test_schema_stamp_changes_with_each_input` and `test_writable_open_stamps_fresh_db_skips_matching_stamp_and_migrates_any_other` cover the hash inputs and the skip when the stamp matches.
    - `tests/test_db.py::test_pending_edges_table_holds_raw_relation_and_cascades_with_endpoints` covers the cascade.
    - `tests/test_repair.py::test_repair_promotes_pending_edge_through_inverse_alias_and_keeps_unmapped_ones` covers promotion direction and rows that stay pending.
    - `tests/test_registry_audit.py::test_audit_merges_pending_edges_into_unmapped_relation_suggestions` and `test_cli_audit_sync_queues_relations_held_only_in_pending_edges` cover audit and sync.
  - Code read: `check_metadata` reads `self.metadata_max_length`. `upsert_edge` and `update_edge` call `check_relation`. The pipeline writes rows with `canon.matched` False to `insert_pending_edge`. Promotion goes through `canonicalize_edge` and then `upsert_edge`, and runs before `_delete_duplicate_edges`.
- Limit:
  - Component tests with fake LLMs and temp DBs only.
  - (a) covers one entity type and one `text` facet.
  - Blob 470b147 is not in the git object store (`git cat-file -t` fails). The working tree is its only copy, so its identity rests on the hash match plus the append-only diff against 4c28db2.
  - The Build-owned supporting tests were written after the implementation and shown RED by reverting the source.

Guardrail verdicts:
- Fixture ingest produces the c835acc graph: PROVED. Evidence: `test_shipped_fixture_ingest_matches_baseline_graph` passes against unchanged `tests/fixtures/`, with the shipped `entity:person` and `entity:company` declarations active. Limit: fixture notes only.
- Read-only opens of an older-stamped or unstamped DB read without writing: PROVED.
  - Evidence: `test_read_only_open_of_old_or_unstamped_db_reads_without_writing` passes. So does `tests/test_db.py::test_read_only_db_without_pending_table_lists_no_pending_edges`: `list_pending_edges_with_endpoints` checks `sqlite_master` before reading. (g1) also asserts the DB bytes are unchanged across a read-only audit. Read-only opens set `query_only` and skip `_init_schema`.
  - Limit: tested at the DB and audit layer, not on each of the agent, web and search entry points. None of those reads `pending_edges`.
- Undeclared facets round-trip on nodes and edges: PROVED. Evidence: `test_conforming_view_with_free_form_facets_round_trips` and `test_undeclared_edge_facets_round_trip` pass. Limit: one node type and one edge relation.

Scope and duty verdict: scope HELD; duties HELD.
- Evidence:
  - All 24 changed paths are in Frame's Include list. `db/schema.py` adds only the `pending_edges` table and its 3 indexes. `audit.py` only adds read-only reads of `pending_edges` and `AuditSummary.pending_edges`. There is no new dependency, no money kind and no per-relation spec, and web and agent read paths are unchanged.
  - Every amended README constraint matches a Frame `Invariants changed` entry: `README.md:31`, `:144`, c835acc `:138`, c835acc `:147`. So does every amended test assertion: the stance assertions, the test_relationships guard, the test_vocab `:430` replacement and the governance repair rule behind `tests/test_canonical_vocabulary.py`. The stamp-assertion edits were assigned to Build by Proof's test plan, and the other test edits are seed-only (`sector`, `insert_legacy_edge`).
  - The candidate reuses what Frame named (`_facet_specs`, `check_facets`, `drop_uncoercible_optional`, `migrate_facets`, `CanonicalEdgeResult.matched`, `resolve_relation`, the regeneration loop).
  - Constraint-capture duty: the new README schema-stamp entry has a `**Why:**` and a `**Guarded by:**` naming existing, passing tests. The relation-vocabulary and raw-strings constraints were rewritten with guard lists that name existing tests, including (g1) and `tests/test_db.py::test_update_edge_refuses_relation_the_registry_does_not_map`.
  - Every supporting obligation in Frame has code and a passing test.
- Limit: Frame's `Decisions required` still says, from before R1, "unmapped edges are skipped and counted". That's stale ledger wording, which Audit does not edit. The candidate follows the R1 pending design that Frame's final claim and obligations state.

Test homes:
- `tests/test_official_facets.py`: Proof's permanent owner, plus Build's anticipated stamp line.
- `tests/test_vocab.py`: Proof-named owner for subtype merge, the code-minimum drift check, the schema-less refusal and enum membership.
- `tests/test_db.py`: Proof-named owner for the hash stamp, the `update_edge` refusal, the `pending_edges` schema and cascade, and doc-scoped pending deletion, plus the shared `insert_legacy_edge` helper.
- `tests/test_pipeline.py`: Proof-named owner for the pending count, metadata regeneration, per-note pending clearing and the stamp.
- `tests/test_repair.py`: Proof-named owner for the optional-enum drop, promotion and strict abort.
- `tests/test_registry_audit.py`: Proof-named owner for audit merging pending rows and the CLI sync.
- `tests/test_relationships.py`: existing owner of the README:138 guard, reasserted per the R1 invariant.
- `tests/test_canonical_vocabulary.py`: existing owner of the repair-enum test, retargeted to the listed governance invariant.
- `tests/test_agent.py`, `tests/test_web.py` and `tests/test_web_navigation.py`: existing owners of the stance assertions, changed per the R1 invariant. `tests/test_web.py` also gets seed-only legacy-edge routing.
- `tests/test_search_ontology_options.py`: seed-only.

Full gates: PASS.
- `uv run pytest -q`: 386 passed in 7.94s.
- `uv run pytest tests/test_official_facets.py -q`: 32 passed.
- `uv run pytest -q -k "pending or promot or abort or rolls_back"`: 12 passed.
- RED recheck on a c835acc export with blob 470b147: 12 failed, 20 passed.
- `uv run ruff check` on the changed `.py` files (not a required gate under AGENTS.md): 2 `raise-vanilla-args` in `tests/test_web.py`, identical at c835acc.
- Limit: offline fakes only. No ingest or repair was run on the live `ontology.db`. A read-only query of it during the prior audit found canonical stances only and no stamp.

Residual risks:
- The extraction prompt `src/stock_ontology/llm/prompts.py:31` still asks for person `role`/`organization` "when discernible" and for company `sector` only as a useful facet. Live ingest may use up all 3 extraction attempts and then fail notes the LLM under-fills. The file is outside allowed scope.
- Repair stays one strict transaction, as the human accepted. One legacy row breaks the whole run if it carries an unmapped relation that must be rewritten (proved by `test_repair_stays_strict_on_a_legacy_unmapped_edge_it_must_rewrite`), or if it is an entity missing a newly required facet or has over-length text and gets re-upserted through `_canonicalize_facets` or `_merge_cluster`. Frame's measurements suggest the live DB has no such rows today.
- Pending rows on a merge loser are deleted by the FK cascade, not repointed to the survivor. That loses the suggestion evidence for that pair.
- `cli.py` does not print `IngestReport.unmapped_relations_pending`. `audit` is the only human surface.
- `_promote_pending_edges` assigns fresh `uuid` edge ids, so a promotion is not reproducible by id across runs. It is idempotent by content because the pending row is deleted.
- Protected blob 470b147 exists only in the working tree. If that file is lost before commit, the protected revision can't be retrieved.

Recommendation: ACCEPT
Packet: none for the candidate. Commit, merge, and any ingest or repair on the live `ontology.db` stay human-owned. Before or at commit, the human may want to store the witness blob (it is in no git object today) and correct Frame's stale "skipped and counted" wording.

## Revisions

### R1 — 2026-11-23 — scope: three rule changes not listed under Invariants changed; new relations no longer reach the suggestion queue
- Verdict: REVISE — scope EXPANDED: Build changed c835acc `README.md:138` and `:147` and the stance assertions in `tests/test_agent.py`, `tests/test_web.py`, `tests/test_web_navigation.py`, none listed in Frame's `Invariants changed`; residual risk that skipped relations reach no human surface.
- Changed: `docs/proposals/registry-schema-v2.md` Frame — the three changes listed with human approval; human added `pending_edges` so unmapped relations become suggestions and are promoted by `repair`; repair stays strict; aliases canonical only. Proof, Build and Audit rerun against it.
- Re-audit: ACCEPT — R1 answered by listed invariants and the `pending_edges` loop; 386 passed; candidate `c835acc + working tree, git diff c835acc sha256 39e68be0c92f36a4, witness blob 470b147`

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
