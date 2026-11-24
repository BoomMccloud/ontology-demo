---
proposal_id: "node-typeahead"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Typeahead instead of the whole graph in edit pages

## Proposal

### Intent

When note actions are on, the note reader loads every node (or every entity) and renders each one as a choice in the relationship and entity editors. The registry record edit page puts `db.list_all_nodes()` into its page JSON. Page size, query time and template work all grow with the graph on every view, even when the user never opens an editor.

Benefit: note and registry pages stay fast and small as the graph grows, and the editors search the whole graph instead of a preloaded list.

### Tentative primary claim

Choosing a node in the note reader or registry editors finds it by typing part of its name, and opening those pages does not load the whole graph.

### Why now

Found in the 2026-11-24 simplify review. The cost grows with every ingested note.

### Known constraints

The web app stays read-only.

### Non-goals

None stated.

### Open choices

- Whether a server-rendered fallback is needed for use without JavaScript.

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
