"""Closed enum vocabularies for node and edge facets, and the shared signal filter rules.

This is the one source for every closed enum the ontology stores. The extraction
models, the LLM prompt, the agent tool schema, `repair` and `audit` all read from
here. `ontology_registry.json` stays the data registry (relations, companies,
themes); it does not hold these vocabularies.

Each vocabulary has one rule: strip, lowercase, map spaces and hyphens to `_`,
then apply its alias map. A result outside the members is not canon.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast, get_args

EntityType = Literal["company", "person", "product", "institution", "sector", "region"]
EventType = Literal["fact", "news", "earnings", "catalyst", "meeting"]
EventStatus = Literal["occurred", "upcoming", "rumored"]
ViewType = Literal["rumor", "analyst_report", "pm_view", "channel_check", "consensus"]
ViewStatus = Literal["active", "superseded"]
Stance = Literal["bullish", "bearish", "neutral"]
Sentiment = Literal["positive", "negative", "neutral", "mixed"]
SupportStrength = Literal["strong", "moderate", "weak"]
Conviction = Literal["high", "medium", "low"]
Stage = Literal["emerging", "accelerating", "consensus", "fading"]


def _clean(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned or None


@dataclass(frozen=True)
class Vocabulary:
    """One closed enum: its members with definitions, aliases, and the ingest fallback."""

    group: str
    """Facet key, and the `enum.<group>.<member>` locale group."""
    literal: Any
    definitions: Mapping[str, str]
    aliases: Mapping[str, str] = field(default_factory=dict)
    fallback: str | None = None
    """Value ingest stores for an out-of-vocabulary input. None means treat it as missing."""

    def __post_init__(self) -> None:
        members = get_args(self.literal)
        if tuple(self.definitions) != members:
            raise ValueError(f"{self.group}: definitions must list exactly {members}")  # noqa: TRY003
        if any(target not in members for target in self.aliases.values()):
            raise ValueError(f"{self.group}: every alias must map to a member")  # noqa: TRY003
        if self.fallback is not None and self.fallback not in members:
            raise ValueError(f"{self.group}: fallback must be a member")  # noqa: TRY003

    @property
    def members(self) -> tuple[str, ...]:
        return cast(tuple[str, ...], get_args(self.literal))

    def coerce(self, raw: Any) -> str | None:
        """Return the canonical member for `raw`, or None when it is not in the vocabulary."""
        cleaned = _clean(raw)
        if cleaned is None:
            return None
        cleaned = self.aliases.get(cleaned, cleaned)
        return cleaned if cleaned in self.members else None

    def coerce_or_fallback(self, raw: Any) -> str | None:
        """Ingest rule: the canonical member, else this vocabulary's fallback."""
        value = self.coerce(raw)
        return value if value is not None else self.fallback

    def canonicalize_stored(self, raw: Any) -> Any:
        """Repair rule: the canonical member, else the lowercased raw value (never the fallback)."""
        if not isinstance(raw, str):
            return raw
        value = self.coerce(raw)
        return value if value is not None else raw.strip().lower()


ENTITY_TYPE = Vocabulary(
    "entity_type",
    EntityType,
    {
        "company": "A business, listed or private.",
        "person": "An individual, such as an executive, analyst or author.",
        "product": "A product, technology or platform.",
        "institution": "A government body, regulator, fund or other non-company organization.",
        "sector": "An industry or market segment.",
        "region": "A country, region or market geography.",
    },
    fallback="company",
)
EVENT_TYPE = Vocabulary(
    "event_type",
    EventType,
    {
        "fact": "An objective observation or data point.",
        "news": "A reported news item.",
        "earnings": "An earnings release or results call.",
        "catalyst": "A dated future event that may move the stock.",
        "meeting": "A meeting, call or conference with a company or expert.",
    },
    fallback="fact",
)
EVENT_STATUS = Vocabulary(
    "status",
    EventStatus,
    {
        "occurred": "It already happened.",
        "upcoming": "It is expected to happen.",
        "rumored": "It is reported but unconfirmed.",
    },
    aliases={"rumoured": "rumored"},
    fallback="occurred",
)
VIEW_TYPE = Vocabulary(
    "view_type",
    ViewType,
    {
        "rumor": "An unconfirmed claim heard in the market.",
        "analyst_report": "A sell-side or independent analyst's take.",
        "pm_view": "A portfolio manager's own view.",
        "channel_check": "A finding from suppliers, customers or other channel contacts.",
        "consensus": "The fund's house consensus, synthesized by the pipeline only.",
    },
    aliases={"rumour": "rumor", "house_consensus": "consensus"},
    fallback="analyst_report",
)
VIEW_STATUS = Vocabulary(
    "status",
    ViewStatus,
    {
        "active": "The current consensus view.",
        "superseded": "A retired consensus view kept for history.",
    },
    aliases={"stale": "superseded"},
)
STANCE = Vocabulary(
    "stance",
    Stance,
    {
        "bullish": "Expects the price or fundamentals to improve, including a buy rating.",
        "bearish": "Expects the price or fundamentals to worsen, including a sell rating.",
        "neutral": "No directional call, including a hold rating.",
    },
    aliases={
        "buy": "bullish",
        "outperform": "bullish",
        "overweight": "bullish",
        "sell": "bearish",
        "cautious": "bearish",
        "underperform": "bearish",
        "underweight": "bearish",
        "hold": "neutral",
        "unknown": "neutral",
    },
    fallback="neutral",
)
SENTIMENT = Vocabulary(
    "sentiment",
    Sentiment,
    {
        "positive": "Good for the subject.",
        "negative": "Bad for the subject.",
        "neutral": "No directional impact.",
        "mixed": "Offsetting effects, or opposite effects on different companies.",
    },
)
SUPPORT_STRENGTH = Vocabulary(
    "support_strength",
    SupportStrength,
    {
        "strong": "Well supported by evidence.",
        "moderate": "Partly supported.",
        "weak": "Thinly supported.",
    },
    fallback="moderate",
)
CONVICTION = Vocabulary(
    "conviction",
    Conviction,
    {
        "high": "The speaker is confident.",
        "medium": "The speaker is fairly confident.",
        "low": "The speaker is tentative.",
    },
    fallback="medium",
)
STAGE = Vocabulary(
    "stage",
    Stage,
    {
        "emerging": "Early, not widely recognized.",
        "accelerating": "Gaining momentum and attention.",
        "consensus": "Widely accepted and priced in.",
        "fading": "Losing relevance.",
    },
    fallback="accelerating",
)

