---
proposal_id: "ontology-search"
state: PROPOSAL
witness: builder
candidate: "unassigned"
---

# Proposal: Generic ontology search

## Proposal

Status: revised by the human on 2026-11-22, open choices decided, awaiting approval of the revision.

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
3. **Raw notes** are searched in the raw files with grep, at query time,
   rather than stored in the database. One grep function is shared by the Web
   UI and the PM agent, and the agent also gets a grep tool for its own
   follow-up searches. When an event or view extracted from a note also
   matches, the extracted item is shown and links to the matching line in
   that note instead of the passage appearing twice. (Revised 2026-11-22.)
4. **Presentation** is a top "best match" card for the matched entity, followed
   by grouped sections (entities, relationships, notes). In the human's words:
   "the table returns the functional results first... with another window
   that returns agent results, and ask the user to chat with the agent, we'll
   have to design a new search result component / product behavior / page for
   this". (Revised 2026-11-22.)
5. **Surfaces**: both the Web UI search and the PM agent's search tool use it.
6. **Each result explains why it matched** (name, alias, relationship, text in
   a note, or semantic similarity).
7. **Sequence**: entity search, edge expansion, raw note search, and the new
   presentation ship as one change.
8. **The `entity-first-search` ledger** is abandoned in favor of this proposal.
   It was removed in commit `b8444a2`.
9. **Time is a ranking signal**: recency, and a time range the search word
   implies (such as an earnings quarter), affect rank.
10. **No reranking step for now.** Combined results are presented in their
    combined order. (Revised 2026-11-22: "skip rerank for now".)
11. **Search starts an agent run.** Each Web UI search also runs the PM agent on
    the search word. Its answer appears in a separate window after the
    functional results, and that window invites the user to keep chatting with
    the agent. (Added 2026-11-22.)

12. **Search page layout** is the mockup's layout A
    (https://claude.ai/artifact/SJQ5oCUte9f5pbSpyYfvdt): the agent window is a
    side column beside the functional results. In the human's words: "when
    the window goes down, the side column remains, and has access to the
    context of the window so user can ask questions", and it "can detach from
    side window into floating". (Added 2026-11-22.)

### Open choices

None.

## Frame

## Proof

## Build

## Audit

## Revisions
