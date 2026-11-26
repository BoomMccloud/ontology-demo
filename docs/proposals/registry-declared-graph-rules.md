---
proposal_id: "registry-declared-graph-rules"
state: PROPOSAL
witness: builder
candidate: "unassigned"
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

<!-- Replaced only by proposal-frame. Include verified reality; one primary claim;
guardrail claims; supporting obligations; allowed scope with the reuse it extends and
the cheaper alternative it rejected; routing; witness owner; invariants changed;
blocking decisions. -->

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
