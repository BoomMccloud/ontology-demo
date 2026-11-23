"""Closed enum vocabularies for node and edge facets, and the shared signal filter rules.

`ontology_registry.json` is the official ontology and the source of truth: it
declares the vocabularies under `facet_vocabularies` and each official facet's
kind and required flag under `facet_schema`. This module is code's typed copy,
which the extraction models, the LLM prompt, the agent tool schema, `repair` and
`audit` read. `load_registry` checks code against the registry and fails when
they differ (`facet_vocabulary_differences`, `facet_schema_differences`).

Each vocabulary has one rule: strip, lowercase, map spaces and hyphens to `_`,
then apply its alias map. A result outside the members is not canon.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
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
EdgeBasis = Literal["extracted", "synthesized"]


def _clean(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned or None


def coerce_member(raw: Any, members: Iterable[str], aliases: Mapping[str, str]) -> str | None:
    """The one vocabulary rule: clean, apply aliases, and keep the result only if it is a member."""
    cleaned = _clean(raw)
    if cleaned is None:
        return None
    cleaned = aliases.get(cleaned, cleaned)
    return cleaned if cleaned in members else None


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
        return coerce_member(raw, self.members, self.aliases)

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
EDGE_BASIS = Vocabulary(
    "basis",
    EdgeBasis,
    {
        "extracted": "Read from a source note by extraction.",
        "synthesized": "Inferred by consensus synthesis across notes, with no source note of its own.",
    },
)
"""Set by code at each edge write, never by the LLM."""

EDGE_FACET_VOCABS: dict[str, Vocabulary] = {"sentiment": SENTIMENT, "basis": EDGE_BASIS}

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


def is_synthesized_edge(facets: Mapping[str, Any] | None) -> bool:
    """True when an edge's `basis` is `synthesized`. An edge with no `basis` counts as extracted."""
    return bool(facets) and facets.get("basis") == "synthesized"


def _vocabulary_spec(v: Vocabulary) -> dict[str, Any]:
    return {"members": dict(v.definitions), "aliases": dict(v.aliases), "fallback": v.fallback}


def facet_vocabularies_spec() -> dict[str, Any]:
    """The official facet vocabularies as the registry declares them (`facet_vocabularies`)."""
    return {
        "node": {
            node_type: {key: _vocabulary_spec(v) for key, v in group.items()}
            for node_type, group in NODE_FACET_VOCABS.items()
        },
        "edge": {key: _vocabulary_spec(v) for key, v in EDGE_FACET_VOCABS.items()},
    }


def _compare_keys(where: str, got: Mapping[str, Any], want: Mapping[str, Any], diffs: list[str]) -> list[str]:
    diffs.extend(f"{where}.{k}: missing from the registry" for k in sorted(set(want) - set(got)))
    diffs.extend(f"{where}.{k}: not in code" for k in sorted(set(got) - set(want)))
    return sorted(set(want) & set(got))


def _compare_vocabulary(where: str, got: Any, want: dict[str, Any], diffs: list[str]) -> None:
    if not isinstance(got, Mapping):
        diffs.append(f"{where}: not a vocabulary object")
        return
    members = got.get("members")
    if not isinstance(members, Mapping):
        diffs.append(f"{where}.members: missing or not an object")
    else:
        for m in sorted(set(want["members"]) - set(members)):
            diffs.append(f"{where}: member {m!r} missing from the registry")
        for m in sorted(set(members) - set(want["members"])):
            diffs.append(f"{where}: member {m!r} not in code")
        for m in sorted(set(want["members"]) & set(members)):
            if members[m] != want["members"][m]:
                diffs.append(f"{where}: definition of {m!r} differs from code")
    for key in ("aliases", "fallback"):
        if got.get(key, {} if key == "aliases" else None) != want[key]:
            diffs.append(f"{where}.{key}: registry has {got.get(key)!r}, code has {want[key]!r}")


def facet_vocabulary_differences(declared: Mapping[str, Any]) -> list[str]:
    """Each way `declared` (a registry `facet_vocabularies` section) differs from code."""
    want = facet_vocabularies_spec()
    diffs: list[str] = []
    root = "facet_vocabularies"
    for group in _compare_keys(root, declared, want, diffs):
        got_group, want_group = declared[group], want[group]
        if not isinstance(got_group, Mapping):
            diffs.append(f"{root}.{group}: not an object")
            continue
        if group == "edge":
            for key in _compare_keys(f"{root}.edge", got_group, want_group, diffs):
                _compare_vocabulary(f"{root}.edge.{key}", got_group[key], want_group[key], diffs)
            continue
        for node_type in _compare_keys(f"{root}.node", got_group, want_group, diffs):
            got_nt = got_group[node_type]
            if not isinstance(got_nt, Mapping):
                diffs.append(f"{root}.node.{node_type}: not an object")
                continue
            for key in _compare_keys(f"{root}.node.{node_type}", got_nt, want_group[node_type], diffs):
                _compare_vocabulary(
                    f"{root}.node.{node_type}.{key}", got_nt[key], want_group[node_type][key], diffs
                )
    return diffs


def out_of_vocabulary_node_facets(node_type: str, facets: dict[str, Any]) -> dict[str, str]:
    """Return `{facet: value}` for stored enum facets that are not a vocabulary member."""
    vocabs = NODE_FACET_VOCABS.get(node_type, {})
    return {
        k: str(v)
        for k, v in facets.items()
        if k in vocabs and isinstance(v, str) and v not in vocabs[k].members
    }


