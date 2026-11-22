"""Strictly read-only PM query agent that traverses the SQLite stock ontology."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, AbstractToolset, FunctionToolset, Tool, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai.toolsets import WrapperToolset

from stock_ontology.db import OntologyDB, node_to_dict
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    get_language_spec,
    normalize_language,
    translate,
)
from stock_ontology.llm import AgentTurn, LLMClient
from stock_ontology.llm.pydantic_ai_model import LLMClientModel
from stock_ontology.models import VALID_SENTIMENTS, Node, NodeType
from stock_ontology.search import SearchFilters, SearchHit, grep_notes, search_ontology

AGENT_SYSTEM_PROMPT = """You are an investment research assistant for portfolio managers at a stock fund.
You query a strictly read-only 4-node stock ontology database containing:
- entity (companies, people, products, institutions, sectors)
- event (facts, earnings, news, meetings, catalysts; each carries `facets.source` and `facets.sentiment`: `positive` | `negative` | `neutral` | `mixed`, with optional per-company `ABOUT` edge overrides)
- view (rumors, analyst reports, channel checks, PM views, and pipeline-synthesized fund `consensus` views; carries `stance` plus `facets.sentiment`, with optional per-company `ABOUT` edge overrides)
- theme (meta-narratives / investment theses)

Rules:
1. Always ground claims in tool outputs from the ontology database. Never fabricate facts, stances, or sources.
2. Cite exact source file paths (`facets.source.file_path`) and dates when referencing events or views.
3. For UX #1 (when a PM presents a new meeting note or update and asks if it changes our consensus view):
   - Call `get_entity_overview` for the relevant company/companies.
   - Inspect the active `consensus` view, especially `facets.pillars`, plus existing `events` and `views`.
   - Compare each new claim against the consensus pillars: does it confirm, weaken, contradict, or introduce a new risk? Weigh speaker role/credibility against existing evidence strength.
   - Deliver a clear verdict (**Keep**, **Watch**, or **Revisit Consensus**) with concrete reasoning.
   - Remind the PM that you are strictly read-only: to incorporate this note into the database and re-synthesize consensus, save the note under `data/` and run `ingest`.
4. For UX #2 (when a PM asks about companies related to a theme):
   - Call `find_theme_companies` (and `traverse_graph` or `get_entity_overview` if deeper context is helpful).
   - Separate results into **1st-order exposures** (beneficiaries vs. headwinds/risks) and **2nd-order exposures** (suppliers, customers, competitors), explaining the link and citing source files.
5. For counting/filtering questions (e.g., "how many negative rumors or news have we heard about this company?"):
   - Call `query_entity_signals` with the appropriate filters (`sentiments`, `categories`, `node_types`, `statuses`, `date_from`, `date_to`).
   - Report the exact deterministic counts from tool output (`total_matched`, `counts_by_sentiment`, `counts_by_subtype`), list each matching item with its date, `effective_sentiment` (noting when an `ABOUT` edge override sets the company-specific polarity), and source file path (`facets.source.file_path`).
   - If `unclassified_in_scope` is greater than 0, explicitly note how many older items in scope lack a `sentiment` facet and mention that running `stock-ontology ingest --force` classifies legacy notes.
