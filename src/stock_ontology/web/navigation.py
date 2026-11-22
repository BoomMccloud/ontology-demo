"""Navigation registry: one source of truth for the Web UI shell.

Every HTML route is registered here with a resolver that maps the request and the page
context to a workflow (top nav), an owning section (left nav), an archetype (`page` for a
functional page, `component` for a functional template such as a list or detail view),
and the breadcrumb trail for detail and drill-down views. `_render` in `app.py` calls
`resolve_nav` for every HTML response, so templates never hand-set navigation state and an
unregistered route fails loudly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote


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


WORKFLOWS: tuple[NavItem, ...] = (
    NavItem("research", "nav.research", "/"),
    NavItem("ontology", "rail.ontology", "/ontology"),
)

_OVERVIEW = NavItem("overview", "nav.overview", "/")
_COMPANIES = NavItem("companies", "rail.companies", "/companies")
_THEMES = NavItem("themes", "rail.themes", "/themes")
_OTHER = NavItem("other_entities", "nav.other_entities", "/companies?kind=other")
_NOTES_BY_COMPANY = NavItem("notes_by_company", "nav.notes_by_company", "/catalog?view=company")
_NOTES_BY_AUTHOR = NavItem("notes_by_author", "nav.notes_by_author", "/catalog?view=author")
_NOTES_ALL = NavItem("notes_all", "nav.notes_all", "/catalog?view=all")
_SEARCH = NavItem("search", "nav.search", "/search")

LEFT_NAV: dict[str, tuple[NavGroup, ...]] = {
    "research": (
        NavGroup(None, (_OVERVIEW, _COMPANIES, _THEMES, _OTHER)),
        NavGroup("nav.notes", (_NOTES_BY_COMPANY, _NOTES_BY_AUTHOR, _NOTES_ALL)),
        NavGroup(None, (_SEARCH,)),
    ),
    "ontology": (
        NavGroup(
            "nav.model",
            (
                NavItem("entity", "nav.entities", "/ontology?tab=entity"),
                NavItem("event", "nav.events", "/ontology?tab=event"),
                NavItem("view", "nav.views", "/ontology?tab=view"),
                NavItem("theme", "nav.themes", "/ontology?tab=theme"),
                NavItem("edges", "nav.edges", "/ontology?tab=edges"),
            ),
        ),
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
_NOTES_ROOT = Crumb(label_key="nav.notes", href="/catalog")


def _crumb(item: NavItem) -> Crumb:
    return Crumb(label_key=item.label_key, href=item.href)


Resolver = Callable[[Mapping[str, str], Mapping[str, Any]], NavState]


def _home(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("research", "overview", "page")


def _companies(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    section = "other_entities" if ctx.get("active_kind") == "other" else "companies"
    return NavState("research", section, "component")


def _themes(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("research", "themes", "component")


def _search(_q: Mapping[str, str], _ctx: Mapping[str, Any]) -> NavState:
    return NavState("research", "search", "page")


def _entity(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    owner = _COMPANIES if ctx.get("is_company") else _OTHER
    name = str(getattr(ctx.get("entity"), "name", ""))
    return NavState("research", owner.key, "component", [_ROOT, _crumb(owner), Crumb(label=name)])


def _theme(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    name = str(getattr(ctx.get("theme"), "name", ""))
    return NavState("research", "themes", "component", [_ROOT, _crumb(_THEMES), Crumb(label=name)])


_NOTES_BY_VIEW = {"company": _NOTES_BY_COMPANY, "author": _NOTES_BY_AUTHOR, "all": _NOTES_ALL}


def _catalog(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    view_mode = str(ctx.get("view_mode") or "company")
    group = ctx.get("active_group")
    note = ctx.get("active_note")

    if note:
        notes_item = _NOTES_BY_VIEW.get(view_mode, _NOTES_BY_COMPANY)
        crumbs = [_ROOT, _NOTES_ROOT, _crumb(notes_item)]
        if view_mode == "author" and group:
            crumbs.append(
                Crumb(
                    label=str(group.get("label", "")),
                    href=f"/catalog?view=author&author={quote(str(group.get('id', '')))}",
                )
            )
        elif view_mode == "company":
            crumbs.append(
                Crumb(
                    label=str(getattr(note, "subject_label", "")),
                    href=f"/catalog?view=company&dir={quote(str(getattr(note, 'folder', '')))}",
                )
            )
        crumbs.append(Crumb(label=str(getattr(note, "title", ""))))
        return NavState("research", notes_item.key, "component", crumbs)

    notes_item = _NOTES_BY_VIEW.get(view_mode, _NOTES_BY_COMPANY)
    if group and view_mode in ("author", "company"):
        crumbs = [_ROOT, _NOTES_ROOT, _crumb(notes_item), Crumb(label=str(group.get("label", "")))]
        return NavState("research", notes_item.key, "component", crumbs)

    return NavState("research", notes_item.key, "component")


_ONTOLOGY_TABS = {item.key for group in LEFT_NAV["ontology"] for item in group.items}


def _ontology(_q: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    tab = str(ctx.get("active_tab") or "entity")
    return NavState("ontology", tab if tab in _ONTOLOGY_TABS else "entity", "page")


NAV_ROUTES: dict[str, Resolver] = {
    "/": _home,
    "/companies": _companies,
    "/themes": _themes,
    "/search": _search,
    "/entity/{entity_id}": _entity,
    "/theme/{theme_id}": _theme,
    "/catalog": _catalog,
    "/ontology": _ontology,
}


def resolve_nav(route_path: str, query: Mapping[str, str], ctx: Mapping[str, Any]) -> NavState:
    """Return the navigation state for a registered route. Raises KeyError when unregistered."""
    return NAV_ROUTES[route_path](query, ctx)