# ---------------------------------------------------------------------------
# Facet schema: each official facet's value kind and whether it is required
# ---------------------------------------------------------------------------

FacetKind = Literal["enum", "number", "date", "text", "list"]
FACET_KINDS: tuple[str, ...] = get_args(FacetKind)


@dataclass(frozen=True)
class FacetSpec:
    """One official facet: its value kind, and whether every node or edge must carry it."""

    kind: FacetKind
    required: bool = False


_ENUM = FacetSpec("enum")
_REQUIRED_ENUM = FacetSpec("enum", required=True)

# Code's copy of the registry's `facet_schema`. Every `enum` facet has a vocabulary above.
NODE_FACET_SCHEMA: dict[str, dict[str, FacetSpec]] = {
    "entity": {"entity_type": _REQUIRED_ENUM},
    "event": {
        "event_type": _REQUIRED_ENUM,
        "status": _ENUM,
        "sentiment": _ENUM,
        "event_date": FacetSpec("date"),
    },
    "view": {
        "view_type": _REQUIRED_ENUM,
        "status": _ENUM,
        "stance": _ENUM,
        "sentiment": _ENUM,
        "support_strength": _ENUM,
        "conviction": _ENUM,
        "as_of": FacetSpec("date"),
        "target_price": FacetSpec("number"),
    },
    "theme": {"stage": _REQUIRED_ENUM},
}
EDGE_FACET_SCHEMA: dict[str, FacetSpec] = {"sentiment": _ENUM, "basis": _REQUIRED_ENUM}


def _facet_spec_json(spec: FacetSpec) -> dict[str, Any]:
    return {"kind": spec.kind, "required": spec.required}


def facet_schema_spec() -> dict[str, Any]:
    """The official facet schema as the registry declares it (`facet_schema`)."""
    return {
        "node": {
            node_type: {key: _facet_spec_json(spec) for key, spec in group.items()}
            for node_type, group in NODE_FACET_SCHEMA.items()
        },
        "edge": {key: _facet_spec_json(spec) for key, spec in EDGE_FACET_SCHEMA.items()},
    }


def facet_schema_differences(declared: Mapping[str, Any]) -> list[str]:
    """Each way `declared` (a registry `facet_schema` section) differs from code."""
    want = facet_schema_spec()
    diffs: list[str] = []
    root = "facet_schema"

    def compare_group(where: str, got: Any, want_group: Mapping[str, Any]) -> None:
        if not isinstance(got, Mapping):
            diffs.append(f"{where}: not an object")
            return
        for key in _compare_keys(where, got, want_group, diffs):
            if got[key] != want_group[key]:
                diffs.append(f"{where}.{key}: registry has {got[key]!r}, code has {want_group[key]!r}")

    for group in _compare_keys(root, declared, want, diffs):
        if group == "edge":
            compare_group(f"{root}.edge", declared[group], want[group])
            continue
        got_node = declared[group]
        if not isinstance(got_node, Mapping):
            diffs.append(f"{root}.node: not an object")
            continue
        for node_type in _compare_keys(f"{root}.node", got_node, want["node"], diffs):
            compare_group(f"{root}.node.{node_type}", got_node[node_type], want["node"][node_type])
    return diffs


_INT_RE = re.compile(r"-?(0|[1-9][0-9]*)")
_FLOAT_RE = re.compile(r"-?(0|[1-9][0-9]*)\.[0-9]+")


def coerce_facet_value(
    kind: str,
    value: Any,
    *,
    members: Iterable[str] = (),
    aliases: Mapping[str, str] | None = None,
    required: bool = False,
) -> Any:
    """Return `value` as `kind`, converting only where nothing is lost; raise ValueError otherwise.

    A number may arrive as a numeric string (`"630"` becomes `630`). A date is an ISO
    date or datetime string, kept as written. Text accepts a number as its string. An
    enum value is a string; a required enum must also be a vocabulary member and is
    stored as that member, while an optional one keeps today's rule (audit reports
    values outside the vocabulary, repair lowercases them).
    """
    if kind == "enum":
        if not isinstance(value, str):
            raise ValueError(f"expected an enum string, got {value!r}")  # noqa: TRY003
        if not required:
            return value
        member = coerce_member(value, tuple(members), aliases or {})
        if member is None:
            raise ValueError(f"{value!r} is not in the vocabulary")  # noqa: TRY003
        return member
    if kind == "number":
        if isinstance(value, bool):
            raise ValueError(f"expected a number, got {value!r}")  # noqa: TRY003
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if _INT_RE.fullmatch(text):
                return int(text)
            if _FLOAT_RE.fullmatch(text):
                return float(text)
        raise ValueError(f"expected a number, got {value!r}")  # noqa: TRY003
    if kind == "date":
        if isinstance(value, str):
            try:
                if len(value) == 10:
                    date.fromisoformat(value)
                else:
                    datetime.fromisoformat(value)
            except ValueError:
                pass
            else:
                return value
        raise ValueError(f"expected an ISO date, got {value!r}")  # noqa: TRY003
    if kind == "text":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        raise ValueError(f"expected text, got {value!r}")  # noqa: TRY003
    if kind == "list":
        if isinstance(value, list):
            return value
        raise ValueError(f"expected a list, got {value!r}")  # noqa: TRY003
    raise ValueError(f"unknown facet kind {kind!r}")  # noqa: TRY003


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
