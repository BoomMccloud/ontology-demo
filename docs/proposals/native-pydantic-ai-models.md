---
proposal_id: "native-pydantic-ai-models"
state: ACCEPTED
witness: independent
candidate: "01f65f3 @ worktree .claude/worktrees/native-pydantic-ai-models (branch proposal/native-pydantic-ai-models)"
---

# Proposal: Run Clippy on off-the-shelf Pydantic AI models

## Proposal

### Intent

Stop running the agent through a custom harness. "I don't want custom harness,
I rather use off the shelf so I can get more features and functionalities
upstream." Clippy's agent should use Pydantic AI's own model classes, so
features such as model settings (for example `max_tokens`), streaming, token
usage, thinking and caching work as upstream ships them.

### Tentative primary claim

Clippy answers PM questions through Pydantic AI's off-the-shelf models, so
upstream Pydantic AI model features apply to Clippy without custom adapter code.

### Why now

Clippy is extremely verbose, and the upstream controls that could help (such as
model settings) are ignored by the current custom adapter.

### Known constraints

"Agent only": the change covers the agent behind Clippy. Ingestion
(extraction, consensus synthesis, embeddings) stays on the existing LLM router.

### Non-goals

Migrating ingestion to Pydantic AI.

### Open choices

- Fallback behavior: the existing router skips a failed provider for 60 seconds
  and classifies errors; off-the-shelf fallback may not. Whether losing that is
  acceptable for the agent.
- Sequence: whether this proposal also shortens Clippy's answers, or only
  enables the upstream controls for a later change.
- Providers: whether the agent keeps all three configured providers (Gemini,
  DashScope, Anthropic) or only the ones the deployment uses.

## Frame

Candidate: `ce3a230 @ main checkout /Users/jasonbxu/Documents/GitHub/stock_ontology` (untracked: this ledger, `docs/proposals/app-login.md`)

### Verified reality
- `uv run pytest -q` at `ce3a230` — proves the offline suite was green before this change (543 passed); limit: offline only, no live provider exercised.
- `src/stock_ontology/llm/pydantic_ai_model.py:LLMClientModel.request` — proves the agent's only model is a custom adapter that forwards system prompt, messages and tool schemas to `LLMClient.generate_agent_reply` and ignores `model_settings`; it reports no token usage and has no streaming method; limit: does not show which upstream features users want first.
- `src/stock_ontology/agent.py:OntologyAgent.ask` (542–569) — proves `Agent(model, toolsets=...)` is built per call with no `instructions` or `model_settings`, bounded by `UsageLimits(request_limit=max_rounds)`; limit: none.
- `src/stock_ontology/agent.py:OntologyAgent._record_turn` / `chat` — proves `ChatTurn.provider/model/fallback_used` come from the router's `AgentTurn` stamps; limit: none.
- `src/stock_ontology/llm/router.py:LLMRouter._execute` / `generate_agent_reply` — proves the current agent path gets error classification, a cooldown of `llm_cooldown_seconds` (default 60) after `rate_limit`/`auth`/`config` errors, and a "cooled providers last" ordering; limit: shared with ingestion, which stays.
- `src/stock_ontology/config.py:19,143–169` — proves five chat providers are configurable (`gemini`, `dashscope`, `openai`, `anthropic`, `openai_compatible`), with `dashscope_api_url` (OpenAI-compatible) and `anthropic_api_url` defaulting to `https://api.anthropic.com/v1`; limit: does not show which the deployment uses (live `/api/health`: gemini then dashscope).
- `uv run python -c "import pydantic_ai.models.<x>"` on 2.71.0 — proves `models.google` imports (google-genai is locked), while `models.openai` and `models.anthropic` fail for missing `openai` / `anthropic` SDKs; `FallbackModel(default_model, fallback_models, fallback_on)` defaults `fallback_on` to `(ModelAPIError,)`, which `ModelHTTPError` (incl. 429) subclasses; `models.function.FunctionModel` exists for offline fakes; limit: no live call made.
- `src/stock_ontology/web/clippy/routes.py:chat_endpoint` — proves `/api/chat` builds `OntologyAgent(db, shell.llm, ...)` per request and returns `turn.provider/model/fallback_used`; `shell.llm` is the router (`web/shell.py:91–94`); limit: none.
- `src/stock_ontology/cli.py:710,735` — proves CLI `ask`/`chat` build `OntologyAgent(store, llm, ...)`; limit: none.
- `src/stock_ontology/agent.py` tool handlers (`_tool_search_nodes` via `search_ontology(self.db, self.llm, ...)`) — proves the agent still needs `LLMClient` for embeddings inside tools, separately from the chat model; limit: none.
- Tests on the reply path: `tests/test_agent.py` (`ScriptedAgentLLM` and subclasses, `test_pydantic_ai_model_round_trips_raw_content_call_ids_and_provider`, `test_agent_chat_returns_immutable_turn_contract`), `tests/test_llm_router.py::test_cross_provider_agent_turn_fallback_gemini_and_dashscope`, `::test_web_health_and_chat_report_provider_and_no_secret_leak`, `tests/test_gemini.py::test_gemini_agent_tool_calling_thought_filtering_and_empty_tools`, `::test_cross_provider_fallback_dashscope_to_gemini_sets_thought_signature`, `tests/test_dashscope.py::test_dashscope_embeddings_structured_and_agent_tools`, `tests/test_i18n.py::test_ontology_agent_language_prompt_and_max_rounds`, `tests/test_relationships.py::test_guardrail_read_only_agent_web_inspect_and_audit`, plus the `generate_agent_reply` fake in `tests/web_support.py`; limit: grep-based map.
- `docs/architecture/README.md:13`, `agent.md:9`, `llm.md:15,28` — prove the module map names `llm/pydantic_ai_model.py` and `generate_agent_reply`, and `tests/test_architecture.py` keeps that map in sync; limit: none.

