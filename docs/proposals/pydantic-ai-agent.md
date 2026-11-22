---
proposal_id: "pydantic-ai-agent"
state: BUILT
witness: independent
candidate: "6d4b2d7 @ main + uncommitted working tree (manifest sha256 cbf1a3b1)"
---

# Proposal: Use Pydantic AI as the agent framework

## Proposal

### Intent

Switch the app's hand-rolled agent to Pydantic AI as the framework, so the app
can integrate with MCP or A2A.

### Tentative primary claim

The query agent answers PM questions over the ontology through Pydantic AI, and
is ready to integrate with MCP or A2A.

### Why now

The requester wants to integrate with MCP or A2A, and Pydantic AI has both built
in where LiteLLM does not.

### Known constraints

"Right now it should just be the ask section": the switch covers the agent
behind the Ask page (Reference Desk). "Keep the cli": the switch also
incorporates Pydantic AI into the CLI, meaning the `ask` and `chat` commands
that share that agent.

### Non-goals

None stated.

### Open choices

- Sequence: whether this proposal covers only the framework switch, or also an
  MCP integration, an A2A integration, or both. The request bundles parts that
  could ship separately.
- MCP direction: whether "integrate with MCP" means the agent using outside MCP
  tools, other agents querying the ontology through MCP, or both.
- Fallback: whether the current multi-provider fallback behavior must be kept
  as it is, or may change to whatever Pydantic AI offers.

## Frame

Candidate: `6d4b2d7 @ main, working tree /Users/jasonbxu/Documents/GitHub/stock_ontology (inspected 2026-11-22, before any change)`

### Verified reality
- `uv run pytest -q` — proves the offline suite was green before the change: 80 passed in 3.22s; limit: says nothing about live providers.
- `src/stock_ontology/agent.py:432` `OntologyAgent.ask` — proves the agent is a hand-rolled loop: it calls `LLMClient.generate_agent_reply` with `TOOL_SCHEMAS`, runs tool calls through `execute_tool` (`agent.py:412`), records `tool_trace`, and stops on a turn with no tool calls or after `max_rounds` (default 8) with `agent.max_rounds_reached`; limit: does not show provider-side behavior.
- `src/stock_ontology/agent.py:220` — proves `OntologyAgent` raises `ValueError` on a writable DB; limit: tool methods enforce read-only only through the DB handle.
- `src/stock_ontology/web/app.py:530` `chat_endpoint` — proves the Ask page contract: `POST /api/chat` restores `agent.messages` from an in-memory session store, calls `ask()`, saves `agent.messages` back, and returns `reply`, `tools_used` (from `tool_trace`), `provider`, `model`, `fallback_used`; limit: sessions are in memory only, not stored data.
- `src/stock_ontology/cli.py:470` `ask` and `cli.py:507` `chat` — prove both CLI commands build the same `OntologyAgent` and call `ask()`; `chat` also calls `reset()`; limit: none.
- `src/stock_ontology/llm/base.py:46` `AgentTurn` and `llm/router.py:237` — prove every provider returns a normalized turn (`text`, `tool_calls`, `raw_content`, `provider`, `model`, `fallback_used`) and the router applies fallback, error classification, and cooldowns; limit: none.
- `src/stock_ontology/llm/providers/gemini.py:151` — proves Gemini replays `raw_content` (a `types.Content`) on later turns, so a model turn's raw content must survive in history; limit: does not show which Gemini models require it.
- `tests/test_agent.py:136`, `test_web.py:152`, `test_i18n.py:196`, `test_relationships.py:130`, `test_llm_router.py:97`, `test_gemini.py:294`, `test_dashscope.py:221` — prove the offline tests drive the agent through fake `LLMClient`s that implement `generate_agent_reply`; limit: none.
- `uv run --isolated --no-project --with pydantic-ai-slim` (scratch env, 2.71.0) — proves `pydantic_ai.models.Model` needs only `request`, `model_name`, `system`; `ModelResponse` and `ToolCallPart` carry `provider_details`; `Tool.from_schema` accepts an existing JSON schema; `FunctionToolset` and `Agent(..., toolsets=...)` exist; `UsageLimits(request_limit=...)` bounds runs; `MCPToolset` needs the `[mcp]` extra; limit: `Agent.to_a2a` does not exist in 2.71.0, so built-in A2A support is unverified.

