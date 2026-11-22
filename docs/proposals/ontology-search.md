---
proposal_id: "ontology-search"
state: PROVED
witness: independent
candidate: "d2b2c2b @ .claude/worktrees/ontology-search"
---

# Proposal: Generic ontology search

## Proposal

Status: revision approved by the human on 2026-11-22.

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

Candidate: `a8701d4 @ .claude/worktrees/ontology-search (proposal/ontology-search)`

### Verified reality
- `uv run pytest -q` at `8c38731`, whose source tree matches the candidate (only the ledger changed since) — proves the suites judging this change were green before it started (144 passed); limit: offline fakes only, nothing about live Gemini embeddings.
- `src/stock_ontology/web/viewmodels.py:run_hybrid_search` — proves the Web UI search adds vector hits first and appends keyword hits after with no re-sort, so a vector hit such as "Consensus: Buy Apple Inc." can outrank the NVIDIA name match; limit: not reproduced against the live `ontology.db`.
- `src/stock_ontology/agent.py:_tool_search_nodes` — proves the agent's `search_nodes` is a second, separate vector-then-keyword merge with no expansion or match reasons; limit: none.
- `src/stock_ontology/db/storage.py:find_by_name_or_alias`, `keyword_search`, `vector_search`, `get_incident_edges`, `get_entity_connected_nodes` — proves storage already provides indexed name and alias lookup, substring and vector search, and one-hop edge expansion; limit: nodes only, no note text.
- `src/stock_ontology/db/schema.py:init_schema` and `src/stock_ontology/pipeline.py:_build_node_source` — proves the DB holds no note text and an extracted item records only its source file, so linking an item to a matching line means grepping its own source file; limit: none.
- `src/stock_ontology/web/catalog.py:resolve_safe_note_path` and `src/stock_ontology/config.py:SUPPORTED_EXTENSIONS` — proves a traversal-safe resolver for note files under `ONTOLOGY_DATA_DIR` exists, but in the web module, which the agent may not import; limit: the resolver checks one path, it does not walk a directory.
- `src/stock_ontology/agent.py:OntologyAgent.__init__`, `execute_tool`, `_ontology_toolset` — proves the agent takes only a DB and LLM today, and every tool is dispatched by name and registered async with `sequential=True`, so a new tool follows one existing pattern; limit: the agent has no data directory to grep.
- `src/stock_ontology/web/app.py:chat_endpoint` and `ChatRequest` — proves `/api/chat` already accepts `session_id`, `message`, and `page_context` and goes through `OntologyAgent.chat()` only; limit: it is synchronous and holds sessions in memory.
- `src/stock_ontology/web/static/clippy.js:sendMessage` — proves the Clippy dock already keeps one chat session per tab in `sessionStorage` and sends `page_context`, so the side column, the detached window, and the dock can share one session; limit: the dock is a single fixed element today.
- `tests/test_architecture.py:MODULE_OF` and `ALLOWED` — proves the agent may not import `web`, so one function shared by both surfaces needs a module both may import; limit: none.

### Final primary claim
- Searching "nvidia" (or any word that names an entity) on the Web UI search page shows a best-match card for that entity labeled with why it matched, then a straight list of sections for other entities, entities and themes connected through relationships, events and views, and grepped note passages, each labeled with its match reason. A pinned side column beside the results then shows the PM agent's answer for that search and lets the PM ask follow-ups in the same session, and the column can detach into a floating window. The agent's search tool returns the same entity-first results from the same function.

### Routing
- Witness: `independent`
- Why: the change crosses the storage, agent, and web components, adds a filesystem read path for user-supplied search words, and starts an LLM run on every search.
- Human-owned irreversible action: merging the branch.

### Decisive witness
- Layer: integration over the FastAPI test client and the agent with fake LLM clients, plus a unit test of the shared search function.
- Permanent owner: a new `tests/test_search.py`, with the page and agent cases in `tests/test_web.py` and `tests/test_agent.py`.
- Witness: with a fixture DB and fake embeddings where an Apple consensus view is the nearest vector to "nvidia" and a fixture data directory whose notes mention NVIDIA, `GET /search?q=nvidia` renders the NVIDIA entity as the best-match card with reason "name" above the consensus view, which carries reason "semantic"; a note line naming NVIDIA appears under note passages with its file and line; the agent's search tool returns the same entity first; and the page carries the agent column wired to `/api/chat` with that search.