### Final primary claim
- Clippy (`/api/chat`) and CLI `ask`/`chat` answer through Pydantic AI's off-the-shelf model classes (`GoogleModel`, `OpenAIChatModel`, `AnthropicModel` in a `FallbackModel`), so a `model_settings` value set on the agent reaches the provider request with no custom adapter in between.

### Routing
- Witness: `independent`
- Why: the change replaces the agent's boundary to external LLM providers, including fallback and error handling on every Clippy and CLI answer.
- Human-owned irreversible action: merging to `main` and running `./deploy.sh` to the production server; the deploy also needs `openai` and `anthropic` installed there.

### Decisive witness
- Layer: offline agent unit test with a recording Pydantic AI `FunctionModel`.
- Permanent owner: `tests/test_agent.py`.
- Witness: an `OntologyAgent` given a Pydantic AI model and a `model_settings` value (e.g. `{"max_tokens": 123}`) answers a question, the model receives that value in its `ModelSettings`, and the agent's `LLMClient` receives no chat call.

### Guardrail claims
- When the first configured chat provider raises an API error (such as a 429), the turn is answered by the next configured provider and `ChatTurn.provider`, `model` and `fallback_used` name the provider that answered.
- `OntologyAgent` still rejects a writable DB, its ontology tools stay read-only and `sequential=True`, and `/api/chat` still uses only `OntologyAgent(...)` and `chat()` with opaque `ChatTurn.history`.
- After a chat provider fails with a rate-limit or auth error, the agent's following turns within `llm_cooldown_seconds` try the other configured providers first and use the cooled provider only as a last resort, as `LLMRouter` does today.
- Ingestion (extraction, consensus synthesis, embeddings) and `/api/health` keep running on `LLMRouter` unchanged.

### Supporting obligations
- Add a builder (e.g. `stock_ontology/llm/agent_model.py:build_agent_model(settings)`) that maps the configured chat chain to native models: `gemini`→`GoogleModel`; `dashscope`, `openai`, `openai_compatible`→`OpenAIChatModel` with `OpenAIProvider(base_url, api_key)`; `anthropic`→`AnthropicModel` with the `/v1` suffix stripped from `anthropic_api_url`. Unit test: chain order and base URLs, offline.
- `OntologyAgent` takes the chat model as an argument (keeping `llm` for tool embeddings); set `instructions=build_agent_system_prompt(...)` on the `Agent`; read provider and model from the answering `ModelResponse` (`provider_name`, `model_name`) and derive `fallback_used`.
- Keep a small cooldown wrapper (human decision 2026-11-24): one long-lived object per process that holds the native models and a cooldown map, builds each turn's `FallbackModel` with cooled models ordered last, and records a cooldown from `fallback_on` when a model raises `ModelHTTPError` 429/401/403 (or `ModelAPIError` the router would classify as rate_limit/auth/config). Reuse `classify_error` where it fits. Unit test with a fake clock and `FunctionModel`s.
- Web shell and CLI build that object once from settings and pass it in.
- Replace `generate_agent_reply` fakes in agent tests with `FunctionModel`; delete `LLMClientModel`, `generate_agent_reply` (protocol, base, router, three providers), `AgentTurn`/`ToolCall`, and their provider-level tests.
- Add `pydantic-ai-slim[google,openai,anthropic]==2.71.0` to `pyproject.toml` and refresh `uv.lock`.
- Update `README.md` (LLM router and Calling the Agent sections) and `docs/architecture/{README,agent,llm}.md`.

