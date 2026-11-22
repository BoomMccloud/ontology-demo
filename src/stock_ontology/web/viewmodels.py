"""ViewModels transforming read-only OntologyDB records into template contexts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from collections import Counter

from stock_ontology.audit import (
    AuditReport,
    classify_edge_against_registry,
    node_type_label,
    run_ontology_audit,
)
from stock_ontology.db import SIGNAL_CATEGORY_ALIASES, OntologyDB, node_to_dict
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    translate,
    translate_enum,
    translate_facet_label,
)
from stock_ontology.llm import LLMClient
from stock_ontology.models import VALID_SENTIMENTS, Node, NodeType, resolve_item_sentiment
from stock_ontology.registry import (
    OntologyRegistry,
    normalize_name_key,
    normalize_relation_name,
)
from stock_ontology.web.catalog import format_source_citation, resolve_safe_note_path

COMPANY_FACET_KEYS = (
    "ticker",
    "sector",
    "industry",
    "exchange",
    "market_cap",
    "headquarters",
)
PERSON_FACET_KEYS = ("role", "organization", "credibility", "title", "firm")
CONSENSUS_CORE_KEYS = {
    "view_type",
    "status",
    "stance",
    "sentiment",
    "support_strength",
    "conviction",
    "as_of",
    "pillars",
}

DEFAULT_SUBTYPES_BY_TYPE: dict[str, list[str]] = {
    "entity": ["company", "person", "product", "institution", "sector", "region"],
    "event": ["fact", "news", "earnings", "catalyst", "meeting"],
    "view": ["consensus", "analyst_report", "pm_view", "rumor", "channel_check"],
    "theme": ["emerging", "accelerating", "consensus", "fading"],
}

CANONICAL_STANCES: list[str] = [
    "buy",
    "bullish",
    "overweight",
    "outperform",
    "hold",
    "neutral",
    "cautious",
    "sell",
    "bearish",
    "underperform",
    "underweight",
]

STRUCTURE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "key": "entity",
        "number": "1",
        "title": "Entity",
        "plural": "Entities",
        "subtitle": "Companies, People, Products, Institutions & Regions",
        "lifecycle": "Canonical (deduplicated across notes)",
        "subtype_key": "entity_type",
        "description": "Durable real-world actors and instruments. Merged across documents by name, alias, and vector similarity.",
    },
    {
        "key": "event",
        "number": "2",
        "title": "Event",
        "plural": "Events",
        "subtitle": "Objective Facts, News, Earnings, Meetings & Catalysts",
        "lifecycle": "Document-scoped (linked to raw notes)",
        "subtype_key": "event_type",
        "description": "Timestamped observations extracted from research files with status, source provenance, and directional sentiment.",
    },
    {
        "key": "view",
        "number": "3",
        "title": "View",
        "plural": "Views",
        "subtitle": "Analyst Reports, Rumors, Channel Checks, PM & Consensus Views",
        "lifecycle": "Doc-scoped + synthesized House Consensus",
        "subtype_key": "view_type",
        "description": "Subjective theses and ratings, plus pipeline-synthesized fund consensus views with falsifiable pillars.",
    },
    {
        "key": "theme",
        "number": "4",
        "title": "Theme",
        "plural": "Themes",
        "subtitle": "Secular Narratives & Multi-Company Investment Theses",
        "lifecycle": "Canonical (stage-tracked narratives)",
        "subtype_key": "stage",
        "description": "Cross-company macro or industry theses enabling 1st-order and 2nd-order supply-chain exposure mapping.",
    },
)


def format_facet_value(value: Any, lang: str = DEFAULT_LANGUAGE) -> str:
    """Render any JSON facet value into a human-readable string."""
    if isinstance(value, bool):
        return translate_enum("bool", value, lang=lang)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _format_facet_pairs(
    facets: dict[str, Any],
    keys: tuple[str, ...] | list[str],
    lang: str = DEFAULT_LANGUAGE,
) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for k in keys:
        if k in facets and facets[k] not in (None, "", [], {}):
            pairs.append(
                {
                    "key": k,
                    "label": translate_facet_label(k, lang=lang),
                    "value": format_facet_value(facets[k], lang=lang),
                }
            )
    return pairs


def build_rail_context(db: OntologyDB) -> dict[str, Any]:
    """Compute lightweight sidebar navigation counts from read-only OntologyDB."""
    stats = db.get_stats()
    all_entities = db.list_nodes(node_type="entity", limit=1000)
    company_count = sum(
        1
        for ent in all_entities
        if str(ent.facets.get("entity_type", "entity")).lower() == "company"
    )
    other_entity_count = len(all_entities) - company_count
    return {
        "total_nodes": stats["total_nodes"],
        "total_edges": stats["total_edges"],
        "company_count": company_count,
        "other_entity_count": other_entity_count,
        "theme_count": stats["nodes"]["theme"],
        "doc_count": stats["ingested_files"],
    }


def _load_entities_split(
    db: OntologyDB,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load and sort company entities separately from non-company entities."""
    all_entities = db.list_nodes(node_type="entity", limit=1000)
    companies: list[dict[str, Any]] = []
    other_entities: list[dict[str, Any]] = []

    for ent in all_entities:
        etype = str(ent.facets.get("entity_type", "entity")).lower()
        if etype == "company":
            overview = db.get_entity_overview(ent.id)
            cons = overview["consensus"]
            companies.append(
                {
                    "id": ent.id,
                    "name": ent.name,
                    "summary": ent.summary,
                    "aliases": ent.aliases,
                    "ticker": ent.facets.get("ticker", ""),
                    "sector": ent.facets.get("sector", ""),
                    "facets": ent.facets,
                    "consensus": {
                        "stance": cons["facets"].get("stance", ""),
                        "conviction": cons["facets"].get("conviction", ""),
                        "support_strength": cons["facets"].get("support_strength", ""),
                        "as_of": cons["facets"].get("as_of", ""),
                        "summary": cons["summary"],
                    }
                    if cons
                    else None,
                    "event_count": len(overview["events"]),
                    "view_count": len(overview["views"]),
                    "theme_count": len(overview["themes"]),
                }
            )
        else:
            other_entities.append(
                {
                    "id": ent.id,
                    "name": ent.name,
                    "entity_type": etype,
                    "role": ent.facets.get("role", ""),
                    "credibility": ent.facets.get("credibility", ""),
                    "organization": ent.facets.get("organization", ""),
                    "summary": ent.summary,
                }
            )

    companies.sort(
        key=lambda c: (
            0 if c["consensus"] else 1,
            -(c["event_count"] + c["view_count"]),
            c["name"].casefold(),
        )
    )
    other_entities.sort(key=lambda e: e["name"].casefold())
    return companies, other_entities


