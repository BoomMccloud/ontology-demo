"""Core 4-node ontology models, unified edge model, and Gemini structured-output schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

NodeType = Literal["entity", "event", "view", "theme"]
Sentiment = Literal["positive", "negative", "neutral", "mixed"]
SentimentSource = Literal["edge", "node", "stance"]

VALID_SENTIMENTS: tuple[Sentiment, ...] = ("positive", "negative", "neutral", "mixed")
STANCE_TO_SENTIMENT: dict[str, Sentiment] = {
    "buy": "positive",
    "bullish": "positive",
    "outperform": "positive",
    "overweight": "positive",
    "sell": "negative",
    "bearish": "negative",
    "cautious": "negative",
    "underperform": "negative",
    "underweight": "negative",
    "hold": "neutral",
    "neutral": "neutral",
}


def normalize_sentiment(value: Any) -> Sentiment | None:
    """Return canonical Sentiment if `value` is a valid polarity string, else None."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned in VALID_SENTIMENTS:
        return cast(Sentiment, cleaned)
    return None


def derive_sentiment_from_stance(stance: Any) -> Sentiment | None:
    """Map a view stance string onto a canonical Sentiment, or None if unrecognized."""
    if not isinstance(stance, str):
        return None
    return STANCE_TO_SENTIMENT.get(stance.strip().lower())


def resolve_item_sentiment(
    node_facets: dict[str, Any],
    edge_facets: dict[str, Any] | None = None,
) -> tuple[Sentiment | None, SentimentSource | None]:
    """Resolve effective sentiment using edge override -> node sentiment -> view stance fallback."""
    if edge_facets:
        edge_sent = normalize_sentiment(edge_facets.get("sentiment"))
        if edge_sent is not None:
            return edge_sent, "edge"

    node_sent = normalize_sentiment(node_facets.get("sentiment"))
    if node_sent is not None:
        return node_sent, "node"

    stance_sent = derive_sentiment_from_stance(node_facets.get("stance"))
    if stance_sent is not None:
        return stance_sent, "stance"

    return None, None


def utc_now() -> datetime:
    """Return current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Node(BaseModel):
    """Canonical graph node across all 4 ontology types (entity, event, view, theme)."""

    id: str
    node_type: NodeType
    name: str
    summary: str
    aliases: list[str] = Field(default_factory=list)
    facets: dict[str, Any] = Field(default_factory=dict)
    source_doc_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Edge(BaseModel):
    """Unified directed typed relationship between two ontology nodes."""

    id: str
    from_id: str
    to_id: str
    relation: str
    facets: dict[str, Any] = Field(default_factory=dict)
    source_doc_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Gemini Structured-Output Schemas (uses list[FacetKV] instead of open dicts)
# ---------------------------------------------------------------------------


class FacetKV(BaseModel):
    """Key-value facet pair compatible with Gemini structured JSON schemas."""

    key: str = Field(description="Snake_case facet key, e.g., ticker, sector, author, speaker_role.")
    value: str = Field(
        description="Plain string value, or JSON-encoded list/boolean/number when structured."
    )


def facets_list_to_dict(items: list[FacetKV]) -> dict[str, Any]:
    """Convert a list of FacetKV items into a Python dictionary with light type coercion."""
    result: dict[str, Any] = {}
    for item in items:
        key = item.key.strip()
        if not key:
            continue
        raw = item.value.strip()
        parsed: Any = item.value
        if raw in ("true", "false"):
            parsed = raw == "true"
        elif raw and (raw[0] in "[{" or _looks_numeric_json(raw)):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = item.value
        result[key] = parsed
    return result


def _looks_numeric_json(raw: str) -> bool:
    """Return True if raw string appears to be a JSON integer or float."""
    if raw[0] not in "-0123456789":
        return False
    try:
        float(raw)
    except ValueError:
        return False
    else:
        # Preserve identifiers like "005930" as strings.
        if len(raw) > 1 and raw[0] == "0" and raw[1].isdigit():
            return False
        if len(raw) > 2 and raw.startswith("-0") and raw[2].isdigit():
            return False
        return True


class ExtractedEntity(BaseModel):
    """Entity extracted from a research note or article."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 'e1'.")
    name: str = Field(description="Canonical entity name, e.g. 'NVIDIA' or 'Jane Doe'.")
    summary: str = Field(description="Concise description of the entity in context.")
    aliases: list[str] = Field(default_factory=list, description="Alternative names, tickers, acronyms.")
    entity_type: str = Field(
        default="company",
        description="Entity subtype: company | person | product | institution | sector | region.",
    )
    facets: list[FacetKV] = Field(
        default_factory=list,
        description="Dynamic facets such as ticker, sector, role, credibility, organization.",
    )