### Allowed scope
- Reuse: extends the existing Pydantic AI `Agent` in `OntologyAgent.ask` and the existing `Settings` provider chain (`resolve_provider_chain`); `LLMRouter` stays for ingestion and tool embeddings.
- Cheaper alternative: making `LLMClientModel` forward `model_settings` into `generate_agent_reply` was rejected, because the Proposal asks for no custom harness and upstream features (streaming, usage, thinking, caching) would each still need adapter work.
- Include: `src/stock_ontology/agent.py`, `src/stock_ontology/llm/` (new builder; removal of the agent-reply path), `src/stock_ontology/web/shell.py` and `web/clippy/routes.py` (model wiring only), `src/stock_ontology/cli.py` (`ask`/`chat` wiring), `pyproject.toml`, `uv.lock`, the tests listed in Verified reality, `README.md`, `docs/architecture/`.
- Exclude/protect: ingestion paths (`pipeline.py`, `worker.py`, router `extract_*`, `synthesize_consensus`, `embed_texts`); `/api/health` output; the system prompt text and answer length (human decision 2026-11-24: brevity is a follow-up proposal); deploy scripts and the production server.

### Invariants changed
- `README.md:37` — today: `LLMRouter` fallback and cooldowns cover every LLM call, including the agent; after: they cover ingestion and embeddings, and the agent falls back through Pydantic AI `FallbackModel` with its own cooldown on the same `LLM_COOLDOWN_SECONDS`.
- `README.md:55` (`turn.provider, turn.model, turn.fallback_used`) — today: stamped by `LLMRouter`; after: taken from the answering `ModelResponse`.
- `tests/test_llm_router.py::test_cross_provider_agent_turn_fallback_gemini_and_dashscope`, `tests/test_gemini.py::test_cross_provider_fallback_dashscope_to_gemini_sets_thought_signature`, `tests/test_agent.py::test_pydantic_ai_model_round_trips_raw_content_call_ids_and_provider` — today: guard the router-based agent reply path (named as protected owners in `pydantic-ai-agent`); after: removed or rewritten against `FallbackModel`.
- `docs/proposals/pydantic-ai-agent.md` Frame's rejected option (native models with `FallbackModel`) — today: rejected; after: adopted by this Proposal. That ledger stays unedited.

### Decisions required
- None. Settled by the human on 2026-11-24: keep a small cooldown wrapper for the agent; answer brevity goes to a follow-up proposal.

## Proof

Candidate: `ce3a230 @ worktree .claude/worktrees/native-pydantic-ai-models (branch proposal/native-pydantic-ai-models)` plus the uncommitted witness diff to `tests/test_agent.py` (+95 lines appended; nothing else changed). Independence: separate subagent context.

**Assumed public interface (Build must satisfy)**
- `OntologyAgent(db, llm, *, model: pydantic_ai.models.Model, model_settings: pydantic_ai.settings.ModelSettings | None = None, language=..., toolsets=..., data_dir=...)`. `model` accepts any plain Pydantic AI `Model` (including `FunctionModel` and `FallbackModel`); if Build passes its cooldown wrapper some other way, `model=` must still accept a plain `Model`. `llm` stays for tool embeddings.
- The agent passes `model_settings` to every model request and sends `build_agent_system_prompt(language)` as Pydantic AI `instructions`.
- `ChatTurn.provider`/`model` come from the answering `ModelResponse.provider_name`/`model_name`; `fallback_used` is `False` when the first model in the chain answers and `True` when a later one does.
- A scratch stand-in implemented this shape and both witnesses passed against it, so the assertions are satisfiable and not tied to that implementation.