### Guardrail claims
- Searching never writes to `ontology.db` and never reads a file outside `ONTOLOGY_DATA_DIR` or a hidden or unsupported file, whatever the search word contains.
- The functional results render completely when the agent run or the embedding provider fails, and the agent column then shows its failed state.
- Existing advanced-search filters (type, subtype, sentiment, stance, entity, date range, source file, keyword mode) keep narrowing results as they do today.

### Supporting obligations
- A new `search` module, allowed to import shared, ontology, storage, and llm, that both `agent` and `web` import; it owns entity resolution, expansion, note grep, de-duplication, time ranking, and match reasons. `run_hybrid_search` filters and `_tool_search_nodes` move onto it.
- Entity resolution uses `find_by_name_or_alias` first, then keyword, then vector search; expansion uses `get_incident_edges` with registry-canonical relations and does not return edges as results.
- Note grep treats the search word as a literal, case-insensitive string, never a regex, walks only supported, non-hidden files under the data directory, caps passages per file and in total, and returns file, line number, and the line.
- When an extracted event or view and a grepped line come from the same file, the line is folded into that item's source link instead of listed again.
- Time: a deterministic parser for explicit periods in the search word (quarter, fiscal year, year, month) restricts or boosts items dated in that period; otherwise recency is a bounded ranking term. No LLM call for parsing.
- `OntologyAgent` gains an optional `data_dir` and a `search_notes` tool registered like the others (async, `sequential=True`); `search_nodes` calls the shared function.
- The search page starts one agent run only when the search has a word, through `clippy.js` and `/api/chat` with the existing session id and a `page_context` naming the search; the same session carries the side column, the detached window, and the dock.
- New strings in all six locale files; new styles in `library.css` and routes kept in `navigation.py`, no inline styles.
- Unit candidates: name match beats a nearer vector hit; literal grep of `a.*` matches only that text; traversal and hidden paths are skipped; a quarter in the word narrows dates; item and passage from one file appear once.

### Allowed scope
- Reuse: storage lookups and expansion, `run_hybrid_search`'s filter logic, `resolve_safe_note_path`'s rules (moved below `web` so both surfaces share them), `/search` and `search.html`, `/api/chat` and `clippy.js` sessions, and the agent's tool registration.
- Cheaper alternative: re-sorting the current results so exact name and alias matches come first. It fixes "nvidia" but gives no expansion, note passages, match reasons, time ranking, agent column, or shared agent search, all of which the approved Proposal requires.
- Include: the `search` module, the agent's `data_dir` and `search_notes`, the search page's best-match card, sections, and agent side column with detach, `clippy.js` changes, locale strings, CSS, tests, and the architecture docs and test entries for the new module.
- Exclude/protect: no reranker; no schema change, no new DB write, and no re-ingest; no change to ingestion or merge rules; no new HTTP route beyond what `/search` and `/api/chat` serve; no live provider calls in tests.

### Invariants changed
- `tests/test_architecture.py:MODULE_OF` and `ALLOWED`, with `docs/architecture/README.md` — today: no `search` module; after: `search` may import shared, ontology, storage, and llm, and `agent` and `web` may import `search`.
- `docs/architecture/agent.md:30` — today: `search_nodes` is "vector and keyword search"; after: it calls the shared search, and `search_notes` greps research notes.
- `docs/architecture/web.md:10` and `docs/architecture/storage.md:52` — today: search is `run_hybrid_search` over `vector_search` and `keyword_search`; after: both surfaces call the shared search function.
- `README.md` "Calling the Agent" — today: `OntologyAgent(db, llm, language=...)`; after: also accepts an optional `data_dir` for note search, with the same two entry points.
- `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` (lines 268-276) and `tests/test_web.py::test_web_nav_and_advanced_search_filters` (lines 551-590) — today: assert the flat results table; after: assert the same items appear in the new card and sections.

