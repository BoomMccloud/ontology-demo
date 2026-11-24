"""Ontology view models: model structure tabs, diagram links, registry, and audit views."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from stock_ontology.audit import (
    AuditReport,
    classify_edge_against_registry,
    node_type_label,
    run_ontology_audit,
)
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    translate,
    translate_enum,
)
from stock_ontology.models import Node, resolve_item_sentiment
from stock_ontology.registry import (
    OntologyRegistry,
    normalize_name_key,
    normalize_relation_name,
)
from stock_ontology.search import (
    node_date,
    node_source_file,
    node_subtype,
    resolve_safe_note_path,
)
from stock_ontology.services import GraphStore
from stock_ontology.web.shared import (
    format_facet_value,
    resolve_result_href,
)

STRUCTURE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "key": "entity",
        "number": "1",
        "title": "Entity",
        "plural": "Entities",
        "subtitle": "Companies, People, Institutions & Regions",
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
        "description": "Cross-company macro or industry theses and the companies they affect.",
    },
)


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
    db: GraphStore,
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
            sub = node_subtype(n) or "unspecified"
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
            from_href = resolve_result_href(db, from_node) if from_node else "/"
            to_href = resolve_result_href(db, to_node) if to_node else "/"
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
                if (node_subtype(n) or "unspecified") == active_subtype
            ]

        if active_tab in ("entity", "theme"):
            candidates = sorted(
                candidates,
                key=lambda n: (-edge_counts.get(n.id, 0), n.name.casefold()),
            )
        else:
            candidates = sorted(
                candidates,
                key=lambda n: (node_date(n) or "", n.updated_at.isoformat()),
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
            subtype_val = node_subtype(n) or "unspecified"
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
            source_file = node_source_file(n)
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
                    "stance": str(n.facets.get("stance") or "") or None,
                    "status": str(n.facets.get("status") or "") or None,
                    "date": node_date(n) or None,
                    "edge_count": edge_counts.get(n.id, 0),
                    "href": resolve_result_href(db, n),
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
