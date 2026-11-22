---
proposal_id: "entity-first-search"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Entity-first hybrid search

## Proposal

Status: draft, awaiting human approval.

### Intent

When I search for a named thing, such as "nvidia", the first result should be
that thing, the NVIDIA company, not a news item or a view from the notes.
Search should return named things (companies, people, entities, themes)
separately from items extracted from the notes, and rank each sensibly. The
same search behavior should serve both the Web UI search and the PM agent's
node search, as in the hybrid search patterns brief: exact and alias tiering
with rank fusion, weighted lexical search, query-intent weighting, graph-aware
expansion, and embedding and index hygiene.

### Tentative primary claim

Searching "nvidia" or "NVDA", in the Web UI or through the PM agent, returns
the canonical NVIDIA entity as the first result, followed by other named things
and then the most relevant items from the notes.

### Why now

The current Web UI search for "nvidia" shows "Consensus: Buy Apple Inc." first,
even after the embedding database was re-created with Gemini.

### Known constraints

- The embedding database has already been re-created with Gemini.
- The change is strictly about how results are returned, named things versus
  items from the notes.

### Non-goals

None stated.

### Open choices

1. **Embedding changes.** The brief's embedding and index hygiene pattern
   (retrieval task types, richer embedding text, enriched canonical summaries,
   a drift guard) needs another re-embed. That conflicts with "strictly how
   results are returned." Include it, defer it to its own proposal, or drop it.
2. **Sequence.** The brief bundles parts that could ship separately: ranking
   (tiering, fusion, cutoff, graph boost), weighted lexical search, query-intent
   weighting, and embedding hygiene. Ship them together or in steps.
3. **Query-intent weighting.** Keep it, or skip it until exact-match tiering
   proves not enough.
4. **Result layout.** Show named things and note items as separate sections in
   the Web UI, or as one ranked list.
5. **Exact matches.** Always pin an exact name, alias, or ticker match first, or
   boost it inside the fused score so a strong note item can still outrank it.

## Frame

## Proof

## Build

## Audit

## Revisions