def _load_themes_list(db: OntologyDB) -> list[dict[str, Any]]:
    """Load and sort investment themes with 1st- and 2nd-order company counts."""
    themes: list[dict[str, Any]] = []
    for thm in db.list_nodes(node_type="theme", limit=500):
        tc = db.find_theme_companies(thm.id, include_second_order=True)
        first_companies: list[dict[str, str]] = []
        for entry in tc["first_order"]:
            comp = entry["company"]
            rel = ""
            if entry["links"]:
                first_link = entry["links"][0]
                rel = first_link.get("relation") or first_link.get("theme_relation") or ""
            first_companies.append(
                {
                    "id": comp["id"],
                    "name": comp["name"],
                    "ticker": str(comp["facets"].get("ticker", "")),
                    "relation": rel,
                }
            )
        neighbor_ids: dict[str, set[str]] = {"view": set(), "event": set()}
        for item in db.get_incident_edges(thm.id):
            nb = item["neighbor"]
            if nb["node_type"] in neighbor_ids:
                neighbor_ids[nb["node_type"]].add(str(nb["id"]))
        themes.append(
            {
                "id": thm.id,
                "name": thm.name,
                "summary": thm.summary,
                "stage": thm.facets.get("stage", ""),
                "first_order_companies": first_companies,
                "first_order_count": len(tc["first_order"]),
                "second_order_count": len(tc["second_order"]),
                "view_count": len(neighbor_ids["view"]),
                "event_count": len(neighbor_ids["event"]),
            }
        )

    themes.sort(
        key=lambda t: (
            -(t["first_order_count"] + t["second_order_count"]),
            t["name"].casefold(),
        )
    )
    return themes


