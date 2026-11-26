"""Research view models: overview, companies, themes, and the entity, theme, and thesis pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    translate,
    translate_enum,
)
from stock_ontology.models import resolve_item_sentiment
from stock_ontology.services import GraphStore, reconcile_sentiment
from stock_ontology.vocab import (
    is_synthesized_edge,
)
from stock_ontology.web.search.views import build_search_filter_options
from stock_ontology.web.shared import (
    format_facet_pairs,
    format_source_citation,
)

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


def is_company_entity(entity_type: str) -> bool:
    """The one rule for whether an entity belongs to Companies rather than Other Entities."""
    return entity_type == "company"


def _load_entities_split(
    db: GraphStore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load and sort company entities separately from non-company entities."""
    all_entities = db.list_nodes(node_type="entity", limit=1000)
    companies: list[dict[str, Any]] = []
    other_entities: list[dict[str, Any]] = []

    for ent in all_entities:
        etype = str(ent.facets.get("entity_type", "entity"))
        if is_company_entity(etype):
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


def _load_themes_list(db: GraphStore) -> list[dict[str, Any]]:
    """Load and sort investment themes with their affected-company counts."""
    themes: list[dict[str, Any]] = []
    for thm in db.list_nodes(node_type="theme", limit=500):
        tc = db.find_theme_companies(thm.id)
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
                "company_count": len(tc["companies"]),
                "view_count": len(neighbor_ids["view"]),
                "event_count": len(neighbor_ids["event"]),
            }
        )

    themes.sort(
        key=lambda t: (
            -t["company_count"],
            t["name"].casefold(),
        )
    )
    return themes


