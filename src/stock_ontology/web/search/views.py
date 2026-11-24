"""Search view models: filter options and the shaped results page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stock_ontology.i18n import translate, translate_enum, translate_subtype
from stock_ontology.llm import LLMClient
from stock_ontology.models import resolve_item_sentiment
from stock_ontology.registry import (
    OntologyRegistry,
)
from stock_ontology.search import (
    NODE_TYPES,
    SearchFilters,
    SearchHit,
    node_date,
    node_source_file,
    node_subtype,
    search_ontology,
    split_qualified_value,
)
from stock_ontology.services import GraphStore, node_to_dict
from stock_ontology.vocab import (
    CONVICTION,
    NODE_FACET_VOCABS,
    SENTIMENT_FILTER_VALUES,
    STANCE,
    SUBTYPE_FACET,
    SUPPORT_STRENGTH,
)
from stock_ontology.web.shared import (
    format_source_citation,
    resolve_result_href,
)


def build_search_filter_options(db: GraphStore, registry: OntologyRegistry | None = None) -> dict[str, Any]:
    """Collect dropdown filter options for the integrated Advanced Search bar.

    Every enum option comes from `vocab.py` and relations from `registry`, never from
    values observed in the DB. With no registry, `relations` is empty and the relation
    filter is hidden. Only the entity options are DB instances.
    """
    companies: list[dict[str, str]] = []
    people: list[dict[str, str]] = []
    other_entities: list[dict[str, str]] = []

    for node in db.list_nodes(node_type="entity", limit=5000):
        etype = node_subtype(node) or "entity"
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

    return {
        "companies": companies,
        "people": people,
        "other_entities": other_entities,
        "node_types": list(NODE_TYPES),
        "subtypes": {nt: list(NODE_FACET_VOCABS[nt][facet].members) for nt, facet in SUBTYPE_FACET.items()},
        "statuses": {
            nt: list(NODE_FACET_VOCABS[nt]["status"].members) for nt in NODE_TYPES if "status" in NODE_FACET_VOCABS[nt]
        },
        "sentiments": list(SENTIMENT_FILTER_VALUES),
        "stances": list(STANCE.members),
        "support_strengths": list(SUPPORT_STRENGTH.members),
        "convictions": list(CONVICTION.members),
        "relations": [spec.name for spec in registry.relations] if registry is not None else [],
    }


def _format_search_hit(db: GraphStore, hit: SearchHit, data_dir: Path) -> dict[str, Any]:
    node = hit.node
    eff_sent, sent_src = resolve_item_sentiment(node.facets, hit.edge_facets)
    source_file = node_source_file(node) or None
    source_label, source_exists = format_source_citation(source_file, data_dir)
    return {
        **node_to_dict(node),
        "subtype": node_subtype(node),
        "effective_sentiment": eff_sent,
        "sentiment_source": sent_src,
        "stance": str(node.facets.get("stance") or "") or None,
        "date": node_date(node) or None,
        "source_file": source_file,
        "source_label": source_label or None,
        "source_exists": source_exists,
        "note_line": hit.note_line,
        "match_reason": hit.match_reason,
        "distance": hit.distance,
        "via_relation": hit.via_relation,
        "via_node_name": hit.via_node_name,
        "href": resolve_result_href(db, node),
    }


def build_search_results(
    db: GraphStore,
    llm: LLMClient | None,
    query: str,
    filters: SearchFilters,
    data_dir: Path,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Run the shared entity-first search and shape it into the search page's card and sections."""
    found = search_ontology(db, llm, query, filters=filters, data_dir=data_dir, limit=limit)
    sections = [
        {"key": key, "hits": [_format_search_hit(db, hit, data_dir) for hit in hits]}
        for key, hits in (
            ("entities", found.entities),
            ("related", found.related),
            ("signals", found.signals),
        )
    ]
    passages = []
    for p in found.passages:
        label, exists = format_source_citation(p.file, data_dir)
        passages.append({**p.to_dict(), "source_label": label or p.file, "source_exists": exists})
    return {
        "best_match": _format_search_hit(db, found.best_match, data_dir) if found.best_match else None,
        "sections": [s for s in sections if s["hits"]],
        "passages": passages,
        "notes_truncated": found.notes_truncated,
        "count": found.count,
    }


# Enum-valued filters shown as chips: (filter key, enum group). Labels are `search.filter_<key>`.
_ENUM_FILTERS = (
    ("sentiment", "sentiment"), ("stance", "stance"), ("support_strength", "support_strength"),
    ("conviction", "conviction"), ("relation", "relation"),
)
# Free-text filters shown verbatim: (filter key, label key suffix).
_TEXT_FILTERS = (("date_from", "from"), ("date_to", "to"), ("source_file", "source"))


def build_active_filters(
    node_type: str, filters: dict[str, str], entity_label: str, lang: str,
) -> list[tuple[str, str]]:
    """Label and value for each filter the search page applies, in display order."""

    def label(suffix: str) -> str:
        return translate(f"search.filter_{suffix}", lang=lang)

    active: list[tuple[str, str]] = []
    if node_type:
        active.append((label("type"), translate_enum("node_type", node_type, lang=lang)))
    if filters["subtype"]:
        sub_nt, sub_value = split_qualified_value(filters["subtype"])
        active.append((label("subtype"), translate_subtype(sub_value, lang=lang, node_type=sub_nt or node_type or None)))
    if filters["status"]:
        _, status_value = split_qualified_value(filters["status"])
        active.append((label("status"), translate_enum("status", status_value, lang=lang)))
    for key, group in _ENUM_FILTERS:
        if filters[key]:
            active.append((label(key), translate_enum(group, filters[key], lang=lang)))
    if filters["entity_id"]:
        active.append((label("entity"), entity_label))
    for key, suffix in _TEXT_FILTERS:
        if filters[key]:
            active.append((label(suffix), filters[key]))
    if filters["search_mode"] == "keyword":
        active.append((label("mode"), translate("search.mode_keyword_short", lang=lang)))
    return active
