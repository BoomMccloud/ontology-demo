---
proposal_id: "agent-chat-contract"
state: ACCEPTED
witness: independent
candidate: "5b143b3 + uncommitted working tree @ worktree .claude/worktrees/agent-chat-contract (agent.py 847845342225, web/app.py eceabb011da2, README.md a35d9cd4904a, tests/test_agent.py a7df37cb92d9, tests/test_web.py 7aa9c682ef9d)"
---

# Proposal: Narrow the web-to-agent chat contract

## Proposal

Status: approved by requester on 2026-11-22 ("Do this task here").

### Intent

If I change agent behavior, it shouldn't affect other components. The web chat (`/api/chat`) should talk to the agent through one small, stated interface, not by reaching into the agent's attributes.

### Tentative primary claim

The web chat gets everything it needs from one public agent chat call, so changing the agent's internals without changing that call cannot break the web chat.

### Why now

The pydantic-ai rewrite of the agent just landed, and it only kept the web chat working because it happened to keep the same attribute names.

### Known constraints

- Do not change agent prompts, tools, or reply behavior.
- Add a contract test that pins the chat call's result shape.
- Tests stay offline with fake LLM clients.

### Non-goals

- Other couplings, such as the shared `OntologyDB` or `LLMClient` surfaces.
- Changing how the CLI uses the agent.

### Open choices

None stated.

## Frame

Candidate: `5b143b3 @ worktree .claude/worktrees/agent-chat-contract (branch proposal/agent-chat-contract), clean`

### Verified reality
- `uv run pytest -q -p no:cacheprovider` at the candidate: 83 passed. Proves the suites judging this change are green before it starts.
- `src/stock_ontology/web/app.py:559-585` (`chat_endpoint`): constructs `OntologyAgent(db, active_llm, language=lang)`, assigns `agent.messages = history`, calls `agent.ask(prompt)`, then reads `agent.messages`, `agent.tool_trace[*]["tool"]`, `agent.last_provider`, `agent.last_model`, `agent.last_fallback_used`. Proves the web depends on five agent attributes, one of which it writes. Limit: says nothing about the CLI.
- `src/stock_ontology/web/app.py:105` types `sessions` as `dict[str, list[dict[str, Any]]]`, but `src/stock_ontology/agent.py:250` now stores `list[ModelMessage]`. Proves the web's view of history is already stale and only works because it treats history as opaque.
- `src/stock_ontology/agent.py:483-510` (`ask`): runs one Pydantic AI turn over `self.messages`, then replaces `self.messages`; `tool_trace` is appended to and never cleared per call (`agent.py:219-229`, `reset()` at `:256`). Proves a reused agent's trace accumulates across turns, so "tools used this turn" must be sliced. Limit: the web builds a fresh agent per request today, so it does not see the accumulation.
- `rg "agent\.(messages|tool_trace|last_)" src`: outside `agent.py`, only `web/app.py` matches. `src/stock_ontology/cli.py:527-585` uses only `OntologyAgent(...)`, `ask()` and `reset()`. Proves the web handler is the only production caller depending on attributes.
- `tests/test_agent.py`, `tests/test_gemini.py`, `tests/test_llm_router.py`, `tests/test_dashscope.py` read `tool_trace`, `last_provider`, `last_model`, `last_fallback_used`, and `messages` directly. Proves those attributes are relied on by agent-layer tests and must stay.
- `tests/test_web.py:175` (`test_web_home_entity_theme_search_and_clippy_chat`) drives `/api/chat` end to end with `FakeWebLLM`. Proves the existing guard is end to end only.

### Final primary claim
- `OntologyAgent.chat(message, history)` returns one immutable result carrying the reply, the updated history to pass back unchanged, the tool names used in that turn only, and the provider, model and fallback flag; `/api/chat` uses only `OntologyAgent(...)` and `chat()` and touches no other agent attribute, and its JSON response is unchanged.

### Routing
- Witness: `independent`
- Why: it changes the interface between the web app and agent components, and the chat endpoint is the user-facing path to the agent.
- Human-owned irreversible action: merging into `main`.

### Decisive witness
- Layer: unit contract test on the agent, plus a static check on the web handler.
- Permanent owner: `tests/test_agent.py` for the result contract; `tests/test_web.py` for the handler check.
- Witness: (1) with `ScriptedAgentLLM`, two `chat()` calls where the second receives the first's history return results whose field names are exactly the pinned set, whose `history` is a tuple that grows across turns, whose second-turn tools list holds only that turn's tools, and whose provider fields come from the turn; (2) an AST scan of `web/app.py` finds no attribute access on the agent object other than `chat`.

