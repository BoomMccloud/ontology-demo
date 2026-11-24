"""The web shell every module renders through: request language, read-only graph access, and page rendering.

Module routers receive one `WebShell` and never build their own templates, database handles, or
navigation state. `render` resolves navigation through the registry in `navigation.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from stock_ontology.config import Settings
from stock_ontology.i18n import (
    DEFAULT_LANGUAGE,
    LANG_COOKIE_NAME,
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
from stock_ontology.llm import LLMClient
from stock_ontology.registry import OntologyRegistry, load_registry
from stock_ontology.services import GraphStore, open_graph
from stock_ontology.web.navigation import LEFT_NAV, WORKFLOWS, resolve_nav

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
LANG_COOKIE_MAX_AGE = 31536000

# HTTP status for each typed service error.
HTTP_STATUS = {"not_found": 404, "conflict": 409, "invalid": 422, "unavailable": 503}


def sanitize_next_path(raw_next: str | None) -> str:
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


def build_next_path(request: Request) -> str:
    """Return current request path + query parameters excluding `lang`."""
    kept = [(k, v) for k, v in request.query_params.multi_items() if k != "lang"]
    query_str = urlencode(kept)
    return f"{request.url.path}?{query_str}" if query_str else request.url.path


class WebShell:
    """Per-app services shared by every module router."""

    def __init__(
        self, settings: Settings, llm: LLMClient, *, note_actions: bool, registry_origin: str | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.note_actions = note_actions
        self.registry_origin = registry_origin
        self.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def lang(self, request: Request, explicit_lang: str | None = None) -> str:
        return resolve_language(
            query_lang=explicit_lang or request.query_params.get("lang"),
            cookie_lang=request.cookies.get(LANG_COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
            default=self.settings.default_language,
        )

    def load_registry(self) -> tuple[OntologyRegistry | None, str | None]:
        if not self.settings.registry_path.exists():
            return None, None
        try:
            return load_registry(self.settings.registry_path), None
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    def open_db(self, lang: str = DEFAULT_LANGUAGE) -> GraphStore:
        reg, _ = self.load_registry()
        try:
            return open_graph(self.settings, reg)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=translate(
                    "api.db_not_initialized", lang=lang, db_path=self.settings.db_path
                ),
            ) from exc

    def render(
        self,
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
            "next_path": build_next_path(request),
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
        resp = self.templates.TemplateResponse(request, template_name, full_ctx)
        explicit_query_lang = normalize_language(request.query_params.get("lang"))
        if explicit_query_lang is not None:
            resp.set_cookie(
                key=LANG_COOKIE_NAME,
                value=explicit_query_lang,
                max_age=LANG_COOKIE_MAX_AGE,
                samesite="lax",
                path="/",
            )
        return resp
