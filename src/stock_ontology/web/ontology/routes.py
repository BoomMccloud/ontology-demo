"""Ontology module routes: model structure, registry, and audit tabs."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from stock_ontology.web.ontology.views import build_ontology_context
from stock_ontology.web.shared import build_rail_context
from stock_ontology.web.shell import WebShell


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings

    @router.get("/ontology", response_class=HTMLResponse)
    def ontology_page(
        request: Request,
        tab: str = "entity",
        subtype: str = "",
        reg_status: str = "",
    ) -> HTMLResponse:
        lang = shell.lang(request)
        reg, reg_err = shell.load_registry()
        with shell.open_db(lang) as db:
            ctx = build_ontology_context(
                db,
                tab=tab,
                subtype=subtype,
                reg_status=reg_status,
                data_dir=settings.data_dir,
                registry=reg,
                registry_path=settings.registry_path,
                registry_error=reg_err,
                lang=lang,
            )
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "ontology.html", ctx, lang)

    return router