NODE_FACET_VOCABS: dict[str, dict[str, Vocabulary]] = {
    "entity": {"entity_type": ENTITY_TYPE},
    "event": {"event_type": EVENT_TYPE, "status": EVENT_STATUS, "sentiment": SENTIMENT},
    "view": {
        "view_type": VIEW_TYPE,
        "status": VIEW_STATUS,
        "stance": STANCE,
        "sentiment": SENTIMENT,
        "support_strength": SUPPORT_STRENGTH,
        "conviction": CONVICTION,
    },
    "theme": {"stage": STAGE},
}
EDGE_FACET_VOCABS: dict[str, Vocabulary] = {"sentiment": SENTIMENT}

ALL_VOCABS: tuple[Vocabulary, ...] = (
    ENTITY_TYPE,
    EVENT_TYPE,
    EVENT_STATUS,
    VIEW_TYPE,
    VIEW_STATUS,
    STANCE,
    SENTIMENT,
    SUPPORT_STRENGTH,
    CONVICTION,
    STAGE,
)

# Facet holding each node type's subtype.
SUBTYPE_FACET: dict[str, str] = {
    "entity": "entity_type",
    "event": "event_type",
    "view": "view_type",
    "theme": "stage",
}

# View types an individual document may produce; `consensus` is pipeline-synthesized.
EXTRACTED_VIEW_TYPES: tuple[str, ...] = tuple(m for m in VIEW_TYPE.members if m != "consensus")

VALID_SENTIMENTS: tuple[Sentiment, ...] = cast(tuple[Sentiment, ...], SENTIMENT.members)


def coerce_entity_type(raw: Any) -> str | None:
    return ENTITY_TYPE.coerce(raw)


def coerce_event_type(raw: Any) -> str | None:
    return EVENT_TYPE.coerce(raw)


def coerce_event_status(raw: Any) -> str | None:
    return EVENT_STATUS.coerce(raw)


def coerce_view_type(raw: Any) -> str | None:
    return VIEW_TYPE.coerce(raw)


def coerce_view_status(raw: Any) -> str | None:
    return VIEW_STATUS.coerce(raw)


def coerce_stance(raw: Any) -> str | None:
    return STANCE.coerce(raw)


def coerce_sentiment(raw: Any) -> Sentiment | None:
    return cast(Sentiment | None, SENTIMENT.coerce(raw))


def coerce_support_strength(raw: Any) -> str | None:
    return SUPPORT_STRENGTH.coerce(raw)


def coerce_conviction(raw: Any) -> str | None:
    return CONVICTION.coerce(raw)


def coerce_stage(raw: Any) -> str | None:
    return STAGE.coerce(raw)


def normalize_sentiment(value: Any) -> Sentiment | None:
    """Return canonical Sentiment if `value` is a valid polarity string, else None."""
    return coerce_sentiment(value)


def fold_cautious_conviction(facets: Any) -> Any:
    """A `cautious` stance becomes `bearish` with low conviction, so the nuance moves to `conviction`."""
    if isinstance(facets, dict) and _clean(facets.get("stance")) == "cautious":
        return {**facets, "conviction": "low"}
    return facets


