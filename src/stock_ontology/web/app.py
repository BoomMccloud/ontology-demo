"""FastAPI web application: the Library shell and its module routers.

Each user-facing module (Research, Search, Notes, Ontology, Clippy) owns a package under `web/` with
its routes and view models, and renders through the shared `WebShell`. This file only assembles them
and keeps the shell-level language and health routes.

The app opens `ontology.db` only read-only. Saving a note, **Process**, and every note-reader
correction submit a job through `services.ProcessingService` and return its reference with
202; the background worker applies it, and the reader polls `/api/jobs/{job_id}`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stock_ontology.config import Settings
from stock_ontology.i18n import LANG_COOKIE_NAME, SUPPORTED_LANGUAGE_CODES, normalize_language, translate
from stock_ontology.llm import LLMClient, create_llm_client
from stock_ontology.web.clippy.routes import build_router as build_clippy_router
from stock_ontology.web.notes.routes import build_router as build_notes_router
from stock_ontology.web.ontology.routes import build_router as build_ontology_router
from stock_ontology.web.research.routes import build_router as build_research_router
from stock_ontology.web.search.routes import build_router as build_search_router
from stock_ontology.web.shell import LANG_COOKIE_MAX_AGE, STATIC_DIR, WebShell, sanitize_next_path


class LanguageRequest(BaseModel):
    lang: str


def create_app(
    settings: Settings, llm: LLMClient | None = None, *, note_actions: bool = False,
    registry_origin: str | None = None,
) -> FastAPI:
    """Create the library. `note_actions` enables Process and corrections, which queue worker jobs."""
    app = FastAPI(title="Stock Ontology Library", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    shell = WebShell(
        settings, llm if llm is not None else create_llm_client(settings), note_actions=note_actions,
        registry_origin=registry_origin,
    )
    for build_router in (
        build_research_router,
        build_search_router,
        build_notes_router,
        build_ontology_router,
        build_clippy_router,
    ):
        app.include_router(build_router(shell))

    @app.get("/set-language")
    def set_language_route(
        request: Request,
        lang: str = "",
        next: str = "/",
    ) -> RedirectResponse:
        resolved = normalize_language(lang) or shell.lang(request)
        target = sanitize_next_path(next)
        resp = RedirectResponse(url=target, status_code=303)
        resp.set_cookie(
            key=LANG_COOKIE_NAME,
            value=resolved,
            max_age=LANG_COOKIE_MAX_AGE,
            samesite="lax",
            path="/",
        )
        return resp

    @app.post("/api/language")
    def api_set_language(request: Request, payload: LanguageRequest) -> JSONResponse:
        req_lang = shell.lang(request)
        resolved = normalize_language(payload.lang)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=translate(
                    "api.unsupported_language",
                    lang=req_lang,
                    requested=payload.lang,
                    supported=", ".join(SUPPORTED_LANGUAGE_CODES),
                ),
            )
        resp = JSONResponse(
            {"lang": resolved, "supported": list(SUPPORTED_LANGUAGE_CODES)}
        )
        resp.set_cookie(
            key=LANG_COOKIE_NAME,
            value=resolved,
            max_age=LANG_COOKIE_MAX_AGE,
            samesite="lax",
            path="/",
        )
        return resp

    @app.get("/api/health")
    def health(request: Request) -> JSONResponse:
        lang = shell.lang(request)
        if str(settings.db_path) != ":memory:" and not Path(settings.db_path).exists():
            return JSONResponse(
                {"status": "not_initialized", "db_path": str(settings.db_path)},
                status_code=503,
            )
        with shell.open_db(lang) as db:
            stats = db.get_stats()
        llm_info = shell.llm.describe() if hasattr(shell.llm, "describe") else None
        reg, reg_err = shell.load_registry()
        if reg is not None:
            reg_info: dict[str, Any] = {
                "loaded": True,
                "path": str(settings.registry_path),
                "version": reg.version,
                "official_relations": len(reg.relations),
                "official_companies": len(reg.companies),
                "official_themes": len(reg.themes),
                "pending_suggestions": {
                    "relations": sum(
                        1 for s in reg.suggestions.relations if s.status == "pending"
                    ),
                    "companies": sum(
                        1 for s in reg.suggestions.companies if s.status == "pending"
                    ),
                    "themes": sum(
                        1 for s in reg.suggestions.themes if s.status == "pending"
                    ),
                },
            }
        else:
            reg_info = {
                "loaded": False,
                "path": str(settings.registry_path),
                "error": reg_err,
            }
        return JSONResponse(
            {
                "status": "ok",
                "read_only": True,
                "default_language": settings.default_language,
                "supported_languages": list(SUPPORTED_LANGUAGE_CODES),
                "stats": stats,
                "llm": llm_info,
                "registry": reg_info,
            }
        )

    return app
