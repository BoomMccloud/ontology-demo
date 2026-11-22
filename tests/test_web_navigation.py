"""Decisive witness for the codified navigation UX (proposal `codified-navigation-ux`).

Render checks: every HTML route is in the navigation registry, every page marks exactly one
workflow in the top nav and exactly one section in the left nav, detail and drill-down views
render a breadcrumb from the workflow root, and the Ask Clippy dock is on every page.

Static checks: templates carry no inline styles, page templates extend `base.html`, partials
never extend it or emit shell navigation, and every literal class token is defined in
`library.css`. Ruff does not parse Jinja, so these checks live here.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from stock_ontology.config import Settings
from stock_ontology.web import create_app
from test_web import DIM, FakeWebLLM, _seed_web_db

WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "stock_ontology" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
CSS_PATH = WEB_DIR / "static" / "library.css"

NOTE_FILE = "NVDA/2026-10-15_q3.md"

# (url, workflow, section, last breadcrumb label or None when the view is not a drill-down)
VARIANTS: list[tuple[str, str, str, str | None]] = [
    ("/", "research", "overview", None),
    ("/companies", "research", "companies", None),
    ("/companies?kind=other", "research", "other_entities", None),
    ("/themes", "research", "themes", None),
    ("/catalog", "research", "notes_by_company", None),
    ("/catalog?view=company", "research", "notes_by_company", None),
    ("/catalog?view=author", "research", "notes_by_author", None),
    ("/catalog?view=person", "research", "notes_by_author", None),
    ("/catalog?view=all", "research", "notes_all", None),
    ("/catalog?view=company&dir=NVDA", "research", "notes_by_company", "NVIDIA"),
    ("/catalog?view=author&author=Kenji+Sato", "research", "notes_by_author", "Kenji Sato"),
    (f"/catalog?file={NOTE_FILE}", "research", "notes_by_company", "NVDA Q3 Preview"),
    (f"/catalog?view=all&file={NOTE_FILE}", "research", "notes_all", "NVDA Q3 Preview"),
    ("/search", "research", "search", None),
    ("/search?q=Blackwell", "research", "search", None),
    ("/entity/ent_nvda", "research", "companies", "NVIDIA"),
    ("/entity/ent_kenji", "research", "other_entities", "Kenji Sato"),
    ("/theme/thm_power", "research", "themes", "AI Data Center Power Bottleneck"),
    ("/ontology", "ontology", "entity", None),
    ("/ontology?tab=entity", "ontology", "entity", None),
    ("/ontology?tab=event", "ontology", "event", None),
    ("/ontology?tab=view", "ontology", "view", None),
    ("/ontology?tab=theme", "ontology", "theme", None),
    ("/ontology?tab=edges", "ontology", "edges", None),
    ("/ontology?tab=registry", "ontology", "registry", None),
    ("/ontology?tab=audit", "ontology", "audit", None),
]


class _NavParser(HTMLParser):
    """Collect aria-current markers per nav region and the breadcrumb items."""

    REGIONS = ("top-nav", "side-nav", "breadcrumb", "clippy-dock")

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.current: dict[str, list[str]] = {r: [] for r in self.REGIONS}
        self.seen: set[str] = set()
        self.ids: set[str] = set()
        self.body_attrs: dict[str, str] = {}
        self.crumbs: list[dict[str, object]] = []
        self._crumb: dict[str, object] | None = None

    def _region(self) -> str | None:
        for _tag, region in reversed(self.stack):
            if region:
                return region
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "body":
            self.body_attrs = a
        region = a.get("id") if a.get("id") in self.REGIONS else None
        if region:
            self.seen.add(region)
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.stack.append((tag, region))
        cur_region = region or self._region()
        if a.get("aria-current") == "page" and cur_region:
            self.current[cur_region].append(a.get("data-nav", a.get("id", tag)))
        if cur_region == "breadcrumb" and tag == "li":
            self._crumb = {"text": "", "link": False, "current": a.get("aria-current") == "page"}
            self.crumbs.append(self._crumb)
        if cur_region == "breadcrumb" and tag == "a" and self._crumb is not None:
            self._crumb["link"] = True
            self._crumb["href"] = a.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx:]
                break
        if tag == "li":
            self._crumb = None

    def handle_data(self, data: str) -> None:
        if self._crumb is not None:
            self._crumb["text"] = (str(self._crumb["text"]) + data).strip()


def _parse(text: str) -> _NavParser:
    parser = _NavParser()
    parser.feed(text)
    return parser


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "nav.db"
    _seed_web_db(db_path)
    data_dir = tmp_path / "data"
    (data_dir / "NVDA").mkdir(parents=True)
    (data_dir / "NVDA" / "2026-10-15_q3.md").write_text(
        "# NVDA Q3 Preview\n\n**Author:** Kenji Sato\n\nBlackwell rack ramp update.\n",
        encoding="utf-8",
    )
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    return TestClient(create_app(settings, llm=FakeWebLLM()))


def _html_get_routes(client: TestClient) -> set[str]:
    paths: set[str] = set()
    for route in client.app.routes:
        if isinstance(route, APIRoute) and "GET" in route.methods:
            response_class = getattr(route.response_class, "value", route.response_class)
            if isinstance(response_class, type) and issubclass(response_class, HTMLResponse):
                paths.add(route.path)
    return paths


def test_every_html_route_is_in_the_navigation_registry(client: TestClient) -> None:
    from stock_ontology.web.navigation import NAV_ROUTES

    html_routes = _html_get_routes(client)
    assert html_routes, "expected HTML GET routes"
    missing = html_routes - set(NAV_ROUTES)
    assert not missing, f"HTML routes missing from the navigation registry: {sorted(missing)}"
    stale = set(NAV_ROUTES) - html_routes
    assert not stale, f"registry entries without an HTML route: {sorted(stale)}"

    covered = {urlparse(url).path for url, *_ in VARIANTS}
    for path in html_routes:
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"
        assert any(re.match(pattern, p) for p in covered), f"no render variant covers {path}"


@pytest.mark.parametrize(("url", "workflow", "section", "last_crumb"), VARIANTS)
def test_page_marks_workflow_section_breadcrumb_and_dock(
    client: TestClient, url: str, workflow: str, section: str, last_crumb: str | None
) -> None:
    resp = client.get(url)
    assert resp.status_code == 200, url
    page = _parse(resp.text)

    assert {"top-nav", "side-nav", "clippy-dock"} <= page.seen, url
    assert page.current["top-nav"] == [workflow], url
    assert page.current["side-nav"] == [section], url
    assert page.body_attrs.get("data-archetype") in ("page", "component"), url

    # Ask Clippy dock on every page, wired to the existing client.
    assert {"clippy-launcher", "clippy-window", "clippy-form", "clippy-input", "clippy-messages"} <= page.ids
    assert '<script src="/static/clippy.js"></script>' in resp.text
    assert "portal-frame-wide" not in resp.text

    if last_crumb is None:
        assert "breadcrumb" not in page.seen, url
        return

    assert "breadcrumb" in page.seen, url
    crumbs = page.crumbs
    assert len(crumbs) >= 2, (url, crumbs)
    first, *middle, last = crumbs
    assert first["link"] is True and first["text"] == workflow.capitalize(), (url, crumbs)
    assert all(c["link"] is True and not c["current"] for c in middle), (url, crumbs)
    assert last["link"] is False and last["current"] is True, (url, crumbs)
    assert last["text"] == last_crumb, (url, crumbs)
    assert page.current["breadcrumb"] == ["li"], url


def test_ask_redirects_to_overview_with_clippy_open_and_context(client: TestClient) -> None:
    resp = client.get("/ask", params={"context": "Entity NVIDIA"}, follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    target = urlparse(resp.headers["location"])
    assert target.path == "/"
    query = parse_qs(target.query)
    assert query.get("ask") == ["1"]
    assert query.get("context") == ["Entity NVIDIA"]

    landed = client.get("/ask", params={"context": "Entity NVIDIA"})
    assert landed.status_code == 200
    assert 'data-open="1"' in landed.text
    assert 'data-context="Entity NVIDIA"' in landed.text
    page = _parse(landed.text)
    assert page.current["side-nav"] == ["overview"]


def test_ask_about_links_open_the_dock_with_page_context(client: TestClient) -> None:
    for url in ("/entity/ent_nvda", "/theme/thm_power"):
        text = client.get(url).text
        assert "data-clippy-context=" in text, url


def test_clippy_dock_chat_round_trip_uses_existing_backend(client: TestClient) -> None:
    r1 = client.post("/api/chat", json={"message": "Check NVDA", "page_context": "Entity NVIDIA"})
    assert r1.status_code == 200
    sid = r1.json()["session_id"]
    assert "buy" in r1.json()["reply"].lower()
    assert client.post("/api/chat/reset", json={"session_id": sid}).status_code == 200
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "Again"})
    assert "user turns=1" in r2.json()["reply"]


# ---------------------------------------------------------------------------
# Static template and CSS checks
# ---------------------------------------------------------------------------


def _templates() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def _css_classes() -> set[str]:
    css = re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(encoding="utf-8"), flags=re.S)
    return set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css))


def test_templates_have_no_inline_styles() -> None:
    offenders = []
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\sstyle\s*=|<style\b", text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(TEMPLATES_DIR)}:{line}")
    assert not offenders, f"inline styles found: {offenders}"


def test_page_templates_extend_base_and_partials_do_not() -> None:
    shell_markers = ('id="top-nav"', 'id="side-nav"', 'id="clippy-dock"', "portal-rail")
    for path in _templates():
        rel = path.relative_to(TEMPLATES_DIR)
        text = path.read_text(encoding="utf-8")
        if rel.parts[0] == "partials":
            assert "{% extends" not in text, f"{rel} must not extend a layout"
            for marker in shell_markers:
                assert marker not in text, f"{rel} emits shell navigation ({marker})"
        elif rel.name != "base.html":
            assert text.lstrip().startswith('{% extends "base.html" %}'), f"{rel} must extend base.html"


def test_every_literal_class_token_is_defined_in_library_css() -> None:
    defined = _css_classes()
    undefined: dict[str, set[str]] = {}
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        for attr in re.findall(r'\bclass="([^"]*)"', text):
            stripped = re.sub(r"\{\{.*?\}\}", "\x00", attr)
            stripped = re.sub(r"\{%.*?%\}", " ", stripped)
            for token in stripped.split():
                if "\x00" in token:
                    continue
                if token not in defined:
                    undefined.setdefault(token, set()).add(str(path.relative_to(TEMPLATES_DIR)))
    assert not undefined, f"class tokens not defined in library.css: {undefined}"


def test_one_desktop_width_and_one_mobile_breakpoint() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".portal-frame-wide" not in css
    frame_rule = re.search(r"\.portal-frame\s*\{([^}]*)\}", css)
    assert frame_rule is not None and "max-width: 1080px" in frame_rule.group(1)
    media = re.findall(r"@media\s*([^{]+)\{", css)
    assert media and all(m.strip() == "(max-width: 740px)" for m in media), media
    for path in _templates():
        assert "wide_layout" not in path.read_text(encoding="utf-8"), path


def test_navigation_registry_lookup() -> None:
    from stock_ontology.web.navigation import resolve_nav

    nav = resolve_nav("/entity/{entity_id}", {}, {"entity": {"name": "NVIDIA"}, "is_company": True})
    assert (nav.workflow, nav.section, nav.archetype) == ("research", "companies", "component")
    assert [c.label_key or c.label for c in nav.crumbs][-1] == "NVIDIA"

    nav = resolve_nav("/ontology", {"tab": "audit"}, {"active_tab": "audit"})
    assert (nav.workflow, nav.section, nav.archetype) == ("ontology", "audit", "page")
    assert nav.crumbs == []

    with pytest.raises(KeyError):
        resolve_nav("/not-registered", {}, {})