**Protected witness**
- Primary: `tests/test_agent.py::test_agent_answers_through_native_model_with_model_settings` (helper `_NoChatLLM`).
  - Defect and boundary: `OntologyAgent.ask` always wraps `LLMClient` in the custom `LLMClientModel`, which drops `model_settings` and cannot take a native model; boundary is agent → LLM provider model.
  - Asserts a recording `FunctionModel` receives `max_tokens == 123` and `instructions == build_agent_system_prompt()` on both requests (tool round and final answer), `list_catalog` runs, the reply is the model's text, `ChatTurn` is `("gemini", "gemini-test", False)`, and `LLMClient.generate_agent_reply` gets 0 calls.
  - Limit: does not prove `GoogleModel`/`OpenAIChatModel`/`AnthropicModel` are built from settings or send `max_tokens` on the wire; does not cover web or CLI wiring.
- Guardrail (fallback): `tests/test_agent.py::test_agent_falls_back_to_next_native_model_and_stamps_answering_provider`.
  - Defect and boundary: the agent cannot run a `FallbackModel` chain and its stamps come only from the router's `AgentTurn`; boundary is agent → provider fallback chain.
  - Asserts a `FallbackModel` of a `FunctionModel` raising `ModelHTTPError(429)` then one answering (`dashscope`, `qwen-test`) is called in order `["gemini", "dashscope"]`, the reply is the fallback's text, `ChatTurn` is `("dashscope", "qwen-test", True)`, and `LLMClient` gets 0 chat calls.
  - Limit: does not prove cooldown ordering across turns or 401/403/config classification.
- Guardrails not newly witnessed (existing behavior, cannot go RED), kept by existing green owners that must stay green without weakened assertions: `tests/test_agent.py::test_agent_requires_read_only_db`, `::test_agent_chat_returns_immutable_turn_contract` (only its fake model and provider stamps may be rewritten), `tests/test_relationships.py::test_guardrail_read_only_agent_web_inspect_and_audit`; ingestion and `/api/health` by the existing ingestion and health tests in `tests/test_llm_router.py` and `tests/test_pipeline.py`.
- Protected paths: in `tests/test_agent.py`, the two witness functions and `_NoChatLLM`. If upstream `generate_agent_reply` is deleted, `_NoChatLLM.generate_agent_reply` may remain as an unused trap; do not delete it or the `chat_calls == 0` assertions. The rest of `tests/test_agent.py` stays Build-editable under Frame's obligation to replace `generate_agent_reply` fakes.
- Protected revision: `work/native-pydantic-ai-models/witness.patch` (sha1 `78465b9aa5c5fa5045e05cbbd1ec22913bbcb77c`) on `ce3a230`; `tests/test_agent.py` blob at RED `0e3d363c09b58a70036521b0beb9eb75a24e6ef8`.

**Red evidence**
- `cd .claude/worktrees/native-pydantic-ai-models && uv run pytest tests/test_agent.py -v -k "native_model or falls_back_to_next_native"` → 2 failed, both `TypeError: OntologyAgent.__init__() got an unexpected keyword argument 'model'` at construction (the missing behavior); imports, DB seed and `FunctionModel`/`FallbackModel` setup succeed. Log: `work/native-pydantic-ai-models/red.log`.
- `uv run pytest tests/test_agent.py -q` (same worktree) → 2 failed (the witnesses), 12 passed.

**Supporting test plan**
- `build_agent_model(settings)` → Build unit test: chain order, `gemini`→`GoogleModel`, `dashscope`/`openai`/`openai_compatible`→`OpenAIChatModel` with correct `base_url`, `anthropic`→`AnthropicModel` with `/v1` stripped. Needs `openai` and `anthropic` SDKs.
- Cooldown wrapper → Build unit test with fake clock and `FunctionModel`s: 429/401/403 records a cooldown; within `llm_cooldown_seconds` the next turn's chain orders the cooled model last; the cooled model is still the last resort.
- Web and CLI wiring → move `tests/test_llm_router.py::test_web_health_and_chat_report_provider_and_no_secret_leak` and the `tests/web_support.py` fake to `FunctionModel`.

## Build

Candidate: `01f65f3 @ worktree .claude/worktrees/native-pydantic-ai-models (branch proposal/native-pydantic-ai-models)`, local commits `ce3a230` → `51629e3` → `01f65f3`, including the witness diff unchanged. Not pushed or merged.

