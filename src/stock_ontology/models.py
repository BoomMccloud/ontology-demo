"""Core 4-node ontology models, unified edge model, and Gemini structured-output schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from stock_ontology.vocab import (
    CONVICTION,
    ENTITY_TYPE,
    EVENT_STATUS,
    EVENT_TYPE,
    EXTRACTED_VIEW_TYPES,
    SENTIMENT,
    STAGE,
    STANCE,
    SUPPORT_STRENGTH,
    VALID_SENTIMENTS,  # noqa: F401  (re-exported for callers)
    VIEW_TYPE,
    Conviction,
    EntityType,
    EventStatus,
    EventType,
    Sentiment,
    Stage,
    Stance,
    SupportStrength,
    Vocabulary,
    ViewType,
    fold_cautious_conviction,
    normalize_sentiment,
)

NodeType = Literal["entity", "event", "view", "theme"]
SentimentSource = Literal["edge", "node", "stance"]
STANCE_TO_SENTIMENT: dict[str, Sentiment] = {
    "bullish": "positive",
    "bearish": "negative",
    "neutral": "neutral",
}


def derive_sentiment_from_stance(stance: Any) -> Sentiment | None:
    """Map a view stance string onto a canonical Sentiment, or None if unrecognized."""
    if not isinstance(stance, str):
        return None
    canonical = STANCE.coerce(stance)
    return STANCE_TO_SENTIMENT.get(canonical) if canonical is not None else None


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


def _ingest_coercer(vocab: Vocabulary) -> BeforeValidator:
    """Pydantic before-validator: canonical member, else the vocabulary's ingest fallback."""
    return BeforeValidator(vocab.coerce_or_fallback)


def _choices(members: tuple[str, ...]) -> str:
    return " | ".join(members)


# Required subtypes (registry `facet_schema`): an out-of-vocabulary value becomes None instead of
# the fallback, and the default applies only when the field is omitted. Under a registry that
# requires the facet, the pipeline treats either as missing and regenerates the extraction.
CoercedEntityType = Annotated[EntityType | None, BeforeValidator(ENTITY_TYPE.coerce)]
CoercedEventType = Annotated[EventType | None, BeforeValidator(EVENT_TYPE.coerce)]
CoercedEventStatus = Annotated[EventStatus, _ingest_coercer(EVENT_STATUS)]
CoercedViewType = Annotated[ViewType | None, BeforeValidator(VIEW_TYPE.coerce)]
CoercedStance = Annotated[Stance, _ingest_coercer(STANCE)]
CoercedSupportStrength = Annotated[SupportStrength, _ingest_coercer(SUPPORT_STRENGTH)]
CoercedConviction = Annotated[Conviction, _ingest_coercer(CONVICTION)]
CoercedStage = Annotated[Stage | None, BeforeValidator(STAGE.coerce)]
# An unknown sentiment is treated as missing, so `resolve_item_sentiment` precedence applies.
CoercedSentiment = Annotated[Sentiment | None, BeforeValidator(SENTIMENT.coerce)]


class ExtractedEntity(BaseModel):
    """Entity extracted from a research note or article."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 'e1'.")
    name: str = Field(description="Canonical entity name, e.g. 'NVIDIA' or 'Jane Doe'.")
    summary: str = Field(description="Concise description of the entity in context.")
    aliases: list[str] = Field(default_factory=list, description="Alternative names, tickers, acronyms.")
    entity_type: CoercedEntityType = Field(
        default="company",
        description=f"Entity subtype: {_choices(ENTITY_TYPE.members)}.",
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
    event_type: CoercedEventType = Field(
        default="fact",
        description=f"Event subtype: {_choices(EVENT_TYPE.members)}.",
    )
    event_date: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD when the event occurred or is expected.",
    )
    status: CoercedEventStatus = Field(
        default="occurred",
        description=f"Status: {_choices(EVENT_STATUS.members)}.",
    )
    sentiment: CoercedSentiment = Field(
        default="neutral",
        description=(
            f"Directional polarity for the primary subject: {_choices(SENTIMENT.members)}. "
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
    view_type: CoercedViewType = Field(
        default="analyst_report",
        description=f"Subtype: {_choices(EXTRACTED_VIEW_TYPES)} (never 'consensus').",
    )
    stance: CoercedStance = Field(
        default="neutral",
        description=f"Directional stance: {_choices(STANCE.members)}.",
    )
    sentiment: CoercedSentiment = Field(
        default=None,
        description=(
            f"Directional polarity: {_choices(SENTIMENT.members)}. "
            "Consistent with stance; if omitted, derived from stance."
        ),
    )
    support_strength: CoercedSupportStrength = Field(
        default="moderate",
        description=f"Evidence strength: {_choices(SUPPORT_STRENGTH.members)}.",
    )
    conviction: CoercedConviction = Field(
        default="medium",
        description=f"Speaker or author conviction: {_choices(CONVICTION.members)}.",
    )
    as_of: str | None = Field(default=None, description="ISO date YYYY-MM-DD when the view was stated.")
    facets: list[FacetKV] = Field(
        default_factory=list,
        description="Dynamic facets including optional author, speaker_role, source_kind, horizon.",
    )


    @model_validator(mode="before")
    @classmethod
    def _fold_cautious(cls, data: Any) -> Any:
        return fold_cautious_conviction(data)


class ExtractedTheme(BaseModel):
    """Meta-narrative or investment thesis extracted from a document."""

    temp_id: str = Field(description="Temporary ID unique within this extraction, e.g. 't1'.")
    name: str = Field(description="Canonical theme title, e.g. 'AI Data Center Power Bottleneck'.")
    summary: str = Field(description="Description of the macro/secular narrative or thesis.")
    aliases: list[str] = Field(default_factory=list, description="Alternative phrasings of this theme.")
    stage: CoercedStage = Field(
        default="accelerating",
        description=f"Lifecycle stage: {_choices(STAGE.members)}.",
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
            f"or sentiment ({'|'.join(SENTIMENT.members)} on EXPOSED_TO entity->theme edges "
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


class EntityStageResult(BaseModel):
    """Extraction run 1: the note's entities and themes, and the edges between them."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    themes: list[ExtractedTheme] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class EventStageResult(BaseModel):
    """Extraction run 2: the note's events and their edges to resolved nodes."""

    events: list[ExtractedEvent] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class ViewStageResult(BaseModel):
    """Extraction run 3: the note's views and their edges to resolved nodes."""

    views: list[ExtractedView] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


class ConsensusSynthesis(BaseModel):
    """Pipeline-synthesized fund consensus view for a single company entity."""

    stance: CoercedStance = Field(description=f"Fund stance: {_choices(STANCE.members)}.")
    support_strength: CoercedSupportStrength = Field(
        description=f"Overall evidence strength: {_choices(SUPPORT_STRENGTH.members)}."
    )
    conviction: CoercedConviction = Field(
        description=f"Overall conviction: {_choices(CONVICTION.members)}."
    )
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

    @model_validator(mode="before")
    @classmethod
    def _fold_cautious(cls, data: Any) -> Any:
        return fold_cautious_conviction(data)
