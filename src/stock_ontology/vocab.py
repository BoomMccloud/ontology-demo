"""Closed enum vocabularies for node and edge facets, and the shared signal filter rules.

`ontology_registry.json` is the official ontology and the source of truth: it
declares the vocabularies under `facet_vocabularies` and each official facet's
kind and required flag under `facet_schema`. This module holds code's typed copy
of the vocabularies, which the extraction models, the LLM prompt, the agent tool
schema, `repair` and `audit` read; `load_registry` fails when they differ
(`facet_vocabulary_differences`). Code keeps no copy of the per-type facet specs:
it checks only that `facet_schema` declares the subtype facets code depends on
(`facet_schema_problems`), and keeps a base schema for the built-in registry.

Each vocabulary has one rule: strip, lowercase, map spaces and hyphens to `_`,
then apply its alias map. A result outside the members is not canon.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, cast, get_args

EntityType = Literal["company", "person", "institution", "sector", "region"]
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

ACCURACY = Vocabulary(
    "accuracy",
    Conviction,
    {
        "high": "Our view: the person's claims usually prove accurate.",
        "medium": "Our view: the person's claims are sometimes accurate.",
        "low": "Our view: the person's claims often prove inaccurate.",
    },
)
"""A person's accuracy as we judge it. Set by hand in the app, never by extraction."""

NODE_FACET_VOCABS: dict[str, dict[str, Vocabulary]] = {
    "entity": {"entity_type": ENTITY_TYPE, "accuracy": ACCURACY},
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

EDGE_CONFIDENCE = Vocabulary(
    "confidence",
    Conviction,
    {
        "high": "The source states the link directly.",
        "medium": "The source implies the link.",
        "low": "The link is tentative.",
    },
)

EDGE_FACET_VOCABS: dict[str, Vocabulary] = {"sentiment": SENTIMENT, "basis": EDGE_BASIS, "confidence": EDGE_CONFIDENCE}

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
    ACCURACY,
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

FacetKind = Literal["enum", "number", "date", "text", "list", "money"]
FACET_KINDS: tuple[str, ...] = get_args(FacetKind)


@dataclass(frozen=True)
class FacetSpec:
    """One official facet: its value kind, and whether every node or edge must carry it."""

    kind: FacetKind
    required: bool = False


_ENUM = FacetSpec("enum")
_REQUIRED_ENUM = FacetSpec("enum", required=True)

# Base schema of the built-in registry (`create_minimal_registry`), used when a DB is opened
# without one. It is a minimum, not a copy of the shipped `facet_schema`, and is never compared with it.
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
        "target_price": FacetSpec("money"),
    },
    "theme": {"stage": _REQUIRED_ENUM},
}
EDGE_FACET_SCHEMA: dict[str, FacetSpec] = {"sentiment": _ENUM, "basis": _REQUIRED_ENUM}

# The facets code depends on: every registry `facet_schema` must declare each as a required enum.
REQUIRED_NODE_SUBTYPE_FACETS: dict[str, str] = dict(SUBTYPE_FACET)
REQUIRED_EDGE_FACETS: tuple[str, ...] = ("basis",)

# Node metadata whose max length the registry declares (`metadata_max_length`), with the
# built-in registry's values.
METADATA_MAX_LENGTH: dict[str, int] = {"name": 200, "summary": 1000}


def _facet_spec_json(spec: FacetSpec) -> dict[str, Any]:
    return {"kind": spec.kind, "required": spec.required}


def facet_schema_spec() -> dict[str, Any]:
    """The built-in registry's base facet schema, in the registry's `facet_schema` shape."""
    return {
        "node": {
            node_type: {key: _facet_spec_json(spec) for key, spec in group.items()}
            for node_type, group in NODE_FACET_SCHEMA.items()
        },
        "edge": {key: _facet_spec_json(spec) for key, spec in EDGE_FACET_SCHEMA.items()},
    }