### Guardrail claims
- `/api/chat` returns the same JSON keys (`session_id`, `lang`, `reply`, `tools_used`, `provider`, `model`, `fallback_used`) and keeps multi-turn history per `session_id`, with `tests/test_web.py:175` passing unchanged.
- The CLI `ask` and `chat` commands and every existing agent test pass unchanged.

### Supporting obligations
- Add a frozen `ChatTurn` dataclass and `OntologyAgent.chat()` in `agent.py`, built on `ask()` so the loop is not duplicated; slice `tool_trace` from the call's start.
- Change `sessions` in `web/app.py` to hold the opaque history tuple.

### Allowed scope
- Reuse: `OntologyAgent.ask()` for the turn; `ScriptedAgentLLM` and `_seed_db` in `tests/test_agent.py`; `FakeWebLLM` in `tests/test_web.py`.
- Cheaper alternative: documenting the five attributes as public was rejected, because it freezes the internals the Proposal wants free to change.
- Include: `src/stock_ontology/agent.py` (add `ChatTurn` and `chat()` only), `src/stock_ontology/web/app.py` (`chat_endpoint` and the `sessions` annotation), `tests/test_agent.py`, `tests/test_web.py` (new static check only).
- Exclude/protect: agent prompts, tool schemas and the tool loop; `cli.py`; `db/`; `llm/`; every existing test assertion; templates and static files.

### Invariants changed
- None.

### Decisions required
- None.

## Proof

Candidate: `5b143b3 @ worktree .claude/worktrees/agent-chat-contract (branch proposal/agent-chat-contract)`. No `src/` changes. The only working-tree changes are the two appended tests below and the untracked ledger.

**Protected witness**
- `OntologyAgent.chat(message, history)` returns one immutable result carrying the reply, a history to pass back unchanged, this turn's tool names only, and the provider, model and fallback flag. The test is in `tests/test_agent.py`, `test_agent_chat_returns_immutable_turn_contract` (line 593). It reuses `ScriptedAgentLLM` and `_seed_db` through a small subclass, `ProviderStampedAgentLLM`, which stamps each model call with `prov-N`, `model-N` and `fallback_used = (N == 4)`.
  - Defect and boundary: the agent has no public chat call, so callers must read and write its internal attributes. The boundary is the agent's public API as consumed by the web layer.
  - Assertion: two `chat()` calls run on the same reused agent, and the second gets `first.history`. `type(result).__name__ == "ChatTurn"`, and it is a dataclass whose field names, in order, are exactly `reply, history, tools_used, provider, model, fallback_used`. Assigning a field raises `FrozenInstanceError`. Each reply holds the scripted answer for its turn. `history` is a non-empty tuple; the second history starts with the first and is longer. `tools_used` is `("get_entity_overview",)` for turn 1 and `("find_theme_companies",)` for turn 2, so the slice holds only the current turn's tools even though `tool_trace` accumulates on a reused agent. Provider fields come from each turn's final model call: `("prov-2","model-2",False)`, then `("prov-4","model-4",True)`.
  - Limit: it doesn't prove `/api/chat` uses `chat()` or that the endpoint's JSON is unchanged. It pins `tools_used` as a tuple and the field order. It doesn't cover the error path or `max_rounds`.
- `/api/chat` uses only `OntologyAgent(...)` and `chat()`. The test is in `tests/test_web.py`, `test_web_chat_endpoint_uses_only_agent_chat` (line 1381).
  - Defect and boundary: `chat_endpoint` reaches into `messages` (it writes this one), `ask`, `tool_trace`, `last_provider`, `last_model` and `last_fallback_used`. The boundary is web handler to agent.
  - Assertion: an AST scan of `src/stock_ontology/web/app.py` finds exactly one `chat_endpoint`. The variables assigned from `OntologyAgent(...)` must be non-empty. The only attribute accessed on them, read or write, must be `chat`. Any other load of the agent name (passing it, `getattr`) also fails.
  - Limit: it's static. It doesn't follow aliases created other than by direct assignment from `OntologyAgent(...)`, and it doesn't check runtime JSON. The guardrail for JSON stays with the unchanged `test_web_home_entity_theme_search_and_clippy_chat`.
