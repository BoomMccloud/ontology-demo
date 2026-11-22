# Stock Ontology MVP

An investment research knowledge graph and strictly read-only portfolio manager (PM) query agent built with Python, SQLite + `sqlite-vec`, and a unified multi-LLM provider router (`LLMRouter`) supporting DashScope/Qwen, OpenAI, Anthropic, Google Gemini, and generic OpenAI-compatible endpoints with automatic fallback.

## Architecture

Strictly **one-directional data flow**:

```text
data/**/*.md|.txt   (any folder layout)
        │
        ▼  (IngestionPipeline: extract -> resolve -> upsert -> synthesize consensus)
  ontology.db (SQLite + sqlite-vec)
        │
        ▼  (PRAGMA query_only = ON)
  OntologyAgent (read-only PM chat, CLI ask, & Library Clippy UI)
```

### Research Notes Layout
- Ingestion scans `ONTOLOGY_DATA_DIR` (default `data/`) recursively for `.md` and `.txt` files. Hidden files and folders are skipped.
- Folder names do not decide which company a note is about. Companies, people, and themes come from the note's content via LLM extraction, so one note can cover several companies. Flat files at the root of `data/` work too.
- The note's relative path is stored as provenance in `facets.source.file_path`, and its parent directory (if any) in `facets.source.folder`.
- Organize however you like, for example by author (`data/JASON/`, `data/analysts/sarah/`), by date, or flat. The Web UI catalog groups notes by top-level folder and matches a folder to a company or person when its name matches one in the graph. Folders under `people/`, `persons/`, or `analysts/` are shown as person folders, and `_general/` or root-level notes are shown as general.

### 4-Node Ontology + Unified Edges
- **`entity`**: Companies, people, products, institutions, sectors (`facets.entity_type`, `ticker`, `credibility`, etc.)
- **`event`**: Objective observations — subsumes facts, news, earnings, meetings, and catalysts (`facets.event_type`, `facets.status`, `facets.sentiment` (`positive|negative|neutral|mixed`), `facets.source`)
- **`view`**: Subjective claims — rumors, analyst reports, channel checks, PM views, and pipeline-synthesized fund **`consensus`** views (`facets.view_type`, `stance`, `facets.sentiment` (`positive|negative|neutral|mixed`), `support_strength`, `pillars`, `facets.source`)
- **`theme`**: Secular narratives / investment theses (`facets.stage`)
- **Unified `edges`**: Minimal directed canonical relationships (`ABOUT`, `AUTHORED_BY`, `BUY`, `COMPETE`, `OWNS`, `WORKS_AT`, `EXPOSED_TO`, `RELATES_TO`, `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES`) with open JSON `facets` (including `sentiment` exposure facets on `EXPOSED_TO` and optional per-company `sentiment` overrides on `ABOUT` edges).
- **Official Registry & Audit (`ontology_registry.json`)**: Minimal canonical definitions for relations (including aliases, inverse mappings, and domain/range rules), core companies, house themes, and facet aliases. Running `uv run stock-ontology audit` verifies `ontology.db` read-only and queues unmapped items under `suggestions` as `pending` for admin review.

### Unified Multi-LLM Provider & Fallback Router (`stock_ontology.llm`)
- `create_llm_client(settings)` builds an `LLMRouter` wrapping pluggable adapters (`DashScopeProvider`, `OpenAIProvider`, `AnthropicProvider`, `OpenAICompatibleProvider`, `GeminiProvider`).
- With `LLM_PROVIDER=auto` (default), all configured providers are ordered automatically (`gemini -> dashscope -> openai -> anthropic -> openai_compatible`).
- You can also set explicit chains with `LLM_PROVIDERS=gemini,dashscope,openai`, append fallbacks with `LLM_FALLBACK_PROVIDERS=...`, or specify a separate embedding chain with `EMBEDDING_PROVIDERS=...` (chat-only providers like Anthropic are automatically skipped for embeddings).
- On `429 RESOURCE_EXHAUSTED`, auth errors, `5xx`, network timeouts, or invalid responses, `LLMRouter` automatically falls back to the next provider and places rate-limited/auth-failed providers on a configurable cooldown (`LLM_COOLDOWN_SECONDS`).
- `/api/health` exposes configured LLM chain diagnostics (without secrets) and `/api/chat` + Clippy display which provider and model served each reply.

