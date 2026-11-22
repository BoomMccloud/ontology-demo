---
proposal_id: "pydantic-ai-agent"
state: PROPOSAL
witness: builder
candidate: "unassigned"
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

None stated.

### Non-goals

None stated.

### Open choices

- Sequence: whether this proposal covers only the framework switch, or also an
  MCP integration, an A2A integration, or both. The request bundles parts that
  could ship separately.
- MCP direction: whether "integrate with MCP" means the agent using outside MCP
  tools, other agents querying the ontology through MCP, or both.
- Reach: whether only the query agent moves to Pydantic AI, or the ingestion
  pipeline's LLM calls move too.
- Fallback: whether the current multi-provider fallback behavior must be kept
  as it is, or may change to whatever Pydantic AI offers.

## Frame

## Proof

## Build

## Audit

## Revisions
