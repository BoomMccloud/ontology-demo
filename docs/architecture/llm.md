# LLM layer

One interface over several model providers, with automatic fallback. The
pipeline, the agent, and embeddings all go through it.

## Files

- `src/stock_ontology/llm/base.py`: the `LLMClient` protocol, `AgentTurn`,
  `ToolCall`, error types, and `classify_error`.
- `src/stock_ontology/llm/router.py`: `LLMRouter` and `create_llm_client(settings)`.
- `src/stock_ontology/llm/providers/`: Gemini, DashScope (Qwen), OpenAI,
  Anthropic, and generic OpenAI-compatible adapters, built by `build_provider`.
- `src/stock_ontology/llm/prompts.py`: ingestion prompts (see
  [pipeline.md](pipeline.md)).
- `src/stock_ontology/llm/pydantic_ai_model.py`: the agent's adapter (see
  [agent.md](agent.md)).

## Interface

`LLMClient` has these methods:

- `extract_stage(stage=...)` runs one ordered extraction (`entities`, `events`
  or `views`) and returns an `ExtractionResult`. Providers and the router
  implement it; a client without it falls back to `extract_document`.
- `extract_document(...)` returns an `ExtractionResult` from one call.
- `synthesize_consensus(...)` returns a `ConsensusSynthesis`.
- `embed_texts(texts)` returns vectors.
- `generate_agent_reply(...)` returns an `AgentTurn` with text or tool calls.

Callers depend on this protocol, which is why tests can pass fake clients.

## Fallback

The router tries providers in order. With `LLM_PROVIDER=auto` the order is
gemini, dashscope, openai, anthropic, openai_compatible, filtered to the ones
configured. On rate limits, auth errors, 5xx, timeouts, or invalid responses it
moves to the next provider. Rate-limited and auth-failed providers go on a
cooldown (`LLM_COOLDOWN_SECONDS`). Embeddings can use their own chain, and
chat-only providers like Anthropic are skipped for them.

## Depends on

[ontology.md](ontology.md) for the structured-output models, and config from
[shared.md](shared.md).

## Used by

The pipeline, agent, web app, and CLI.

## Tests

`tests/test_llm_router.py`, `tests/test_gemini.py`, `tests/test_dashscope.py`.
No test calls a live provider.