### Calling the Agent (`stock_ontology.agent`)
Other components call the agent through two entry points and nothing else.

- **Multi-turn chat, for any caller that keeps its own sessions (the web app does):** `OntologyAgent.chat(message, history)` runs one turn and returns a frozen `ChatTurn`. Store `turn.history` and pass it back unchanged on the next call. Treat it as opaque, because its message format belongs to the agent.

  ```python
  from stock_ontology.agent import OntologyAgent
  from stock_ontology.db import OntologyDB

  with OntologyDB(db_path, embedding_dim=dim, read_only=True) as db:
      agent = OntologyAgent(db, llm, language="en")
      turn = agent.chat("What is our view on NVDA?", history)  # history: () or a previous turn.history
  turn.reply          # str, the answer
  turn.history        # tuple, pass back next time; don't inspect it
  turn.tools_used     # tuple[str, ...], tools called in this turn only
  turn.provider, turn.model, turn.fallback_used  # which LLM served this turn
  ```

- **One-shot or REPL, for a caller that lets the agent hold history (the CLI does):** `OntologyAgent.ask(message)` returns the reply string, and `reset()` clears history.

`OntologyAgent` requires a read-only `OntologyDB` and raises `ValueError` otherwise. Build one agent per request, or per conversation for a REPL. An instance holds mutable state, so don't share one across concurrent callers. Attributes such as `messages`, `tool_trace` and `last_provider` are internal and may change; agent tests may read them, other components must not.

### Multi-Language Support (`en`, `zh`, `ko`, `ja`, `es`, `fr`)
- The Web Library UI, Office-Clippy PM chat, `OntologyAgent`, and CLI support **English (`en`)**, **Chinese (`zh`)**, **Korean (`ko`)**, **Japanese (`ja`)**, **Spanish (`es`)**, and **French (`fr`)** while keeping ingested research notes and database text in their original language.
- **Web UI**: Switch languages via the masthead language selector (`GET /set-language`), `?lang=<code>` query parameter, `stock_ontology_lang` cookie, `POST /api/language`, or browser `Accept-Language` header.
- **Environment & CLI**: Set `APP_LANGUAGE=zh` (or `en|zh|ko|ja|es|fr`) in `.env`, or pass `--lang` / `-l` to CLI commands (`serve`, `ask`, `chat`, `inspect`, `ingest`, `watch`).

## Setup

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=... (and optional fallback keys like DASHSCOPE_AP_SOUTHEAST_1_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY)
uv sync
```

## Usage

```bash
# 1. Ingest notes from data/ (any layout) and synthesize company consensus views
uv run stock-ontology ingest

# 2. Inspect database contents or drill into a company/theme
uv run stock-ontology inspect
uv run stock-ontology inspect NVDA
uv run stock-ontology inspect "AI Data Center Power Bottleneck"

# 2b. Audit ontology.db (strictly read-only) against ontology_registry.json and sync pending suggestions
uv run stock-ontology audit

# 2c. Apply deterministic fixes to ontology.db (writes): delete rows left by notes missing from the
#     ingestion log, rename registered alias/inverse relations, merge exact name/alias duplicates.
#     Run it on a timer (cron or launchd), then `audit` to queue judgment calls as pending suggestions.
uv run stock-ontology repair
uv run stock-ontology repair --json
# After repair merges duplicates, recompute the survivors' embeddings (needs LLM API keys).
uv run stock-ontology repair --reembed

# 3. Periodically watch data/ for new or updated notes
uv run stock-ontology watch --interval 60

# 4. Ask a single question or evaluate a new meeting note against DB consensus
uv run stock-ontology ask "We discussed AI Data Center Power Bottleneck — what are the related companies?"
uv run stock-ontology ask "Does this meeting note change our NVDA consensus?" --file path/to/meeting_note.md

# 5. Interactive PM chat (strictly read-only terminal REPL)
uv run stock-ontology chat

# 6. Start the 1990s Library Web UI + Office-Clippy read-only chat
uv run stock-ontology serve --host 127.0.0.1 --port 8000
```

## Ingestion Constraints

- Write every note's rows inside one `OntologyDB.transaction()` that first clears that note's prior artifacts, and never let individual writes commit on their own.
  **Why:** a note that failed partway left partial rows and no log entry, and the next run wrote a second copy (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_mid_note_failure_leaves_no_rows_and_rerun_yields_one_copy`.