- Protected paths: `tests/test_agent.py` (`ProviderStampedAgentLLM` and `test_agent_chat_returns_immutable_turn_contract`) and `tests/test_web.py` (`test_web_chat_endpoint_uses_only_agent_chat`).
- Protected revision: uncommitted working-tree blobs. `git hash-object tests/test_agent.py` = `a7df37cb92d93dd0449521e71dc9488ca31d5c05`; `git hash-object tests/test_web.py` = `7aa9c682ef9df70154d5063c1df7950a1875ee4d`. Both are appended to their `5b143b3` versions: 114 insertions, 0 deletions.

**Red evidence**
- `uv run pytest tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat -v -p no:cacheprovider` gives 2 failed. The agent test fails with `AttributeError: 'OntologyAgent' object has no attribute 'chat'`. The web test fails with `AssertionError: assert {'ask', 'last_...', 'messages', 'tool_trace', ...} == {'chat'}`.
- Full suite `uv run pytest -q -p no:cacheprovider` gives 2 failed (the new witnesses) and 83 passed.
- Satisfiability check, scratch only: a throwaway monkeypatched `chat()` built on `ask()` made the agent witness pass.

**Supporting test plan**
- The `sessions` annotation change in `web/app.py` has no new test owner. The existing `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` catches broken multi-turn history and JSON key regressions.

## Build

Candidate: `5b143b3 + uncommitted working tree @ worktree .claude/worktrees/agent-chat-contract (agent.py 847845342225, web/app.py eceabb011da2, README.md a35d9cd4904a, tests/test_agent.py a7df37cb92d9, tests/test_web.py 7aa9c682ef9d)`

Changed paths:
- `src/stock_ontology/agent.py`: adds frozen dataclass `ChatTurn` (`reply`, `history`, `tools_used`, `provider`, `model`, `fallback_used`) and `OntologyAgent.chat(user_message, history=(), *, max_rounds=8)`. `chat()` sets `messages` from `history`, clears `last_provider`, `last_model` and `last_fallback_used` so they reflect only this turn, records where `tool_trace` starts, calls the existing `ask()`, and returns a `ChatTurn` with the history as a tuple and only this turn's tool names. Prompts, tool schemas, the loop, and `ask()` are unchanged.
- `src/stock_ontology/web/app.py`: `chat_endpoint` now calls only `OntologyAgent(...)` and `agent.chat(prompt, history)`, stores `turn.history` per session, and builds the same JSON keys from `turn`. `sessions` is typed `dict[str, tuple[Any, ...]]` and documented as opaque history.

Protected witnesses: unchanged. `git hash-object tests/test_agent.py tests/test_web.py` = `a7df37cb92d93dd0449521e71dc9488ca31d5c05`, `7aa9c682ef9df70154d5063c1df7950a1875ee4d`, matching Proof.

GREEN:
- `uv run pytest tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat -q -p no:cacheprovider`: 2 passed.
- `uv run pytest -q -p no:cacheprovider`: 85 passed (83 existing plus the 2 witnesses).
- `uv run ruff check src/stock_ontology/agent.py src/stock_ontology/web/app.py tests/test_agent.py tests/test_web.py`: 1 error, `agent.py:261` raise-vanilla-args on the existing `ValueError` in `OntologyAgent.__init__`, which predates this change and only moved down.

- `README.md` (Revision 1): adds a `## Query Agent Constraints` entry recording that the web app uses only `OntologyAgent(...)` and `chat()`, with **Why:** and **Guarded by:** naming both witnesses. README was not in Frame's Include list; it was added to meet the constraint-capture duty the Audit required.

Deviations: none beyond the README addition above. Not committed; the human owns committing and merging. `docs/architecture/agent.md` and `web.md` exist only as uncommitted work in the main checkout, so they don't mention `chat()` yet.

## Audit

Candidate: `5b143b3 + uncommitted working tree @ worktree .claude/worktrees/agent-chat-contract (agent.py 847845342225, web/app.py eceabb011da2, README.md a35d9cd4904a, tests/test_agent.py a7df37cb92d9, tests/test_web.py 7aa9c682ef9d)`

Independence: fresh-context. The auditing context had seen only the ledger, the `git diff` against `5b143b3`, and its own command results. It did not build the candidate or see the earlier audit's run.

