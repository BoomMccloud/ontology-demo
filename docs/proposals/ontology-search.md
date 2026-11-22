---
proposal_id: "ontology-search"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Generic ontology search

## Proposal

Status: draft, awaiting human approval.

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

### Open choices

1. **What "entities first" means.** List entity matches at the top of the
   results, or resolve the search word to entities first and use them to find
   the related relationships, events, views, and notes, or both.
2. **Whether edges are searched at all.** The request marks this with "?".
   Options: search relationships as results of their own (for example
   "NVIDIA supplies Apple"), use them only to expand from matched entities, or
   leave them out.
3. **Raw notes versus extracted items.** Whether raw note results are the note
   files themselves, passages from them, or the events and views extracted from
   them, and what happens when a raw note and an item extracted from it both
   match.
4. **How results are presented.** One ranked list mixing all kinds, or grouped
   sections (entities, relationships, notes), or a top "best match" card for
   the matched entity followed by the rest.
5. **Which surfaces use it.** The Web UI search, the PM agent's search tool, or
   both.
6. **Whether results explain why they matched** (name, alias, relationship,
   text in a note, or semantic similarity).
7. **Sequence.** These parts could ship separately: entity search, relationship
   search, raw note search, and the new presentation.
8. **The `entity-first-search` ledger.** Abandon it in favor of this proposal,
   or keep it as a first step.
9. **Time as a ranking signal.** Whether how recent a result is, or whether
   it falls in a time range the search word implies (such as an earnings
   quarter), affects its rank, or time stays only a manual filter.
10. **A reranking step after results are combined.** Whether combined results
    are reordered by a dedicated reranking model, as Hindsight does, which adds
    a model the product depends on, or are presented in their combined order.

## Frame

## Proof

## Build

## Audit

## Revisions