def facet_schema_problems(declared: Any) -> list[str]:
    """Each way a registry `facet_schema` is malformed or misses a facet code depends on.

    Node keys are a node type or `entity:<entity_type>`; each facet is `{kind, required}`.
    The subtype facets and edge `basis` must be required enums. Anything else is the registry's call.
    """
    root = "facet_schema"
    if not isinstance(declared, Mapping):
        return [f"{root}: not an object"]
    problems = [f"{root}.{k}: unknown section" for k in sorted(set(declared) - {"node", "edge", "relation"})]

    def check_group(where: str, group: Any) -> Mapping[str, Any]:
        if not isinstance(group, Mapping):
            problems.append(f"{where}: not an object")
            return {}
        for key, spec in group.items():
            if not isinstance(spec, Mapping) or set(spec) != {"kind", "required"}:
                problems.append(f"{where}.{key}: expected exactly {{kind, required}}")
            elif spec["kind"] not in FACET_KINDS:
                problems.append(f"{where}.{key}: unknown kind {spec['kind']!r}")
            elif not isinstance(spec["required"], bool):
                problems.append(f"{where}.{key}: required must be true or false")
        return group

    def require_enum(where: str, group: Mapping[str, Any], key: str) -> None:
        if group.get(key) != {"kind": "enum", "required": True}:
            problems.append(f"{where}.{key}: code requires it declared as a required enum")

    node = declared.get("node")
    if not isinstance(node, Mapping):
        problems.append(f"{root}.node: missing or not an object")
        node = {}
    for owner in node:
        where = f"{root}.node.{owner}"
        base, _, subtype = str(owner).partition(":")
        if base not in REQUIRED_NODE_SUBTYPE_FACETS or (subtype and (base != "entity" or subtype not in ENTITY_TYPE.members)):
            problems.append(f"{where}: unknown node type")
            continue
        group = check_group(where, node[owner])
        if subtype and REQUIRED_NODE_SUBTYPE_FACETS[base] in group:
            problems.append(f"{where}.{REQUIRED_NODE_SUBTYPE_FACETS[base]}: a subtype cannot redeclare it")
    for node_type, key in REQUIRED_NODE_SUBTYPE_FACETS.items():
        group = node.get(node_type)
        require_enum(f"{root}.node.{node_type}", group if isinstance(group, Mapping) else {}, key)

    edge = declared.get("edge")
    if not isinstance(edge, Mapping):
        problems.append(f"{root}.edge: missing or not an object")
        edge = {}
    check_group(f"{root}.edge", edge)
    for key in REQUIRED_EDGE_FACETS:
        require_enum(f"{root}.edge", edge, key)
    relations = declared.get("relation", {})
    if not isinstance(relations, Mapping):
        problems.append(f"{root}.relation: not an object")
        relations = {}
    for relation, group in relations.items():
        where = f"{root}.relation.{relation}"
        checked = check_group(where, group)
        problems.extend(f"{where}.{key}: a relation cannot redeclare it" for key in REQUIRED_EDGE_FACETS if key in checked)
    return problems


_INT_RE = re.compile(r"-?(0|[1-9][0-9]*)")
_FLOAT_RE = re.compile(r"-?(0|[1-9][0-9]*)\.[0-9]+")
_MONEY_SYMBOLS = {"US$": "USD", "NT$": "TWD", "HK$": "HKD"}
_MONEY_AMOUNT = r"(?P<amount>[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)(?P<scale>[KMBT])?(?P<plus>\+)?"
_MONEY_SCALES = {"K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12}
_MONEY_RES = (
    re.compile(rf"(?P<currency>US\$|NT\$|HK\$|[A-Z]{{3}})\s*{_MONEY_AMOUNT}"),
    re.compile(rf"{_MONEY_AMOUNT}\s*(?P<currency>[A-Z]{{3}})"),
)
_CURRENCY_RE = re.compile(r"[A-Z]{3}")


def _coerce_money(value: Any) -> dict[str, Any]:
    """Return `{amount, currency[, qualifier]}`. A bare number or a plain `$` names no currency, so it fails."""
    if isinstance(value, str):
        text = value.strip()
        match = next((m for m in (r.fullmatch(text) for r in _MONEY_RES) if m), None)
        if match is None:
            raise ValueError(f"expected an amount with a currency, got {value!r}")  # noqa: TRY003
        raw = match["amount"].replace(",", "")
        scaled = Decimal(raw) * _MONEY_SCALES.get(match["scale"] or "", 1)
        money: dict[str, Any] = {
            "amount": int(scaled) if scaled == scaled.to_integral_value() else float(scaled),
            "currency": _MONEY_SYMBOLS.get(match["currency"], match["currency"]),
        }
        if match["plus"]:
            money["qualifier"] = "at_least"
        value = money
    if not isinstance(value, Mapping) or not {"amount", "currency"} <= set(value) <= {"amount", "currency", "qualifier"}:
        raise ValueError(f"expected an amount with a currency, got {value!r}")  # noqa: TRY003
    amount, currency = value["amount"], value["currency"]
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError(f"expected a positive amount, got {amount!r}")  # noqa: TRY003
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        raise ValueError(f"expected a 3-letter currency code, got {currency!r}")  # noqa: TRY003
    if value.get("qualifier", "at_least") != "at_least":
        raise ValueError(f"unknown money qualifier {value['qualifier']!r}")  # noqa: TRY003
    return dict(value)


def coerce_facet_value(
    kind: str,
    value: Any,
    *,
    members: Iterable[str] = (),
    aliases: Mapping[str, str] | None = None,
) -> Any:
    """Return `value` as `kind`, converting only where nothing is lost; raise ValueError otherwise.

    A number may arrive as a numeric string (`"630"` becomes `630`). A date is an ISO
    date or datetime string, kept as written. Text accepts a number as its string. An
    enum value, required or optional, must be a vocabulary member and is stored as
    that member.
    """
    if kind == "enum":
        if not isinstance(value, str):
            raise ValueError(f"expected an enum string, got {value!r}")  # noqa: TRY003
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
    if kind == "money":
        return _coerce_money(value)
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