Primary-claim verdict: PROVED. Evidence: `tests/test_agent.py::test_agent_chat_returns_immutable_turn_contract` and `tests/test_web.py::test_web_chat_endpoint_uses_only_agent_chat` pass (2 passed); Proof records both RED before the build. `git hash-object tests/test_agent.py tests/test_web.py` gives `a7df37cb92d93dd0449521e71dc9488ca31d5c05` and `7aa9c682ef9df70154d5063c1df7950a1875ee4d`, matching Proof, and `git diff tests` shows no deleted lines. `chat_endpoint` calls only `OntologyAgent(...)` and `agent.chat(prompt, history)`. `ChatTurn` is frozen with the pinned fields in order, and `chat()` is built on `ask()` and slices `tool_trace` from the call's start. Limit: the AST witness is static and doesn't follow indirect aliases; the error path and `max_rounds` are not covered by the witness.

Guardrail verdicts:
- `/api/chat` JSON keys and multi-turn history unchanged: PROVED. Evidence: `tests/test_web.py::test_web_home_entity_theme_search_and_clippy_chat` is unchanged and passes. The diff builds the same seven keys, `tools_used` is converted back to a list, and the 500 error branch is untouched. Clearing the provider fields at the start of `chat()` sets them to the same values `__init__` sets (`agent.py:270-272`), so it is a no-op for `/api/chat`, which builds a fresh agent per request; `ask()` still sets them from each model turn (`agent.py:497-499`). Limit: end to end with `FakeWebLLM`, no byte-level comparison against the old output.
- CLI `ask`/`chat` and existing agent tests pass unchanged: PROVED. Evidence: `cli.py` isn't in the diff; `ask()`, `reset()`, the prompts and the tool loop are unchanged; the full suite passes with no deleted test lines. Limit: CLI coverage is only as deep as the existing tests.

Scope and duty verdict: scope HELD; duties HELD. Evidence: changes stay in Frame's Include list (`ChatTurn` and `chat()` in `agent.py`, `chat_endpoint` and the `sessions` annotation in `web/app.py`, append-only tests). The provider-field clear is inside `chat()`, as Revision 1's packet requested. `README.md` is outside Include, but it is a new entry required by the constraint-capture duty, which the audit skill exempts from EXPANDED; no existing README invariant was edited. The new `## Query Agent Constraints` entry states the rule with `**Why:**` and `**Guarded by:**` naming both witnesses, and both tests exist and pass. Revision 1's packet is answered by changed paths (`README.md`, `agent.py:535-537`). Limit: `docs/architecture/*` updates are pending in the main checkout and aren't part of this candidate.

Test homes: `tests/test_agent.py` owns the agent's public result contract, next to `ScriptedAgentLLM`. `tests/test_web.py` owns the web handler's use of the agent.

Full gates: PASS. `uv run pytest -q -p no:cacheprovider`: 85 passed. The two witness tests: 2 passed. `uv run ruff check src/stock_ontology/agent.py src/stock_ontology/web/app.py tests/test_agent.py tests/test_web.py`: 1 error at `agent.py:261`, the existing `ValueError` in `__init__`; ruff on `git show 5b143b3:src/stock_ontology/agent.py` also reports exactly 1 error, so it predates the change.

Residual risks:
- The static witness misses indirect aliasing, such as passing the agent into a helper that reads its attributes.
- `chat()` still mutates `messages` and `tool_trace` on the agent instance, so a reused agent isn't safe to share across concurrent callers. The web avoids this by building one agent per request.
- The pre-existing ruff error at `agent.py:261` remains.

Recommendation: ACCEPT
Packet: none required. Merging into `main` stays human-owned.

## Revisions

### Revision 1 (2026-11-22)

Outgoing Audit verdict: REVISE. Primary claim and both guardrails PROVED; scope HELD; duties VIOLATED on constraint capture. Packet: add a `README.md` `## Query Agent Constraints` entry stating that the web app uses only `OntologyAgent(...)` and `OntologyAgent.chat()`, stores `ChatTurn.history` opaquely, and touches no other agent attribute, with `**Why:**` and `**Guarded by:**` naming both witnesses. Optional: clear `last_provider`, `last_model` and `last_fallback_used` at the start of `chat()` so a reused agent can't return a previous turn's provider fields.

Work that answered it: added the README entry; `chat()` now clears the three provider fields before the turn. Rerun from Build.