### Revision 1 (Audit REVISE on 51629e3)
- `src/stock_ontology/llm/agent_model.py:build_native_model`: the DashScope `OpenAIChatModel` gets default `settings={"extra_body": {"enable_thinking": False}}`, matching the old agent path (`extra_chat_body`, `openai_compat.py:302` at `ce3a230`); other OpenAI-compatible providers unchanged.
- `tests/test_dashscope.py::test_dashscope_embeddings_structured_and_agent_tools`: the mock handler again asserts `body["enable_thinking"] is False` on every chat completion including agent turns; the agent model is built by production `build_native_model("dashscope", settings)` with only `OpenAIProvider` monkeypatched for the mock transport; also asserts the builder's base URL.
- RED: `uv run pytest tests/test_dashscope.py -q` against the `51629e3` builder → 1 failed, `KeyError: 'enable_thinking'` on an agent turn (`work/native-pydantic-ai-models/revise1-dashscope-red.log`). GREEN: same command after the fix → 2 passed (`revise1-dashscope-green.log`).
- Witnesses: `uv run pytest tests/test_agent.py -v -k "native_model or falls_back_to_next_native"` → 2 passed (`revise1-witness-green.log`); protected block byte-identical to `witness.patch` at `01f65f3`.
- Gate: `uv run pytest -q` → 543 passed (`revise1-gate.log`).
- Provider labels unchanged (human decision pending, outside this revision).

### Files changed
- `pyproject.toml`, `uv.lock`: `pydantic-ai-slim[google,openai,anthropic]==2.71.0` (adds `openai`, `anthropic` SDKs).
- `src/stock_ontology/llm/agent_model.py` (new): `build_native_model` (gemini→`GoogleModel`; dashscope/openai/openai_compatible→`OpenAIChatModel` with `OpenAIProvider(base_url, api_key)`; anthropic→`AnthropicModel`, `/v1` stripped); `build_agent_models(settings)` over `resolve_provider_chain()`, skipping unconfigured providers, first only when fallback is off; `AgentModelChain` holding models and a cooldown map, `for_turn()` returns a `FallbackModel` with cooled models last (or the single model), `fallback_on` falls back on any `ModelAPIError` and records a cooldown (keyed by `model_name`, `llm_cooldown_seconds`) on 429/401/403, rate-limit/quota/auth errors, or `classify_error` rate_limit/auth/config.
- `src/stock_ontology/agent.py`: `OntologyAgent(..., model=, model_settings=None)`; `Agent` gets `instructions=build_agent_system_prompt(...)` and `model_settings`; provider/model from the run's last `ModelResponse`; `fallback_used` true when the answer came from a model other than the chain's first or carries `failed_attempts`; `llm` kept for tool embeddings.
- `src/stock_ontology/llm/{base.py,router.py,__init__.py,providers/gemini.py,providers/anthropic.py,providers/openai_compat.py}`: deleted `generate_agent_reply` (protocol, abstract, router, three providers), `AgentTurn`/`ToolCall`, and dead helpers `parse_tool_args`, `_THOUGHT_SIGNATURE_SKIP`.
- `src/stock_ontology/llm/pydantic_ai_model.py`: deleted (`LLMClientModel`).
- `src/stock_ontology/web/shell.py`: `WebShell` builds `agent_models` once from settings or wraps an injected `Model`/`AgentModelChain`.
- `src/stock_ontology/web/clippy/routes.py`: `/api/chat` passes `model=shell.agent_models.for_turn()`.
- `src/stock_ontology/web/app.py`: one `agent_model=None` keyword passed to `WebShell` (approved expansion).
- `src/stock_ontology/cli.py`: `ask`/`chat` build `build_agent_models(settings)` once; `chat` refreshes `agent.model = for_turn()` each turn.
- Tests moved to `FunctionModel`, assertions kept or strengthened: `tests/test_agent.py` (non-witness fakes; `test_pydantic_ai_model_round_trips_raw_content_call_ids_and_provider` removed per Invariants changed; `test_agent_chat_returns_immutable_turn_contract` fake and stamps only, turn 2 now via a `FallbackModel` with a 429 first model); `tests/test_llm_router.py` (router fallback/cooldown now via `synthesize_consensus` and `last_attempts`; cross-provider agent test replaced by `test_agent_model_chain_cools_failed_models_last_across_turns`; added `test_build_agent_models_maps_chain_to_native_models`; web health/chat test injects an `AgentModelChain`); `tests/test_gemini.py` (two agent-reply tests removed; error classification via `generate_structured`); `tests/test_dashscope.py` (real `OpenAIChatModel` against the mock transport, asserting `model_settings` reaches the wire as max tokens); `tests/test_i18n.py`, `tests/test_relationships.py`, `tests/web_support.py`, `tests/test_web.py`, `tests/test_web_navigation.py`, `tests/test_search.py`, `tests/test_web_search.py`, `tests/test_pipeline.py` (fakes and wiring only; `test_web_search` now asserts the specific agent error text).
- `README.md`: LLM router and Calling the Agent sections and turn-stamp source updated per Invariants changed; new Query Agent constraint (give the agent a Pydantic AI `Model`, never route chat through `LLMClient` or a custom adapter), guarded by the two witnesses.
- `docs/architecture/{README,agent,llm}.md`: module map lists `llm/agent_model.py`; `generate_agent_reply`/`AgentTurn` removed; agent fallback and cooldown described.

