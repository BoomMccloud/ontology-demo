---
proposal_id: "ontology-search"
state: FRAMED
witness: independent
candidate: "8c38731 @ .claude/worktrees/ontology-search"
---

# Proposal: Generic ontology search

## Proposal

Status: approved by the human on 2026-11-22.

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

Candidate: `8c38731 @ .claude/worktrees/ontology-search (proposal/ontology-search)`

### Verified reality
- `uv run pytest -q` on the candidate — proves the suites judging this change were green before it started (144 passed); limit: offline fakes only, says nothing about live Gemini embeddings.
- `src/stock_ontology/web/viewmodels.py:run_hybrid_search` — proves the Web UI search adds semantic (vector) hits to its result dict first and appends keyword hits after, with no re-sort, so any vector hit (such as an Apple consensus view) outranks an exact name match for "nvidia"; limit: not reproduced against the live `ontology.db`.
- `src/stock_ontology/agent.py:_tool_search_nodes` — proves the PM agent's `search_nodes` tool is a second, separate copy of vector-then-keyword merging, with no filters, expansion, or match reasons; limit: none.
- `src/stock_ontology/db/storage.py:vector_search`, `keyword_search`, `find_by_name_or_alias`, `get_incident_edges`, `get_entity_connected_nodes` — proves storage already offers vector search, substring search, indexed exact name/alias lookup, and one-hop edge expansion over nodes; limit: all of it covers nodes only.
- `src/stock_ontology/db/schema.py:init_schema` — proves `ontology.db` stores no note text: `ingestion_log` holds path and hash, `node_vectors` holds node embeddings only; limit: none.
- `src/stock_ontology/pipeline.py:_build_node_source` — proves an extracted event or view records its source file, author, title, kind, and date, but no passage, offset, or quote; limit: none.
- `src/stock_ontology/web/catalog.py:resolve_safe_note_path` and `app.py` uses of `settings.data_dir` — proves the web app can read raw note files from `ONTOLOGY_DATA_DIR`; limit: `OntologyAgent.__init__` takes only a DB and LLM, so the agent cannot read note files today.
- `src/stock_ontology/llm/base.py:LLMClient` — proves the LLM interface offers chat and `embed_texts` only; there is no rerank call on any provider, and `grep -ri rerank src docs pyproject.toml` finds nothing; limit: does not check which configured providers sell a rerank endpoint.
- `src/stock_ontology/web/viewmodels.py:_node_date` and the `date_from`/`date_to` filters in `run_hybrid_search` — proves nodes carry a date usable for recency and range ranking; limit: dates exist only where extraction set one.

### Final primary claim
- BLOCKED pending decisions 1 and 2. Intended claim once decided: for any search word, the Web UI search page and the PM agent's search tool return, from one shared search function, a best-match entity card when the word resolves to an entity, then grouped sections of entities (with items reached through their relationships), and note passages, each result labeled with why it matched, ordered by the reranker with time as a signal.

### Routing
- Witness: `independent`
- Why: the change crosses the storage, web, and agent components, adds an external model dependency, and (under decision 2, option a) changes what ingestion writes to stored data.
- Human-owned irreversible action: re-ingesting or re-embedding the live `ontology.db` if note passages are stored, and merging the branch.

### Decisive witness
- Layer: BLOCKED pending decisions.
- Permanent owner: BLOCKED. Expected to be a new `tests/test_search.py` with a fake reranker, plus the existing `tests/test_web.py` and `tests/test_agent.py` search assertions.
- Witness: BLOCKED. Expected shape: with a fixture DB where an Apple consensus view is the nearest vector to "nvidia", searching "nvidia" shows the NVIDIA entity as the best-match card labeled "name", on both surfaces.

### Guardrail claims
- Searching never writes to `ontology.db`, and the web UI and agent still open it with `PRAGMA query_only = ON`.
- When the reranker or the embedding provider is unavailable, search still returns results in combined order instead of failing, as the current keyword fallback does.
- Existing advanced-search filters (type, subtype, sentiment, stance, entity, date range, source file, keyword mode) keep narrowing results as they do today.

### Supporting obligations
- One search function owned below both surfaces, replacing `run_hybrid_search`'s merge and `_tool_search_nodes`.
- Entity resolution reuses `find_by_name_or_alias` before keyword and vector search; expansion reuses `get_incident_edges` with registry-canonical relations.
- Each result carries a match reason from a fixed set: name, alias, relationship, note text, semantic.
- Time ranking parses only explicit periods in the search word (quarter, fiscal year, year, month) with deterministic rules, and applies recency as a bounded score term; no LLM call for query parsing.
- A rerank method on the LLM interface, with a fake in tests; tests never call a live provider.
- Unit candidates: name match beats a nearer vector hit; an extracted item suppresses its own source passage; "Q3 2026" boosts items dated in that quarter; reranker failure falls back.

### Allowed scope
- Reuse: `OntologyDB` search and edge helpers, `run_hybrid_search`'s filter logic, the `search.html` template and `/search` route, the `search_nodes` tool registration, and the `LLMRouter` fallback chain for the reranker.
- Cheaper alternative: re-sort the existing results so exact name and alias matches come first. It fixes the "nvidia" case but gives no expansion, notes, match reasons, time signal, or reranker, all of which the approved Proposal requires.
- Include: a shared search module, storage reads it needs, the rerank interface and one provider implementation, the search page layout and locale strings for all six languages, the agent tool, tests, and architecture doc updates.
- Exclude/protect: no change to merge or resolution rules in ingestion; no new write path outside `IngestionPipeline`; no live provider calls in tests; no re-ingest of the live DB by any stage.

### Invariants changed
- `docs/architecture/agent.md:30` — today: `search_nodes` is "vector and keyword search"; after: it calls the shared ontology search and returns grouped, reasoned, reranked results.
- `docs/architecture/web.md:10` and `docs/architecture/storage.md:52` — today: search is `run_hybrid_search` over `vector_search` and `keyword_search`; after: both surfaces call the shared search function.
- `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` (lines 268-276) and `tests/test_web.py::test_web_nav_and_advanced_search_filters` (lines 551-590) — today: assert the flat results table; after: may be updated to the best-match card and grouped sections, keeping what each asserts about which items appear.

### Decisions required
1. **Which reranking model, and where it runs.** Nothing in the repo can rerank today. (a) A hosted rerank endpoint from a provider you already use, such as DashScope's `gte-rerank`, which adds a network call to every search. (b) A local cross-encoder, as Hindsight uses, which adds `sentence-transformers` and PyTorch to the install. (c) The existing chat model scoring the results, which needs no new dependency but is not a dedicated reranking model and is slower.
2. **Where raw note passages come from.** The DB stores no note text, and extracted items record no source passage. (a) Ingestion splits each note into passages and stores them with embeddings in `ontology.db`, so passages get semantic matches, both surfaces can search them, and extracted items can link to their nearest passage. This needs a full re-ingest of the live DB. (b) Search reads note files from `ONTOLOGY_DATA_DIR` at query time, keyword only, with no re-ingest. The agent would need the data directory passed in, and an extracted item could link only to its note file, not a passage.

## Proof

## Build

## Audit

## Revisions