class ExtractedEvent(BaseModel):
    """Event (fact, news, earnings, catalyst, or meeting) extracted from a document."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 'ev1'.")
    name: str = Field(description="Short title of the event or factual observation.")
    summary: str = Field(description="Detailed unstructured description of what happened or was observed.")
    event_type: str = Field(
        default="fact",
        description="Event subtype: fact | news | earnings | catalyst | meeting.",
    )
    event_date: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD when the event occurred or is expected.",
    )
    status: str = Field(
        default="occurred",
        description="Status: occurred | upcoming | rumored.",
    )
    sentiment: str = Field(
        default="neutral",
        description=(
            "Directional polarity for the primary subject: positive | negative | neutral | mixed. "
            "Use 'mixed' when an event helps one company and hurts another "
            "(and put per-company overrides on ABOUT edges)."
        ),
    )
    facets: list[FacetKV] = Field(
        default_factory=list,
        description="Dynamic facets including optional source_kind, author, title, materiality.",
    )


class ExtractedView(BaseModel):
    """Subjective view (rumor, analyst report, PM view) extracted from a document."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 'v1'.")
    name: str = Field(description="Short title summarizing the thesis, rumor, or opinion.")
    summary: str = Field(description="Full statement of the view and its supporting reasoning.")
    view_type: str = Field(
        default="analyst_report",
        description="Subtype: rumor | analyst_report | pm_view | channel_check (never 'consensus').",
    )
    stance: str = Field(
        default="neutral",
        description="Directional stance: buy | hold | sell | bullish | bearish | neutral | cautious.",
    )
    sentiment: str | None = Field(
        default=None,
        description=(
            "Directional polarity: positive | negative | neutral | mixed. "
            "Consistent with stance; if omitted, derived from stance."
        ),
    )
    support_strength: str = Field(
        default="moderate",
        description="Evidence strength: strong | moderate | weak.",
    )
    conviction: str = Field(
        default="medium",
        description="Speaker or author conviction: high | medium | low.",
    )
    as_of: str | None = Field(default=None, description="ISO date YYYY-MM-DD when the view was stated.")
    facets: list[FacetKV] = Field(
        default_factory=list,
        description="Dynamic facets including optional author, speaker_role, source_kind, horizon.",
    )


class ExtractedTheme(BaseModel):
    """Meta-narrative or investment thesis extracted from a document."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 't1'.")
    name: str = Field(description="Canonical theme title, e.g. 'AI Data Center Power Bottleneck'.")
    summary: str = Field(description="Description of the macro/secular narrative or thesis.")
    aliases: list[str] = Field(default_factory=list, description="Alternative phrasings of this theme.")
    stage: str = Field(
        default="accelerating",
        description="Lifecycle stage: emerging | accelerating | consensus | fading.",
    )
    facets: list[FacetKV] = Field(default_factory=list)


class ExtractedEdge(BaseModel):
    """Directed relationship connecting extracted or existing nodes."""

    from_ref: str = Field(description="Existing node ID from catalog OR a temp_id from this extraction.")
    to_ref: str = Field(description="Existing node ID from catalog OR a temp_id from this extraction.")
    relation: str = Field(
        description=(
            "Uppercase canonical relation name (`from_ref -> to_ref`): "
            "BUY (buyer -> seller), COMPETE (company <-> company), OWNS (parent -> child), "
            "WORKS_AT (person -> company/institution), EXPOSED_TO (entity -> theme with sentiment facet), "
            "ABOUT, AUTHORED_BY, SUPPORTS, CONTRADICTS, RELATES_TO (event/view -> theme)."
        )
    )
    facets: list[FacetKV] = Field(
        default_factory=list,
        description=(
            "Optional edge facets such as rationale, confidence, order, as_of, "
            "or sentiment (positive|negative|neutral|mixed on EXPOSED_TO entity->theme edges "
            "and on ABOUT edges when a multi-company event/view impacts entities differently)."
        ),
    )


class ExtractionResult(BaseModel):
    """Full structured extraction output for a single unstructured document."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)
    views: list[ExtractedView] = Field(default_factory=list)
    themes: list[ExtractedTheme] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class ConsensusSynthesis(BaseModel):
    """Pipeline-synthesized fund consensus view for a single company entity."""

    stance: str = Field(description="Fund stance: buy | hold | sell | bullish | bearish | neutral.")
    support_strength: str = Field(description="Overall evidence strength: strong | moderate | weak.")
    conviction: str = Field(description="Overall conviction: high | medium | low.")
    summary: str = Field(description="Concise synthesis of the current fund consensus and key tension points.")
    pillars: list[str] = Field(
        default_factory=list,
        description="Key falsifiable assumptions underpinning the consensus.",
    )
    supporting_node_ids: list[str] = Field(
        default_factory=list,
        description="IDs of existing event/view/theme nodes that support this consensus.",
    )
    contradicting_node_ids: list[str] = Field(
        default_factory=list,
        description="IDs of existing event/view/theme nodes that challenge or risk this consensus.",
    )
    facets: list[FacetKV] = Field(
        default_factory=list,
        description="Optional extra facets such as key_risks, target_horizon, catalysts_to_watch.",
    )