### Unit evidence
- Builder and chain unit tests were written after implementation (no pre-implementation RED). Against a mutant with cooldown recording disabled and `/v1` stripping removed, `uv run pytest tests/test_llm_router.py -q -k "build_agent_models or cools_failed"` → 2 failed (`work/native-pydantic-ai-models/build-unit-mutant-red.log`); restored → 2 passed (`build-unit-green.log`).

### Green evidence
- `uv run pytest tests/test_agent.py -v -k "native_model or falls_back_to_next_native"` → 2 passed (`work/native-pydantic-ai-models/build-witness-green.log`).
- Protected witnesses: appended block in `tests/test_agent.py` byte-identical to `work/native-pydantic-ai-models/witness.patch` (sha1 `78465b9a…`), checked before and after.
- `uv run pytest -q` → 543 passed offline (`work/native-pydantic-ai-models/build-gate.log`); orchestrator re-ran it on `51629e3` → 543 passed.
- Guardrail owners green, assertions not weakened: `test_agent_requires_read_only_db`, `test_agent_chat_returns_immutable_turn_contract`, `tests/test_relationships.py::test_guardrail_read_only_agent_web_inspect_and_audit`, `tests/test_web_clippy.py::test_web_chat_endpoint_uses_only_agent_chat`, `tests/test_architecture.py`, router ingestion and health tests.

### Intervention record
- None. Brevity is a follow-up proposal; nothing sets `model_settings` in production yet.

