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
- **`entity`**: Companies, people, institutions, sectors, regions (`facets.entity_type`, `ticker`, `credibility`, etc.)
- **`event`**: Objective observations — subsumes facts, news, earnings, meetings, and catalysts (`facets.event_type`, `facets.status`, `facets.sentiment` (`positive|negative|neutral|mixed`), `facets.source`)
- **`view`**: Subjective claims — rumors, analyst reports, channel checks, PM views, and pipeline-synthesized fund **`consensus`** views (`facets.view_type`, `stance`, `facets.sentiment` (`positive|negative|neutral|mixed`), `support_strength`, `pillars`, `facets.source`)
- **`theme`**: Secular narratives / investment theses (`facets.stage`)
- **Unified `edges`**: Minimal directed canonical relationships (`ABOUT`, `AUTHORED_BY`, `BUY`, `COMPETE`, `OWNS`, `WORKS_AT`, `EXPOSED_TO`, `RELATES_TO`, `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES`) with open JSON `facets` (including `sentiment` exposure facets on `EXPOSED_TO` and optional per-company `sentiment` overrides on `ABOUT` edges).
- **Official Registry & Audit (`ontology_registry.json`)**: Minimal canonical definitions for relations (including aliases, inverse mappings, and domain/range rules), core companies, house themes, facet aliases, the official facet vocabularies (`facet_vocabularies`), the facet schema (`facet_schema`: each official facet's kind and whether it is required, per node type, per entity type as `entity:<entity_type>` layered on `entity`, and for edges), and the max length of node `name` and `summary` (`metadata_max_length`: 200 and 1,000). The registry is the source and must declare all three; `load_registry` fails without any of them. `vocab.py`'s vocabularies are checked against the registry's and loading fails if they differ. Code keeps no copy of the per-type specs: it checks only that `facet_schema` declares the facets code depends on (`entity_type`, `event_type`, `view_type`, `stage`, edge `basis`, each a required enum), so requiring a facet for an entity type is a registry edit. The shipped registry requires `role` and `organization` on a person and `sector` on a company, and declares a person's optional `accuracy` (`high|medium|low`): our own rating of the author, set only by hand through the app's person correction, never by extraction. Consensus synthesis gets each rumor's person authors with their `accuracy` (or `unrated`) and weighs rumors by it. It is separate from the free-form, LLM-set `credibility`, which is the note's self-description. `ontology.db` records the applied registry and its full revision separately from the facet schema stamp. A maintainer publishes an approved proposal, then separately previews and confirms adoption. Writes are refused when a required facet is missing, an official facet has the wrong kind, an enum (required or optional) is outside its vocabulary, `name` or `summary` is over its limit, or an edge's relation is not mapped by the registry (the pipeline holds such an edge in `pending_edges` for `audit` to suggest and `repair` to promote), also for a DB opened without a registry (the built-in default declares a base schema); other facets stay free-form. Running `uv run stock-ontology audit` verifies `ontology.db` read-only and queues unmapped items in `ontology_registry.suggestions.json` for review.

### Unified Multi-LLM Provider & Fallback Router (`stock_ontology.llm`)
- `create_llm_client(settings)` builds an `LLMRouter` wrapping pluggable adapters (`DashScopeProvider`, `OpenAIProvider`, `AnthropicProvider`, `OpenAICompatibleProvider`, `GeminiProvider`).
- With `LLM_PROVIDER=auto` (default), all configured providers are ordered automatically (`gemini -> dashscope -> openai -> anthropic -> openai_compatible`).
- You can also set explicit chains with `LLM_PROVIDERS=gemini,dashscope,openai`, append fallbacks with `LLM_FALLBACK_PROVIDERS=...`, or specify a separate embedding chain with `EMBEDDING_PROVIDERS=...` (chat-only providers like Anthropic are automatically skipped for embeddings).
- For ingestion (extraction, consensus synthesis) and embeddings, on `429 RESOURCE_EXHAUSTED`, auth errors, `5xx`, network timeouts, or invalid responses, `LLMRouter` automatically falls back to the next provider and places rate-limited/auth-failed providers on a configurable cooldown (`LLM_COOLDOWN_SECONDS`).
- The query agent (Clippy, CLI `ask`/`chat`) answers through Pydantic AI's own models instead (`GoogleModel`, `OpenAIChatModel` for DashScope/OpenAI/OpenAI-compatible, `AnthropicModel`), built from the same provider chain by `build_agent_models(settings)` in `stock_ontology.llm.agent_model`. Each turn runs a Pydantic AI `FallbackModel` that moves to the next provider on any provider API error; a provider that failed with a rate-limit, auth or config error is tried last on every later request, including the rest of the same turn, for `LLM_COOLDOWN_SECONDS`.
- `/api/health` exposes configured LLM chain diagnostics (without secrets). `/api/chat` returns which provider and model served each reply, but Clippy does not show it. Every agent fallback is logged as a server warning naming the failed model, the error kind and any cooldown.

### Calling the Agent (`stock_ontology.agent`)
Other components call the agent through two entry points and nothing else.

- **Multi-turn chat, for any caller that keeps its own sessions (the web app does):** `OntologyAgent.chat(message, history)` runs one turn and returns a frozen `ChatTurn`. Store `turn.history` and pass it back unchanged on the next call. Treat it as opaque, because its message format belongs to the agent.

  ```python
  from stock_ontology.agent import OntologyAgent
  from stock_ontology.db import OntologyDB
  from stock_ontology.llm.agent_model import build_agent_models

  agent_models = build_agent_models(settings)  # once per process
  with OntologyDB(db_path, embedding_dim=dim, read_only=True) as db:
      agent = OntologyAgent(
          db, llm, model=agent_models.for_turn(), language="en", data_dir=notes_dir
      )  # llm embeds tool queries; model answers; data_dir optional, for note search
      turn = agent.chat("What is our view on NVDA?", history)  # history: () or a previous turn.history
  turn.reply          # str, the answer
  turn.history        # tuple, pass back next time; don't inspect it
  turn.tools_used     # tuple[str, ...], tools called in this turn only
  turn.provider, turn.model, turn.fallback_used  # from the answering Pydantic AI ModelResponse
  ```

- **One-shot or REPL, for a caller that lets the agent hold history (the CLI does):** `OntologyAgent.ask(message)` returns the reply string, and `reset()` clears history.

`OntologyAgent` takes any Pydantic AI `Model` as `model=` (a `FunctionModel` in tests) and an optional `model_settings=` (for example `{"max_tokens": 800}`) that reaches every model request; the system prompt goes in as Pydantic AI `instructions`. Build `agent_models = build_agent_models(settings)` once per process and pass `agent_models.for_turn()` for each turn, so a cooled provider goes last. `fallback_used` is true when a model other than the first in that turn's chain answered. `OntologyAgent` requires a read-only `OntologyDB` and raises `ValueError` otherwise. Pass the optional `data_dir` (the research notes directory) to let its `search_notes` tool grep notes; without it that tool returns an error. Build one agent per request, or per conversation for a REPL. An instance holds mutable state, so don't share one across concurrent callers. Attributes such as `messages`, `tool_trace` and `last_provider` are internal and may change; agent tests may read them, other components must not.

### Multi-Language Support (`en`, `zh`, `ko`, `ja`, `es`, `fr`)
- The Web Library UI, Office-Clippy PM chat, `OntologyAgent`, and CLI support **English (`en`)**, **Chinese (`zh`)**, **Korean (`ko`)**, **Japanese (`ja`)**, **Spanish (`es`)**, and **French (`fr`)** while keeping ingested research notes and database text in their original language.
- **Web UI**: Switch languages via the top nav language selector (`GET /set-language`), `?lang=<code>` query parameter, `stock_ontology_lang` cookie, `POST /api/language`, or browser `Accept-Language` header.
- **Environment & CLI**: Set `APP_LANGUAGE=zh` (or `en|zh|ko|ja|es|fr`) in `.env`, or pass `--lang` / `-l` to CLI commands (`serve`, `ask`, `chat`, `inspect`, `ingest`, `watch`).

## Repository Layout

```text
src/stock_ontology/       application code, nine modules (see docs/architecture/)
tests/                    offline test suite with fake LLM clients
tests/fixtures/sample_data/   research notes used by the tests
data/                     research notes to ingest (default ONTOLOGY_DATA_DIR)
ontology_registry.json    published canonical relations, companies, themes, and facet rules
docs/architecture/        one page per module, plus data flow and dependency layers
docs/proposals/           proposal pipeline ledgers, one per change
.codex/skills/            proposal pipeline and diagnostic skills
.claude/skills/           symlinks to .codex/skills/ for Claude Code
```

Start with [docs/architecture/README.md](docs/architecture/README.md) for the module map. `tests/test_architecture.py` keeps that map and the import layers in sync with the code. See [AGENTS.md](AGENTS.md) for the change process.

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

# 2b. Audit the database and write pending proposals to ontology_registry.suggestions.json
uv run stock-ontology audit

# 2c. Record the applied registry once on an existing database. Review before confirming.
uv run stock-ontology registry-apply

# 2d. Draft the proposed full registry JSON separately and increment its version.
#     Review and confirm publication, then separately review and confirm database adoption.
uv run stock-ontology registry-publish proposed-registry.json
uv run stock-ontology registry-apply

# 2e. Preview and confirm deterministic repairs under the applied registry.
uv run stock-ontology repair
uv run stock-ontology repair --json
# Add --reembed to recompute embeddings of merged survivors using the configured provider.
# Merge proposals can be marked approved or rejected in ontology_registry.suggestions.json.

# 3. Run the background worker: the only database writer. It applies queued jobs
#    (Process, corrections, `--no-wait` operator commands) and scans data/ for changes.
uv run stock-ontology watch --interval 60
uv run stock-ontology worker --once   # drain due work once and exit

# 3b. Agent-facing commands with JSON output; writes are queued as jobs.
uv run stock-ontology note save --title "NVDA check" --text "..." --json
uv run stock-ontology process _general/2026-11-24_nvda_check.md --json
uv run stock-ontology status <job_id> --json
uv run stock-ontology entity NVIDIA --json

# 4. Ask a single question or evaluate a new meeting note against DB consensus
uv run stock-ontology ask "We discussed AI Data Center Power Bottleneck — what are the related companies?"
uv run stock-ontology ask "Does this meeting note change our NVDA consensus?" --file path/to/meeting_note.md

# 5. Interactive PM chat (strictly read-only terminal REPL)
uv run stock-ontology chat

# 6. Start the 1990s Library Web UI + Office-Clippy read-only chat
uv run stock-ontology serve --host 127.0.0.1 --port 8000
```

## Deploying

Run `./deploy.sh` after pushing `main`. See [docs/deploy.md](docs/deploy.md).

## Ingestion Constraints

- Merge an extracted entity or theme into an existing node only on an exact ID, name, or alias match, or when the registry maps both to the same official company or theme. Never merge on embedding similarity; propose the pair as a registry merge suggestion instead.
  **Why:** a 0.15 cosine threshold merged competitors (AMD into NVIDIA at 0.114, nVent into Vertiv at 0.106) during the 2026-11-22 rebuild (proposal `exact-entity-merge`).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_does_not_merge_distinct_company_by_embedding_distance`.
- Write every note's rows inside one `OntologyDB.transaction()` that first clears that note's prior artifacts, and never let individual writes commit on their own.
  **Why:** a note that failed partway left partial rows and no log entry, and the next run wrote a second copy (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_mid_note_failure_leaves_no_rows_and_rerun_yields_one_copy`.
- Keep `ontology_registry.json` as the single source of truth for the minimal canonical edge vocabulary (`BUY`, `COMPETE`, `OWNS`, `WORKS_AT`, `EXPOSED_TO`, plus core plumbing relations): write and repair paths normalize via `OntologyRegistry.canonicalize_edge()` (ingestion holds unknown relations in `pending_edges` and counts them in `IngestReport.unmapped_relations_pending`, `audit --sync-suggestions` queues them in the separate proposal file, and a confirmed rollout or repair promotes them if the adopted registry maps the relation), and read paths (`OntologyDB`, web UI, and CLI) canonicalize in memory, deduplicate `(node, canonical_relation, direction)` with reconciled polarity, and render natural directional labels without mention counts.
  **Why:** un-normalized aliases, inverse pairs (`SUPPLIES_TO`/`CUSTOMER_OF`), and multi-note duplicate rows caused repeated theme and peer entries on entity pages such as Vertiv (proposal `minimal-entity-relationships`, 2026-11-22); dropping unmapped extracted edges instead of holding them would leave new relations no path to a suggestion (proposal `registry-schema-v2`, R1, 2026-11-23).
  **Guarded by:** `tests/test_official_facets.py::test_unmapped_edge_is_held_pending_suggested_by_audit_and_promoted_by_repair`, `tests/test_relationships.py::test_read_side_consolidation_and_natural_ux_labels`, `tests/test_relationships.py::test_write_side_normalization_oov_queueing_and_catalog_signatures`, and `tests/test_relationships.py::test_registry_driven_repair_and_reciprocal_contradiction_audit`.
- Set edge `basis` in code at each write (`extracted` in `IngestionPipeline`, `synthesized` in `OntologyDB.upsert_consensus_view`), never from the LLM, and have theme readers skip `synthesized` edges rather than filtering consensus by node type.
  **Why:** a theme-to-consensus `SUPPORTS` edge the LLM picked as evidence put Microsoft's consensus view on the Enterprise AI Monetization theme page as if it were about the theme (proposal `official-edge-facets`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_sets_edge_basis_by_code_not_by_llm`, `tests/test_web_research.py::test_theme_readers_skip_synthesized_edges`, and `tests/test_web_research.py::test_find_theme_companies_skips_synthesized_edges`.
- Never give a facet the registry requires (`facet_schema`) an ingest fallback, and give `IngestionPipeline` the loaded registry so it calls `OntologyDB.use_registry`. A missing or out-of-vocabulary required facet, or a `name` or `summary` over the registry's `metadata_max_length`, must fail the write with `FacetSchemaError`, which the pipeline answers by regenerating the extraction (3 calls, then the note fails). A bad optional `date` or `money` value (`as_of: Q3 2026`, `target_price: $650`) also regenerates; if it is still bad on the last attempt, only that facet is dropped and counted in `IngestReport.invalid_facets_dropped`. Any other optional official facet that cannot be coerced, including an optional enum outside its vocabulary, is dropped before the write (`OntologyRegistry.drop_uncoercible_optional`), as is any bad consensus facet, and the note is kept. `target_price` is `{amount, currency[, qualifier]}`; `repair` migrates older values, reading a missing currency from the source note. An extracted edge whose relation the registry does not map, or whose endpoints break the relation's `from_types` and `to_types`, is held in `pending_edges` (never dropped), counted in `IngestReport.unmapped_relations_pending` and the `ingest` output, and the note is kept. The extraction catalog lists each entity type's required facets from the registry.
  **Why:** the extraction models filled every omitted or unknown subtype with its fallback (`view_type` became `analyst_report`), so a missing subtype could never be detected, and official facets were not typed or enforced on write (proposal `typed-registry-schema`, 2026-11-23).
  **Guarded by:** `tests/test_official_facets.py::test_ingest_regenerates_extraction_missing_required_view_type`, `tests/test_official_facets.py::test_ingest_fails_note_after_regeneration_cap`, `tests/test_official_facets.py::test_ingest_drops_uncoercible_optional_facet_and_keeps_note`, `tests/test_official_facets.py::test_default_db_without_registry_refuses_missing_required_or_wrong_kind_facet`, `tests/test_official_facets.py::test_ingest_drops_optional_enum_outside_vocabulary_and_keeps_note`, `tests/test_official_facets.py::test_ingest_skips_unmapped_edge_keeps_mapped_edge_and_note`, `tests/test_pipeline.py::test_over_length_summary_fails_the_note_after_the_regeneration_cap`, and `tests/test_pipeline.py::test_consensus_synthesis_drops_uncoercible_optional_facet`.
- Keep registry publication and application separate. Use `registry-publish` and `registry-apply` for CLI confirmations. To confirm a browser record edit, start `serve --registry-actions` on a literal loopback address and open its exact local URL. Offer browser application only for an outstanding browser publication whose worker plan has been reviewed. Pin ordinary ingestion to the applied registry and write audit suggestions to a separate file.
  **Why:** the older checkout could change the live stamp while retaining incompatible price values (proposal `registry-governance`, 2026-11-23).
  **Guarded by:** `tests/test_registry_governance.py::test_publish_and_apply_require_separate_interactive_decisions`, `tests/test_registry_governance.py::test_writable_open_does_not_migrate_to_candidate_registry`, and `tests/test_registry_governance.py::test_audit_writes_proposals_without_changing_official_registry`.
- Resolve every extracted relation through the registry in the pipeline (`OntologyRegistry.canonicalize_edge`) before calling `upsert_edge`. `upsert_edge` and `update_edge` accept a mapped alias or inverse name but refuse a relation the registry does not map; tests that need a legacy unmapped row seed it by raw SQL (`tests/test_db.py::insert_legacy_edge`).
  **Why:** the pipeline only uppercased relation names, so 39 names drifted into `ontology.db`, including registered aliases and inverses such as `PARTNER_WITH` and `HAS_EMPLOYEE` (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_stores_registered_alias_and_inverse_relations_canonically`, `tests/test_official_facets.py::test_upsert_edge_refuses_relation_the_registry_does_not_map`, and `tests/test_db.py::test_update_edge_refuses_relation_the_registry_does_not_map`.
- Look up names and aliases with SQL over `name` and `aliases_json` (`OntologyDB.find_by_name_or_alias`), never with a capped Python scan, and keep the edge-reference fallback limited to entities and themes.
  **Why:** a 5,000-node scan ordered by recency let newer events and views push old entities out of the window, so ingestion created duplicate entities (proposal `ingestion-write-integrity`, 2026-11-22).
  **Guarded by:** `tests/test_pipeline.py::test_pipeline_resolves_old_entity_past_5000_newer_nodes`.
- Insert nodes, and change a node's name or aliases, only through `OntologyDB.upsert_node`. Raw SQL that does either skips the indexed `node_lookup` table, so name and alias lookups miss the node and ingestion creates duplicates. Raw deletes are fine (`node_lookup` cascades), as are raw updates to other columns such as `facets_json`. A writable open also rebuilds `node_lookup` if any node lacks a lookup row.
  **Why:** name lookup moved from a full scan to the `node_lookup` index (proposal `ingestion-followups`, 2026-11-22).
  **Guarded by:** `tests/test_db.py::test_node_lookup_uses_index_and_tracks_alias_edits_and_deletes`.
- Take a note's `doc_id` from its ingestion log entry, not from its current path. A moved note keeps its original `doc_id`, so a path-derived ID can collide with it.
  **Why:** moved notes are relinked instead of re-extracted (proposal `ingestion-followups`, 2026-11-22).
  **Guarded by:** `tests/test_db.py::test_moves_handle_root_folder_ambiguity_reused_paths_and_force`.
- Coerce every enum facet through `stock_ontology.vocab` when you write it, and compare stored values directly when you read them. Don't add a new copy of a vocabulary list or re-lowercase on read.
  **Why:** enum values were stored in whatever case the LLM returned, about 30 readers re-lowercased them inconsistently, and consensus retirement wrote `stale` in one path and `superseded` in another (proposal `canonical-vocabulary`, 2026-11-22).
  **Guarded by:** `tests/test_canonical_vocabulary.py` and `tests/test_vocab.py`.
- Drop a person's `accuracy` from extracted facets before ingest writes them, on both the single-call and staged paths, and refresh consensus for every company with a rumor by that person when the app changes it.
  **Why:** `accuracy` is our hand-set view of an author; ingest adds any facet a stored node lacks, so an extraction could otherwise rate an author from the note's own claims, and the note-scoped correction refresh would leave the person's other rumors weighed by the old rating (proposal `author-accuracy`, 2026-11-25).
  **Guarded by:** `tests/test_pipeline.py::test_reingest_never_sets_or_changes_person_accuracy`, `tests/test_staged_extraction.py::test_staged_extraction_cannot_set_a_person_accuracy`, and `tests/test_pipeline.py::test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors`.
- Run each worker job attempt on its own `Worker.open_store()` connection. The worker's long-lived queue connection serves only spool intake, claims, scan checks and failure records, and reopens once on `RegistryChangedError`.
  **Why:** executors change a connection's registry (`IngestionPipeline` calls `use_registry`), so a shared connection would carry one job's registry into the next; the queue connection replaced three opens per idle tick (proposal `worker-connection-reuse`, 2026-11-25).
  **Guarded by:** `tests/test_worker.py::test_idle_worker_opens_once_and_starts_a_spooled_job_within_two_seconds` and `tests/test_worker.py::test_reused_worker_connection_detects_a_registry_change_between_ticks`.

## Query Agent Constraints

- Register the ontology tools on the Pydantic AI agent as `async` functions with `sequential=True`, so they run on the thread that opened the `OntologyDB`. Never register a plain `def` tool that touches the DB.
  **Why:** Pydantic AI runs sync tools in worker threads, and the SQLite connection refused them ("objects created in a thread can only be used in that same thread"), so every ontology tool returned an error (proposal `pydantic-ai-agent`, 2026-11-22).
  **Guarded by:** `tests/test_agent.py::test_agent_ux1_meeting_note_consensus_check`.
- The web app talks to the agent only through `OntologyAgent(...)` and `OntologyAgent.chat()`. It stores `ChatTurn.history` per session without inspecting it and never reads or writes other agent attributes (`messages`, `tool_trace`, `last_provider`, and so on).
  **Why:** the pydantic-ai rewrite kept `/api/chat` working only because the agent's attribute names happened to survive; a stated contract lets agent internals change without breaking the web chat (proposal `agent-chat-contract`, 2026-11-22).
  **Guarded by:** `tests/test_web_clippy.py::test_web_chat_endpoint_uses_only_agent_chat` and `tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract`.
- Give the agent its chat model as a Pydantic AI `Model` (`OntologyAgent(..., model=, model_settings=)`, built by `build_agent_models`). Never route agent chat through `LLMClient` or wrap it in a custom `Model` adapter.
  **Why:** the custom `LLMClientModel` adapter dropped `model_settings`, so upstream controls such as `max_tokens` never reached the provider while Clippy was too verbose (proposal `native-pydantic-ai-models`, 2026-11-24).
  **Guarded by:** `tests/test_agent.py::test_agent_answers_through_native_model_with_model_settings` and `tests/test_agent.py::test_agent_falls_back_to_next_native_model_and_stamps_answering_provider`.
- Search the ontology, from the web page or the agent, only through `stock_ontology.search.search_ontology`, and read notes for a search word only through its `grep_notes`. Never add a second vector-then-keyword merge, and never let a vector hit outrank an exact name or alias match.
  **Why:** the web page and the agent each merged vector hits ahead of keyword hits, so searching "nvidia" showed "Consensus: Buy Apple Inc." before NVIDIA (proposal `ontology-search`, 2026-11-22).
  **Guarded by:** `tests/test_web_search.py::test_web_search_entity_first_card_sections_notes_and_agent_column`, `tests/test_agent.py::test_agent_search_nodes_returns_entity_first_with_match_reasons`, and `tests/test_web_search.py::test_web_search_reads_only_data_dir_notes_and_never_writes_db`.

## Web UI Constraints

- Add notes only through `services/notes.py::save_pasted_note`. Never write a note directly to its final path or replace an existing one: write a hidden temp file and publish it with `os.link`.
  **Why:** ingestion scans the data folder at any time, so a direct write can be read half-finished, and a check-then-write can overwrite a note saved at the same moment (proposal `paste-note`, 2026-11-23).
  **Guarded by:** `tests/test_web_notes.py::test_paste_note_never_overwrites_including_concurrent_same_title` and `tests/test_web_notes.py::test_paste_note_is_never_visible_to_ingestion_partially_written`.
- Register every HTML route and view variant in `src/stock_ontology/web/navigation.py` (workflow, owning section, archetype, breadcrumb) and let `_render` derive navigation from it; never set nav state in a template or view model, and never use `style=` or `<style>` in templates (add a class to `library.css`).
  **Why:** detail pages cleared every left-nav highlight because each view model hand-set `active_nav`, and 98 inline styles plus a second frame width let pages drift from one layout (proposal `codified-navigation-ux`, 2026-11-22).
  **Guarded by:** `tests/test_web_navigation.py`.
- Keep named Ontology explorer and Audit URLs reachable when changing the Registry landing. Use the published registry for shared definitions. Link relationship evidence only when the existing note reader resolves the same file as the logged source.
  **Why:** A saved explorer URL must still resolve, and the note reader trims the file query, which can otherwise send a citation to a different note (proposal `ontology-registry-and-schema`).
  **Guarded by:** `tests/test_web_ontology.py::test_ontology_registry_schema_browse_records_and_sources` and `tests/test_web_ontology.py::test_web_ontology_view_connected_to_registry_and_audit`.
- Bind each Registry browser confirmation to a server-held review. Recheck the completed worker plan or the selected note and reviewed graph fields before any write. Offer a source for a new relationship only if the note contains the anchor record, the record cites the note, or an extracted relationship connects the record to the note.
  **Why:** a stale adoption plan or an unrelated note can authorize changes the operator did not review (proposal `ontology-registry-editing`, R1).
  **Guarded by:** `tests/test_web_ontology.py::test_ontology_registry_editing_operator_two_decisions`, `tests/test_web_ontology.py::test_ontology_registry_editing_note_correction`, and `tests/test_web_ontology.py::test_ontology_registry_editing_relationship_add_source`.
- Give the entity and theme page templates (`entity.html`, `theme.html` and every partial they include, among them the shared `section_events.html` and `section_views.html`) only the presentation models built in `web/research/views.py`. Never pass a raw ontology node, `facets`, or `edge_facets` to them, and never read `.facets` in them; add a field to the model and map it in the view model instead. The catalog note page follows the same rule: `partials/note_reader.html` reads only the frozen `NoteDetail` built by `_note_detail` in `web/notes/views.py`, and links and labels are decided there, not in the template.
  **Why:** templates read raw facets and resolved sentiment inline, so the pages depended on how ontology data is shaped (proposals `company-view-separation` and `theme-view-separation`, 2026-11-22). The note page passed a raw dict and built its back and sibling links inline from the list state (proposal `event-view-separation`, 2026-11-22).
  **Guarded by:** `tests/test_web_research.py::test_entity_page_templates_only_see_presentation_models`, `tests/test_web_research.py::test_theme_page_templates_only_see_presentation_models` and `tests/test_web_notes.py::test_note_page_templates_only_see_presentation_models`.
- Treat an extraction as current only when its source hash matches and its entity membership has been recorded. Send Process and corrections through ingestion, as worker jobs. On an entity relink, update the selected note's attribution and edges while keeping shared entities and other notes' evidence.
  **Why:** canonical entities had no note membership of their own, so edge-only attribution missed isolated entities, and mutating a shared node to fix one match would affect unrelated notes (proposal `note-reader`, 2026-11-24).
  **Guarded by:** `tests/test_web_notes.py::test_note_reader_extraction_workflow` and `tests/test_db.py::test_note_entity_membership_follows_canonical_merge_and_document_removal`.
- Apply every correction's graph change through a public `IngestionPipeline` method built on `_correct_note`. Keep graph-row writes and private pipeline calls out of `Worker`; it claims the job, rechecks the review and moves the job's stage.
  **Why:** the worker's ontology-correction executor wrote graph rows itself and called private pipeline methods, so a pipeline change could break it silently, and each correction repeated its own transaction frame (proposal `pipeline-correction-api`, 2026-11-25).
  **Guarded by:** `tests/test_worker.py::test_worker_applies_graph_changes_only_through_public_pipeline_methods` and `tests/test_pipeline.py::test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus`.
- Add relationships with the current note's document ID and validate that the selected note owns a relationship before deleting it.
  **Why:** Two notes can independently support the same relationship. Adding or deleting one contribution must preserve the other (proposal `note-relationship-actions`).
  **Guarded by:** `tests/test_web_notes.py::test_note_reader_adds_and_deletes_relationships` and `tests/test_pipeline.py::test_delete_note_relationship_removes_only_its_pending_edge`.
- Judge every relationship correction, from the note reader or the Ontology page, with `services.corrections.review_note_correction` and apply it with `IngestionPipeline.apply_note_correction`. The note reader reviews at submit and queues the reviewed payload as `note.ontology.correction`; `note.relationship*` jobs can no longer be submitted, and the worker reviews any still queued by the same rules. Check a corrected, added or relinked edge only with `OntologyRegistry.check_note_edge`, and build names and aliases for record edits, person corrections and rollout only with `identity_aliases`, `identity_labels` and `labels_taken` in `services/registry.py`. Give an edge whose relation or endpoints change a new ID.
  **Why:** the two pages had separate edge validators that disagreed on duplicates, pending edges and errors, and identity edits were written three times (proposal `unified-note-corrections`, 2026-11-25).
  **Guarded by:** `tests/test_web_notes.py::test_note_reader_and_ontology_page_judge_a_relationship_correction_alike`, `::test_queued_legacy_relationship_jobs_are_judged_by_the_same_review`, `::test_note_reader_form_opened_before_an_ontology_correction_cannot_reapply`, `tests/test_relationships.py::test_check_note_edge_is_the_one_edge_rule_for_corrections` and `tests/test_registry_governance.py::test_record_edits_person_corrections_and_rollout_share_one_identity_rule`.
- When removing an entity from a note, remove its membership and that note's incident edges in one ingestion transaction. Keep the canonical entity and other notes' evidence.
  **Why:** A note's relationship table should reflect its entity corrections, and canonical entities can be referenced by many notes (proposal `note-entity-actions`).
  **Guarded by:** `tests/test_web_notes.py::test_note_reader_adds_and_deletes_entities`.
- Build every `/search` enum option in `build_search_filter_options` from `vocab.py` and relations from the loaded registry; never add values observed in the DB or a hand-kept list. Subtype and status options are `<node_type>:<value>` so a theme stage and a view type with the same name stay apart.
  **Why:** hand-kept lists merged with observed values offered stances such as `outperform` that the ontology does not define, and `consensus` matched both a consensus view and a consensus-stage theme (proposal `search-ontology`, 2026-11-22).
  **Guarded by:** `tests/test_search_ontology_options.py`.
- Submit browser edits, wait for their jobs, and build relationship editor choices only through `src/stock_ontology/web/static/editor.js` (`StockEditor`) and the one server model `web/shared.py::relationship_editor_model`; never add a job poller, JSON POST helper, or list-facet parser to a page script. Web code reads facet specs only through `OntologyRegistry.field_specs`, never `_facet_specs` or `_vocabulary`.
  **Why:** the note reader and Ontology page each had their own copy, and they drifted: one poller gave up after 300 tries while the other waited forever, and one split list facets on commas only (proposal `shared-editor-script`, 2026-11-25).
  **Guarded by:** `tests/test_web_ontology.py::test_page_scripts_post_and_poll_jobs_through_the_shared_editor_script` and `tests/test_web_ontology.py::test_note_reader_and_ontology_record_share_one_relationship_editor`.
- Never load every node or every entity to fill an editor. Pages embed only the nodes they show in `relationship_editor_model`; the editors find any other node by name or alias through `/api/nodes/search` (`OntologyDB.search_nodes_by_name`, at most 20 results, filtered by the endpoint types the relation allows).
  **Why:** the note reader and the Ontology record page put the whole graph into their HTML on every view, so page size and render time grew with every ingested note (proposal `node-typeahead`, 2026-11-26).
  **Guarded by:** `tests/test_web_ontology.py::test_editors_find_nodes_by_search_instead_of_loading_the_graph` and `tests/test_db.py::test_search_nodes_by_name_matches_names_and_aliases_within_types`.

## Tests (Offline)

```bash
uv run pytest -v
```