- Keep `ontology_registry.json` as the single source of truth for the minimal canonical edge vocabulary (`BUY`, `COMPETE`, `OWNS`, `WORKS_AT`, `EXPOSED_TO`, plus core plumbing relations): write and repair paths normalize via `OntologyRegistry.canonicalize_edge()` (queuing unknown relations via `audit --sync` instead of inventing aliases), and read paths (`OntologyDB`, web UI, and CLI) canonicalize in memory, deduplicate `(node, canonical_relation, direction)` with reconciled polarity, and render natural directional labels without mention counts.
  **Why:** un-normalized aliases, inverse pairs (`SUPPLIES_TO`/`CUSTOMER_OF`), and multi-note duplicate rows caused repeated theme and peer entries on entity pages such as Vertiv (proposal `minimal-entity-relationships`, 2026-11-22).
  **Guarded by:** `tests/test_relationships.py::test_read_side_consolidation_and_natural_ux_labels`, `tests/test_relationships.py::test_write_side_normalization_oov_queueing_and_catalog_signatures`, and `tests/test_relationships.py::test_registry_driven_repair_and_reciprocal_contradiction_audit`.
- Resolve every extracted relation through the registry in the pipeline (`IngestionPipeline._canonical_relation`) before calling `upsert_edge`. Keep `upsert_edge` accepting raw strings, since audit tests seed raw names through it.
  **Why:** the pipeline only uppercased relation names, so 39 names drifted into `ontology.db`, including registered aliases and inverses such as `PARTNER_WITH` and `HAS_EMPLOYEE` (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_stores_registered_alias_and_inverse_relations_canonically`.
- Look up names and aliases with SQL over `name` and `aliases_json` (`OntologyDB.find_by_name_or_alias`), never with a capped Python scan, and keep the edge-reference fallback limited to entities and themes.
  **Why:** a 5,000-node scan ordered by recency let newer events and views push old entities out of the window, so ingestion created duplicate entities (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_resolves_old_entity_past_5000_newer_nodes`.
- Insert nodes, and change a node's name or aliases, only through `OntologyDB.upsert_node`. Raw SQL that does either skips the indexed `node_lookup` table, so name and alias lookups miss the node and ingestion creates duplicates. Raw deletes are fine (`node_lookup` cascades), as are raw updates to other columns such as `facets_json`. A writable open also rebuilds `node_lookup` if any node lacks a lookup row.
  **Why:** name lookup moved from a full scan to the `node_lookup` index (proposal `ingestion-followups`, 2026-11-22).
  **Guarded by:** `tests/test_db.py::test_node_lookup_uses_index_and_tracks_alias_edits_and_deletes`.
- Take a note's `doc_id` from its ingestion log entry, not from its current path. A moved note keeps its original `doc_id`, so a path-derived ID can collide with it.
  **Why:** moved notes are relinked instead of re-extracted (proposal `ingestion-followups`, 2026-11-22).
  **Guarded by:** `tests/test_db.py::test_moves_handle_root_folder_ambiguity_reused_paths_and_force`.

## Query Agent Constraints

- Register the ontology tools on the Pydantic AI agent as `async` functions with `sequential=True`, so they run on the thread that opened the `OntologyDB`. Never register a plain `def` tool that touches the DB.
  **Why:** Pydantic AI runs sync tools in worker threads, and the SQLite connection refused them ("objects created in a thread can only be used in that same thread"), so every ontology tool returned an error (proposal `pydantic-ai-agent`, 2026-11-22).
  **Guarded by:** `tests/test_agent.py::test_agent_ux1_meeting_note_consensus_check`.
- The web app talks to the agent only through `OntologyAgent(...)` and `OntologyAgent.chat()`. It stores `ChatTurn.history` per session without inspecting it and never reads or writes other agent attributes (`messages`, `tool_trace`, `last_provider`, and so on).
  **Why:** the pydantic-ai rewrite kept `/api/chat` working only because the agent's attribute names happened to survive; a stated contract lets agent internals change without breaking the web chat (proposal `agent-chat-contract`, 2026-11-22).
  **Guarded by:** `tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat` and `tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract`.

## Tests (Offline)

```bash
uv run pytest -v
```
