---
proposal_id: "ontology-search"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Generic ontology search

## Proposal

Status: open choices decided, awaiting human approval.

### Intent

One generic "search" function that searches across our ontology, because that
is the point of the product. For a search word, it:

1. searches all the entities first, since entities are the items with the
   richest information;
2. also searches the edges and relationships (tentative: "?");
3. also searches the raw notes;

then, based on the results, presents results back to the user. The earlier
`entity-first-search` frame was too limited: it was built around one example
("nvidia") rather than general search behavior.

### Tentative primary claim

For any search word, search returns matching entities, relationships, and raw
note content from across the ontology, with entities searched first, and
presents those results back to the user.

### Why now

Searching "nvidia" in the Web UI shows "Consensus: Buy Apple Inc." first rather
than the NVIDIA company, and the earlier proposal framed the fix too narrowly.

### Known constraints

- The embedding database has already been re-created with Gemini.

### Non-goals

None stated.

### Decisions

Decided by the human on 2026-11-22, in answer to the draft's open choices.

1. **Entities first** means both: matched entities are listed at the top, and
   they are also used to find the related relationships, events, views, and
   notes.
2. **Edges** are used only to expand from matched entities. Relationships are
   not results of their own.
3. **Raw notes** results are passages from the note files. When an event or
   view extracted from a note also matches, the extracted item is shown and
   links to its source passage instead of the passage appearing twice.
4. **Presentation** is a top "best match" card for the matched entity, followed
   by grouped sections (entities, relationships, notes).
5. **Surfaces**: both the Web UI search and the PM agent's search tool use it.
6. **Each result explains why it matched** (name, alias, relationship, text in
   a note, or semantic similarity).
7. **Sequence**: entity search, edge expansion, raw note search, and the new
   presentation ship as one change.
8. **The `entity-first-search` ledger** is abandoned in favor of this proposal.
   It was removed in commit `b8444a2`.
9. **Time is a ranking signal**: recency, and a time range the search word
   implies (such as an earnings quarter), affect rank.
10. **A reranking step** reorders the combined results with a dedicated
    reranking model, as Hindsight does.

## Frame

## Proof

## Build

## Audit

## Revisions