### Final primary claim
- The Ask page and the CLI `ask` and `chat` commands answer through a Pydantic AI `Agent`, and that agent accepts additional Pydantic AI toolsets (the interface MCP toolsets use), with every current answer behavior unchanged.

### Routing
- Witness: `independent`
- Why: it replaces the loop between the Ask page and CLI and the external LLM providers, crossing the agent-to-LLM component boundary and the `/api/chat` contract.
- Human-owned irreversible action: None.

### Decisive witness
- Layer: offline unit test on `OntologyAgent` with a scripted fake `LLMClient`.
- Permanent owner: `tests/test_agent.py`.
- Witness: an `OntologyAgent` built with an extra `FunctionToolset` holding a tool not among the seven ontology tools answers a question whose scripted model turn calls that tool; the tool runs, appears in `tool_trace`, and its result reaches the final reply. RED today because `OntologyAgent` takes no toolsets.

### Guardrail claims
- `OntologyAgent` still rejects a writable DB, and the seven ontology tools stay read-only (`tests/test_agent.py:229`, `tests/test_relationships.py:743`).
- `POST /api/chat` keeps returning `reply`, `tools_used`, `provider`, `model`, `fallback_used` as today, including router fallback, and a second request in the same session sees the first turn's history (`tests/test_web.py`, `tests/test_llm_router.py:556`, `tests/test_gemini.py:392`).
- `max_rounds` still bounds a model that never stops calling tools and returns the localized `agent.max_rounds_reached` message (`tests/test_agent.py:272`, `tests/test_i18n.py:235`).

### Supporting obligations
- Add a pinned `pydantic-ai-slim` dependency to `pyproject.toml` and refresh `uv.lock`; no extras.
- Add a Pydantic AI `Model` adapter over the existing `LLMClient`: convert `list[ModelMessage]` to today's message dicts, call `generate_agent_reply` with the run's tool schemas, return `TextPart`/`ToolCallPart`s, carry `raw_content` in `provider_details` so Gemini replay survives, and expose provider, model, and `fallback_used` for `last_*`. Unit-test the round trip, including a Gemini-style `raw_content` turn.
- Register the seven tools with `Tool.from_schema` from the existing `TOOL_SCHEMAS`, so the model sees the same names, descriptions, and schemas; keep `execute_tool` as the dispatch and `tool_trace` as the record.
- Map `max_rounds` to `UsageLimits(request_limit=...)` and turn `UsageLimitExceeded` into the localized message.
- Keep `messages`, `reset()`, `last_provider`, `last_model`, `last_fallback_used` as the public surface `web/app.py` and `cli.py` use; `messages` may hold `ModelMessage` objects since callers only copy it.
- Confirm `Agent.run_sync` works from FastAPI's sync handler threads and from the CLI.
- Keep `_resolve_node`'s `llm.embed_texts` call on the existing client.

### Allowed scope
- Reuse: the existing `LLMClient`/`LLMRouter` and providers stay as the model layer under a thin Pydantic AI `Model` adapter; the existing fake `LLMClient`s keep driving the tests.
- Cheaper alternative: None smaller. Leaving the loop as is fails the claim. The rejected larger option is native Pydantic AI provider models with `FallbackModel`, which would change fallback behavior (no error classification or cooldowns), add the Anthropic and OpenAI SDKs, and rewrite every test fake.
- Include: `pyproject.toml`, `uv.lock`, `src/stock_ontology/agent.py`, one new adapter module under `src/stock_ontology/llm/`, focused tests in `tests/test_agent.py` and existing agent-facing tests only where the message type changes.
- Exclude/protect: `llm/providers/`, `llm/router.py`, ingestion (`pipeline.py`, `ingest`, `reembed`, `watch`, `audit`, `repair`), `inspect`, web templates and `clippy.js`, any MCP or A2A server or client, the `[mcp]` extra, embeddings, and the read-only DB invariant.