def canonicalize_node_facets(node_type: str, facets: dict[str, Any]) -> dict[str, Any]:
    """Repair rule over one node's facets: members canonical, unknown values lowercased."""
    vocabs = NODE_FACET_VOCABS.get(node_type, {})
    if node_type == "view":
        facets = fold_cautious_conviction(facets)
    return {k: vocabs[k].canonicalize_stored(v) if k in vocabs else v for k, v in facets.items()}


def canonicalize_edge_facets(facets: dict[str, Any]) -> dict[str, Any]:
    """Repair rule over one edge's facets."""
    return {
        k: EDGE_FACET_VOCABS[k].canonicalize_stored(v) if k in EDGE_FACET_VOCABS else v
        for k, v in facets.items()
    }


def out_of_vocabulary_node_facets(node_type: str, facets: dict[str, Any]) -> dict[str, str]:
    """Return `{facet: value}` for stored enum facets that are not a vocabulary member."""
    vocabs = NODE_FACET_VOCABS.get(node_type, {})
    return {
        k: str(v)
        for k, v in facets.items()
        if k in vocabs and isinstance(v, str) and v not in vocabs[k].members
    }


def format_choices(members: Iterable[str], sep: str = " | ") -> str:
    """Render members as "`a` | `b`" for prompts."""
    return sep.join(f"`{m}`" for m in members)


# ---------------------------------------------------------------------------
# Signal filter rules shared by the agent and web search
# ---------------------------------------------------------------------------

UNCLASSIFIED = "unclassified"
SIGNAL_CATEGORIES: tuple[str, ...] = (
    "rumor",
    "news",
    "fact",
    "earnings",
    "catalyst",
    "meeting",
    "analyst_report",
    "pm_view",
    "channel_check",
)
SIGNAL_CATEGORY_ALIASES: dict[str, str] = {
    "rumor": "rumor",
    "rumors": "rumor",
    "news": "news",
    "fact": "fact",
    "facts": "fact",
    "earnings": "earnings",
    "catalyst": "catalyst",
    "catalysts": "catalyst",
    "meeting": "meeting",
    "meetings": "meeting",
    "analyst_report": "analyst_report",
    "analyst_reports": "analyst_report",
    "pm_view": "pm_view",
    "pm_views": "pm_view",
    "channel_check": "channel_check",
    "channel_checks": "channel_check",
    "consensus": "consensus",
}
SENTIMENT_FILTER_VALUES: tuple[str, ...] = (*SENTIMENT.members, UNCLASSIFIED)


def parse_sentiment_filter(raw: Any) -> str | None:
    """Parse one user sentiment filter value; `unknown`/`none` mean unclassified."""
    cleaned = str(raw).strip().lower() if raw is not None else ""
    if not cleaned:
        return None
    return UNCLASSIFIED if cleaned in ("unknown", UNCLASSIFIED, "none") else cleaned


def parse_category_filter(raw: Any) -> str | None:
    """Parse one user subtype/category filter value, applying the plural aliases."""
    cleaned = str(raw).strip().lower().replace(" ", "_") if raw is not None else ""
    if not cleaned:
        return None
    return SIGNAL_CATEGORY_ALIASES.get(cleaned, cleaned)


def parse_filter_values(raws: Iterable[Any] | None, parse: Any) -> set[str] | None:
    """Parse several filter values with `parse`; None when nothing usable remains."""
    if not raws:
        return None
    parsed = {value for value in (parse(raw) for raw in raws) if value is not None}
    return parsed or None


def node_subtype(node_type: str, facets: dict[str, Any]) -> str:
    """Return the stored subtype facet for a node type ("" when absent)."""
    key = SUBTYPE_FACET.get(node_type)
    return str(facets.get(key) or "") if key else ""


def matches_signal_filter(
    node_type: str,
    facets: dict[str, Any],
    effective_sentiment: str | None,
    *,
    categories: set[str] | None = None,
    sentiments: set[str] | None = None,
) -> bool:
    """The one category and sentiment rule used by the agent and web search.

    A category matches the node's subtype, except `rumor`, which also matches an
    event whose status is `rumored`. A sentiment matches the effective sentiment,
    with no sentiment counting as `unclassified`. Filters are pre-parsed sets.
    """
    if categories is not None:
        subtype = node_subtype(node_type, facets)

        def _matches(cat: str) -> bool:
            if cat == "rumor":
                return (node_type == "view" and subtype == "rumor") or (
                    node_type == "event" and (facets.get("status") == "rumored" or subtype == "rumor")
                )
            return subtype == cat

        if not any(_matches(cat) for cat in categories):
            return False
    if sentiments is not None and (effective_sentiment or UNCLASSIFIED) not in sentiments:
        return False
    return True
