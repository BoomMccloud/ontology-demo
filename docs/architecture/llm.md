# LLM layer

One interface over several model providers, with automatic fallback. The
pipeline and embeddings (including the agent's tool embeddings) go through it.
The agent's chat models are Pydantic AI's own, built here in `agent_model.py`.

## Files

- `src/stock_ontology/llm/base.py`: the `LLMClient` protocol, error types,
  and `classify_error`.
- `src/stock_ontology/llm/router.py`: `LLMRouter` and `create_llm_client(settings)`.
- `src/stock_ontology/llm/providers/`: Gemini, DashScope (Qwen), OpenAI,
  Anthropic, and generic OpenAI-compatible adapters, built by `build_provider`.
- `src/stock_ontology/llm/prompts.py`: ingestion prompts (see
  [pipeline.md](pipeline.md)).
- `src/stock_ontology/llm/agent_model.py`: `build_agent_models(settings)` and
  `AgentModelChain`, the agent's Pydantic AI models (see [agent.md](agent.md)).

## Interface

`LLMClient` has these methods:

- `extract_stage(stage=...)` runs one ordered extraction (`entities`, `events`
  or `views`) and returns an `ExtractionResult`. Providers and the router
  implement it; a client without it falls back to `extract_document`.
- `extract_document(...)` returns an `ExtractionResult` from one call.
- `synthesize_consensus(...)` returns a `ConsensusSynthesis`.
- `embed_texts(texts)` returns vectors.

Callers depend on this protocol, which is why tests can pass fake clients.

## Fallback

The router tries providers in order. With `LLM_PROVIDER=auto` the order is
gemini, dashscope, openai, anthropic, openai_compatible, filtered to the ones
configured. On rate limits, auth errors, 5xx, timeouts, or invalid responses it
moves to the next provider. Rate-limited and auth-failed providers go on a
cooldown (`LLM_COOLDOWN_SECONDS`). Embeddings can use their own chain, and
chat-only providers like Anthropic are skipped for them.

The agent does not use the router for chat. `build_agent_models(settings)` maps
the same chat chain, configured providers only, to `GoogleModel` (gemini),
`OpenAIChatModel` with an `OpenAIProvider` base URL (dashscope, openai,
openai_compatible) and `AnthropicModel` (anthropic, with `/v1` stripped from
`ANTHROPIC_API_URL`). `AgentModelChain.for_turn()` returns a Pydantic AI
`FallbackModel` that moves on after any provider API error. A model that failed
with 429/401/403, or an error `classify_error` calls rate_limit, auth or config,
goes last for `LLM_COOLDOWN_SECONDS` but stays the last resort.

## Depends on

[ontology.md](ontology.md) for the structured-output models, and config from
[shared.md](shared.md).

## Used by

The pipeline, agent, web app, and CLI.

## Tests

`tests/test_llm_router.py`, `tests/test_gemini.py`, `tests/test_dashscope.py`.
No test calls a live provider.