def build_home_context(db: GraphStore, lang: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
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
    db: GraphStore, kind: str = "companies", lang: str = DEFAULT_LANGUAGE
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
    db: GraphStore, lang: str = DEFAULT_LANGUAGE
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
# display-ready. `tests/test_web_research.py::test_entity_page_templates_only_see_presentation_models`
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
class ExposureNote:
    """One note's stated exposure of a company to a theme."""

    sentiment: str | None
    source: SourceCitation


@dataclass(frozen=True)
class ThemeEvidenceItem:
    """An event or view about both a company and a theme, linking to its row on the page."""

    id: str
    name: str
    date: str | None
    # Set only from the company's own ABOUT edge, never inherited from the event or view.
    sentiment: str | None


@dataclass(frozen=True)
class ThemeCompanyRow:
    """One company on a theme page. `is_exposed` means a note states an EXPOSED_TO link.

    `suggested` means no thesis on the theme has a membership for the company, so the notes
    only suggest it as a candidate."""

    company: EntityHeader
    is_exposed: bool
    exposure: str | None
    notes: tuple[ExposureNote, ...]
    evidence: tuple[ThemeEvidenceItem, ...]
    suggested: bool


@dataclass(frozen=True)
class ThesisLinkRow:
    """One thesis on a theme page, linking to its thesis page."""

    id: str
    statement: str
    member_count: int
    candidate_count: int


@dataclass(frozen=True)
class CatalystRow:
    """The event a candidate membership waits for, by when, and what it would do."""

    event: str
    by_date: str
    expected_effect: str


@dataclass(frozen=True)
class ThesisHeader:
    """Title block of a thesis page."""

    id: str
    statement: str
    theme_id: str
    theme_name: str


@dataclass(frozen=True)
class ThesisMembershipRow:
    """One company on a thesis page. `status` is `in` or `candidate`."""

    id: str
    company: EntityHeader
    status: str
    reason: str
    catalyst: CatalystRow | None


@dataclass(frozen=True)
class CompanyThesisRow:
    """One thesis a company belongs to, shown on the company page."""

    thesis_id: str
    statement: str
    status: str
    theme_id: str
    theme_name: str
    catalyst: CatalystRow | None


@dataclass(frozen=True)
class CompanyOption:
    """A company the membership form can add."""

    id: str
    name: str


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
        extra_facets=format_facet_pairs(cf, extra_keys, lang=lang),
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


def _canonical_relation(db: GraphStore, relation: Any) -> str:
    match = db.registry.resolve_relation(str(relation))
    return match.canonical if match is not None else str(relation)


def _exposure_notes(
    db: GraphStore,
    theme_edges: list[dict[str, Any]],
    company_id: str,
    file_by_doc: dict[str, str],
    data_dir: Path | None,
) -> tuple[ExposureNote, ...]:
    """Return one stated exposure per source note, so disagreement between notes stays visible."""
    by_doc: dict[str | None, str | None] = {}
    for item in theme_edges:
        if (
            item["neighbor"]["id"] != company_id
            or is_synthesized_edge(item.get("facets"))
            or _canonical_relation(db, item["relation"]) != "EXPOSED_TO"
        ):
            continue
        doc_id = item.get("source_doc_id")
        by_doc[doc_id] = reconcile_sentiment(by_doc.get(doc_id), (item.get("facets") or {}).get("sentiment"))
    notes = [
        ExposureNote(
            sentiment=sentiment,
            source=_source_citation({"source": {"file_path": file_by_doc.get(doc_id or "", "")}}, data_dir),
        )
        for doc_id, sentiment in by_doc.items()
    ]
    return tuple(sorted(notes, key=lambda note: note.source.label or ""))


def _theme_evidence(
    db: GraphStore,
    row: dict[str, Any],
    edges_by_node: dict[str, list[dict[str, Any]]],
) -> tuple[ThemeEvidenceItem, ...]:
    """Return each event or view linking this company to the theme, newest first."""
    company_id = row["company"]["id"]
    items: dict[str, ThemeEvidenceItem] = {}
    for link in row.get("links", ()):
        node_id = link.get("via_node_id")
        if not node_id or node_id in items:
            continue
        if node_id not in edges_by_node:
            edges_by_node[node_id] = db.get_incident_edges(node_id)
        edges = edges_by_node[node_id]
        sentiment = None
        for edge in edges:
            if (
                edge["neighbor"]["id"] == company_id
                and not is_synthesized_edge(edge.get("facets"))
                and _canonical_relation(db, edge["relation"]) == "ABOUT"
            ):
                sentiment = reconcile_sentiment(sentiment, (edge.get("facets") or {}).get("sentiment"))
        facets = link.get("facets") or {}
        items[node_id] = ThemeEvidenceItem(
            id=str(node_id),
            name=str(link.get("via", "")).partition(": ")[2],
            date=_text(facets.get("event_date") or facets.get("as_of")),
            sentiment=sentiment,
        )
    return tuple(sorted(items.values(), key=lambda item: (item.date or "", item.name), reverse=True))


def _theme_company_rows(
    db: GraphStore,
    theme_id: str,
    rows: list[dict[str, Any]],
    data_dir: Path | None,
) -> list[ThemeCompanyRow]:
    """Map theme companies to rows, most-documented first."""
    theme_edges = db.get_incident_edges(theme_id)
    covered = db.claims.covered_company_ids(theme_id)
    file_by_doc = {entry["doc_id"]: path for path, entry in db.get_ingestion_log().items()}
    edges_by_node: dict[str, list[dict[str, Any]]] = {}
    out: list[ThemeCompanyRow] = []
    for row in rows:
        exposure_link = next(
            (
                link
                for link in row.get("links", ())
                if link.get("via") == "direct" and link.get("relation") == "EXPOSED_TO"
            ),
            None,
        )
        out.append(
            ThemeCompanyRow(
                company=_entity_header(row["company"], "company"),
                is_exposed=exposure_link is not None,
                exposure=_text(exposure_link.get("exposure_sentiment")) if exposure_link else None,
                notes=(
                    _exposure_notes(db, theme_edges, row["company"]["id"], file_by_doc, data_dir)
                    if exposure_link
                    else ()
                ),
                evidence=_theme_evidence(db, row, edges_by_node),
                suggested=row["company"]["id"] not in covered,
            )
        )
    out.sort(key=lambda r: (-len(r.notes), -len(r.evidence), r.company.name.casefold()))
    return out


def _catalyst_row(catalyst: dict[str, Any] | None) -> CatalystRow | None:
    if not catalyst:
        return None
    return CatalystRow(
        event=str(catalyst["event"]), by_date=str(catalyst["by_date"]),
        expected_effect=str(catalyst["expected_effect"]),
    )


def _thesis_link_rows(db: GraphStore, theme_id: str) -> list[ThesisLinkRow]:
    rows = []
    for thesis in db.claims.list_theses(theme_id):
        memberships = db.claims.list_memberships(thesis["id"])
        rows.append(ThesisLinkRow(
            id=str(thesis["id"]),
            statement=str(thesis["statement"]),
            member_count=sum(1 for m in memberships if m["status"] == "in"),
            candidate_count=sum(1 for m in memberships if m["status"] != "in"),
        ))
    return rows


def _company_thesis_rows(db: GraphStore, company_id: str) -> list[CompanyThesisRow]:
    memberships = db.claims.company_memberships(company_id)
    theme_names = {node.id: node.name for node in db.get_nodes([str(m["theme_id"]) for m in memberships])}
    return [
        CompanyThesisRow(
            thesis_id=str(m["thesis_id"]),
            statement=str(m["statement"]),
            status=str(m["status"]),
            theme_id=str(m["theme_id"]),
            theme_name=theme_names.get(str(m["theme_id"]), str(m["theme_id"])),
            catalyst=_catalyst_row(m["catalyst"]),
        )
        for m in memberships
    ]


def build_thesis_context(
    db: GraphStore,
    thesis_id: str,
    *,
    company_id: str = "",
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare a thesis page: the thesis, its company memberships, and the membership form's choices.

    `company_id` preselects a company in the form (the theme page's suggested-candidate links).
    Raises KeyError when the thesis does not exist."""
    thesis = db.claims.get_thesis(thesis_id)
    if thesis is None:
        raise KeyError(thesis_id)
    theme = db.get_node(str(thesis["theme_id"]))
    theme_name = theme.name if theme is not None else str(thesis["theme_id"])
    memberships = db.claims.list_memberships(thesis_id)
    companies = {node.id: node for node in db.get_nodes([str(m["company_id"]) for m in memberships])}
    rows = []
    for m in memberships:
        node = companies.get(str(m["company_id"]))
        entity = {"id": m["company_id"], "name": node.name if node else m["company_id"],
                  "summary": node.summary if node else "", "aliases": node.aliases if node else [],
                  "facets": {"ticker": node.facets.get("ticker")} if node else {}}
        rows.append(ThesisMembershipRow(
            id=str(m["id"]),
            company=_entity_header(entity, "company"),
            status=str(m["status"]),
            reason=str(m["reason"]),
            catalyst=_catalyst_row(m["catalyst"]),
        ))
    taken = {str(m["company_id"]) for m in memberships}
    options = sorted(
        (
            CompanyOption(id=node.id, name=node.name)
            for node in db.list_nodes(node_type="entity", limit=1000)
            if is_company_entity(str(node.facets.get("entity_type", ""))) and node.id not in taken
        ),
        key=lambda option: option.name.casefold(),
    )
    return {
        "thesis": ThesisHeader(
            id=str(thesis["id"]), statement=str(thesis["statement"]),
            theme_id=str(thesis["theme_id"]), theme_name=theme_name,
        ),
        "memberships": rows,
        "company_options": options,
        "selected_company": company_id if any(option.id == company_id for option in options) else "",
        "page_context": translate(
            "page_context.thesis", lang=lang, statement=thesis["statement"], theme=theme_name,
        ),
    }


def build_entity_context(
    db: GraphStore,
    entity_id: str,
    *,
    data_dir: Path | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare dynamic facet-driven context for any entity (company, person, etc.)."""
    overview = db.get_entity_overview(entity_id)
    entity = overview["entity"]
    if entity["node_type"] != "entity":
        raise KeyError(f"Node {entity_id} is a {entity['node_type']}, not an entity")  # noqa: TRY003

    facets: dict[str, Any] = entity.get("facets", {})
    entity_type = str(facets.get("entity_type", "entity"))

    company_facets = format_facet_pairs(facets, COMPANY_FACET_KEYS, lang=lang)
    person_facets = format_facet_pairs(facets, PERSON_FACET_KEYS, lang=lang)

    consumed = {"entity_type", *COMPANY_FACET_KEYS, *PERSON_FACET_KEYS}
    extra_keys = [k for k in sorted(facets.keys()) if k not in consumed]
    extra_facets = format_facet_pairs(facets, extra_keys, lang=lang)

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
        "is_company": is_company_entity(entity_type),
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
        "thesis_memberships": _company_thesis_rows(db, entity_id),
        "page_context": translate(
            "page_context.entity",
            lang=lang,
            name=entity["name"],
            entity_type=translate_enum("entity_type", entity_type, lang=lang),
        ),
    }


def build_theme_context(
    db: GraphStore,
    theme_id: str,
    *,
    data_dir: Path | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Prepare context for an investment theme catalog page."""
    theme_data = db.find_theme_companies(theme_id)
    theme = theme_data["theme"]
    facets = theme.get("facets", {})
    extra_keys = [k for k in sorted(facets.keys()) if k != "stage"]

    events_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    views_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    for item in db.get_incident_edges(theme_id):
        nb = item["neighbor"]
        nid = str(nb["id"])
        # A synthesized edge (consensus evidence) doesn't make its neighbor about the theme.
        if is_synthesized_edge(item.get("facets")):
            continue
        rel = str(item["relation"])
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
    company_rows = _theme_company_rows(db, theme_id, theme_data["companies"], data_dir)

    return {
        "theme": _theme_header(theme),
        "stage": facets.get("stage", ""),
        "extra_facets": format_facet_pairs(facets, extra_keys, lang=lang),
        "theses": _thesis_link_rows(db, theme_id),
        "exposed_companies": [row for row in company_rows if row.is_exposed],
        "mentioned_companies": [row for row in company_rows if not row.is_exposed],
        "events": events,
        "views": views,
        "page_context": translate(
            "page_context.theme",
            lang=lang,
            name=theme["name"],
        ),
    }
