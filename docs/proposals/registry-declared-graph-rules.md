---
proposal_id: "registry-declared-graph-rules"
state: FRAMED
witness: independent
candidate: "5166148 @ worktree pipeline-correction-api-47e1d2"
---

# Proposal: Registry-declared graph rules

## Proposal

### Intent

Each ontology rule should have a single source. Domain graph rules that are hardcoded in Python move into `ontology_registry.json` as data, so the write paths and `tests/test_ontology_mutations.py` read each rule from the registry and no rule has two sources.

### Tentative primary claim

Every domain graph rule that a write path enforces, and that `tests/test_ontology_mutations.py` checks, is read from the registry, so changing that rule in `ontology_registry.json` changes what the write paths accept and what the test checks, with no second copy in Python to update.

### Why now

The `ontology-mutation-suite` proposal (accepted 2026-11-26) added a test suite that reads content rules from the registry and structure rules from SQLite, with no copy of either. The requester agreed then that moving the remaining code-held domain rules into the registry belongs in a later, separate proposal. This is that proposal.

### Known constraints

- The project is in beta, so a registry change, and the publish and apply it needs, are acceptable.
- Adding a registry field changes the registry revision, so the deployed database needs a registry publish and apply on the server. Only the human runs those. No stage runs them.
- Database structure rules (foreign keys, unique `doc_id`) stay in `src/stock_ontology/db/schema.py`.
- Job-behavior rules, such as "a refused job changes nothing", stay in the test.

### Non-goals

- Moving database structure rules into the registry.
- Moving job-behavior rules out of `tests/test_ontology_mutations.py`.

### Open choices

- Which rules move. Candidates the requester named or a survey of `src/stock_ontology/` turned up:
  - Per-relation uniqueness or cardinality. Today one edge per (from, relation, to, source note) is held by the edge write and by `repair`, and the mutation suite restates the same key.
  - Which `basis` values each write path may set: `extracted` for ingestion and note corrections, `synthesized` for consensus views, and the rule `repair` uses to backfill a missing `basis`.
  - One active consensus view per company, with the prior one superseded and linked.
  - An entity-to-theme `RELATES_TO` edge becoming `EXPOSED_TO`.
  - The typed copy of the facet vocabularies and the required facets code depends on, which code keeps beside the registry and checks against it on load.
  - Relation names that read paths, such as research views, match by name. These are read rules, not write rules, and may be out.
- Whether "uniqueness or cardinality" means only declaring rules code already enforces, or also adding new ones the registry could now express.
- What happens when a published registry declares a rule the live graph already breaks: refuse the apply, fix the graph through `repair`, or apply and report.
- Sequence: one proposal for every rule that moves, or one rule group at a time, each with its own publish and apply.

## Frame

Candidate: `5166148 @ worktree pipeline-correction-api-47e1d2 (branch claude/charming-bohr-6bc4a2, main c2911eb plus this ledger)`

