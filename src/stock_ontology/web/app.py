"""FastAPI read-only web application for the 1990s Library UI and Clippy PM chat."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from stock_ontology.agent import OntologyAgent
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    LANG_COOKIE_NAME,
    SUPPORTED_LANGUAGE_CODES,
    SUPPORTED_LANGUAGES,
    format_relation_label,
    format_via_label,
    get_clippy_i18n,
    get_language_spec,
    normalize_language,
    resolve_language,
    translate,
    translate_enum,
    translate_subtype,
)
from stock_ontology.llm import LLMClient, create_llm_client
from stock_ontology.registry import OntologyRegistry, load_registry
from stock_ontology.web.catalog import build_catalog_context, format_source_citation
from stock_ontology.web.navigation import LEFT_NAV, WORKFLOWS, resolve_nav
from stock_ontology.web.viewmodels import (
    build_companies_context,
    build_entity_context,
    build_home_context,
    build_ontology_context,
    build_rail_context,
    build_search_filter_options,
    build_theme_context,
    build_themes_context,
    run_hybrid_search,
)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
MAX_CHAT_SESSIONS = 50


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    page_context: str | None = None
    lang: str | None = None


class ChatResetRequest(BaseModel):
    session_id: str


class LanguageRequest(BaseModel):
    lang: str


def _sanitize_next_path(raw_next: str | None) -> str:
    """Validate an internal relative redirect path and strip any stale `lang` query param."""
    if not raw_next:
        return "/"
    parsed = urlparse(raw_next.strip())
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        return "/"
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k != "lang"
    ]
    query_str = urlencode(kept)
    return f"{parsed.path}?{query_str}" if query_str else parsed.path


def _build_next_path(request: Request) -> str:
    """Return current request path + query parameters excluding `lang`."""
    kept = [(k, v) for k, v in request.query_params.multi_items() if k != "lang"]
    query_str = urlencode(kept)
    return f"{request.url.path}?{query_str}" if query_str else request.url.path


def create_app(settings: Settings, llm: LLMClient | None = None) -> FastAPI:
    """Create the FastAPI app wired strictly read-only to `settings.db_path`."""
    app = FastAPI(title="Stock Ontology Library", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    active_llm: LLMClient = llm if llm is not None else create_llm_client(settings)
    # Opaque per-session history from `ChatTurn.history`, passed back unchanged.
    sessions: dict[str, tuple[Any, ...]] = {}

    def _resolve_request_lang(
        request: Request, explicit_lang: str | None = None
    ) -> str:
        return resolve_language(
            query_lang=explicit_lang or request.query_params.get("lang"),
            cookie_lang=request.cookies.get(LANG_COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
            default=settings.default_language,
        )

    def _open_ro_db(lang: str = DEFAULT_LANGUAGE) -> OntologyDB:
        reg, _ = _load_optional_registry()
        try:
            return OntologyDB(
                settings.db_path,
                embedding_dim=settings.embedding_dim,
                read_only=True,
                registry=reg,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=translate(
                    "api.db_not_initialized", lang=lang, db_path=settings.db_path
                ),
            ) from exc

    def _load_optional_registry() -> tuple[OntologyRegistry | None, str | None]:
        if not settings.registry_path.exists():
            return None, None
        try:
            return load_registry(settings.registry_path), None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    def _render(
        request: Request,
        template_name: str,
        ctx: dict[str, Any],
        lang: str,
    ) -> HTMLResponse:
        spec = get_language_spec(lang)
        default_rail = {
            "total_nodes": 0,
            "total_edges": 0,
            "company_count": 0,
            "other_entity_count": 0,
            "theme_count": 0,
            "doc_count": 0,
        }
        route = request.scope.get("route")
        nav = resolve_nav(getattr(route, "path", request.url.path), request.query_params, ctx)
        full_ctx = {
            "rail": default_rail,
            **ctx,
            "nav": nav,
            "nav_workflows": WORKFLOWS,
            "nav_groups": LEFT_NAV[nav.workflow],
            "clippy_open": request.query_params.get("ask") == "1",
            "clippy_context": request.query_params.get("context", "").strip(),
            "lang": lang,
            "html_lang": spec["html_lang"],
            "languages": SUPPORTED_LANGUAGES,
            "next_path": _build_next_path(request),
            "t": lambda key, **kw: translate(key, lang=lang, **kw),
            "t_enum": lambda group, value: translate_enum(group, value, lang=lang),
            "t_subtype": lambda value, node_type=None: translate_subtype(
                value, lang=lang, node_type=node_type
            ),
            "format_via": lambda via: format_via_label(via, lang=lang),
            "format_relation": lambda rel, direction=None: format_relation_label(
                rel, direction=direction, lang=lang
            ),
            "clippy_i18n": get_clippy_i18n(lang),
        }
        resp = templates.TemplateResponse(request, template_name, full_ctx)
        explicit_query_lang = normalize_language(request.query_params.get("lang"))
        if explicit_query_lang is not None:
            resp.set_cookie(
                key=LANG_COOKIE_NAME,
                value=explicit_query_lang,
                max_age=31536000,
                samesite="lax",
                path="/",
            )
        return resp

    @app.get("/set-language")
    def set_language_route(
        request: Request,
        lang: str = "",
        next: str = "/",
    ) -> RedirectResponse:
        resolved = normalize_language(lang) or _resolve_request_lang(request)
        target = _sanitize_next_path(next)
        resp = RedirectResponse(url=target, status_code=303)
        resp.set_cookie(
            key=LANG_COOKIE_NAME,
            value=resolved,
            max_age=31536000,
            samesite="lax",
            path="/",
        )
        return resp

    @app.post("/api/language")
    def api_set_language(request: Request, payload: LanguageRequest) -> JSONResponse:
        req_lang = _resolve_request_lang(request)
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
            max_age=31536000,
            samesite="lax",
            path="/",
        )
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
            ctx = build_home_context(db, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return _render(request, "home.html", ctx, lang)

    @app.get("/companies", response_class=HTMLResponse)
    def companies_page(request: Request, kind: str = "companies") -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
            ctx = build_companies_context(db, kind=kind, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return _render(request, "companies.html", ctx, lang)

    @app.get("/themes", response_class=HTMLResponse)
    def themes_page(request: Request) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
            ctx = build_themes_context(db, lang=lang)
            ctx["rail"] = build_rail_context(db)
        return _render(request, "themes.html", ctx, lang)

    @app.get("/ask")
    def ask_redirect(request: Request, context: str = "") -> RedirectResponse:
        """The Ask desk is the on-page Clippy dock: open it on Overview, carrying the context."""
        params = {"ask": "1"}
        if context.strip():
            params["context"] = context.strip()
        explicit_lang = normalize_language(request.query_params.get("lang"))
        if explicit_lang is not None:
            params["lang"] = explicit_lang
        return RedirectResponse(url=f"/?{urlencode(params)}", status_code=303)

    @app.get("/entity/{entity_id}", response_class=HTMLResponse)
    def entity_page(request: Request, entity_id: str) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
            try:
                ctx = build_entity_context(
                    db, entity_id, data_dir=settings.data_dir, lang=lang
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.entity_not_found", lang=lang, entity_id=entity_id),
                ) from exc
            ctx["rail"] = build_rail_context(db)
        return _render(request, "entity.html", ctx, lang)

    @app.get("/theme/{theme_id}", response_class=HTMLResponse)
    def theme_page(request: Request, theme_id: str) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
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
        return _render(request, "theme.html", ctx, lang)

    @app.get("/search", response_class=HTMLResponse)
    def search_page(
        request: Request,
        q: str = "",
        node_type: str = "",
        subtype: str = "",
        sentiment: str = "",
        stance: str = "",
        entity_id: str = "",
        date_from: str = "",
        date_to: str = "",
        source_file: str = "",
        search_mode: str = "hybrid",
    ) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        norm_mode = "keyword" if search_mode.strip().lower() == "keyword" else "hybrid"
        filters = {
            "subtype": subtype.strip(),
            "sentiment": sentiment.strip(),
            "stance": stance.strip(),
            "entity_id": entity_id.strip(),
            "date_from": date_from.strip(),
            "date_to": date_to.strip(),
            "source_file": source_file.strip(),
            "search_mode": norm_mode,
        }
        with _open_ro_db(lang) as db:
            rail = build_rail_context(db)
            search_options = build_search_filter_options(db)
            results = run_hybrid_search(
                db,
                active_llm,
                query=q,
                node_type=node_type or None,
                limit=50,
                subtype=filters["subtype"] or None,
                sentiment=filters["sentiment"] or None,
                stance=filters["stance"] or None,
                entity_id=filters["entity_id"] or None,
                date_from=filters["date_from"] or None,
                date_to=filters["date_to"] or None,
                source_file=filters["source_file"] or None,
                search_mode=norm_mode,
            )
            entity_label = filters["entity_id"]
            if filters["entity_id"]:
                ent_node = db.get_node(filters["entity_id"])
                if ent_node is not None:
                    entity_label = ent_node.name

        for item in results:
            sf = item.get("source_file")
            label, exists = format_source_citation(
                str(sf) if sf else None, settings.data_dir
            )
            item["source_label"] = label or None
            item["source_exists"] = exists

        active_filters: list[tuple[str, str]] = []
        if node_type.strip():
            active_filters.append(
                (
                    translate("search.filter_type", lang=lang),
                    translate_enum("node_type", node_type.strip(), lang=lang),
                )
            )
        if filters["subtype"]:
            active_filters.append(
                (
                    translate("search.filter_subtype", lang=lang),
                    translate_subtype(
                        filters["subtype"], lang=lang, node_type=node_type.strip() or None
                    ),
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
            "results": results,
            "page_context": (
                translate("page_context.search_query", lang=lang, query=q)
                if q.strip()
                else translate("page_context.search_empty", lang=lang)
            ),
        }
        return _render(request, "search.html", ctx, lang)

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog_page(
        request: Request,
        view: str = "company",
        dir: str = "",
        author: str = "",
        person: str = "",
        alpha: str = "",
        file: str = "",
        format: str = "rendered",
    ) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        with _open_ro_db(lang) as db:
            try:
                ctx = build_catalog_context(
                    db,
                    settings.data_dir,
                    view=view,
                    selected_dir=dir,
                    selected_author=author,
                    selected_person=person,
                    selected_alpha=alpha,
                    selected_file=file,
                    note_format=format,
                    lang=lang,
                )
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=translate("api.raw_note_not_found", lang=lang, file=file),
                ) from exc
            ctx["rail"] = build_rail_context(db)
        return _render(request, "catalog.html", ctx, lang)

    @app.get("/ontology", response_class=HTMLResponse)
    def ontology_page(
        request: Request,
        tab: str = "entity",
        subtype: str = "",
        reg_status: str = "",
    ) -> HTMLResponse:
        lang = _resolve_request_lang(request)
        reg, reg_err = _load_optional_registry()
        with _open_ro_db(lang) as db:
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
        return _render(request, "ontology.html", ctx, lang)

    @app.get("/api/health")
    def health(request: Request) -> JSONResponse:
        lang = _resolve_request_lang(request)
        if str(settings.db_path) != ":memory:" and not Path(settings.db_path).exists():
            return JSONResponse(
                {"status": "not_initialized", "db_path": str(settings.db_path)},
                status_code=503,
            )
        with _open_ro_db(lang) as db:
            stats = db.get_stats()
        llm_info = active_llm.describe() if hasattr(active_llm, "describe") else None
        reg, reg_err = _load_optional_registry()
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

    @app.post("/api/chat")
    def chat_endpoint(request: Request, payload: ChatRequest) -> JSONResponse:
        lang = _resolve_request_lang(request, explicit_lang=payload.lang)
        msg = payload.message.strip()
        if not msg:
            raise HTTPException(
                status_code=400,
                detail=translate("api.chat_empty_error", lang=lang),
            )

        sid = payload.session_id or f"sess_{uuid.uuid4().hex[:12]}"
        if sid not in sessions and len(sessions) >= MAX_CHAT_SESSIONS:
            oldest = next(iter(sessions))
            sessions.pop(oldest, None)

        history = sessions.get(sid, ())
        prompt = (
            f"[Current library page: {payload.page_context}]\n{msg}"
            if payload.page_context
            else msg
        )

        with _open_ro_db(lang) as db:
            agent = OntologyAgent(db, active_llm, language=lang)
            try:
                turn = agent.chat(prompt, history)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    {
                        "session_id": sid,
                        "lang": lang,
                        "error": str(exc),
                        "reply": translate("api.chat_error", lang=lang, error=exc),
                        "tools_used": [],
                    },
                    status_code=500,
                )
            sessions[sid] = turn.history

        return JSONResponse(
            {
                "session_id": sid,
                "lang": lang,
                "reply": turn.reply,
                "tools_used": list(turn.tools_used),
                "provider": turn.provider,
                "model": turn.model,
                "fallback_used": turn.fallback_used,
            }
        )

    @app.post("/api/chat/reset")
    def chat_reset(payload: ChatResetRequest) -> JSONResponse:
        sessions.pop(payload.session_id, None)
        return JSONResponse({"status": "reset", "session_id": payload.session_id})

    return app
