---
proposal_id: "registry-declared-graph-rules"
state: FRAMED
witness: independent
candidate: "12e6a49 @ worktree pipeline-correction-api-47e1d2"
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

Candidate: `12e6a49 @ worktree pipeline-correction-api-47e1d2 (branch claude/charming-bohr-6bc4a2, main c2911eb plus this ledger)`

### Verified reality
- Requester decision (2026-11-26): move only the edge uniqueness key and the `basis` each write path sets. This settles the earlier decisions 1 (option a), 2 (declare only what code already enforces, no new limits), and 4 (one rule group, so one publish and apply). Decision 3 is not material for this scope: the shipped declarations match what the code enforces today, and `src/stock_ontology/repair.py:92` `validate_rollout` already refuses an apply whose graph breaks the proposed registry, so reusing it is the cheapest option.
- `uv run pytest -q -x -p no:cacheprovider` — proves the suites judging this change were green before it started: 630 passed in 24.13s; limit: offline fakes only.
- `src/stock_ontology/db/storage.py:358` `upsert_edge`, `src/stock_ontology/repair.py:396` `_delete_duplicate_edges`, `src/stock_ontology/registry.py:743` `check_note_edge` (note-scoped triples from `services/corrections.py:90`), and `tests/test_ontology_mutations.py` `ontology_problems` — prove the edge key (from, to, relation, source note) is written four times; limit: none.
- `src/stock_ontology/db/storage.py:487` `delete_document_artifacts` — proves a note's edges are deleted by `source_doc_id`. A key without `source_doc_id` would merge two notes' edges into one row, and deleting either note would then delete the edge the other note still supports. Note corrections check duplicates only among the note's own edges, so they assume the same thing. limit: this is the only safe-variation analysis; no other key field exists on `edges` (`schema.py:39`: `id`, `facets_json`, `created_at` are not identity).
- `src/stock_ontology/pipeline.py:690`, `src/stock_ontology/db/storage.py:621`, `src/stock_ontology/registry.py:766`, `src/stock_ontology/repair.py:226` — prove `basis` is set as a literal by ingestion (`extracted`), consensus (`synthesized`), corrections (`extracted`), and the repair backfill (both); limit: none.
- `src/stock_ontology/vocab.py:240` `EDGE_BASIS` and `vocab.py:358` `is_synthesized_edge`, read at `web/research/views.py:528,563,693`, `db/storage.py:1691,1718`, `services/corrections.py:38` — prove the basis vocabulary is closed to `extracted|synthesized` in code's typed copy, and readers hide consensus evidence by comparing to the literal `synthesized`. A registry that mapped consensus to `extracted`, or ingestion to `synthesized`, would put consensus views on theme pages or hide real evidence, the bug `README.md:162` records. limit: these readers are out of scope.
- `src/stock_ontology/vocab.py:484` `REQUIRED_EDGE_FACETS`, `vocab.py:505` `facet_schema_problems`, `README.md:31` — prove the accepted pattern for a rule code depends on: the registry declares it, and code refuses on load a registry that does not declare the value code depends on; limit: under that pattern code still holds the required value.
- `src/stock_ontology/registry.py:358` `revision()` — proves new fields in `official_definitions()` change the revision, so the deployed database needs a publish and apply; limit: none.

### Final primary claim
- BLOCKED pending decision 1 below. Neither chosen rule has a value other than today's that the code can accept safely, so a registry field for either one is a declaration the code pins on load (the `README.md:31` pattern), not a rule a maintainer can change.

### Routing
- Witness: BLOCKED pending decisions (expected `independent`).
- Why: the change rewrites how the edge, consensus, correction, and repair writes decide which rows `ontology.db` keeps, which is stored user data.
- Human-owned irreversible action: merging to `main`, deploying, then a registry publish and apply on the server. No stage runs them.

### Decisive witness
- Layer: BLOCKED pending decisions (expected: offline pytest).
- Permanent owner: BLOCKED (expected `tests/test_ontology_mutations.py`, with `tests/test_official_facets.py` for load refusal).
- Witness: BLOCKED.

### Guardrail claims
- The shipped registry leaves every existing case in the 630-test suite passing, so no write result changes on today's data.
- Ingestion still never takes `basis` from the LLM, and theme readers still skip consensus evidence (`README.md:161-163`).

### Supporting obligations
- Under option (a) of decision 1: `edge_identity` and `edge_basis` (per write path: ingest, correction, consensus) in `OntologyRegistry`, shipped in `ontology_registry.json` and `create_minimal_registry`; load refuses a value other than the one code depends on, naming it; every write site and `ontology_problems` read the accessor; unit tests for load refusal.
- Under option (b): one constant for the key and one per-write-path basis map in Python, read by the same sites and the suite; no registry change, no revision change, no publish.

### Allowed scope
- Reuse: the `facet_schema_problems` load-check pattern (`vocab.py:505`) for (a); `vocab.py` constants for (b); `tests/test_ontology_mutations.py` as owner for both.
- Cheaper alternative: option (b) is cheaper and gives the same "one copy in code reads" result for these two rules, but it keeps the rules in Python, so it changes the Proposal's "into `ontology_registry.json` as data". Frame cannot take it without the requester.
- Include: BLOCKED until decision 1.
- Exclude/protect: `src/stock_ontology/db/schema.py` structure rules; job-behavior checks in the suite; readers that call `is_synthesized_edge`; the `vocab.py` typed vocabulary; the deployed database.

### Invariants changed
- `README.md:161` — today: set edge `basis` in code at each write; after (a): each write sets the `basis` the registry declares for it, which load pins to today's values, never from the LLM; after (b): each write sets the `basis` from one shared map in code.
- `README.md:233` — today: the suite never restates a rule; after: unchanged, and the edge-key restatement in `ontology_problems` is removed so the suite meets it.

### Decisions required
- 1. How to give the key and `basis` one source, given neither can safely vary. (a) Declare both in `ontology_registry.json`, with load refusing any value other than today's (the pattern `facet_schema` uses for required facets). The registry states the rule, but code still holds the required value to check it, and the change needs a publish and apply. (b) Keep both in Python as one shared constant each, read by every write path and the suite. No registry change and no publish. This amends the Proposal, because the rules stay in code. (c) Stop here and abandon, because neither form gives a maintainer a rule they can change.

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