def build_home_context(db: OntologyDB, lang: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """Prepare curated 1997 Reading Room home page data."""
    stats = db.get_stats()
    companies, other_entities = _load_entities_split(db)
    themes = _load_themes_list(db)

    return {
        "stats": stats,
        "companies": companies,
        "other_entities": other_entities,
        "themes": themes,
        "featured_companies": companies[:5],
        "featured_themes": themes[:5],
        "total_companies": len(companies),
        "total_themes": len(themes),
        "total_other_entities": len(other_entities),
        "search_options": build_search_filter_options(db),
        "page_context": translate("page_context.home", lang=lang),
    }


def build_companies_context(
    db: OntologyDB, kind: str = "companies", lang: str = DEFAULT_LANGUAGE
) -> dict[str, Any]:
    """Prepare the full Companies & Catalogued Entities directory context."""
    active_kind = "other" if kind.strip().lower() == "other" else "companies"
    companies, other_entities = _load_entities_split(db)
    return {
        "active_kind": active_kind,
        "companies": companies,
        "other_entities": other_entities,
        "page_context": translate("page_context.companies", lang=lang),
    }


def build_themes_context(
    db: OntologyDB, lang: str = DEFAULT_LANGUAGE
) -> dict[str, Any]:
    """Prepare the full Investment Themes directory context."""
    themes = _load_themes_list(db)
    return {
        "themes": themes,
        "page_context": translate("page_context.themes", lang=lang),
    }


def _resolve_source_fields(
    source_obj: Any, data_dir: Path | None
) -> tuple[str | None, str | None, bool]:
    fp = (
        str(source_obj.get("file_path") or "").strip()
        if isinstance(source_obj, dict)
        else ""
    )
    label, exists = format_source_citation(fp, data_dir)
    return (fp or None), (label or None), exists


# ---------------------------------------------------------------------------
# Presentation models
#
# Page templates read only these frozen dataclasses and prepared label/value pairs,
# never raw ontology nodes, `facets`, or `edge_facets`. The mappers below are the one
# place that knows how ontology records are shaped. Enum fields keep the raw code so
# templates translate them with `t_enum` and pick badge classes; everything else is
# display-ready. `tests/test_web.py::test_entity_page_templates_only_see_presentation_models`
# and `::test_theme_page_templates_only_see_presentation_models` enforce this for the
# entity and theme pages.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceCitation:
    """Where an event or view came from, ready to cite."""

    label: str | None = None
    file: str | None = None
    exists: bool = False
    author: str | None = None
    kind: str | None = None


@dataclass(frozen=True)
class EventRow:
    """One row of the events section."""

    id: str
    name: str
    summary: str
    relation: str
    date: str
    event_type: str | None
    status: str | None
    sentiment: str | None
    # None, "entity" (sentiment is this entity's impact), or "overall" (it differs from overall_sentiment).
    impact_note: str | None
    overall_sentiment: str | None
    source: SourceCitation


@dataclass(frozen=True)
class ViewRow:
    """One row of the views section."""

    id: str
    name: str
    summary: str
    stance: str | None
    sentiment: str | None
    support_strength: str | None
    view_type: str | None
    as_of: str | None
    conviction: str | None
    impact_note: str | None
    overall_sentiment: str | None
    source: SourceCitation


@dataclass(frozen=True)
class EntityHeader:
    """Title block of an entity page."""

    id: str
    name: str
    summary: str
    aliases: tuple[str, ...]
    ticker: str | None
    entity_type: str


@dataclass(frozen=True)
class ConsensusSummary:
    """The active house consensus card."""

    name: str
    summary: str
    stance: str | None
    support_strength: str | None
    conviction: str | None
    as_of: str | None
    pillars: tuple[str, ...]
    extra_facets: list[dict[str, str]]


@dataclass(frozen=True)
class PriorConsensusRow:
    """One superseded consensus in the history list."""

    stance: str
    as_of: str
    summary: str


@dataclass(frozen=True)
class ThemeLinkRow:
    """One theme an entity is linked to."""

    id: str
    name: str
    summary: str
    stage: str | None
    relation: str
    direction: str
    exposure_sentiment: str | None
    via: str


@dataclass(frozen=True)
class RelationLink:
    relation: str
    direction: str


@dataclass(frozen=True)
class RelatedEntityRow:
    """One peer entity and the relationships to it."""

    id: str
    name: str
    summary: str
    entity_type: str | None
    relationships: tuple[RelationLink, ...]


@dataclass(frozen=True)
class ThemeHeader:
    """Title block of a theme page."""

    id: str
    name: str
    summary: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ExposureLink:
    """How a first-order company is exposed to a theme: directly, or via an event or view."""

    # "direct", or "<event|view>: <name>" for a link through an event or view.
    via: str
    relation: str | None
    direction: str | None
    sentiment: str | None
    entity_relation: str | None
    theme_relation: str | None
    source: SourceCitation


@dataclass(frozen=True)
class FirstOrderRow:
    """One company directly or evidentially exposed to a theme."""

    company: EntityHeader
    consensus_stance: str | None
    links: tuple[ExposureLink, ...]


@dataclass(frozen=True)
class SecondOrderPath:
    """One relationship tying a second-order company to a first-order one."""

    relation: str
    direction: str
    connected_to: str
    connected_to_id: str


@dataclass(frozen=True)
class SecondOrderRow:
    """One supply-chain or peer company reached through a first-order company."""

    company: EntityHeader
    consensus_stance: str | None
    paths: tuple[SecondOrderPath, ...]


def _text(value: Any) -> str | None:
    """Return a non-empty facet value as text, or None."""
    return str(value) if value else None


def _source_citation(facets: dict[str, Any], data_dir: Path | None) -> SourceCitation:
    src = facets.get("source")
    fp, label, exists = _resolve_source_fields(src, data_dir)
    src_map = src if isinstance(src, dict) else {}
    return SourceCitation(
        label=label,
        file=fp,
        exists=exists,
        author=_text(src_map.get("author")),
        kind=_text(src_map.get("kind")),
    )


def _sentiment_display(item: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return (shown sentiment, impact note, overall sentiment) for an event or view row."""
    node_sent = item.get("facets", {}).get("sentiment")
    shown = item.get("effective_sentiment") or node_sent
    if item.get("sentiment_source") != "edge":
        return _text(shown), None, None
    if node_sent and node_sent != shown:
        return _text(shown), "overall", _text(node_sent)
    return _text(shown), "entity", None


def _event_row(item: dict[str, Any], data_dir: Path | None) -> EventRow:
    facets = item.get("facets", {})
    sentiment, note, overall = _sentiment_display(item)
    event_type = facets.get("event_type", "event")
    return EventRow(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        summary=str(item.get("summary", "")),
        relation=str(item.get("relation", "")),
        date=str(facets.get("event_date", "-")),
        event_type=None if event_type is None else str(event_type),
        status=_text(facets.get("status")),
        sentiment=sentiment,
        impact_note=note,
        overall_sentiment=overall,
        source=_source_citation(facets, data_dir),
    )


def _view_row(item: dict[str, Any], data_dir: Path | None) -> ViewRow:
    facets = item.get("facets", {})
    sentiment, note, overall = _sentiment_display(item)
    view_type = facets.get("view_type", "view")
    return ViewRow(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        summary=str(item.get("summary", "")),
        stance=_text(facets.get("stance")),
        sentiment=sentiment,
        support_strength=_text(facets.get("support_strength")),
        view_type=None if view_type is None else str(view_type),
        as_of=_text(facets.get("as_of")),
        conviction=_text(facets.get("conviction")),
        impact_note=note,
        overall_sentiment=overall,
        source=_source_citation(facets, data_dir),
    )


def _entity_header(entity: dict[str, Any], entity_type: str) -> EntityHeader:
    return EntityHeader(
        id=str(entity["id"]),
        name=str(entity.get("name", "")),
        summary=str(entity.get("summary", "")),
        aliases=tuple(str(a) for a in entity.get("aliases") or ()),
        ticker=_text(entity.get("facets", {}).get("ticker")),
        entity_type=entity_type,
    )


def _consensus_summary(cons: dict[str, Any], lang: str) -> ConsensusSummary:
    cf = cons.get("facets", {})
    extra_keys = [k for k in sorted(cf.keys()) if k not in CONSENSUS_CORE_KEYS]
    pillars = cf.get("pillars") or ()
    if not isinstance(pillars, (list, tuple)):
        pillars = (pillars,)
    return ConsensusSummary(
        name=str(cons.get("name", "")),
        summary=str(cons.get("summary", "")),
        stance=_text(cf.get("stance")),
        support_strength=_text(cf.get("support_strength")),
        conviction=_text(cf.get("conviction")),
        as_of=_text(cf.get("as_of")),
        pillars=tuple(str(p) for p in pillars),
        extra_facets=_format_facet_pairs(cf, extra_keys, lang=lang),
    )


def _prior_consensus_row(cons: dict[str, Any]) -> PriorConsensusRow:
    cf = cons.get("facets", {})
    return PriorConsensusRow(
        stance=str(cf.get("stance", "unknown")),
        as_of=str(cf.get("as_of", "")),
        summary=str(cons.get("summary", "")),
    )


def _theme_link_row(thm: dict[str, Any]) -> ThemeLinkRow:
    edge_facets = thm.get("edge_facets")
    edge_sent = edge_facets.get("sentiment") if isinstance(edge_facets, dict) else None
    return ThemeLinkRow(
        id=str(thm["id"]),
        name=str(thm.get("name", "")),
        summary=str(thm.get("summary", "")),
        stage=_text(thm.get("facets", {}).get("stage")),
        relation=str(thm.get("relation", "")),
        direction=str(thm.get("direction", "")),
        exposure_sentiment=_text(thm.get("exposure_sentiment") or edge_sent),
        via=str(thm.get("via", "")),
    )


def _related_entity_row(rel: dict[str, Any]) -> RelatedEntityRow:
    links = rel.get("relationships") or [rel]
    entity_type = rel.get("facets", {}).get("entity_type", "entity")
    return RelatedEntityRow(
        id=str(rel["id"]),
        name=str(rel.get("name", "")),
        summary=str(rel.get("summary", "")),
        entity_type=None if entity_type is None else str(entity_type),
        relationships=tuple(
            RelationLink(relation=str(r.get("relation", "")), direction=str(r.get("direction", "")))
            for r in links
        ),
    )


def _theme_header(theme: dict[str, Any]) -> ThemeHeader:
    return ThemeHeader(
        id=str(theme["id"]),
        name=str(theme.get("name", "")),
        summary=str(theme.get("summary", "")),
        aliases=tuple(str(a) for a in theme.get("aliases") or ()),
    )


def _exposure_link(link: dict[str, Any], data_dir: Path | None) -> ExposureLink:
    via = str(link.get("via", ""))
    if via == "direct":
        facets = link.get("facets")
        link_sent = facets.get("sentiment") if isinstance(facets, dict) else None
        return ExposureLink(
            via=via,
            relation=str(link.get("relation", "")),
            direction=str(link.get("direction", "outgoing")),
            sentiment=_text(link.get("exposure_sentiment") or link_sent),
            entity_relation=None,
            theme_relation=None,
            source=SourceCitation(),
        )
    return ExposureLink(
        via=via,
        relation=None,
        direction=None,
        sentiment=None,
        entity_relation=str(link.get("entity_relation", "")),
        theme_relation=str(link.get("theme_relation", "")),
        source=_source_citation(link, data_dir),
    )


def _first_order_row(row: dict[str, Any], data_dir: Path | None) -> FirstOrderRow:
    return FirstOrderRow(
        company=_entity_header(row["company"], "company"),
        consensus_stance=_text(row.get("consensus_stance")),
        links=tuple(_exposure_link(link, data_dir) for link in row.get("links", ())),
    )


def _second_order_row(row: dict[str, Any]) -> SecondOrderRow:
    return SecondOrderRow(
        company=_entity_header(row["company"], "company"),
        consensus_stance=_text(row.get("consensus_stance")),
        paths=tuple(
            SecondOrderPath(
                relation=str(path.get("relation", "")),
                direction=str(path.get("direction", "")),
                connected_to=str(path.get("connected_to", "")),
                connected_to_id=str(path.get("connected_to_id", "")),
            )
            for path in row.get("paths", ())
        ),
    )


def build_entity_context(
    db: OntologyDB,
    entity_id: str,
    *,
    data_dir: Path | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare dynamic facet-driven context for any entity (company, person, product, etc.)."""
    overview = db.get_entity_overview(entity_id)
    entity = overview["entity"]
    if entity["node_type"] != "entity":
        raise KeyError(f"Node {entity_id} is a {entity['node_type']}, not an entity")  # noqa: TRY003

    facets: dict[str, Any] = entity.get("facets", {})
    entity_type = str(facets.get("entity_type", "entity")).lower()

    company_facets = _format_facet_pairs(facets, COMPANY_FACET_KEYS, lang=lang)
    person_facets = _format_facet_pairs(facets, PERSON_FACET_KEYS, lang=lang)

    consumed = {"entity_type", *COMPANY_FACET_KEYS, *PERSON_FACET_KEYS}
    extra_keys = [k for k in sorted(facets.keys()) if k not in consumed]
    extra_facets = _format_facet_pairs(facets, extra_keys, lang=lang)

    cons_raw = overview["consensus"]
    consensus = _consensus_summary(cons_raw, lang) if cons_raw is not None else None

    events = sorted(
        overview["events"],
        key=lambda ev: str(ev.get("facets", {}).get("event_date", "") or ""),
        reverse=True,
    )
    views = sorted(
        overview["views"],
        key=lambda vw: str(vw.get("facets", {}).get("as_of", "") or ""),
        reverse=True,
    )

    return {
        "entity": _entity_header(entity, entity_type),
        "entity_type": entity_type,
        "is_company": entity_type == "company" or bool(company_facets),
        "is_person": entity_type == "person" or bool(person_facets),
        "company_facets": company_facets,
        "person_facets": person_facets,
        "extra_facets": extra_facets,
        "consensus": consensus,
        "prior_consensuses": [_prior_consensus_row(c) for c in overview["prior_consensuses"]],
        "events": [_event_row(ev, data_dir) for ev in events],
        "views": [_view_row(vw, data_dir) for vw in views],
        "themes": [_theme_link_row(thm) for thm in overview["themes"]],
        "related_entities": [_related_entity_row(rel) for rel in overview["related_entities"]],
        "page_context": translate(
            "page_context.entity",
            lang=lang,
            name=entity["name"],
            entity_type=translate_enum("entity_type", entity_type, lang=lang),
        ),
    }


def build_theme_context(
    db: OntologyDB,
    theme_id: str,
    *,
    data_dir: Path | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare context for an investment theme catalog page."""
    theme_data = db.find_theme_companies(theme_id, include_second_order=True)
    theme = theme_data["theme"]
    facets = theme.get("facets", {})
    extra_keys = [k for k in sorted(facets.keys()) if k != "stage"]

    events_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    views_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    for item in db.get_incident_edges(theme_id):
        nb = item["neighbor"]
        nid = str(nb["id"])
        rel = str(item["relation"]).strip().upper()
        edge_facets = item.get("facets") or {}
        eff_sent, sent_src = resolve_item_sentiment(nb.get("facets", {}), edge_facets)
        rank = (
            1 if edge_facets.get("sentiment") else 0,
            1 if rel in ("SUPPORTS", "CONTRADICTS", "ABOUT") else 0,
        )
        entry = {
            **nb,
            "relation": item["relation"],
            "direction": item["direction"],
            "edge_facets": edge_facets,
            "effective_sentiment": eff_sent,
            "sentiment_source": sent_src,
        }
        if nb["node_type"] == "event":
            if nid not in events_by_id or rank > events_by_id[nid][0]:
                events_by_id[nid] = (rank, entry)
        elif nb["node_type"] == "view":
            if nid not in views_by_id or rank > views_by_id[nid][0]:
                views_by_id[nid] = (rank, entry)

    events = [_event_row(pair[1], data_dir) for pair in events_by_id.values()]
    views = [_view_row(pair[1], data_dir) for pair in views_by_id.values()]

    return {
        "theme": _theme_header(theme),
        "stage": facets.get("stage", ""),
        "extra_facets": _format_facet_pairs(facets, extra_keys, lang=lang),
        "first_order": [_first_order_row(row, data_dir) for row in theme_data["first_order"]],
        "second_order": [_second_order_row(row) for row in theme_data["second_order"]],
        "events": events,
        "views": views,
        "page_context": translate(
            "page_context.theme",
            lang=lang,
            name=theme["name"],
        ),
    }


def _node_subtype(node: Node) -> str:
    facets = node.facets or {}
    if node.node_type == "entity":
        return str(facets.get("entity_type") or "").strip().lower()
    if node.node_type == "event":
        return str(facets.get("event_type") or "").strip().lower()
    if node.node_type == "view":
        return str(facets.get("view_type") or "").strip().lower()
    if node.node_type == "theme":
        return str(facets.get("stage") or "").strip().lower()
    return ""


def _node_date(node: Node) -> str:
    facets = node.facets or {}
    raw = facets.get("event_date") or facets.get("as_of")
    if not raw and isinstance(facets.get("source"), dict):
        raw = facets["source"].get("date")
    return str(raw or "").strip()


def _node_source_file(node: Node) -> str:
    src = (node.facets or {}).get("source")
    if isinstance(src, dict):
        return str(src.get("file_path") or "").strip()
    return ""


def _merge_ordered(defaults: list[str], extra: set[str]) -> list[str]:
    merged = list(defaults)
    seen = set(defaults)
    for item in sorted(extra):
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def build_search_filter_options(db: OntologyDB) -> dict[str, Any]:
    """Collect dropdown filter options for the integrated Advanced Search bar."""
    companies: list[dict[str, str]] = []
    people: list[dict[str, str]] = []
    other_entities: list[dict[str, str]] = []
    observed_subtypes: dict[str, set[str]] = {
        "entity": set(),
        "event": set(),
        "view": set(),
        "theme": set(),
    }
    observed_stances: set[str] = set()

    for node in db.list_nodes(limit=5000):
        sub = _node_subtype(node)
        if sub and node.node_type in observed_subtypes:
            observed_subtypes[node.node_type].add(sub)
        stance = str(node.facets.get("stance") or "").strip().lower()
        if stance:
            observed_stances.add(stance)

        if node.node_type == "entity":
            etype = sub or "entity"
            if etype == "company":
                companies.append(
                    {
                        "id": node.id,
                        "name": node.name,
                        "ticker": str(node.facets.get("ticker", "")),
                    }
                )
            elif etype == "person":
                people.append(
                    {
                        "id": node.id,
                        "name": node.name,
                        "role": str(node.facets.get("role", "")),
                    }
                )
            else:
                other_entities.append(
                    {
                        "id": node.id,
                        "name": node.name,
                        "entity_type": etype,
                    }
                )

    companies.sort(key=lambda c: c["name"].casefold())
    people.sort(key=lambda p: p["name"].casefold())
    other_entities.sort(key=lambda e: e["name"].casefold())

    subtypes = {
        nt: _merge_ordered(DEFAULT_SUBTYPES_BY_TYPE[nt], observed_subtypes[nt])
        for nt in ("entity", "event", "view", "theme")
    }
    stances = _merge_ordered(CANONICAL_STANCES, observed_stances)

    return {
        "companies": companies,
        "people": people,
        "other_entities": other_entities,
        "subtypes": subtypes,
        "sentiments": [*VALID_SENTIMENTS, "unclassified"],
        "stances": stances,
    }


def _resolve_result_href(db: OntologyDB, node: Node) -> str:
    if node.node_type == "entity":
        return f"/entity/{node.id}"
    if node.node_type == "theme":
        return f"/theme/{node.id}"
    for edge in db.get_incident_edges(node.id):
        nb = edge["neighbor"]
        if nb["node_type"] == "entity":
            return f"/entity/{nb['id']}#node-{node.id}"
    for edge in db.get_incident_edges(node.id):
        nb = edge["neighbor"]
        if nb["node_type"] == "theme":
            return f"/theme/{nb['id']}#node-{node.id}"
    return "/"


def _format_search_result(
    db: OntologyDB,
    node: Node,
    *,
    score_type: str,
    distance: float | None,
    edge_facets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eff_sent, sent_src = resolve_item_sentiment(node.facets, edge_facets)
    return {
        **node_to_dict(node),
        "subtype": _node_subtype(node),
        "effective_sentiment": eff_sent,
        "sentiment_source": sent_src,
        "stance": str(node.facets.get("stance") or "").strip().lower() or None,
        "date": _node_date(node) or None,
        "source_file": _node_source_file(node) or None,
        "score_type": score_type,
        "distance": round(distance, 4) if distance is not None else None,
        "href": _resolve_result_href(db, node),
    }


def run_hybrid_search(
    db: OntologyDB,
    llm: LLMClient | None,
    query: str,
    node_type: str | None = None,
    limit: int = 20,
    *,
    subtype: str | None = None,
    sentiment: str | None = None,
    stance: str | None = None,
    entity_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_file: str | None = None,
    search_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    """Run vector + keyword search and structured facet filtering across the ontology."""
    cleaned = query.strip()
    valid_types = ("entity", "event", "view", "theme")
    nt: NodeType | None = node_type if node_type in valid_types else None  # type: ignore[assignment]

    norm_subtype: str | None = None
    if subtype and subtype.strip():
        sub_low = subtype.strip().lower().replace(" ", "_")
        norm_subtype = SIGNAL_CATEGORY_ALIASES.get(sub_low, sub_low)

    norm_sentiment: str | None = None
    if sentiment and sentiment.strip():
        s_low = sentiment.strip().lower()
        norm_sentiment = "unclassified" if s_low in ("unknown", "unclassified", "none") else s_low

    norm_stance = stance.strip().lower() if stance and stance.strip() else None
    norm_entity_id = entity_id.strip() if entity_id and entity_id.strip() else None
    norm_date_from = date_from.strip() if date_from and date_from.strip() else None
    norm_date_to = date_to.strip() if date_to and date_to.strip() else None
    norm_source_file = source_file.strip().casefold() if source_file and source_file.strip() else None
    mode = "keyword" if search_mode.strip().lower() == "keyword" else "hybrid"

    has_filters = any(
        [
            nt,
            norm_subtype,
            norm_sentiment,
            norm_stance,
            norm_entity_id,
            norm_date_from,
            norm_date_to,
            norm_source_file,
        ]
    )
    if not cleaned and not has_filters:
        return []

    connected_map: dict[str, dict[str, Any] | None] = {}
    if norm_entity_id is not None:
        if db.get_node(norm_entity_id) is None:
            return []
        connected_map = db.get_entity_connected_nodes(norm_entity_id)

    def _matches_filters(node: Node) -> bool:
        if nt is not None and node.node_type != nt:
            return False
        if norm_entity_id is not None and node.id not in connected_map:
            return False
        if norm_subtype is not None:
            node_sub = _node_subtype(node)
            if norm_subtype == "rumor":
                status_val = str(node.facets.get("status") or "").strip().lower()
                if not (
                    (node.node_type == "view" and node_sub == "rumor")
                    or (
                        node.node_type == "event"
                        and (status_val == "rumored" or node_sub == "rumor")
                    )
                ):
                    return False
            elif node_sub != norm_subtype:
                return False
        if norm_sentiment is not None:
            edge_facets = connected_map.get(node.id) if norm_entity_id else None
            eff_sent, _ = resolve_item_sentiment(node.facets, edge_facets)
            actual = eff_sent or "unclassified"
            if actual != norm_sentiment:
                return False
        if norm_stance is not None:
            node_stance = str(node.facets.get("stance") or "").strip().lower()
            if node_stance != norm_stance:
                return False
        if norm_date_from is not None or norm_date_to is not None:
            node_date = _node_date(node)
            if not node_date:
                return False
            if norm_date_from is not None and node_date < norm_date_from:
                return False
            if norm_date_to is not None and node_date > norm_date_to:
                return False
        if norm_source_file is not None:
            if norm_source_file not in _node_source_file(node).casefold():
                return False
        return True

    if not cleaned:
        matched_nodes = [
            node for node in db.list_nodes(node_type=nt, limit=5000) if _matches_filters(node)
        ]
        matched_nodes.sort(key=lambda n: n.name.casefold())
        matched_nodes.sort(
            key=lambda n: (_node_date(n) or "", n.updated_at.isoformat()),
            reverse=True,
        )
        return [
            _format_search_result(
                db,
                node,
                score_type="filter",
                distance=None,
                edge_facets=connected_map.get(node.id) if norm_entity_id else None,
            )
            for node in matched_nodes[:limit]
        ]

    seen: dict[str, dict[str, Any]] = {}
    vec_limit = max(limit * 5, 100) if has_filters else limit
    kw_limit = max(limit * 10, 500) if has_filters else limit

    if mode != "keyword" and llm is not None:
        try:
            vec = llm.embed_texts([cleaned])[0]
            for node, dist in db.vector_search(vec, node_type=nt, limit=vec_limit):
                if not _matches_filters(node):
                    continue
                seen[node.id] = _format_search_result(
                    db,
                    node,
                    score_type="semantic",
                    distance=dist,
                    edge_facets=connected_map.get(node.id) if norm_entity_id else None,
                )
        except Exception:  # noqa: BLE001
            # Offline or missing API key gracefully degrades to keyword search.
            pass

    for node in db.keyword_search(cleaned, node_type=nt, limit=kw_limit):
        if node.id in seen:
            continue
        if not _matches_filters(node):
            continue
        seen[node.id] = _format_search_result(
            db,
            node,
            score_type="keyword",
            distance=None,
            edge_facets=connected_map.get(node.id) if norm_entity_id else None,
        )

    return list(seen.values())[:limit]


def _format_diagram_top_label(
    relations: list[dict[str, Any]],
    fallback_rels: tuple[str, ...],
    lang: str,
    max_len: int = 26,
) -> str:
    names = [r["relation"] for r in relations] if relations else list(fallback_rels)
    translated = [translate_enum("relation", name, lang=lang) for name in names[:2]]
    joined = " / ".join(translated)
    if len(joined) > max_len and translated:
        joined = translated[0]
    if len(joined) > max_len:
        joined = joined[: max_len - 1] + "…"
    return joined


def _build_diagram_links(
    diagram_pairs: dict[str, dict[str, Any]], lang: str
) -> dict[str, dict[str, Any]]:
    def _combine(keys: list[str], fallback: tuple[str, ...], *, max_len: int = 26) -> dict[str, Any]:
        total = 0
        counts: Counter[str] = Counter()
        for key in keys:
            info = diagram_pairs.get(key, {})
            total += int(info.get("count", 0))
            for r in info.get("relations", []):
                counts[r["relation"]] += int(r["count"])
        rels = [{"relation": rel, "count": cnt} for rel, cnt in counts.most_common()]
        return {
            "count": total,
            "top_label": _format_diagram_top_label(rels, fallback, lang, max_len=max_len),
        }

    entity_theme = _combine(
        ["entity->theme", "theme->entity"], ("EXPOSED_TO",), max_len=28
    )
    entity_theme["reversed_count"] = int(diagram_pairs.get("theme->entity", {}).get("count", 0))

    view_theme = _combine(
        ["view->theme", "theme->view"], ("SUPPORTS", "RELATES_TO"), max_len=24
    )
    view_theme["reversed_count"] = int(diagram_pairs.get("theme->view", {}).get("count", 0))

    return {
        "entity_entity": _combine(["entity->entity"], ("BUY", "WORKS_AT"), max_len=26),
        "view_view": _combine(["view->view"], ("SUPPORTS", "SUPERSEDES"), max_len=26),
        "entity_theme": entity_theme,
        "event_entity": _combine(["event->entity"], ("ABOUT", "AUTHORED_BY"), max_len=24),
        "view_theme": view_theme,
        "event_view": _combine(["event->view"], ("SUPPORTS", "CONTRADICTS"), max_len=28),
        "view_entity": _combine(["view->entity"], ("ABOUT", "AUTHORED_BY"), max_len=20),
        "event_theme": _combine(["event->theme"], ("SUPPORTS", "RELATES_TO"), max_len=20),
    }


def _build_registry_view(
    registry: OntologyRegistry,
    audit_report: AuditReport,
    all_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    rel_counts: dict[str, dict[str, int]] = {
        spec.name: {"exact": 0, "alias": 0, "inverse": 0, "issue": 0}
        for spec in registry.relations
    }
    for edge in all_edges:
        cls = classify_edge_against_registry(
            registry,
            edge["relation"],
            from_type=edge["from_type"],
            from_entity_type=edge["from_entity_type"],
            to_type=edge["to_type"],
            to_entity_type=edge["to_entity_type"],
        )
        if cls.canonical_relation is None or cls.canonical_relation not in rel_counts:
            continue
        bucket = rel_counts[cls.canonical_relation]
        if cls.issue_type is not None:
            bucket["issue"] += 1
        elif cls.match_kind in bucket:
            bucket[cls.match_kind] += 1

    relations_rows: list[dict[str, Any]] = []
    for spec in registry.relations:
        cnt = rel_counts[spec.name]
        total = cnt["exact"] + cnt["alias"] + cnt["inverse"] + cnt["issue"]
        relations_rows.append(
            {
                "name": spec.name,
                "description": spec.description,
                "from_types": list(spec.from_types),
                "to_types": list(spec.to_types),
                "aliases": list(spec.aliases),
                "inverse_aliases": list(spec.inverse_aliases),
                "traversal_group": spec.traversal_group,
                "exact_count": cnt["exact"],
                "alias_count": cnt["alias"],
                "inverse_count": cnt["inverse"],
                "issue_count": cnt["issue"],
                "total_count": total,
            }
        )

    co_matches_by_official: dict[str, list[dict[str, Any]]] = {}
    for m in audit_report.mapped_companies:
        co_matches_by_official.setdefault(m.official_name, []).append(
            {
                "id": m.node_id,
                "name": m.db_name,
                "href": f"/entity/{m.node_id}",
                "match_kind": m.match_kind,
                "raw_ticker": m.raw_ticker,
            }
        )

    companies_rows = [
        {
            "name": spec.name,
            "ticker": spec.ticker,
            "sector": spec.sector,
            "aliases": list(spec.aliases),
            "db_matches": co_matches_by_official.get(spec.name, []),
        }
        for spec in registry.companies
    ]

    thm_matches_by_official: dict[str, list[dict[str, Any]]] = {}
    for m in audit_report.mapped_themes:
        thm_matches_by_official.setdefault(m.official_name, []).append(
            {
                "id": m.node_id,
                "name": m.db_name,
                "href": f"/theme/{m.node_id}",
                "match_kind": m.match_kind,
            }
        )

    themes_rows = [
        {
            "name": spec.name,
            "stage": spec.stage,
            "description": spec.description,
            "aliases": list(spec.aliases),
            "db_matches": thm_matches_by_official.get(spec.name, []),
        }
        for spec in registry.themes
    ]

    facet_hit_map = {
        (fh.node_type, fh.raw_key): fh.count for fh in audit_report.facet_alias_hits
    }
    facet_rows: list[dict[str, Any]] = []
    for ntype in sorted(registry.facet_aliases.keys()):
        for raw_key, canon_key in sorted(registry.facet_aliases[ntype].items()):
            facet_rows.append(
                {
                    "node_type": ntype,
                    "raw_key": raw_key,
                    "canonical_key": canon_key,
                    "hit_count": facet_hit_map.get((ntype, raw_key), 0),
                }
            )

    return {
        "relations": relations_rows,
        "companies": companies_rows,
        "themes": themes_rows,
        "facet_aliases": facet_rows,
    }


def _build_audit_view(
    audit_report: AuditReport,
    rel_sug_by_key: dict[str, Any],
    co_sug_by_key: dict[str, Any],
    thm_sug_by_key: dict[str, Any],
) -> dict[str, Any]:
    unmapped_relations = []
    for r in audit_report.unmapped_relations:
        sug = rel_sug_by_key.get(normalize_relation_name(r.name))
        unmapped_relations.append(
            {
                **r.model_dump(),
                "suggestion_status": sug.status if sug is not None else "unsynced",
                "mapped_to": sug.mapped_to if sug is not None else None,
            }
        )

    unmapped_companies = []
    for c in audit_report.unmapped_companies:
        sug = co_sug_by_key.get(normalize_name_key(c.name))
        unmapped_companies.append(
            {
                **c.model_dump(),
                "href": f"/entity/{c.node_id}",
                "suggestion_status": sug.status if sug is not None else "unsynced",
                "mapped_to": sug.mapped_to if sug is not None else None,
            }
        )

    unmapped_themes = []
    for t in audit_report.unmapped_themes:
        sug = thm_sug_by_key.get(normalize_name_key(t.name))
        unmapped_themes.append(
            {
                **t.model_dump(),
                "href": f"/theme/{t.node_id}",
                "suggestion_status": sug.status if sug is not None else "unsynced",
                "mapped_to": sug.mapped_to if sug is not None else None,
            }
        )

    return {
        "summary": audit_report.summary.model_dump(),
        "unmapped_relations": unmapped_relations,
        "unmapped_companies": unmapped_companies,
        "unmapped_themes": unmapped_themes,
        "normalization_hits": [
            h.model_dump() for h in audit_report.relation_normalization_hits
        ],
        "direction_issues": [d.model_dump() for d in audit_report.direction_issues],
        "near_duplicate_themes": [
            {
                **p.model_dump(),
                "href_a": f"/theme/{p.node_a_id}",
                "href_b": f"/theme/{p.node_b_id}",
            }
            for p in audit_report.near_duplicate_themes
        ],
        "suspicious_aliases": [
            {**sa.model_dump(), "href": f"/entity/{sa.node_id}"}
            for sa in audit_report.suspicious_aliases
        ],
        "duplicate_companies": [
            {
                **p.model_dump(),
                "href_a": f"/entity/{p.node_a_id}",
                "href_b": f"/entity/{p.node_b_id}",
            }
            for p in audit_report.duplicate_company_candidates
        ],
        "ticker_issues": [
            {**ti.model_dump(), "href": f"/entity/{ti.node_id}"}
            for ti in audit_report.ticker_normalization_issues
        ],
        "facet_hits": [fh.model_dump() for fh in audit_report.facet_alias_hits],
    }


def build_ontology_context(
    db: OntologyDB,
    *,
    tab: str = "entity",
    subtype: str = "",
    reg_status: str = "",
    data_dir: Path | None = None,
    registry: OntologyRegistry | None = None,
    registry_path: Path | None = None,
    registry_error: str | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare the 4-structure Ontology View architectural explorer context."""
    active_tab = tab.strip().lower()
    if active_tab not in ("entity", "event", "view", "theme", "edges", "registry", "audit"):
        active_tab = "entity"
    active_subtype = subtype.strip().lower()
    raw_reg_status = reg_status.strip().lower()
    active_reg_status = raw_reg_status if raw_reg_status in ("official", "unmapped") else ""

    stats = db.get_stats()
    known_facets = db.get_known_facet_keys()
    edge_schema = db.get_edge_schema_summary()
    edge_counts = db.get_node_edge_counts()

    nodes_by_type: dict[str, list[Node]] = {}
    node_by_id: dict[str, Node] = {}
    for nt in ("entity", "event", "view", "theme"):
        fetched = db.list_nodes(node_type=nt, limit=1000)  # type: ignore[arg-type]
        nodes_by_type[nt] = fetched
        for n in fetched:
            node_by_id[n.id] = n

    # Aggregate pairwise inter-structure relationships for the 4-node architecture diagram
    pair_acc: dict[tuple[str, str], dict[str, Any]] = {}
    for ft in ("entity", "event", "view", "theme"):
        for tt in ("entity", "event", "view", "theme"):
            pair_acc[(ft, tt)] = {"count": 0, "relations": []}

    relations_by_type: dict[str, list[dict[str, Any]]] = {
        "entity": [],
        "event": [],
        "view": [],
        "theme": [],
    }
    for row in edge_schema:
        ft = row["from_type"]
        tt = row["to_type"]
        rel = row["relation"]
        cnt = row["count"]
        if (ft, tt) in pair_acc:
            pair_acc[(ft, tt)]["count"] += cnt
            pair_acc[(ft, tt)]["relations"].append({"relation": rel, "count": cnt})
        if ft in relations_by_type:
            relations_by_type[ft].append(
                {"relation": rel, "direction": "out", "other_type": tt, "count": cnt}
            )
        if tt in relations_by_type and tt != ft:
            relations_by_type[tt].append(
                {"relation": rel, "direction": "in", "other_type": ft, "count": cnt}
            )

    diagram_pairs: dict[str, dict[str, Any]] = {}
    for (ft, tt), info in pair_acc.items():
        rels = sorted(info["relations"], key=lambda r: (-r["count"], r["relation"]))
        top_names = [r["relation"] for r in rels[:2]]
        diagram_pairs[f"{ft}->{tt}"] = {
            "from_type": ft,
            "to_type": tt,
            "count": info["count"],
            "relations": rels,
            "top_label": " / ".join(top_names),
        }
    diagram_links = _build_diagram_links(diagram_pairs, lang)

    audit_report: AuditReport | None = None
    company_match_by_id: dict[str, Any] = {}
    theme_match_by_id: dict[str, Any] = {}
    unmapped_company_by_id: dict[str, Any] = {}
    unmapped_theme_by_id: dict[str, Any] = {}
    rel_sug_by_key: dict[str, Any] = {}
    co_sug_by_key: dict[str, Any] = {}
    thm_sug_by_key: dict[str, Any] = {}

    if registry is not None:
        audit_report = run_ontology_audit(db, registry)
        company_match_by_id = {m.node_id: m for m in audit_report.mapped_companies}
        theme_match_by_id = {m.node_id: m for m in audit_report.mapped_themes}
        unmapped_company_by_id = {u.node_id: u for u in audit_report.unmapped_companies}
        unmapped_theme_by_id = {u.node_id: u for u in audit_report.unmapped_themes}
        rel_sug_by_key = {
            normalize_relation_name(s.name): s for s in registry.suggestions.relations
        }
        co_sug_by_key = {
            normalize_name_key(s.name): s for s in registry.suggestions.companies
        }
        thm_sug_by_key = {
            normalize_name_key(s.name): s for s in registry.suggestions.themes
        }
        pending_rel = sum(1 for s in registry.suggestions.relations if s.status == "pending")
        pending_co = sum(1 for s in registry.suggestions.companies if s.status == "pending")
        pending_thm = sum(1 for s in registry.suggestions.themes if s.status == "pending")
        pending_total = pending_rel + pending_co + pending_thm
        registry_summary: dict[str, Any] = {
            "loaded": True,
            "path": str(registry_path or "ontology_registry.json"),
            "version": registry.version,
            "official_relations": len(registry.relations),
            "official_companies": len(registry.companies),
            "official_themes": len(registry.themes),
            "pending_relations": pending_rel,
            "pending_companies": pending_co,
            "pending_themes": pending_thm,
            "pending_total": pending_total,
            "audit": audit_report.summary.model_dump(),
            "error": None,
        }
    else:
        registry_summary = {
            "loaded": False,
            "path": str(registry_path or "ontology_registry.json"),
            "error": registry_error,
            "pending_total": 0,
        }

    structures: list[dict[str, Any]] = []
    subtypes_by_structure: dict[str, list[dict[str, Any]]] = {}
    for defn in STRUCTURE_DEFINITIONS:
        key = defn["key"]
        type_nodes = nodes_by_type[key]
        sub_counter: dict[str, int] = {}
        for n in type_nodes:
            sub = _node_subtype(n) or "unspecified"
            sub_counter[sub] = sub_counter.get(sub, 0) + 1
        sub_list = [
            {"name": name, "count": cnt}
            for name, cnt in sorted(sub_counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        subtypes_by_structure[key] = sub_list

        top_rels = sorted(
            relations_by_type[key],
            key=lambda r: (-r["count"], r["relation"]),
        )[:5]

        raw_facet_keys = known_facets.get(key, [])
        facet_key_items = []
        for fk in raw_facet_keys:
            canon_fk = registry.resolve_facet_key(key, fk) if registry is not None else fk
            facet_key_items.append(
                {
                    "key": fk,
                    "canonical_target": canon_fk if canon_fk != fk else None,
                }
            )

        registry_coverage: dict[str, Any] | None = None
        if audit_report is not None and registry is not None:
            asum = audit_report.summary
            if key == "entity":
                registry_coverage = {
                    "kind": "companies",
                    "official_defined": len(registry.companies),
                    "mapped": asum.mapped_companies,
                    "total": asum.total_companies,
                    "unmapped": asum.unmapped_companies,
                }
            elif key == "theme":
                registry_coverage = {
                    "kind": "themes",
                    "official_defined": len(registry.themes),
                    "mapped": asum.mapped_themes,
                    "total": asum.total_themes,
                    "unmapped": asum.unmapped_themes,
                }
            elif key == "event":
                registry_coverage = {
                    "kind": "sentiment",
                    "missing": asum.events_missing_sentiment,
                    "total": asum.total_events,
                    "facet_drift": sum(
                        h.count for h in audit_report.facet_alias_hits if h.node_type == "event"
                    ),
                }
            elif key == "view":
                registry_coverage = {
                    "kind": "sentiment",
                    "missing": asum.views_missing_sentiment,
                    "total": asum.total_views,
                    "facet_drift": sum(
                        h.count for h in audit_report.facet_alias_hits if h.node_type == "view"
                    ),
                }

        structures.append(
            {
                **defn,
                "title": translate(f"ontology.struct_{key}_title", lang=lang),
                "plural": translate(f"ontology.struct_{key}_plural", lang=lang),
                "subtitle": translate(f"ontology.struct_{key}_subtitle", lang=lang),
                "lifecycle": translate(f"ontology.struct_{key}_lifecycle", lang=lang),
                "description": translate(f"ontology.struct_{key}_description", lang=lang),
                "count": stats["nodes"].get(key, len(type_nodes)),
                "subtype_counts": sub_list,
                "facet_keys": raw_facet_keys,
                "facet_key_items": facet_key_items,
                "registry_coverage": registry_coverage,
                "top_relations": top_rels,
            }
        )

    tab_records: list[dict[str, Any]] = []
    active_subtypes: list[dict[str, Any]] = []
    edge_samples: list[dict[str, Any]] = []
    edge_schema_detailed: list[dict[str, Any]] = []
    registry_view: dict[str, Any] | None = None
    audit_view: dict[str, Any] | None = None

    all_edges_with_endpoints: list[dict[str, Any]] = []
    if active_tab in ("edges", "registry"):
        all_edges_with_endpoints = db.list_edges_with_endpoints()

    if active_tab == "registry":
        if registry is not None and audit_report is not None:
            registry_view = _build_registry_view(
                registry, audit_report, all_edges_with_endpoints
            )
    elif active_tab == "audit":
        if audit_report is not None:
            audit_view = _build_audit_view(
                audit_report, rel_sug_by_key, co_sug_by_key, thm_sug_by_key
            )
    elif active_tab == "edges":
        sig_groups: dict[tuple[str, str | None, str, str, str | None], int] = {}
        for e in all_edges_with_endpoints:
            gkey = (
                e["from_type"],
                e["from_entity_type"],
                e["relation"],
                e["to_type"],
                e["to_entity_type"],
            )
            sig_groups[gkey] = sig_groups.get(gkey, 0) + 1

        for (ft, fet, rel, tt, tet), cnt in sorted(
            sig_groups.items(), key=lambda kv: (-kv[1], kv[0][2], kv[0][0], kv[0][3])
        ):
            cls_dict: dict[str, Any] | None = None
            sug_status: str | None = None
            if registry is not None:
                cls = classify_edge_against_registry(
                    registry,
                    rel,
                    from_type=ft,
                    from_entity_type=fet,
                    to_type=tt,
                    to_entity_type=tet,
                )
                cls_dict = cls.model_dump()
                if cls.status == "unmapped":
                    sug = rel_sug_by_key.get(normalize_relation_name(rel))
                    sug_status = sug.status if sug is not None else "unsynced"
            if active_reg_status == "official" and cls_dict is not None and cls_dict["status"] == "unmapped":
                continue
            if active_reg_status == "unmapped" and (cls_dict is None or cls_dict["status"] != "unmapped"):
                continue
            edge_schema_detailed.append(
                {
                    "from_type": ft,
                    "from_entity_type": fet,
                    "from_label": node_type_label(ft, fet),
                    "relation": rel,
                    "to_type": tt,
                    "to_entity_type": tet,
                    "to_label": node_type_label(tt, tet),
                    "count": cnt,
                    "classification": cls_dict,
                    "suggestion_status": sug_status,
                }
            )

        for e in all_edges_with_endpoints:
            cls_dict = None
            if registry is not None:
                cls_dict = classify_edge_against_registry(
                    registry,
                    e["relation"],
                    from_type=e["from_type"],
                    from_entity_type=e["from_entity_type"],
                    to_type=e["to_type"],
                    to_entity_type=e["to_entity_type"],
                ).model_dump()
            if active_reg_status == "official" and cls_dict is not None and cls_dict["status"] == "unmapped":
                continue
            if active_reg_status == "unmapped" and (cls_dict is None or cls_dict["status"] != "unmapped"):
                continue

            from_node = node_by_id.get(e["from_id"])
            to_node = node_by_id.get(e["to_id"])
            from_href = _resolve_result_href(db, from_node) if from_node else "/"
            to_href = _resolve_result_href(db, to_node) if to_node else "/"
            edge_samples.append(
                {
                    **e,
                    "from_label": node_type_label(e["from_type"], e["from_entity_type"]),
                    "to_label": node_type_label(e["to_type"], e["to_entity_type"]),
                    "from_href": from_href,
                    "to_href": to_href,
                    "classification": cls_dict,
                    "facet_summary": ", ".join(
                        f"{k}={format_facet_value(v, lang=lang)}"
                        for k, v in sorted(e["facets"].items())
                    ),
                }
            )
            if len(edge_samples) >= 80:
                break
    else:
        active_subtypes = subtypes_by_structure.get(active_tab, [])
        candidates = nodes_by_type[active_tab]
        if active_subtype:
            candidates = [
                n for n in candidates
                if (_node_subtype(n) or "unspecified") == active_subtype
            ]

        if active_tab in ("entity", "theme"):
            candidates = sorted(
                candidates,
                key=lambda n: (-edge_counts.get(n.id, 0), n.name.casefold()),
            )
        else:
            candidates = sorted(
                candidates,
                key=lambda n: (_node_date(n) or "", n.updated_at.isoformat()),
                reverse=True,
            )

        skip_preview = {
            "source",
            "pillars",
            "entity_type",
            "event_type",
            "view_type",
            "stage",
            "sentiment",
            "stance",
            "event_date",
            "as_of",
        }
        for n in candidates:
            subtype_val = _node_subtype(n) or "unspecified"
            registry_info: dict[str, Any] | None = None
            if registry is not None:
                if n.node_type == "entity" and subtype_val == "company":
                    cmatch = company_match_by_id.get(n.id)
                    if cmatch is not None:
                        registry_info = {
                            "status": "official",
                            "official_name": cmatch.official_name,
                            "match_kind": cmatch.match_kind,
                            "renamed": cmatch.db_name.casefold()
                            != cmatch.official_name.casefold(),
                        }
                    else:
                        sug = co_sug_by_key.get(normalize_name_key(n.name))
                        um = unmapped_company_by_id.get(n.id)
                        registry_info = {
                            "status": "unmapped",
                            "suggestion_status": sug.status if sug is not None else "unsynced",
                            "nearest_official": (
                                um.nearest_official.model_dump()
                                if um is not None and um.nearest_official is not None
                                else None
                            ),
                        }
                elif n.node_type == "theme":
                    tmatch = theme_match_by_id.get(n.id)
                    if tmatch is not None:
                        registry_info = {
                            "status": "official",
                            "official_name": tmatch.official_name,
                            "match_kind": tmatch.match_kind,
                            "renamed": tmatch.db_name.casefold()
                            != tmatch.official_name.casefold(),
                        }
                    else:
                        sug = thm_sug_by_key.get(normalize_name_key(n.name))
                        um = unmapped_theme_by_id.get(n.id)
                        registry_info = {
                            "status": "unmapped",
                            "suggestion_status": sug.status if sug is not None else "unsynced",
                            "nearest_official": (
                                um.nearest_official.model_dump()
                                if um is not None and um.nearest_official is not None
                                else None
                            ),
                        }

            if (
                active_reg_status in ("official", "unmapped")
                and active_tab in ("entity", "theme")
                and registry is not None
            ):
                if registry_info is None or registry_info["status"] != active_reg_status:
                    continue

            eff_sent, _ = resolve_item_sentiment(n.facets)
            source_file = _node_source_file(n)
            source_exists = (
                resolve_safe_note_path(data_dir, source_file) is not None
                if data_dir is not None and source_file
                else False
            )
            preview_pairs = []
            for k in sorted(n.facets.keys()):
                if k in skip_preview or n.facets[k] in (None, "", [], {}):
                    continue
                val_str = format_facet_value(n.facets[k], lang=lang)
                if len(val_str) > 48:
                    val_str = val_str[:45] + "..."
                preview_pairs.append({"key": k, "value": val_str})
                if len(preview_pairs) >= 4:
                    break

            tab_records.append(
                {
                    "id": n.id,
                    "node_type": n.node_type,
                    "name": n.name,
                    "summary": n.summary,
                    "subtype": subtype_val,
                    "effective_sentiment": eff_sent,
                    "stance": str(n.facets.get("stance") or "").strip().lower() or None,
                    "status": str(n.facets.get("status") or "").strip().lower() or None,
                    "date": _node_date(n) or None,
                    "edge_count": edge_counts.get(n.id, 0),
                    "href": _resolve_result_href(db, n),
                    "source_file": source_file or None,
                    "source_exists": source_exists,
                    "facet_preview": preview_pairs,
                    "registry_info": registry_info,
                }
            )

    return {
        "stats": stats,
        "structures": structures,
        "diagram_pairs": diagram_pairs,
        "diagram_links": diagram_links,
        "edge_schema": edge_schema,
        "edge_schema_detailed": edge_schema_detailed,
        "registry_summary": registry_summary,
        "registry_view": registry_view,
        "audit_view": audit_view,
        "active_tab": active_tab,
        "active_subtype": active_subtype,
        "active_reg_status": active_reg_status,
        "active_subtypes": active_subtypes,
        "tab_records": tab_records,
        "edge_samples": edge_samples,
        "page_context": translate("page_context.ontology", lang=lang, tab=active_tab),
    }