"""


def build_agent_system_prompt(language: str = DEFAULT_LANGUAGE) -> str:
    """Build the agent system prompt with a response-language instruction."""
    resolved = normalize_language(language) or DEFAULT_LANGUAGE
    llm_name = get_language_spec(resolved)["llm_name"]
    return (
        f"{AGENT_SYSTEM_PROMPT}\n"
        f"6. Language rule: Always respond to the PM in {llm_name} (even if underlying research notes, "
        f"database summaries, or citations are in another original language). Keep exact `facets.source.file_path`, "
        f"ticker symbols, and canonical entity names verbatim when citing sources."
    )

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_nodes",
        "description": (
            "Entity-first search across the ontology: entities matching by name or alias come first, "
            "then items connected to them through relationships, keyword and semantic matches. "
            "Each result carries `match_reason` (name, alias, relationship, note, semantic)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language or keyword search query."},
                "node_type": {
                    "type": "string",
                    "enum": ["entity", "event", "view", "theme"],
                    "description": "Optional filter to restrict to one ontology node type.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 8).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_notes",
        "description": (
            "Grep the raw research notes for a literal, case-insensitive phrase. Returns matching "
            "`passages` with `file` (relative to the notes directory), 1-based `line`, and `text`."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Literal phrase to find (not a regex)."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of passages to return (default 20).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_entity_overview",
        "description": (
            "Get full ontology context for an entity (company/person/etc.) by name, ticker, alias, or node ID: "
            "active fund consensus (including pillars), events, external views, themes, and peer edges."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_name_or_id": {
                    "type": "string",
                    "description": "Company name, ticker, alias (e.g. 'NVDA', 'NVIDIA'), or node ID.",
                }
            },
            "required": ["entity_name_or_id"],
        },
    },
    {
        "name": "query_entity_signals",
        "description": (
            "Deterministically filter and count events and views linked to an entity by sentiment "
            "(positive, negative, neutral, mixed, unclassified), category (rumor, news, fact, earnings, "
            "catalyst, meeting, analyst_report, pm_view, channel_check), status, or date range."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_name_or_id": {
                    "type": "string",
                    "description": "Company/entity name, ticker, alias (e.g. 'NVDA', 'NVIDIA'), or node ID.",
                },
                "sentiments": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral", "mixed", "unclassified"],
                    },
                    "description": "Optional filter on effective sentiment (supports per-company ABOUT edge overrides).",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional subtype/category filter: rumor, news, fact, earnings, catalyst, "
                        "meeting, analyst_report, pm_view, channel_check."
                    ),
                },
                "node_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["event", "view"]},
                    "description": "Optional filter restricting signals to 'event' and/or 'view'.",
                },
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional event status filter (e.g. occurred, upcoming, rumored).",
                },
                "date_from": {
                    "type": "string",
                    "description": "Optional inclusive lower bound date (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional inclusive upper bound date (YYYY-MM-DD).",
                },
                "include_consensus": {
                    "type": "boolean",
                    "description": "Include active fund consensus view in results (default false).",
                },
            },
            "required": ["entity_name_or_id"],
        },
    },
    {
        "name": "find_theme_companies",
        "description": (
            "Find 1st-order and 2nd-order companies exposed to an investment theme, including exposure "
            "polarity, consensus stance, and source citations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "theme_query": {
                    "type": "string",
                    "description": "Theme name, alias, natural-language description, or node ID.",
                },
                "include_second_order": {
                    "type": "boolean",
                    "description": "Include 2nd-order supply chain / peer companies (default true).",
                },
            },
            "required": ["theme_query"],
        },
    },
    {
        "name": "get_node_details",
        "description": "Inspect full node fields, facets, and all incoming/outgoing edges for a node ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Exact node ID."},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "traverse_graph",
        "description": "Perform multi-hop BFS graph traversal starting from a node ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_node_id": {"type": "string", "description": "Starting node ID."},
                "relations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of uppercase relation names to follow.",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Maximum traversal depth (1-3, default 2).",
                },
            },
            "required": ["start_node_id"],
        },
    },
    {
        "name": "list_catalog",
        "description": "List all entities and themes currently stored in the ontology plus database stats.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


class _TracedToolset(WrapperToolset[Any]):
    """Records calls to an extra toolset's tools in the agent's `tool_trace`."""

    def __init__(self, wrapped: AbstractToolset[Any], tool_trace: list[dict[str, Any]]) -> None:
        super().__init__(wrapped)
        self.tool_trace = tool_trace

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        self.tool_trace.append({"tool": name, "args": tool_args, "result": result})
        return result


@dataclass(frozen=True)
class ChatTurn:
    """One chat turn's result: the agent's public contract for chat callers.

    `history` is opaque. Callers store it and pass it back to the next `chat()`
    call unchanged, and never inspect it, so the agent can change its message
    format without breaking them.
    """

    reply: str
    history: tuple[Any, ...]
    tools_used: tuple[str, ...]
    provider: str | None
    model: str | None
    fallback_used: bool


class OntologyAgent:
    """Read-only conversational agent that traverses the stock ontology via tools.

    Public interface for other components: construct it with a read-only
    `OntologyDB`, then call `chat(message, history)` for caller-held multi-turn
    sessions, or `ask(message)` and `reset()` when the agent holds history.
    Other attributes (`messages`, `tool_trace`, `last_*`) are internal.
    """

    def __init__(
        self,
        db: OntologyDB,
        llm: LLMClient,
        *,
        language: str = DEFAULT_LANGUAGE,
        toolsets: Sequence[AbstractToolset[Any]] = (),
        data_dir: Path | None = None,
    ) -> None:
        if not db.read_only:
            raise ValueError(
                "OntologyAgent requires a read-only OntologyDB (read_only=True) to enforce one-way data flow."
            )
        self.db = db
        self.llm = llm
        self.language = normalize_language(language) or DEFAULT_LANGUAGE
        self.toolsets = list(toolsets)
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.messages: list[ModelMessage] = []
        self.tool_trace: list[dict[str, Any]] = []
        self.last_provider: str | None = None
        self.last_model: str | None = None
        self.last_fallback_used: bool = False

    def reset(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
        self.tool_trace.clear()
        self.last_provider = None
        self.last_model = None
        self.last_fallback_used = False

    def _resolve_node(self, query: str, node_type: NodeType) -> Node | None:
        cleaned = query.strip()
        if not cleaned:
            return None
        by_id = self.db.get_node(cleaned)
        if by_id is not None and by_id.node_type == node_type:
            return by_id
        by_alias = self.db.find_by_name_or_alias(cleaned, node_type=node_type)
        if by_alias is not None:
            return by_alias
        kw = self.db.keyword_search(cleaned, node_type=node_type, limit=1)
        if kw:
            return kw[0]
        vec = self.llm.embed_texts([cleaned])[0]
        matches = self.db.vector_search(vec, node_type=node_type, limit=1)
        if matches and matches[0][1] < 0.30:
            return matches[0][0]
        return None

    def _tool_search_nodes(
        self, *, query: str, node_type: str | None = None, limit: int = 8
    ) -> dict[str, Any]:
        if not query.strip():
            return {"results": []}
        valid_types = ("entity", "event", "view", "theme")
        if node_type and node_type not in valid_types:
            return {"error": f"Invalid node_type {node_type!r}. Must be one of {valid_types}."}
        limit = max(1, min(int(limit), 25))
        found = search_ontology(
            self.db, self.llm, query, filters=SearchFilters.from_raw(node_type=node_type), limit=limit
        )
        return {"results": [self._format_hit(hit) for hit in found.ranked()[:limit]]}

    @staticmethod
    def _format_hit(hit: SearchHit) -> dict[str, Any]:
        item: dict[str, Any] = {
            **node_to_dict(hit.node),
            "match_reason": hit.match_reason,
            "score": round(hit.score, 4),
        }
        if hit.distance is not None:
            item["distance"] = hit.distance
        if hit.via_relation:
            item["via"] = {
                "relation": hit.via_relation,
                "node_id": hit.via_node_id,
                "node_name": hit.via_node_name,
            }
        return item

    def _tool_search_notes(self, *, query: str, limit: int = 20) -> dict[str, Any]:
        if self.data_dir is None:
            return {"error": "No research notes directory is configured for this agent."}
        if not query.strip():
            return {"passages": []}
        limit = max(1, min(int(limit), 50))
        passages = grep_notes(self.data_dir, [query], total=limit)
        return {"passages": [p.to_dict() for p in passages]}

    def _tool_get_entity_overview(self, *, entity_name_or_id: str) -> dict[str, Any]:
        node = self._resolve_node(entity_name_or_id, "entity")
        if node is None:
            return {"error": f"No entity found matching {entity_name_or_id!r}."}
        return self.db.get_entity_overview(node.id)

    @staticmethod
    def _coerce_str_list(value: str | list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else None
        cleaned_items = [str(item).strip() for item in value if str(item).strip()]
        return cleaned_items or None

    def _tool_query_entity_signals(
        self,
        *,
        entity_name_or_id: str,
        sentiments: str | list[str] | None = None,
        categories: str | list[str] | None = None,
        node_types: str | list[str] | None = None,
        statuses: str | list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        include_consensus: bool = False,
    ) -> dict[str, Any]:
        sent_list = self._coerce_str_list(sentiments)
        if sent_list is not None:
            valid_sents = {*VALID_SENTIMENTS, "unclassified", "unknown"}
            invalid_sents = [s for s in sent_list if s.lower() not in valid_sents]
            if invalid_sents:
                return {
                    "error": (
                        f"Invalid sentiment filter {invalid_sents!r}. "
                        f"Must be one of {sorted(valid_sents)}."
                    )
                }

        nt_list = self._coerce_str_list(node_types)
        if nt_list is not None:
            valid_signal_types = {"event", "view"}
            invalid_types = [nt for nt in nt_list if nt.lower() not in valid_signal_types]
            if invalid_types:
                return {
                    "error": (
                        f"Invalid node_types {invalid_types!r}. "
                        f"Must be one of {sorted(valid_signal_types)}."
                    )
                }

        node = self._resolve_node(entity_name_or_id, "entity")
        if node is None:
            return {"error": f"No entity found matching {entity_name_or_id!r}."}

        return self.db.query_entity_signals(
            node.id,
            sentiments=sent_list,
            node_types=nt_list,
            categories=self._coerce_str_list(categories),
            statuses=self._coerce_str_list(statuses),
            include_consensus=bool(include_consensus),
            date_from=date_from,
            date_to=date_to,
        )

    def _tool_find_theme_companies(
        self, *, theme_query: str, include_second_order: bool = True
    ) -> dict[str, Any]:
        theme = self._resolve_node(theme_query, "theme")
        if theme is None:
            return {"error": f"No theme found matching {theme_query!r}."}
        return self.db.find_theme_companies(
            theme.id, include_second_order=bool(include_second_order)
        )

    def _tool_get_node_details(self, *, node_id: str) -> dict[str, Any]:
        node = self.db.get_node(node_id)
        if node is None:
            return {"error": f"Node not found: {node_id!r}."}
        return {
            "node": node_to_dict(node),
            "edges": self.db.get_incident_edges(node.id),
        }

    def _tool_traverse_graph(
        self,
        *,
        start_node_id: str,
        relations: list[str] | None = None,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        hops = max(1, min(int(max_hops), 3))
        try:
            return self.db.traverse_bfs(start_node_id, relations=relations, max_hops=hops)
        except KeyError as exc:
            return {"error": str(exc)}

    def _tool_list_catalog(self) -> dict[str, Any]:
        entities = self.db.list_nodes(node_type="entity", limit=200)
        themes = self.db.list_nodes(node_type="theme", limit=200)
        return {
            "stats": self.db.get_stats(),
            "entities": [
                {
                    "id": e.id,
                    "name": e.name,
                    "aliases": e.aliases,
                    "entity_type": e.facets.get("entity_type"),
                    "ticker": e.facets.get("ticker"),
                }
                for e in entities
            ],
            "themes": [
                {
                    "id": t.id,
                    "name": t.name,
                    "aliases": t.aliases,
                    "stage": t.facets.get("stage"),
                }
                for t in themes
            ],
        }

    def execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a read-only ontology tool call."""
        handlers = {
            "search_nodes": lambda: self._tool_search_nodes(**args),
            "search_notes": lambda: self._tool_search_notes(**args),
            "get_entity_overview": lambda: self._tool_get_entity_overview(**args),
            "query_entity_signals": lambda: self._tool_query_entity_signals(**args),
            "find_theme_companies": lambda: self._tool_find_theme_companies(**args),
            "get_node_details": lambda: self._tool_get_node_details(**args),
            "traverse_graph": lambda: self._tool_traverse_graph(**args),
            "list_catalog": lambda: self._tool_list_catalog(),
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name!r}"}
        try:
            result = handler()
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"Tool {name} failed: {exc}"}
        self.tool_trace.append({"tool": name, "args": args, "result": result})
        return result

    def _ontology_toolset(self) -> FunctionToolset[Any]:
        """The read-only ontology and note tools, offered with their `TOOL_SCHEMAS`."""

        def make_handler(name: str) -> Any:
            async def handler(**kwargs: Any) -> dict[str, Any]:
                return self.execute_tool(name, kwargs)

            return handler

        return FunctionToolset(
            [
                Tool.from_schema(
                    make_handler(schema["name"]),
                    name=schema["name"],
                    description=schema["description"],
                    json_schema=schema["parameters"],
                    sequential=True,
                )
                for schema in TOOL_SCHEMAS
            ]
        )

    def _record_turn(self, turn: AgentTurn) -> None:
        if turn.provider is not None:
            self.last_provider = turn.provider
            self.last_model = turn.model
            self.last_fallback_used = turn.fallback_used

    def ask(self, user_message: str, max_rounds: int = 8) -> str:
        """Process a user query over the read-only ontology and return the final answer."""
        model = LLMClientModel(
            self.llm,
            system_instruction=build_agent_system_prompt(self.language),
            on_turn=self._record_turn,
        )
        agent = Agent(
            model,
            toolsets=[
                self._ontology_toolset(),
                *(_TracedToolset(ts, self.tool_trace) for ts in self.toolsets),
            ],
        )
        with capture_run_messages() as run_messages:
            try:
                result = agent.run_sync(
                    user_message,
                    message_history=list(self.messages),
                    usage_limits=UsageLimits(request_limit=max_rounds),
                    # Let `max_rounds` alone bound the run, as the hand-rolled loop did.
                    retries={"tools": max_rounds, "output": max_rounds},
                )
            except UsageLimitExceeded:
                self.messages = list(run_messages)
                return translate("agent.max_rounds_reached", lang=self.language)
        self.messages = result.all_messages()
        return result.output

    def chat(
        self, user_message: str, history: Sequence[Any] = (), *, max_rounds: int = 8
    ) -> ChatTurn:
        """Run one chat turn over `history` (from a previous `ChatTurn`) and return its result."""
        self.messages = list(history)
        self.last_provider = None
        self.last_model = None
        self.last_fallback_used = False
        trace_start = len(self.tool_trace)
        reply = self.ask(user_message, max_rounds=max_rounds)
        return ChatTurn(
            reply=reply,
            history=tuple(self.messages),
            tools_used=tuple(entry["tool"] for entry in self.tool_trace[trace_start:]),
            provider=self.last_provider,
            model=self.last_model,
            fallback_used=self.last_fallback_used,
        )
