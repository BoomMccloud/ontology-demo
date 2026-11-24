"""Search module routes: the shared search page used by Research and Notes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from stock_ontology.i18n import translate
from stock_ontology.search import SearchFilters
from stock_ontology.web.search.views import build_active_filters, build_search_filter_options, build_search_results
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
                SearchFilters.from_raw(node_type=node_type, **filters),
                settings.data_dir,
            )
            entity_label = filters["entity_id"]
            if filters["entity_id"]:
                ent_node = db.get_node(filters["entity_id"])
                if ent_node is not None:
                    entity_label = ent_node.name

        active_filters = build_active_filters(node_type.strip(), filters, entity_label, lang)

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