### Invariants changed
- None.

### Decisions required
- None. The Proposal's open choices are settled by the cheapest option that meets the claim: this proposal is the framework switch only, with MCP and A2A integration left to later proposals (so MCP direction is not decided here), and the router's current fallback behavior is kept unchanged.

## Proof

Candidate: `working tree @ /Users/jasonbxu/Documents/GitHub/stock_ontology, inspected 2026-11-22, before any product change. The Frame says this is not a git repo, but it is one: HEAD 6d4b2d709fa4a9561354aed956a7acd16c9b5911 on main, with uncommitted ledger edits that predate this stage. The only change Prove made is the witness appended to tests/test_agent.py.`

**Protected witness**
- `The Ask page and CLI agent answers through a Pydantic AI Agent that accepts additional Pydantic AI toolsets` — `tests/test_agent.py` / `test_agent_runs_tools_from_extra_pydantic_ai_toolset` (helper fake `ExtraToolsetLLM` in the same file)
  - Defect and boundary: `OntologyAgent` has no toolsets parameter, and its hand-rolled loop offers and dispatches only the seven hard-coded `TOOL_SCHEMAS` through `execute_tool`, so it can't accept a Pydantic AI toolset (the interface MCP toolsets use); the boundary is the agent loop between the read-only ontology agent and the `LLMClient` model layer.
  - Assertion: an `OntologyAgent` built with `toolsets=[FunctionToolset([get_house_view])]` over a read-only DB answers "What is the house view on NVDA?". The fake model calls `get_house_view` only if that name appears in the tool schemas it is offered; otherwise it replies "not offered". The test asserts that the reply contains `get_house_view` and the tool's sentinel result `OVERWEIGHT-7731`, that `tool_trace` is exactly `[get_house_view]` with args `{"ticker": "NVDA"}`, and that DB stats are unchanged. This proves the extra toolset's tool is offered to the model through the existing `LLMClient` contract, actually runs, has its result fed back into the next model turn and into the final reply, is recorded in `tool_trace`, and leaves the DB untouched. Limit: it does not prove that an MCP toolset works, which needs the excluded `[mcp]` extra. It also doesn't prove that the seven ontology tools keep identical schemas, that Gemini `raw_content` replay survives, that `max_rounds` is mapped, or that the `/api/chat` fields are unchanged. Those stay with the guardrail tests and supporting obligations.
- Guardrail claims (writable DB rejection, read-only tools, the `/api/chat` contract including fallback and session history, the `max_rounds` localized message) got no new RED witness. They describe behavior that already exists, so a new assertion can't be observed failing for missing behavior. They stay protected by the existing green owners Frame named, which must still pass unchanged after Build: `tests/test_agent.py::test_agent_requires_read_only_db`, `tests/test_agent.py::test_agent_tool_error_and_max_rounds_guard`, `tests/test_relationships.py:743`, `tests/test_web.py`, `tests/test_llm_router.py:556`, `tests/test_gemini.py:392`, `tests/test_i18n.py:235`. Their message-type edits are limited to what Frame's Allowed scope permits.
- Protected paths: `tests/test_agent.py` (the new witness, `ExtraToolsetLLM`, and the existing `ScriptedAgentLLM`, `_seed_db`, `test_agent_requires_read_only_db`, `test_agent_tool_error_and_max_rounds_guard` it relies on or that guard the claims).
- Protected revision: `tests/test_agent.py` sha256 `38459b4c3d9171231fd0c5743315566f0927dd9d7d095cf5271b3aaae365a3ef`. Snapshot at `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/test_agent.protected.py`. The pre-proof copy is at `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/test_agent.pre-proof.py`. Also compare with `git diff 6d4b2d7 -- tests/test_agent.py`, which shows +52 lines appended and no existing lines changed.

