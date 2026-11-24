"""Navigation registry: one source of truth for the Web UI shell.

Every HTML route is registered here with a resolver that maps the request and the page
context to a workflow (top nav), an owning section (left nav), an archetype (`page` for a
functional page, `component` for a functional template such as a list or detail view),
and the breadcrumb trail for detail and drill-down views. `_render` in `app.py` calls
`resolve_nav` for every HTML response, so templates never hand-set navigation state and an
unregistered route fails loudly.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlencode, urlsplit


@dataclass(frozen=True)
class NavItem:
    key: str
    label_key: str
    href: str


@dataclass(frozen=True)
class NavGroup:
    label_key: str | None
    items: tuple[NavItem, ...]


@dataclass(frozen=True)
class Crumb:
    """A breadcrumb item. `label_key` is translated in the template; `label` is literal data."""

    label: str = ""
    label_key: str = ""
    href: str | None = None


@dataclass(frozen=True)
class NavState:
    workflow: str
    section: str
    archetype: str
    crumbs: list[Crumb] = field(default_factory=list)
    tool: str = ""


WORKFLOWS: tuple[NavItem, ...] = (
    NavItem("research", "nav.research", "/"),
    NavItem("notes", "nav.notes", "/catalog?view=all"),
    NavItem("ontology", "rail.ontology", "/ontology"),
)

_OVERVIEW = NavItem("overview", "nav.overview", "/")
_COMPANIES = NavItem("companies", "rail.companies", "/companies")
_THEMES = NavItem("themes", "rail.themes", "/themes")
_OTHER = NavItem("other_entities", "companies.tab_other", "/companies?kind=other")
_NOTES = NavItem("notes_library", "nav.notes_library", "/catalog?view=all")
_GRAPH = NavItem("graph", "nav.graph", "/ontology")

MODERN_PRIMARY = (
    _OVERVIEW,
    _COMPANIES,
    _THEMES,
    replace(_OTHER, label_key="nav.other_entities"),
    replace(_NOTES, label_key="nav.notes"),
)

LEFT_NAV: dict[str, tuple[NavGroup, ...]] = {
    "research": (NavGroup(None, (_OVERVIEW, _COMPANIES, _THEMES, _OTHER)),),
    "notes": (NavGroup(None, (_NOTES,)),),
    "ontology": (
        NavGroup("nav.model", (_GRAPH,)),
        NavGroup(
            "nav.governance",
            (
                NavItem("registry", "nav.registry", "/ontology?tab=registry"),
                NavItem("audit", "nav.audit", "/ontology?tab=audit"),
            ),
        ),
    ),
}

_ROOT = Crumb(label_key="nav.research", href="/")
_NOTES_ROOT = Crumb(label_key="nav.notes", href=_NOTES.href)


def _crumb(item: NavItem) -> Crumb:
    return Crumb(label_key=item.label_key, href=item.href)


Resolver = Callable[[Mapping[str, str], Mapping[str, Any]], NavState]


def _home(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("research", "overview", "page")


def _companies(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    owner = _OTHER if ctx.get("active_kind") == "other" else _COMPANIES
    return NavState("research", owner.key, "component")


def _themes(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("research", "themes", "component")


def _search(q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    if q.get("in") == "notes":
        return NavState("notes", _NOTES.key, "page", tool="search")
    return NavState("research", _OVERVIEW.key, "page", tool="search")


def _entity(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    owner = _COMPANIES if ctx.get("is_company") else _OTHER
    name = str(getattr(ctx.get("entity"), "name", ""))
    return NavState("research", owner.key, "component", [_ROOT, _crumb(owner), Crumb(label=name)])


def _theme(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    name = str(getattr(ctx.get("theme"), "name", ""))
    return NavState("research", "themes", "component", [_ROOT, _crumb(_THEMES), Crumb(label=name)])


_NOTES_VIEW_LABEL = {
    "company": "nav.notes_by_company",
    "author": "nav.notes_by_author",
    "all": "nav.notes_all",
}


def note_origin(raw: str) -> Crumb | None:
    """Accept only evidence locations from research records or Search."""
    if not raw.startswith("/") or raw.startswith("//") or any(ord(char) < 32 or char == "\\" for char in raw):
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.path == "/search" and not parts.fragment:
        return Crumb(label_key="nav.search", href=raw)
    if re.fullmatch(r"/(?:entity|theme)/[A-Za-z0-9_.~-]+", parts.path):
        if not parts.query and parts.fragment in {"sec-evidence", "sec-events", "sec-views", "sec-exposure", "sec-authored"}:
            return Crumb(label_key="nav.back_to_record", href=raw)
    return None


def _catalog(q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    view = str(ctx.get("view_mode") or "company")
    group = ctx.get("active_group")
    note = ctx.get("active_note")
    if note:
        parent = note_origin(q.get("from", "")) or Crumb(label=note.back_link.label, href=note.back_link.href)
        return NavState("notes", _NOTES.key, "component", [parent])

    if group and view in ("author", "company"):
        mode = Crumb(label_key=_NOTES_VIEW_LABEL[view], href=f"/catalog?{urlencode({'view': view})}")
        return NavState("notes", _NOTES.key, "component", [_NOTES_ROOT, mode, Crumb(label=str(group["label"]))])
    return NavState("notes", _NOTES.key, "component")


def _note_new(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("notes", _NOTES.key, "page", tool="paste")


def _ontology(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    tab = str(ctx.get("active_tab") or "entity")
    return NavState("ontology", tab if tab in {"registry", "audit"} else _GRAPH.key, "page")


NAV_ROUTES: dict[str, Resolver] = {
    "/": _home,
    "/companies": _companies,
    "/themes": _themes,
    "/search": _search,
    "/entity/{entity_id}": _entity,
    "/theme/{theme_id}": _theme,
    "/catalog": _catalog,
    "/notes/new": _note_new,
    "/ontology": _ontology,
}


def resolve_nav(route_path: str, query: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    """Return the navigation state for a registered route. Raises KeyError when unregistered."""
    return NAV_ROUTES[route_path](query, ctx)