### Verified reality
- `uv run pytest -q -x -p no:cacheprovider` — proves the suites judging this change were green before it started: 630 passed in 24.13s; limit: offline fakes only, nothing against the deployed database.
- `src/stock_ontology/db/storage.py:358` `OntologyDB.upsert_edge` — proves the edge write keeps one edge per (from_id, to_id, normalized relation, source_doc_id) and merges facets into an existing one; limit: the key is written in SQL, not read from the registry.
- `src/stock_ontology/repair.py:396` `_delete_duplicate_edges` — proves `repair` holds the same key a second time in Python; limit: none beyond that.
- `tests/test_ontology_mutations.py` `ontology_problems` (duplicate canonical edge check) — proves the mutation suite restates the same key a third time, after `canonicalize_edge`; limit: this is the one restated rule found in the suite, against `README.md:233`, which says the suite never restates a rule.
- `src/stock_ontology/registry.py:743` `check_note_edge` — proves note corrections refuse a duplicate by (from_id, to_id, relation) within one note, a fourth form of the same key, and default a new correction edge to `basis: extracted`; limit: the caller supplies the note's triples.
- `src/stock_ontology/db/schema.py:39` `edges` — proves SQLite has no UNIQUE constraint on the edge key, so uniqueness is a code rule, not a structure rule; limit: `doc_id` UNIQUE at `schema.py:68` is a structure rule and stays.
- `src/stock_ontology/pipeline.py:690` — proves ingestion sets `basis: extracted` in code and ignores the LLM's value; limit: none.
- `src/stock_ontology/db/storage.py:597-633` `upsert_consensus_view` — proves the consensus write sets `basis: synthesized`, keeps one active consensus view per company by marking the prior `superseded`, and links it with `ABOUT` (`consensus_link`), `SUPERSEDES`, and `SUPPORTS`/`CONTRADICTS` (`consensus_evidence`); limit: relation names and facet values are literals in code.
- `src/stock_ontology/repair.py:226` `_backfill_edge_basis` — proves `repair` derives a missing `basis` from whether an end is a consensus view; limit: a migration rule for old rows, not a write-path rule.
- `src/stock_ontology/registry.py:701` `canonicalize_edge` — proves an entity-to-theme `RELATES_TO` is promoted to `EXPOSED_TO` by code; limit: no registry field expresses it today.
- `src/stock_ontology/registry.py:88` `RelationSpec` — proves a relation declares name, description, endpoint types, aliases, inverse aliases, alias facets, `symmetric`, and `traversal_group`, with no uniqueness, cardinality, allowed-basis, or promotion field; limit: `facet_schema.relation` (`ontology_registry.json:575`) already declares per-relation facets, a place a per-relation rule could live.
- `src/stock_ontology/registry.py:358` `OntologyRegistry.revision()` — proves any new field in `official_definitions()` changes the revision, so the deployed database needs a publish and apply; limit: none.
- `src/stock_ontology/vocab.py:1-30`, `vocab.py:484-485`, `README.md:31` — prove code keeps a typed copy of the facet vocabularies (`Literal` types used by extraction models, the prompt, and the agent schema across 15 importing modules) and the required-facet minimum, checked against the registry on load; limit: removing the copy would remove typed models, which is more than a data move.
- `src/stock_ontology/registry.py:1088` `create_minimal_registry` — proves code holds a built-in starter registry with its own relation list, used when no registry file exists (`services/registry.py:91`, `db/storage.py:103`); limit: the shipped JSON is a superset, not checked against it.
- `pipeline.py:733`, `web/research/views.py:529,564,593,700` — prove read paths match relation names (`AUTHORED_BY`, `EXPOSED_TO`, `ABOUT`, `SUPPORTS`, `CONTRADICTS`) as literals; limit: read rules, not write rules.
- `README.md:161` — proves a current invariant: "Set edge `basis` in code at each write", guarded by `tests/test_pipeline.py::test_pipeline_sets_edge_basis_by_code_not_by_llm` and two `test_web_research.py` tests; limit: it governs who sets basis (code, not the LLM), not where the allowed value is declared.

### Final primary claim
- BLOCKED pending decisions 1 to 4 below. Once they're made: each moved rule is declared once in `ontology_registry.json`, the write paths and `tests/test_ontology_mutations.py` read it through `OntologyRegistry`, and changing that declaration in a test registry changes what the write paths accept and what the suite checks, with no Python copy left to update.

### Routing
- Witness: BLOCKED pending decisions (expected `independent`).
- Why: the change moves rules that decide which rows the edge, consensus, correction, and repair writes keep in `ontology.db`, which is stored user data.
- Human-owned irreversible action: merging to `main`, deploying, then a registry publish and apply on the server so the deployed `ontology.db` adopts the new revision. No stage runs them.

### Decisive witness
- Layer: BLOCKED pending decisions (expected: offline pytest against a test registry).
- Permanent owner: BLOCKED (expected `tests/test_ontology_mutations.py`, plus the existing `tests/test_official_facets.py` and `tests/test_repair.py`).
- Witness: BLOCKED (expected: a test registry that changes each moved rule makes the write path and `assert_ontology_invariants` change verdict together, and `grep` finds no Python copy of the moved rule).