**Red evidence**
- `uv run --with 'pydantic-ai-slim==2.71.0' python -m pytest tests/test_agent.py::test_agent_runs_tools_from_extra_pydantic_ai_toolset -v` → 1 failed: `TypeError: OntologyAgent.__init__() got an unexpected keyword argument 'toolsets'`. This is the decisive RED: with Pydantic AI importable in a temporary overlay (pyproject.toml and uv.lock untouched), the test fails because `OntologyAgent` doesn't accept toolsets. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/red-overlay.log`.
- `uv run pytest tests/test_agent.py::test_agent_runs_tools_from_extra_pydantic_ai_toolset -v` (project env) → 1 failed: `ModuleNotFoundError: No module named 'pydantic_ai'`. Context only, not RED: it shows the dependency obligation is unmet. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/red-project-env.log`.
- `uv run pytest -q` → 1 failed (the new witness), 80 passed. The rest of the suite is unaffected because the witness imports `pydantic_ai` inside the test function. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/suite.log`.
- The primary claim has no proof until the overlay command above is observed RED. That has now been observed, and Build must turn it green in the project env with no overlay.

**Supporting test plan**
- Pydantic AI `Model` adapter over `LLMClient`: ModelMessage-to-dict round trip, `TextPart`/`ToolCallPart` output, Gemini-style `raw_content` carried in `provider_details` and replayed on the next turn, and provider, model and `fallback_used` exposed as `last_*` → Build: `tests/test_agent.py` (or the new adapter's focused test in the same owner). Catches lost Gemini replay content and wrong Ask page `provider`/`model`/`fallback_used`.
- Seven ontology tools registered via `Tool.from_schema` from `TOOL_SCHEMAS`, with the same names, descriptions and schemas as offered today → Build: `tests/test_agent.py`. Catches schema drift that changes model tool selection.
- `max_rounds` mapped to `UsageLimits(request_limit=...)`, with `UsageLimitExceeded` turned into the localized `agent.max_rounds_reached` → Build: the existing `tests/test_agent.py::test_agent_tool_error_and_max_rounds_guard` and `tests/test_i18n.py:235` stay green. Catches an unbounded loop or an uncaught exception reaching the Ask page or CLI.
- `pydantic-ai-slim` pinned with no extras in `pyproject.toml` and `uv.lock` → Build: `uv run pytest tests/test_agent.py::test_agent_runs_tools_from_extra_pydantic_ai_toolset -v` passes without `--with`. Catches a missing or unpinned dependency.
- `Agent.run_sync` called from FastAPI sync handler threads and from the CLI → Build: the existing `tests/test_web.py` chat tests and the CLI ask/chat tests. Catches event-loop errors in threaded handlers.

## Build

Candidate: `6d4b2d7 @ main + uncommitted working tree` (/Users/jasonbxu/Documents/GitHub/stock_ontology). Fingerprint: the per-file manifest `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/candidate-manifest.sha256` hashes to sha256 `cbf1a3b1c1a90f5612caff9ce94f4f88136144a1df1b472e96c3651ebb9efe3a`.

The manifest lists these files:
- README.md `38a4216f…fd36`
- pyproject.toml `9e043057…aaf1`
- uv.lock `1cc331f7…1880`
- src/stock_ontology/agent.py `f00ad10c…aaaa`
- src/stock_ontology/cli.py `9cb15721…4862`
- src/stock_ontology/llm/pydantic_ai_model.py `cc2c1495…964d`
- tests/test_agent.py `71125341…90b2`
- tests/test_gemini.py `8615e3e8…39fe`

Build did not touch the other uncommitted ledgers (`entity-first-search.md`, `codified-navigation-ux.md`, `ontology-search.md`) or this ledger.

### Files changed

- `pyproject.toml`: adds `pydantic-ai-slim==2.71.0` with no extras, for the pinned-dependency obligation.
- `uv.lock`: refreshed by `uv sync`. It adds pydantic-ai-slim 2.71.0, pydantic-graph, genai-prices, griffelib and logfire-api, with no extras.
- `src/stock_ontology/llm/pydantic_ai_model.py` (new adapter module), for the primary claim and the adapter obligation:
  - `LLMClientModel(Model)` wraps the existing `LLMClient`.
  - `to_llm_messages` converts `ModelMessage` history into today's message dicts. `from_agent_turn` builds `TextPart` and `ToolCallPart`.
  - `raw_content` is kept in `ModelResponse.provider_details`. Each provider `call_id`, including `None`, is kept in `ToolCallPart.provider_details`, so Gemini replay and calls without an id survive.
  - An `on_turn` callback feeds `last_*`.
- `src/stock_ontology/agent.py`: `ask()` now runs a Pydantic AI `Agent` through `run_sync`. This covers the primary claim and the max_rounds guardrail.
  - The seven tools are registered with `Tool.from_schema` from `TOOL_SCHEMAS`. Each handler is `async`, marked `sequential=True`, and dispatches through `execute_tool`.
  - A new `toolsets=` parameter takes extra toolsets. Each one is wrapped in `_TracedToolset`, which records its calls in `tool_trace`.
  - `max_rounds` maps to `UsageLimits(request_limit=max_rounds)` plus `retries={"tools": max_rounds, "output": max_rounds}`. `UsageLimitExceeded` becomes the localized `agent.max_rounds_reached` message, and history is kept through `capture_run_messages`.
  - `messages` now holds `ModelMessage`s. `reset()` and `last_provider`, `last_model` and `last_fallback_used` keep their names.
- `src/stock_ontology/cli.py` (scope added by the human decision on deviation 3): adds `import os` and a module-level `os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")`. It runs on import, before any agent runs, so `ask`, `chat` and `serve` don't print Pydantic AI's banner. `serve` runs `uvicorn.run` in the same process, so it inherits the setting.
- `tests/test_agent.py`: appends `RecordingAgentLLM`, `test_agent_offers_ontology_tools_with_existing_schemas_and_prompt` and `test_pydantic_ai_model_round_trips_raw_content_call_ids_and_provider` after the protected content.
  - Before Build, the whole file matched the Proof snapshot.
  - After Build, the first 18279 bytes (the snapshot's length) still hash to sha256 `38459b4c3d9171231fd0c5743315566f0927dd9d7d095cf5271b3aaae365a3ef`, the same as `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/test_agent.protected.py`.
  - `git diff 6d4b2d7 -- tests/test_agent.py` shows 0 removed lines.
- `tests/test_gemini.py`: changed only for the new message type, which Frame allows. Lines 302-303 now check `to_llm_messages(agent.messages)[1]` instead of subscripting `agent.messages[1]`. The assertions are the same: `text is None` and `call_id == "call_gem_1"`.
- `README.md`: one constraint entry under a new "Query Agent Constraints" heading.
  - It says to register the ontology tools as `async` with `sequential=True`. Sync tools run in worker threads, and SQLite rejects a connection used from another thread. I saw this fail when I switched the handlers to plain `def`.
  - Guarded by `tests/test_agent.py::test_agent_ux1_meeting_note_consensus_check`.

### Unit evidence

- Decisive witness RED: already observed by Proof (`/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/proof/red-overlay.log`). This is the independent route, so there is no builder-owned witness.
- The adapter and agent code were written before their two supporting unit tests. To get RED afterwards, I ran the current `tests/test_agent.py` against a `git archive 6d4b2d7` copy of the base tree with the project venv: `python -m pytest tests/test_agent.py -k "existing_schemas or round_trips or extra_pydantic" -v`.
  - The round-trip test is RED: it fails at the `ModelResponse` assertion.
  - The witness is RED: `TypeError ... 'toolsets'`.
  - The schema and prompt test passes at base. That's expected, since it guards behavior that shouldn't change.
  - log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/red-supporting.log`.
- `uv run pytest tests/test_agent.py -v`: GREEN, 8 passed, including both supporting tests, `test_agent_requires_read_only_db` and `test_agent_tool_error_and_max_rounds_guard`.
- Thread constraint: switching the tool handlers to sync `def` for a moment made `tests/test_agent.py` fail with the SQLite same-thread error. I then restored the file byte for byte from a backup.
- Edge-behavior probe, using fake LLMs only. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/probe.log`.
  - A turn with text and tool calls runs the tools and continues.
  - `max_rounds=2` makes exactly 2 model calls.
  - The offered schemas equal `TOOL_SCHEMAS`.
  - Bad tool args return a traced `{"error"}` dict.
  - Provider exceptions propagate unwrapped.
  - The empty-turn and unknown-tool cases behave as described in Deviations 1 and 2.
- Offline CLI smoke after the banner change: `env -u PYDANTIC_AI_NO_BANNER -u GEMINI_API_KEY -u DASHSCOPE_API_KEY -u OPENAI_API_KEY -u ANTHROPIC_API_KEY uv run python /private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/cli_smoke.py`, with `create_llm_client` patched to a fake.
  - `ask` exits 0 and `chat` exits 0, both with the expected answers.
  - The banner is absent: stderr is 0 bytes and neither stream contains "pydantic-ai v" or "NO_BANNER". The smoke run before the change printed it once.
  - logs: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/cli-smoke-nobanner.stdout.log`, `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/cli-smoke-nobanner.stderr.log`. Pre-change log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/cli-smoke.log`.

### Green evidence

- Decisive witness: `uv run pytest tests/test_agent.py::test_agent_runs_tools_from_extra_pydantic_ai_toolset -v` passes in the project env with no overlay, on the final tree. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/witness.log`.
- Guardrail owners: `uv run pytest -v tests/test_web.py tests/test_llm_router.py tests/test_gemini.py tests/test_i18n.py tests/test_relationships.py tests/test_dashscope.py` passes, 46 passed. This run was before the cli.py change, and the full gate below covers those tests again. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/guardrails.log`.
- Gate: `uv sync`, then `uv run pytest -v` on the final tree, passes with 83 passed. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/gate.log`.
- Lint: `uv run ruff check --select F,E9` passes on all changed Python files, including cli.py. The repo's configured `ruff check` reports one TRY003 on the read-only `ValueError` in `agent.py`, which is unchanged from base. log: `/private/tmp/claude-502/-Users-jasonbxu-Documents-GitHub-stock-ontology/e10265b9-d763-427c-a100-e1c5e78afb3a/scratchpad/build/ruff.log`.

### Intervention record

- None. The repository has no intervention ledger, and this framework switch adds no user-facing outcome to measure.

### Deviations

1. Empty model reply. Resolved by the human ("Accept all four"): the new behavior is accepted.
   - Before, a turn with no text and no tool calls returned `""`.
   - Now Pydantic AI asks the model to retry, the retries are bounded by `max_rounds`, and the run ends with the localized `agent.max_rounds_reached` message.
   - No workaround.
2. Unknown tool names. Resolved by the human: accepted.
   - Pydantic AI now answers hallucinated tool names with its own retry message, so they no longer appear in `tool_trace` or `/api/chat` `tools_used`.
   - Retries for them are bounded by `max_rounds`. No shim.
3. CLI banner. Resolved by the human: suppress it.
   - Implemented in `src/stock_ontology/cli.py` with `os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")` at import. This expanded scope by one path, and the human approved it.
   - The offline smoke run shows the banner is gone from stderr for `ask` and `chat`.
4. README "Query Agent Constraints" entry. Resolved by the human: kept as written.

None remain open.

## Audit

## Revisions