### Decisions required
- None.

## Proof

Candidate: `d2b2c2b @ .claude/worktrees/ontology-search` (RED observed on the source tree of `a8701d4`/`c77a84f`, with only the witness tests added)

**Protected witness**
- Primary claim, Web UI: entity-first card, sections, notes, agent column. `tests/test_web.py` / `test_web_search_entity_first_card_sections_notes_and_agent_column`
  - Defect and boundary: `run_hybrid_search` puts vector hits first with no re-sort, has no match reasons, no edge expansion, no note grep, and the page has no agent column. The test goes over the HTTP boundary (FastAPI client → web → storage → filesystem) with fake embeddings, where "Consensus: Buy Apple Inc." is the nearest vector to "nvidia".
  - Assertion: `GET /search?q=nvidia` renders exactly one best-match card, `ent_nvda`, with reason `name`. `vw_cons_aapl` is listed after it with reason `semantic`. `thm_power` comes in through an edge with reason `relationship`, and `evt_nvda_q3` is listed. The passage `Notes/2026-11-10_channel_check.md` line 3 appears with reason `note`. No separate passage is listed for the event's own source file. There is one agent column with `data-agent-query="nvidia"` and a detach control, the page loads `clippy.js` (which posts to `/api/chat`), and `/search` with no word carries no agent query. This proves the claim at the page boundary.
  - Limit: the page contract is data attributes (`data-best-match`, `data-result-id`, `data-match-reason`, `data-note-file`, `data-note-line`, `data-agent-column`, `data-agent-query`, `data-agent-detach`), and Build must emit them. The test does not prove that the client-side JS actually starts the run, keeps one session across the column, floating window and dock, or detaches visually. It does not prove time ranking, the link from an event to its matching note line, or live Gemini behavior.
- Primary claim, agent: same entity-first search. `tests/test_agent.py` / `test_agent_search_nodes_returns_entity_first_with_match_reasons`
  - Defect and boundary: `_tool_search_nodes` is a separate vector-then-keyword merge. The test goes through the model-to-tool boundary, where a scripted model calls `search_nodes` and the test reads the response the agent returned to it.
  - Assertion: `tools_used == ("search_nodes",)`. `results[0].id == "ent_nvda"` with `match_reason == "name"`, and `vw_cons_aapl` has `match_reason == "semantic"`. This proves the agent's tool ranks the name match first and explains it.
  - Limit: it proves the same ordering, not that both surfaces call one function. That sharing is checked by the architecture test, per Frame.
- Primary claim, agent note grep, plus the filesystem guardrail. `tests/test_agent.py` / `test_agent_search_notes_greps_only_supported_notes_inside_data_dir`
  - Defect and boundary: the agent has no `data_dir` and no `search_notes` tool. The test crosses agent → filesystem.
  - Assertion: `OntologyAgent(ro_db, llm, data_dir=...)` is accepted, and `search_notes` is among the offered tool schemas. Calling it returns `passages` that contain `{file: "Notes/2026-11-10_channel_check.md", line: 3}` and that line's text. No passage comes from a symlink that points outside, a dotfile, or a `.pdf`. DB stats are unchanged.
  - Limit: it fixes the tool contract keys `passages[].file`, `line` and `text`. It does not cover caps or regex-literal handling.
- Guardrail: reads stay inside `ONTOLOGY_DATA_DIR`, and the DB is never written. `tests/test_web.py` / `test_web_search_reads_only_data_dir_notes_and_never_writes_db`
  - Defect and boundary: the new filesystem read path takes user-supplied words over HTTP.
  - Assertion: as a positive control, the in-scope note is grepped. For the words `nvidia`, `../outside/secret`, `NVIDIA OUTSIDE`, `.hidden`, `*.md` and `MARKER`, no marker leaks from a symlink to an outside file, a hidden directory, a hidden file, or an unsupported `.pdf`. The `ontology.db` sha256 and mtime are unchanged.
  - Limit: the RED comes from the positive control only. The exclusion assertions held vacuously before the change, so they are protected regressions, not RED-proven.
