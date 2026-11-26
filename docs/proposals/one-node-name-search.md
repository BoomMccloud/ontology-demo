---
proposal_id: "one-node-name-search"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: One node name search, cheap enough for typeahead

## Proposal

### Intent

`search_nodes_by_name` (`db/storage.py`, added for the editor typeahead) and `keyword_search` both run a LIKE over `name` and `aliases_json` with prefix matches first. Only the new one escapes `%` and `_`, so `keyword_search` (used by `search.py` and the query agent) still treats them as wildcards. The typeahead route (`web/app.py`) opens a full `OntologyDB` per keystroke pause (registry file validation, sqlite-vec load, registry parse) that the query never uses, selects whole rows with `summary`, and applies `exclude` in the browser, so excluded nodes can use up the 20-row limit.

Benefit: one search rule, so `%` and `_` mean the same in the agent and the editors, and the typeahead does only the work its results need.

### Tentative primary claim

Every node name search escapes LIKE wildcards the same way, and a typeahead request returns up to 20 non-excluded matches without loading the registry or sqlite-vec.

### Why now

Priority: medium. Found in the 2026-11-26 /simplify pass. Cost is about 1 ms per request today and grows with the graph.

### Known constraints

The web app stays read-only.

### Non-goals

None stated.

### Open choices

- Whether to match against `node_lookup.key` (casefolded, so non-ASCII case-insensitive) instead of `name` and `aliases_json`.

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
