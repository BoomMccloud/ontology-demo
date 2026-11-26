"""Research module routes: overview, companies, themes, the entity, theme, and thesis pages, and
claim writes (theses and thesis memberships) queued as worker jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from stock_ontology.i18n import translate
from stock_ontology.services import GraphQueries, ServiceError
from stock_ontology.web.research.views import (
    build_companies_context,
    build_entity_context,
    build_home_context,
    build_theme_context,
    build_themes_context,
    build_thesis_context,
)
from stock_ontology.web.shared import build_rail_context
from stock_ontology.web.shell import WebShell, http_error


class ClaimRequest(BaseModel):
    kind: str
    params: dict[str, Any]


def build_router(shell: WebShell) -> APIRouter:
    router = APIRouter()
    settings = shell.settings

    @router.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            ctx = build_home_context(db, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "home.html", ctx, lang)

    @router.get("/companies", response_class=HTMLResponse)
    def companies_page(request: Request, kind: str = "companies") -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            ctx = build_companies_context(db, kind=kind, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "companies.html", ctx, lang)

    @router.get("/themes", response_class=HTMLResponse)
    def themes_page(request: Request) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            ctx = build_themes_context(db, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "themes.html", ctx, lang)

    @router.get("/entity/{entity_id}", response_class=HTMLResponse)
    def entity_page(request: Request, entity_id: str) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            try:
                ctx = build_entity_context(
                    db, entity_id, data_dir=settings.data_dir, lang=lang
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.entity_not_found", lang=lang, entity_id=entity_id),
                ) from exc
            ctx["consensus_stale"] = GraphQueries(db).consensus_status(entity_id)["stale"]
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "entity.html", ctx, lang)

    @router.get("/theme/{theme_id}", response_class=HTMLResponse)
    def theme_page(request: Request, theme_id: str) -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            try:
                ctx = build_theme_context(
                    db, theme_id, data_dir=settings.data_dir, lang=lang
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.theme_not_found", lang=lang, theme_id=theme_id),
                ) from exc
            ctx["rail"] = build_rail_context(db)
            ctx["claim_actions"] = shell.note_actions
        return shell.render(request, "theme.html", ctx, lang)

    @router.get("/thesis/{thesis_id}", response_class=HTMLResponse)
    def thesis_page(request: Request, thesis_id: str, company: str = "") -> HTMLResponse:
        lang = shell.lang(request)
        with shell.open_db(lang) as db:
            try:
                ctx = build_thesis_context(db, thesis_id, company_id=company, lang=lang)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.thesis_not_found", lang=lang, thesis_id=thesis_id),
                ) from exc
            ctx["claim_actions"] = shell.note_actions
            ctx["rail"] = build_rail_context(db)
        return shell.render(request, "thesis.html", ctx, lang)

    @router.post("/api/claims", status_code=202)
    def submit_claim(request: Request, payload: ClaimRequest) -> JSONResponse:
        """Queue a thesis or membership write; the page polls `/api/jobs/{job_id}`."""
        shell.require_note_actions(request)
        try:
            ref = shell.processing.submit_claim(payload.kind, payload.params)
        except ServiceError as exc:
            raise http_error(exc, shell.lang(request)) from exc
        return JSONResponse({"job_id": ref.job_id, "state": ref.state}, status_code=202)

    return router
