"""Search module routes: the shared search page used by Research and Notes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from stock_ontology.i18n import translate, translate_enum, translate_subtype
from stock_ontology.search import SearchFilters, split_qualified_value
from stock_ontology.web.search.views import build_search_filter_options, build_search_results
from stock_ontology.web.shared import build_rail_context
from stock_ontology.web.shell import WebShell


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings

    @router.get("/search", response_class=HTMLResponse)
    def search_page(
        request: Request,
        q: str = "",
        node_type: str = "",
        subtype: str = "",
        status: str = "",
        sentiment: str = "",
        stance: str = "",
        support_strength: str = "",
        conviction: str = "",
        relation: str = "",
        entity_id: str = "",
        date_from: str = "",
        date_to: str = "",
        source_file: str = "",
        search_mode: str = "hybrid",
    ) -> HTMLResponse:
        lang = shell.lang(request)
        norm_mode = "keyword" if search_mode.strip().lower() == "keyword" else "hybrid"
        filters = {
            "subtype": subtype.strip(),
            "status": status.strip(),
            "sentiment": sentiment.strip(),
            "stance": stance.strip(),
            "support_strength": support_strength.strip(),
            "conviction": conviction.strip(),
            "relation": relation.strip(),
            "entity_id": entity_id.strip(),
            "date_from": date_from.strip(),
            "date_to": date_to.strip(),
            "source_file": source_file.strip(),
            "search_mode": norm_mode,
        }
        reg, _ = shell.load_registry()
        with shell.open_db(lang) as db:
            rail = build_rail_context(db)
            search_options = build_search_filter_options(db, reg)
            search = build_search_results(
                db,
                shell.llm,
                q,
                SearchFilters.from_raw(
                    node_type=node_type,
                    subtype=filters["subtype"],
                    status=filters["status"],
                    sentiment=filters["sentiment"],
                    stance=filters["stance"],
                    support_strength=filters["support_strength"],
                    conviction=filters["conviction"],
                    relation=filters["relation"],
                    entity_id=filters["entity_id"],
                    date_from=filters["date_from"],
                    date_to=filters["date_to"],
                    source_file=filters["source_file"],
                    search_mode=norm_mode,
                ),
                settings.data_dir,
            )
            entity_label = filters["entity_id"]
            if filters["entity_id"]:
                ent_node = db.get_node(filters["entity_id"])
                if ent_node is not None:
                    entity_label = ent_node.name

        active_filters: list[tuple[str, str]] = []
        if node_type.strip():
            active_filters.append(
                (
                    translate("search.filter_type", lang=lang),
                    translate_enum("node_type", node_type.strip(), lang=lang),
                )
            )
        if filters["subtype"]:
            sub_nt, sub_value = split_qualified_value(filters["subtype"])
            active_filters.append(
                (
                    translate("search.filter_subtype", lang=lang),
                    translate_subtype(
                        sub_value, lang=lang, node_type=sub_nt or node_type.strip() or None
                    ),
                )
            )
        if filters["status"]:
            _, status_value = split_qualified_value(filters["status"])
            active_filters.append(
                (
                    translate("search.filter_status", lang=lang),
                    translate_enum("status", status_value, lang=lang),
                )
            )
        if filters["sentiment"]:
            active_filters.append(
                (
                    translate("search.filter_sentiment", lang=lang),
                    translate_enum("sentiment", filters["sentiment"], lang=lang),
                )
            )
        if filters["stance"]:
            active_filters.append(
                (
                    translate("search.filter_stance", lang=lang),
                    translate_enum("stance", filters["stance"], lang=lang),
                )
            )
        if filters["support_strength"]:
            active_filters.append(
                (
                    translate("search.filter_support_strength", lang=lang),
                    translate_enum("support_strength", filters["support_strength"], lang=lang),
                )
            )
        if filters["conviction"]:
            active_filters.append(
                (
                    translate("search.filter_conviction", lang=lang),
                    translate_enum("conviction", filters["conviction"], lang=lang),
                )
            )
        if filters["relation"]:
            active_filters.append(
                (
                    translate("search.filter_relation", lang=lang),
                    translate_enum("relation", filters["relation"], lang=lang),
                )
            )
        if filters["entity_id"]:
            active_filters.append((translate("search.filter_entity", lang=lang), entity_label))
        if filters["date_from"]:
            active_filters.append((translate("search.filter_from", lang=lang), filters["date_from"]))
        if filters["date_to"]:
            active_filters.append((translate("search.filter_to", lang=lang), filters["date_to"]))
        if filters["source_file"]:
            active_filters.append((translate("search.filter_source", lang=lang), filters["source_file"]))
        if norm_mode == "keyword":
            active_filters.append(
                (
                    translate("search.filter_mode", lang=lang),
                    translate("search.mode_keyword_short", lang=lang),
                )
            )

        has_search_criteria = bool(q.strip() or active_filters)
        ctx = {
            "rail": rail,
            "query": q,
            "node_type": node_type,
            "filters": filters,
            "active_filters": active_filters,
            "has_search_criteria": has_search_criteria,
            "search_options": search_options,
            "advanced_open": True,
            "search": search,
            "agent_query": q.strip(),
            "agent_prompt": (
                translate("search.agent_prompt", lang=lang, query=q.strip()) if q.strip() else ""
            ),
            "page_context": (
                translate("page_context.search_query", lang=lang, query=q)
                if q.strip()
                else translate("page_context.search_empty", lang=lang)
            ),
        }
        return shell.render(request, "search.html", ctx, lang)

    return router