- Guardrail: functional results survive a failed embedding or agent provider. `tests/test_web.py` / `test_web_search_functional_results_survive_embedding_and_agent_failure`
  - Defect and boundary: a provider failure must not blank the search page. The test crosses web → llm.
  - Assertion: with both `embed_texts` and the agent raising, `/search?q=nvidia` still renders the `ent_nvda` best-match card, the note passage, and the agent column. `/api/chat` returns 500 with `error` and `session_id`.
  - Limit: the `/api/chat` error part was already green. It does not prove that the column visibly renders its failed state, which is client-side JS.
- Guardrail: existing advanced-search filters keep working. There is no new witness. The owners are `tests/test_web.py::test_web_nav_and_advanced_search_filters` and `test_web_home_entity_theme_search_and_clippy_chat`, and both are green today. Behavior that must be preserved cannot be observed RED. Build may amend them only as Frame's "Invariants changed" allows: the same items must appear, in the card and sections.
- Protected paths: `tests/test_web.py` (the block after the `# --- Generic ontology search` marker, and the existing tests above) and `tests/test_agent.py` (the block after the `# --- Generic ontology search` marker).
- Protected revision: `d2b2c2b`, compared with `git diff d2b2c2b -- tests/test_web.py tests/test_agent.py`.

**Red evidence**
- `uv run pytest tests/test_web.py tests/test_agent.py -k "search_" -v -rA` gave these results:
  - `test_web_search_entity_first_card_sections_notes_and_agent_column`: "search page has no single best-match card" (0 == 1).
  - `test_web_search_reads_only_data_dir_notes_and_never_writes_db`: the positive control found no note passage.
  - `test_web_search_functional_results_survive_embedding_and_agent_failure`: `[] == ['ent_nvda']`.
  - `test_agent_search_nodes_returns_entity_first_with_match_reasons`: the results put the name match last, in the order `['vw_cons_aapl', 'ent_aapl', 'vw_cons_nvda', 'evt_q3', 'thm_power', 'ent_tsmc', 'ent_vrt', 'ent_nvda']`. This reproduces the reported bug.
  - `test_agent_search_notes_greps_only_supported_notes_inside_data_dir`: `Failed: OntologyAgent does not accept data_dir for note search`. This is caught as an explicit assertion failure, not a setup error.
  - The existing filter and search tests passed.
- `uv run pytest -q` gave `5 failed, 144 passed`. Only the five new witnesses fail. Re-run by the orchestrator at `d2b2c2b`: same result.
- No claim above has proof until its command is observed RED. All five were observed RED.

**Supporting test plan**
- A name match beats a nearer vector hit, alias matches get reason `alias`, and expansion uses registry-canonical relations and does not return edges as results. Build owner: `tests/test_search.py`. It catches ranking or expansion defects in the shared function.
- Note grep treats the word literally: `a.*` matches only that text. It is case-insensitive, caps passages per file and in total, and skips traversal, hidden, and unsupported paths. Build owner: `tests/test_search.py`. It catches regex injection and unbounded output.
- An event or view and a grepped line from the same file appear once, and the item links to the matching line. Build owner: `tests/test_search.py`, plus a page assertion in `tests/test_web.py` once the link format exists. It catches duplicated passages and missing line links.
- A period in the word (quarter, fiscal year, year, month) narrows or boosts dated items, and recency is a bounded term with no LLM call. Build owner: `tests/test_search.py`. It catches time-ranking defects.
- A `search` module may import shared, ontology, storage and llm, and `agent` and `web` may import `search`. Build owner: `tests/test_architecture.py` `MODULE_OF`/`ALLOWED`. It catches a layering violation or a duplicated search path.
- `chat_endpoint` passes `data_dir` to `OntologyAgent` and still uses the agent only for `.chat`. Build owner: `tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat`. It catches an agent column without note search.
- New strings are in all six locales. Build owner: `tests/test_i18n.py`. It catches missing translations.
- The client-side side column, shared session, detach, and failed state have no offline pytest owner. Audit should record this as a limit unless Build adds a JS check the repo already supports.

## Build

## Audit

## Revisions
