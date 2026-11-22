---
proposal_id: "ontology-search"
state: ACCEPTED
witness: independent
candidate: "b8f6839 @ .claude/worktrees/ontology-search"
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

Candidate: `b8f6839 @ .claude/worktrees/ontology-search (proposal/ontology-search)`

### Files changed

- `src/stock_ontology/search.py` (new): this is the shared `search` module. `search_ontology()` resolves entities first: `find_by_name_or_alias` for entities, then themes, then `keyword_search`, then `vector_search`. It expands one hop through `get_incident_edges`, labels each relation with its registry-canonical name via `db.registry.canonicalize_edge`, and never returns edges as results. It labels every result with a `match_reason`, ranks by reason weight plus a bounded recency term (≤0.1), and uses a deterministic `parse_period` (quarter, FY, month, year) that drops items dated outside the period and boosts those inside it. It also contains `grep_notes`: a literal, case-insensitive grep that walks only supported, non-hidden files, never follows a link out of the data dir, caps passages per file and in total, and folds an event or view's own source-note line into that item's `note_line`. `SearchFilters` holds the filter logic moved from `run_hybrid_search`. `resolve_safe_note_path` and the `node_subtype/date/source_file` helpers moved here from `web/`. This covers the primary claim and the filesystem and DB guardrails.
- `src/stock_ontology/agent.py`: `OntologyAgent` takes an optional `data_dir`. `search_nodes` now calls `search_ontology` and returns `match_reason`, `score`, `distance` and `via`. A new `search_notes` tool is added to `TOOL_SCHEMAS` and `execute_tool` and registered like the others (async, `sequential=True`). Without `data_dir` it returns an error. This covers the agent side of the primary claim.
- `src/stock_ontology/web/viewmodels.py`: `run_hybrid_search` and `_format_search_result` are replaced by `build_search_results`, which builds the best-match card, the sections, and the note passages. The node helpers are imported from `search`.
- `src/stock_ontology/web/catalog.py`: imports `resolve_safe_note_path` from `search`. The rules are unchanged.
- `src/stock_ontology/web/app.py`: `/search` calls `build_search_results` with `SearchFilters.from_raw(...)` and passes `agent_query` and `agent_prompt` to the template. `chat_endpoint` passes `data_dir=settings.data_dir` to `OntologyAgent`. No new route.
- `src/stock_ontology/web/templates/search.html`: emits the witness page contract. That is a `data-best-match` card, items carrying `data-result-id`/`data-match-reason`, passages carrying `data-note-file`/`data-note-line`, and a `data-agent-column` with `data-agent-query`, `data-agent-detach` and a failed-state note. Sections are straight lists, and the agent column is pinned beside the results (layout A). No inline styles.
- `src/stock_ontology/web/static/clippy.js`: on the search page, it moves the existing Clippy window into the column. It sends the search prompt to `/api/chat` once per word and language, on the shared `sessionStorage` session. It shows a failed state and retries on the next visit if the run fails. Detach and Pin toggle the floating window.
- `src/stock_ontology/web/static/library.css`: adds the `search-*` classes. It uses no new media query; the existing 740px breakpoint stacks the column.
- `src/stock_ontology/locales/{en,zh,ko,ja,es,fr}.json`: 21 new keys each (`search.*` section, agent and match-reason labels, plus `enum.match_reason.*`).
- `tests/test_search.py` (new): Build-owned unit tests for the supporting obligations. They check that a name match beats a nearer vector hit and that alias matches are labeled `alias`. They check canonical relations (`supplies to` becomes `BUY`) with no edges returned as results. They check semantic failure, keyword mode, and filters. They check period narrowing and bounded recency, then the literal grep of `A.*`, case-insensitivity, the caps, and that traversal, hidden, symlinked and `.pdf` paths are skipped. They check an item and a passage from one file appear once with `note_line`, and that `/api/chat` gives the agent `data_dir` (a `search_notes` round trip).
- `tests/test_architecture.py`: `MODULE_OF` adds `search`. In `ALLOWED`, `search` may import shared, ontology, storage and llm, and `agent` and `web` may import `search` (per Frame's Invariants changed).
- `docs/architecture/README.md`, `docs/architecture/search.md` (new), `agent.md`, `web.md`, `storage.md`: these record the new module, the layer, `search_nodes`/`search_notes`, the shared search for both surfaces, and the column behavior (per Invariants changed).
- `README.md`: "Calling the Agent" now documents the optional `data_dir`. One constraint entry is added under Query Agent Constraints: search only through `search_ontology`/`grep_notes`, and never let a vector hit outrank a name or alias match. Its `**Why:**` cites the "nvidia" showing "Consensus: Buy Apple Inc." first (proposal `ontology-search`, 2026-11-22), and `**Guarded by:**` names the two primary witnesses and the read guardrail.
- Two notes for Audit, neither a scope change:
  - A keyword hit found only in an item's extracted summary or facets is labeled `note`, since the contract lists only name, alias, relationship, note and semantic.
  - Filter-only listings (no search word) carry `data-match-reason="filter"`, which is outside the five listed reasons.
- `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` and `test_web_nav_and_advanced_search_filters` needed no change and pass as they are.

### Unit evidence

- `uv run pytest tests/test_search.py -q`: RED, failed at collection with `ModuleNotFoundError: No module named 'stock_ontology.search'`, before any implementation.
- `uv run pytest tests/test_search.py tests/test_architecture.py tests/test_i18n.py tests/test_web_navigation.py -q`: GREEN, 53 passed.
- Manual check in the browser pane, against a local uvicorn with fake LLM clients and the witness fixtures (script now stopped). Results:
  - `/search?q=nvidia` ran the agent once into the pinned column: state `done`, one session id, dock launcher hidden.
  - Detach made the column `position: fixed` and collapsed the grid. Pin restored it.
  - A failing agent run showed the failed note with state `failed`.
  - This is not an automated test. The client-side JS still has no pytest owner.

### Green evidence

- Decisive witness: `uv run pytest tests/test_web.py tests/test_agent.py -k "search_" -v -rA`: 7 passed, covering all 5 protected witnesses plus the 2 existing search and filter tests.
- Witness integrity: `git diff d2b2c2b -- tests/test_web.py tests/test_agent.py` is empty. Re-checked by the orchestrator at `b8f6839`: empty.
- Gate: `uv run pytest -q`: 157 passed (144 before, plus the 5 witnesses and 8 new unit tests). Re-run by the orchestrator at `b8f6839`: 157 passed.

### Intervention record

- None. The repository has no intervention ledger. The user-facing outcome (search ranking on the live `ontology.db` with Gemini embeddings) is not measured offline.

### Deviations

- None.

## Audit

Candidate: `b8f6839 @ .claude/worktrees/ontology-search` (HEAD 57ec1bb; `git diff --stat b8f6839 57ec1bb` touches only `docs/proposals/ontology-search.md`)

Independence: separate-context. This was a fresh subagent that did not author Frame, Proof, or Build. It had seen only the ledger, the repository, and the candidate.

Primary-claim verdict: PROVED. Evidence: `uv run pytest tests/test_web.py tests/test_agent.py -k "search_" -v -rA` gave 7 passed. These include `test_web_search_entity_first_card_sections_notes_and_agent_column`, `test_agent_search_nodes_returns_entity_first_with_match_reasons`, and `test_agent_search_notes_greps_only_supported_notes_inside_data_dir`. RED checked independently: `git archive d2b2c2b` (the a8701d4 source plus the witnesses only) extracted to the scratchpad, `uv run pytest -q` gave `5 failed, 144 passed`, with exactly the five witnesses failing. `git diff d2b2c2b b8f6839 -- tests/test_web.py tests/test_agent.py` is empty, so the witnesses are unmodified. They still assert what the claim needs: a name-reason best-match card above a semantic Apple consensus, relationship expansion, a note passage with file and line and no duplicate for the event's source, a single agent column with the query and a detach control, an empty query carrying no agent query, and the agent's `search_nodes` putting `ent_nvda` first with reason `name`. Reading the code confirms that one function, `src/stock_ontology/search.py:search_ontology`, backs both `web/viewmodels.py:build_search_results` and `agent.py:_tool_search_nodes`. Limit: the page contract is data attributes. The client-side run, the shared session, the visible detach, and the failed state in `clippy.js` have no automated owner, and Build checked them only by hand. Live Gemini ranking on the real `ontology.db` is not measured.

Guardrail verdicts:
- Never writes the DB, never reads outside `ONTOLOGY_DATA_DIR` or hidden or unsupported files: PROVED. Evidence: `test_web_search_reads_only_data_dir_notes_and_never_writes_db` and the agent `search_notes` witness pass. The web test was RED through its positive control. Code inspection shows `_iter_note_files` prunes dot-dirs, `os.walk` does not follow symlinked dirs, every file goes through `resolve_safe_note_path` (resolve plus `is_relative_to` root, a supported-extension check, and no hidden parts), and `grep_notes` does only literal `casefold` `in` matching. Limit: the exclusion assertions held vacuously before the change, so they are regression guards, not RED-proven. Caps and regex-literal handling are covered only by Build-owned `tests/test_search.py::test_grep_is_literal_case_insensitive_capped_and_stays_in_data_dir`.
- Functional results render when the agent or embedding provider fails: PROVED. Evidence: `test_web_search_functional_results_survive_embedding_and_agent_failure` passes after being RED. `search_ontology` catches embedding errors around the vector step. Limit: the visible failed state of the column is client JS and is not automated.
- Existing advanced-search filters keep narrowing: PROVED. Evidence: `test_web_nav_and_advanced_search_filters` and `test_web_home_entity_theme_search_and_clippy_chat` pass unchanged. `SearchFilters.matches` carries over the removed `run_hybrid_search` rules. Limit: these are preservation tests, so they cannot be shown RED.

Scope and duty verdict: scope HELD, duties HELD. Evidence: the changed files (`git diff --stat a8701d4 b8f6839`) all fall under Frame's Include list. There are no changes under `src/stock_ontology/db/` or `pipeline.py`, no schema change, no new route, and no reranker. The changes to `tests/test_architecture.py` `MODULE_OF`/`ALLOWED` and to the `docs/architecture/*` and README "Calling the Agent" text match Frame's `Invariants changed`. Frame allowed amending the two `test_web.py` tests, but they were left unchanged and their "after" condition holds as written. The work follows Frame's named reuse: storage lookups, `get_incident_edges` plus `registry.canonicalize_edge`, `resolve_safe_note_path` moved into `search`, `/api/chat` plus the `clippy.js` session, and tool registration through `TOOL_SCHEMAS`/`execute_tool`. The constraint-capture duty is met: `README.md` under Query Agent Constraints has an entry with `**Why:**` and `**Guarded by:**`, and the three tests it names exist and pass. `search.html` has no inline styles, and locale parity passes in the full suite. Limit: Proof's supporting plan called for a page assertion in `tests/test_web.py` for the event-to-note-line link "once the link format exists". It was not added. That file is protected, and the fold is covered at function level by `tests/test_search.py::test_item_and_passage_from_one_file_appear_once_with_line`.

Test homes:
- `tests/test_search.py` (new) is the permanent owner of the shared `search` module's unit behavior, as Proof's supporting test plan assigned. It covers ranking, alias, canonical expansion, semantic failure, keyword mode, filters, period and recency, grep literal handling, caps and path safety, the fold, and `chat_endpoint` passing `data_dir`.
- `tests/test_architecture.py` (amended) remains the owner of the layering rules, and the amendment is the entry Frame listed.

Full gates: PASS. `uv run pytest -q` gave 157 passed. The decisive witness command above gave 7 passed. The RED replay at `d2b2c2b` gave 5 failed, 144 passed. Limit: all offline with fake LLM clients. No JS test harness exists, and no live provider was called.

Residual risks:
- An event or view whose source note matches only shows "line N" text beside a link to `/catalog?file=...`, not a line-anchored link. That falls short of Decision 3's "links to the matching line", and no page-level test covers it.
- `grep_notes` walks and reads the whole data directory synchronously on every `/search` with a word. Files over 5 MB are skipped, and passages are capped at 30 in total, but the number of files walked is not capped, so a large corpus could slow the page.
- `clippy.js` runs the agent once per word and language per tab session (`SEARCH_RUN_KEY`). Revisiting the same word in that tab shows the earlier chat rather than a new run, a narrow reading of Decision 11.
- Keyword hits found only in summaries or facets are labeled `note`, and filter-only listings use `filter`, which is outside the five stated reasons. Build disclosed both, and neither breaks a witness.
- The client column behavior (pin, detach, shared session, failed state) has only a manual check.

Recommendation: ACCEPT
Packet: no repair is required. Merging `proposal/ontology-search` remains the human-owned irreversible action. A follow-up proposal could add a line-anchored note link with a page assertion and a cap on the number of files walked, if the human wants them.

## Revisions