### Deviations
- Approved scope expansion (human, 2026-11-24, "Yes, widen with app.py"): `src/stock_ontology/web/app.py` (one `agent_model=None` keyword); `tests/test_pipeline.py`, `tests/test_search.py`, `tests/test_web_search.py`, `tests/test_web.py`, `tests/test_web_navigation.py` (fakes replaced with `FunctionModel` plus wiring only). Applied within those limits.
- Behavior notes for Audit (not scope changes): `ChatTurn.provider` now shows Pydantic AI provider names (`google`, `openai`, `anthropic`), not config names (`gemini`, `dashscope`); when the primary is cooled and a turn starts at the next model, `fallback_used` is false (relative to the turn's chain, where `LLMRouter` compared to the configured primary); a successful answer from a cooled model does not clear its cooldown early.
- Left in place, out of scope: unused `generate_agent_reply` stubs in `tests/test_staged_extraction.py` and `tests/test_official_facets.py`.
- The protected witness has two redundant local imports (`ModelMessage`, `AgentInfo`) flagged by ruff F401; left because the witness is protected.

## Audit

Candidate: `01f65f3 @ worktree .claude/worktrees/native-pydantic-ai-models (branch proposal/native-pydantic-ai-models)`, clean tree, base `ce3a230`, revision diff `51629e3..01f65f3` (`src/stock_ontology/llm/agent_model.py`, `tests/test_dashscope.py`).

Independence: fresh-context subagent that did not build or prove the candidate; it audited `51629e3` earlier (REVISE).

Primary-claim verdict: PROVED. Protected block (`_NoChatLLM` to EOF of `tests/test_agent.py`) byte-identical to the RED revision from `witness.patch` (sha1 `78465b9a…`, blob `0e3d363c…`); `git diff 51629e3..01f65f3 -- tests/test_agent.py` empty; `red.log` shows both witnesses RED on `ce3a230`; `uv run pytest tests/test_agent.py tests/test_dashscope.py -q` → 15 passed; on `51629e3` an in-memory mutant nulling `model_settings` turned the witness and the DashScope wire test RED. `test_dashscope_embeddings_structured_and_agent_tools` now builds through production `build_native_model("dashscope", settings)` and asserts `max_tokens`=77 and `enable_thinking` false in the same wire body. Limit: `GoogleModel`/`AnthropicModel` not exercised on the wire; no live provider.

Guardrail verdicts:
- First-provider API error falls back and stamps the answerer: PROVED (protected witness RED then green; `tests/test_llm_router.py::test_agent_model_chain_cools_failed_models_last_across_turns` green). Limit: production `ChatTurn.provider` shows Pydantic AI names (`google`, `openai`), not config names used by `/api/health`; no test pins the production label.
- Read-only agent and `/api/chat` contract: PROVED (`test_agent_requires_read_only_db`, `test_agent_chat_returns_immutable_turn_contract`, `tests/test_relationships.py::test_guardrail_read_only_agent_web_inspect_and_audit`, `tests/test_web_clippy.py::test_web_chat_endpoint_uses_only_agent_chat` green; diffs change only fakes, wiring and stamps). Limit: cannot go RED.
- Cooled provider last within `llm_cooldown_seconds`: PROVED (429/401/403 cooling, last resort, expiry, no cooling on 500/connection; mutant with cooldown kinds emptied → RED; untouched by the revision). Limit: written after implementation; keyed by `model_name`.
- Ingestion and `/api/health` stay on `LLMRouter`: PROVED (router/base diffs remove only the agent-reply path; router fallback, cooldown and health tests green; DashScope structured calls still assert `enable_thinking` false). Limit: offline only.

Scope and duty verdict: scope HELD; duties HELD. The earlier EXPANDED finding is answered: `build_native_model` gives DashScope `settings={"extra_body": {"enable_thinking": False}}`, restoring the `ce3a230` agent-path behavior, and the test asserts it on every chat completion again. Auditor reproduced RED by swapping in the `51629e3` builder in memory: `uv run pytest tests/test_dashscope.py -q` → 1 failed (`KeyError: 'enable_thinking'`), green on `01f65f3`. Other changes match Allowed scope plus the human-approved widening. README constraint has `**Why:**` and two existing `**Guarded by:**` tests; `docs/architecture` updated; `tests/test_architecture.py` passes. Limit: live DashScope thinking behavior not checked.

Test homes: `tests/test_agent.py` (agent witnesses and fakes); `tests/test_llm_router.py` (router, chain builder, cooldown chain); `tests/test_dashscope.py` (DashScope wire via the production builder); `tests/test_gemini.py` (Gemini provider); the remaining touched test files keep fakes and wiring in their existing owners.

Full gates: PASS. `uv run pytest -q` on `01f65f3` → 543 passed; `uv run pytest tests/test_architecture.py tests/test_web_clippy.py -q` → 5 passed (on `51629e3`; untouched by the revision). `ruff` is not a gate here.

Residual risks:
- Clippy's provider label changes from `gemini`/`dashscope` to `google`/`openai` and no longer matches `/api/health`; human decision pending.
- `fallback_used` is relative to each turn's chain; while the primary is cooled, a second-provider answer reports `false`.
- Deploy needs the `openai` and `anthropic` SDKs on the server; human-owned, no live-provider check.

Recommendation: ACCEPT

Packet: No candidate change required. The human decides on the provider-label change, then on merging to `main` and running `./deploy.sh`. ACCEPT authorizes neither.

## Revisions

### R1 — 2026-11-24 — scope: DashScope agent turns stopped sending `enable_thinking: false`, an unlisted invariant change
- Verdict: REVISE — the native `OpenAIChatModel` for DashScope sent no `enable_thinking`, and `tests/test_dashscope.py` narrowed its assertion to structured calls; neither Frame nor Build listed it.
- Changed: `src/stock_ontology/llm/agent_model.py` (DashScope model defaults `extra_body={"enable_thinking": False}`), `tests/test_dashscope.py` (assertion restored for agent turns, model built through `build_native_model`) — restores the `ce3a230` behavior and covers production wiring.
- Re-audit: ACCEPT — all claims PROVED, scope HELD, 543 passed; candidate `01f65f3 @ worktree .claude/worktrees/native-pydantic-ai-models`