### Guardrail claims
- The shipped registry, published and applied, leaves every existing case in `tests/test_ontology_mutations.py` and the rest of the 630-test suite passing, so moving a rule changes no write result on today's data.
- A registry that leaves a moved rule undeclared, or declares it malformed, fails `load_registry` with a message that names the rule, the way a missing `facet_schema` does today.
- Ingestion still never takes `basis` from the LLM (`README.md:161`'s reason stays true).

### Supporting obligations
- One registry field per moved rule, validated on load in `OntologyRegistry` like `facet_schema` and `metadata_max_length`, with an accessor the write paths and the suite call.
- Ship the declarations in `ontology_registry.json` and `create_minimal_registry`, so a database opened without a registry file enforces the same rules.
- Replace each literal at the cited write sites with the accessor; replace the restated key in `ontology_problems` with it.
- Unit-test candidates: load refuses a missing or malformed declaration; a test registry that changes the edge key (or allowed basis) changes `upsert_edge` (or the ingest and consensus writes) and the suite's verdict together.

### Allowed scope
- Reuse: `OntologyRegistry` load-time validation (`facet_schema_problems`, `metadata_max_length` validator), the `facet_schema.relation` section for per-relation rules, and `tests/test_ontology_mutations.py` as the permanent owner.
- Cheaper alternative: one shared Python constant for the edge key, called by `upsert_edge`, `repair`, and the suite. It removes the duplicate copies with no registry change and no publish, but the rule would still live in code, so the Proposal's "into `ontology_registry.json` as data" needs more. Taking it would be a change to the Proposal.
- Include: BLOCKED until decisions are made; at most the rules chosen in decision 1, their registry fields, their write-site reads, and the suite's reads.
- Exclude/protect: `src/stock_ontology/db/schema.py` structure rules (foreign keys, unique `doc_id`); job-behavior checks in the suite (`_stored_state`, refused-job cases); read-path relation-name matching unless decision 1 includes it; the deployed database and server.

### Invariants changed
- `README.md:161` — today: set edge `basis` in code at each write (`extracted` in `IngestionPipeline`, `synthesized` in `OntologyDB.upsert_consensus_view`); after, if decision 1 moves basis: each write path sets the `basis` the registry declares for it, still never from the LLM. The Proposal names this rule, so the override is intended.
- `README.md:31` — today: `vocab.py`'s vocabularies are a checked typed copy of the registry's; after: unchanged unless decision 1 removes that copy.
- `README.md:233` — today: the suite never restates a rule; after: unchanged, and the edge-key restatement in `ontology_problems` is removed so the suite meets it.

### Decisions required
- 1. Which rules move. Options: (a) only the rules with more than one copy today, the edge uniqueness key and the `basis` each write path sets. This is the cheapest option that meets the claim. (b) Also the consensus rules (one active view per company, supersede, and which relations and facets link it). (c) Also the `RELATES_TO` to `EXPOSED_TO` promotion. (d) Also the `vocab.py` typed copy and `create_minimal_registry`'s relation list. (e) Also the relation names read paths match on. Each step adds registry fields that a maintainer could then edit, and each can change which rows the graph keeps.
- 2. Cardinality: declare only rules code already enforces (the edge key), or also new per-relation limits, such as one employer per person, that would start refusing writes the graph accepts today.
- 3. What a publish and apply does when the live graph already breaks a newly declared rule: refuse the apply, have `repair` fix the graph first, or apply and report the rows that break it.
- 4. Sequence: one proposal, one publish and one apply for everything chosen in decision 1, or one rule group at a time, each with its own publish and apply.

## Proof

<!-- Replaced only by proposal-prove, or by the orchestrator with the builder-route
deferred-witness status. Reference native witness path, exact command, concise RED
result, and candidate identity. -->

## Build

<!-- Replaced only by proposal-build. Reference changed paths, protected witnesses,
exact GREEN command(s), concise result, candidate identity, and deviations. -->

## Audit

<!-- Replaced only by proposal-audit, and only after its outgoing verdict has been
appended to Revisions. Record primary/guardrail and scope/duty verdicts,
deterministic gate references, residual risks, and ACCEPT/REVISE/REJECT. -->

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
