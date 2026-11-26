"""Offline tests for the 1990s Library web UI, dynamic facet pages, and Clippy read-only chat.

Module-specific tests live in test_web_<module>.py; this file keeps tests that span modules."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from web_support import (
    DIM,
    FakeWebLLM,
    seed_web_db,
    unit_vec,
)

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import LANG_COOKIE_NAME, SUPPORTED_LANGUAGE_CODES, get_language_spec, translate
from stock_ontology.models import Edge, Node
from stock_ontology.web import create_app


def test_web_home_entity_theme_search_and_clippy_chat(tmp_path: Path) -> None:
    db_path = tmp_path / "web.db"
    seed_web_db(db_path)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    llm = FakeWebLLM()
    app = create_app(settings, llm=llm, agent_model=llm.model)
    client = TestClient(app)

    # 1. Home page: clean Two-Pane Library Portal (no decorative headings/colophon/floating Clippy).
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "<title>Stock Research Library</title>" in r_home.text
    assert "1990s" not in r_home.text
    assert "Read-only" not in r_home.text
    assert translate("home.product_desc", lang="en") in r_home.text
    # Top nav: workflows; left nav: Research sections; Ask only as the on-page Clippy dock.
    assert 'aria-current="page" data-nav="research">Research<' in r_home.text
    assert ">Ontology<" in r_home.text
    assert 'aria-current="page" data-nav="overview">&rsaquo; Overview<' in r_home.text
    assert ">Companies<" in r_home.text
    assert ">Themes<" in r_home.text
    assert ">Notes<" in r_home.text
    assert ">Search<" in r_home.text
    assert ">Ask<" not in r_home.text
    assert "Coverage Desk" not in r_home.text
    assert "Welcome to the Research Archive" not in r_home.text
    assert "Best viewed at" not in r_home.text
    assert 'id="clippy-dock"' in r_home.text
    assert "Ontology Clippy" not in r_home.text
    assert "NVIDIA" in r_home.text
    assert "TSMC" in r_home.text
    assert "AI Data Center Power Bottleneck" in r_home.text

    # 1b. Dedicated directory & Ask pages (/companies, /themes, /ask).
    r_companies = client.get("/companies")
    assert r_companies.status_code == 200
    assert "NVIDIA" in r_companies.text
    assert "TSMC" in r_companies.text
    assert "Kenji Sato" not in r_companies.text

    r_other = client.get("/companies", params={"kind": "other"})
    assert r_other.status_code == 200
    assert "Kenji Sato" in r_other.text

    r_themes_idx = client.get("/themes")
    assert r_themes_idx.status_code == 200
    assert "AI Data Center Power Bottleneck" in r_themes_idx.text

    # /ask redirects to Overview with the Clippy dock opened.
    r_ask = client.get("/ask")
    assert r_ask.status_code == 200
    assert str(r_ask.url).endswith("/?ask=1")
    assert 'data-open="1"' in r_ask.text
    assert "Mr. User" in r_ask.text
    assert "Ask Clippy" in r_ask.text
    assert "Check meeting note vs. consensus" in r_ask.text

    # 2. Company entity page: company facets + consensus pillars + dynamic custom_metric facet.
    r_nvda = client.get("/entity/ent_nvda")
    assert r_nvda.status_code == 200
    assert "Company Profile" in r_nvda.text
    assert "House Consensus View" in r_nvda.text
    assert "Hyperscaler capex &gt;20%" in r_nvda.text
    assert "Custom Metric" in r_nvda.text
    assert "42GW" in r_nvda.text
    assert "NVDA — Q3 (2026-10-15)" in r_nvda.text
    assert "NVDA/2026-10-15_q3.md" not in r_nvda.text
    assert "doc_1" not in r_nvda.text
    assert "Record ID:" not in r_nvda.text
    assert "custom_metric" not in r_nvda.text
    assert "id%3D" not in r_nvda.text
    assert "type%3D" not in r_nvda.text

    # 3. Person entity page: adapts cleanly using person partial + dynamic extra facet.
    r_person = client.get("/entity/ent_kenji")
    assert r_person.status_code == 200
    assert "Source / Analyst Profile" in r_person.text
    assert "supply_chain_engineer" in r_person.text
    assert "Liquid Cooling CDUs" in r_person.text
    assert "Company Profile" not in r_person.text

    # 4. Theme page: companies tied to the theme only.
    r_theme = client.get("/theme/thm_power")
    assert r_theme.status_code == 200
    assert "Mentioned in Notes" in r_theme.text
    assert "2nd-Order" not in r_theme.text
    assert "NVIDIA" in r_theme.text
    assert "TSMC" not in r_theme.text  # a supplier of an affected company, not listed
    assert "12-24m" in r_theme.text
    assert "Consensus: Buy NVIDIA" not in r_theme.text  # theme is consensus evidence, not its subject
    assert "Record ID:" not in r_theme.text
    assert "id%3D" not in r_theme.text

    # 5. Search page.
    r_search = client.get("/search", params={"q": "Blackwell"})
    assert r_search.status_code == 200
    assert "Blackwell Rack Ramp" in r_search.text
    assert "NVDA — Q3 (2026-10-15)" in r_search.text
    assert "NVDA/2026-10-15_q3.md" not in r_search.text

    r_search_empty = client.get("/search", params={"q": "nonexistent_xyz_term"})
    assert r_search_empty.status_code == 200
    assert "lower right" not in r_search_empty.text

    # 6. Health & Clippy read-only chat API with multi-turn session state & reset.
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["read_only"] is True
    before_stats = r_health.json()["stats"]

    r_chat1 = client.post(
        "/api/chat",
        json={"message": "Check NVDA consensus", "page_context": "Entity NVIDIA"},
    )
    assert r_chat1.status_code == 200
    body1 = r_chat1.json()
    sid = body1["session_id"]
    assert "bullish" in body1["reply"].lower()
    assert "user turns=1" in body1["reply"]
    assert body1["tools_used"] == ["get_entity_overview"]

    r_chat2 = client.post(
        "/api/chat",
        json={"session_id": sid, "message": "Follow up question"},
    )
    assert r_chat2.status_code == 200
    assert "user turns=2" in r_chat2.json()["reply"]

    r_reset = client.post("/api/chat/reset", json={"session_id": sid})
    assert r_reset.status_code == 200

    # Verify DB untouched after all web & chat operations.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        assert ro.get_stats() == before_stats
        assert ro.get_stats()["total_nodes"] == 7
        assert ro.get_stats()["total_edges"] == 9

    # 7. Missing entity/theme returns 404.
    assert client.get("/entity/missing").status_code == 404
    assert client.get("/theme/missing").status_code == 404


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGE_CODES)
def test_web_multilingual_pages_preserve_original_notes(tmp_path: Path, lang: str) -> None:
    db_path = tmp_path / f"web_i18n_{lang}.db"
    seed_web_db(db_path)

    data_dir = tmp_path / "data"
    nvda_dir = data_dir / "NVDA"
    nvda_dir.mkdir(parents=True)
    (nvda_dir / "2026-10-15_q3.md").write_text(
        "# NVDA Q3 Preview\n\nOriginal English note stays intact.\n",
        encoding="utf-8",
    )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    spec = get_language_spec(lang)

    # 1. Home page via ?lang=
    r_home = client.get("/", params={"lang": lang})
    assert r_home.status_code == 200
    assert f'<html lang="{spec["html_lang"]}">' in r_home.text
    assert f'data-lang="{lang}"' in r_home.text
    home_text = html.unescape(r_home.text)
    assert translate("home.product_desc", lang=lang) in home_text
    assert translate("rail.companies", lang=lang) in home_text
    assert translate("rail.themes", lang=lang) in home_text
    assert "badge-bullish" in r_home.text
    assert "badge-accelerating" in r_home.text
    assert "NVIDIA" in r_home.text

    # 1b. Companies, Themes, and Ask (/ask) via ?lang=
    r_companies = client.get("/companies", params={"lang": lang})
    assert r_companies.status_code == 200
    assert translate("companies.page_desc", lang=lang) in html.unescape(r_companies.text)
    assert "NVIDIA" in r_companies.text

    r_themes = client.get("/themes", params={"lang": lang})
    assert r_themes.status_code == 200
    assert translate("themes_index.page_desc", lang=lang) in html.unescape(r_themes.text)
    assert "AI Data Center Power Bottleneck" in r_themes.text

    r_ask = client.get("/ask", params={"lang": lang})
    assert r_ask.status_code == 200
    ask_text = html.unescape(r_ask.text)
    assert translate("ask.subtitle", lang=lang) in ask_text
    assert translate("clippy.send_btn", lang=lang) in ask_text

    # 2. Entity pages (company + person)
    r_nvda = client.get("/entity/ent_nvda", params={"lang": lang})
    assert r_nvda.status_code == 200
    nvda_text = html.unescape(r_nvda.text)
    assert translate("entity.company_profile", lang=lang) in nvda_text
    assert translate("consensus.heading", lang=lang) in nvda_text
    assert "Maintain Buy driven by hyperscaler capex." in r_nvda.text
    assert "42GW" in r_nvda.text
    assert "Hyperscaler capex &gt;20%" in r_nvda.text

    r_person = client.get("/entity/ent_kenji", params={"lang": lang})
    assert r_person.status_code == 200
    person_text = html.unescape(r_person.text)
    assert translate("entity.person_profile", lang=lang) in person_text
    assert "supply_chain_engineer" in r_person.text
    assert "Liquid Cooling CDUs" in r_person.text

    # 3. Theme page
    r_theme = client.get("/theme/thm_power", params={"lang": lang})
    assert r_theme.status_code == 200
    theme_text = html.unescape(r_theme.text)
    assert translate("theme.exposed_companies", lang=lang) in theme_text
    assert "AI Data Center Power Bottleneck" in r_theme.text

    # 4. Search page
    r_search = client.get("/search", params={"q": "Blackwell", "lang": lang})
    assert r_search.status_code == 200
    assert translate("search.advanced_toggle", lang=lang) in html.unescape(r_search.text)
    assert "Blackwell Rack Ramp" in r_search.text

    # 5. Catalog page (raw notes remain in original language; tabs localize cleanly)
    r_cat = client.get("/catalog", params={"file": "NVDA/2026-10-15_q3.md", "lang": lang})
    assert r_cat.status_code == 200
    assert translate("catalog.heading", lang=lang) in html.unescape(r_cat.text)
    assert "Original English note stays intact." in r_cat.text

    expected_by_author = translate("catalog.by_author", lang=lang, count=1)
    expected_all_notes = translate("catalog.all_notes", lang=lang, count=1)
    for params in ({}, {"view": "author"}, {"view": "all"}):
        r_tab = client.get("/catalog", params={**params, "lang": lang})
        assert r_tab.status_code == 200
        tab_text = html.unescape(r_tab.text)
        assert expected_by_author in tab_text
        assert expected_all_notes in tab_text
        assert "catalog.by_author" not in r_tab.text
        assert "catalog.all_notes" not in r_tab.text

    # 6. Ontology view page
    r_ont = client.get("/ontology", params={"tab": "entity", "lang": lang})
    assert r_ont.status_code == 200
    ont_text = html.unescape(r_ont.text)
    assert translate("ontology.structures_heading", lang=lang) in ont_text
    assert translate("ontology.struct_entity_title", lang=lang) in ont_text
    assert "custom_metric" in r_ont.text


def test_web_language_switching_cookie_header_chat_and_open_redirect_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "web_lang_switch.db"
    seed_web_db(db_path)

    llm = FakeWebLLM()
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=llm, agent_model=llm.model)
    client = TestClient(app)

    # 1. /api/health reports language metadata
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    health = r_health.json()
    assert health["default_language"] == "en"
    assert health["supported_languages"] == list(SUPPORTED_LANGUAGE_CODES)

    # 2. Accept-Language header auto-detection (no query/cookie)
    r_accept = client.get("/", headers={"Accept-Language": "de-DE;q=0.9, ko-KR;q=0.8"})
    assert r_accept.status_code == 200
    assert '<html lang="ko">' in r_accept.text
    assert translate("home.product_desc", lang="ko") in html.unescape(r_accept.text)

    # 3. /set-language sets cookie and strips stale lang= while preserving other params
    r_switch = client.get(
        "/set-language",
        params={"lang": "zh", "next": "/search?q=NVDA&lang=en"},
        follow_redirects=False,
    )
    assert r_switch.status_code == 303
    assert r_switch.headers["location"] == "/search?q=NVDA"
    assert LANG_COOKIE_NAME in r_switch.cookies

    # Subsequent request uses persisted cookie
    r_follow = client.get("/")
    assert r_follow.status_code == 200
    assert '<html lang="zh-CN">' in r_follow.text
    assert translate("home.product_desc", lang="zh") in html.unescape(r_follow.text)

    # 4. Open-redirect protection on /set-language
    for bad_next in ("https://evil.example/phish", "//evil.example/path", "javascript:alert(1)"):
        r_bad_next = client.get(
            "/set-language",
            params={"lang": "fr", "next": bad_next},
            follow_redirects=False,
        )
        assert r_bad_next.status_code == 303
        assert r_bad_next.headers["location"] == "/"

    # 5. POST /api/language valid + invalid
    r_api_lang = client.post("/api/language", json={"lang": "ja-JP"})
    assert r_api_lang.status_code == 200
    assert r_api_lang.json()["lang"] == "ja"

    r_api_bad = client.post("/api/language", json={"lang": "xx"})
    assert r_api_bad.status_code == 400

    # 6. POST /api/chat propagates language via cookie and explicit payload.lang
    r_chat_cookie = client.post("/api/chat", json={"message": "Check NVDA"})
    assert r_chat_cookie.status_code == 200
    assert r_chat_cookie.json()["lang"] == "ja"
    assert "Japanese" in llm.seen_system_instructions[-1]

    r_chat_body = client.post("/api/chat", json={"message": "Check NVDA", "lang": "es"})
    assert r_chat_body.status_code == 200
    assert r_chat_body.json()["lang"] == "es"
    assert "Spanish" in llm.seen_system_instructions[-1]


def test_web_clean_reader_pages_no_db_ids_plumbing_or_italic_markers(tmp_path: Path) -> None:
    db_path = tmp_path / "web_clean_reader.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        comp = Node(
            id="ent_acme_1234ab",
            node_type="entity",
            name="Acme Corp",
            summary="Cloud hardware vendor.",
            facets={"entity_type": "company", "ticker": "ACME"},
        )
        thm = Node(
            id="thm_edge_ai_9988cd",
            node_type="theme",
            name="Edge AI Buildout",
            summary="Distributed inference trend.",
            facets={"stage": "emerging"},
        )
        evt_bridge = Node(
            id="evt_bridge_7766ef",
            node_type="event",
            name="Bridge Launch Event",
            summary="Launched edge node.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-20",
                "status": "occurred",
                "source": {"file_path": "ACME/2026-11-20_launch.md"},
            },
            source_doc_id="doc_acme_1",
        )
        evt_docid_only = Node(
            id="evt_docid_only_5544aa",
            node_type="event",
            name="DocId Only Event",
            summary="Legacy observation without file_path.",
            facets={
                "event_type": "fact",
                "event_date": "2026-11-10",
                "source": {"doc_id": "doc_internal_secret_999"},
            },
            source_doc_id="doc_internal_secret_999",
        )
        for idx, n in enumerate([comp, thm, evt_bridge, evt_docid_only]):
            db.upsert_node(n, embedding=unit_vec(idx))
        db.upsert_edge(Edge(id="e1", from_id=evt_bridge.id, to_id=comp.id, relation="ABOUT", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e2", from_id=evt_bridge.id, to_id=thm.id, relation="SUPPORTS", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e3", from_id=evt_docid_only.id, to_id=comp.id, relation="ABOUT", facets={"basis": "extracted"}))

    data_dir = tmp_path / "data"
    acme_dir = data_dir / "ACME"
    acme_dir.mkdir(parents=True)
    (acme_dir / "2026-11-20_launch.md").write_text(
        "# Acme Edge Launch Note\n\n*As of November 21, 2026*\n\nFull details inside.\n",
        encoding="utf-8",
    )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))

    # Entity page resolves 1-hop via event by human name (never evt_... ID) and resolves disk note title
    r_ent = client.get(f"/entity/{comp.id}")
    assert r_ent.status_code == 200
    ent_visible = html.unescape(re.sub(r"<[^>]+>", " ", r_ent.text))
    assert "event: Bridge Launch Event" in ent_visible
    assert "via event" not in ent_visible
    assert evt_bridge.id not in ent_visible
    assert comp.id not in ent_visible
    assert "id%3D" not in r_ent.text
    assert "Acme Edge Launch Note" in ent_visible
    assert "ACME/2026-11-20_launch.md" not in ent_visible
    assert "doc_internal_secret_999" not in r_ent.text

    # Catalog excerpt strips single-asterisk markdown italics
    r_cat = client.get("/catalog")
    assert r_cat.status_code == 200
    assert "Acme Corp" in r_cat.text
    for params in ({"view": "company", "dir": "ACME"}, {"view": "all"}):
        r_list = client.get("/catalog", params=params)
        assert r_list.status_code == 200
        assert "As of November 21, 2026" in r_list.text
        assert "*As of November 21, 2026*" not in r_list.text

    # Theme page shows disk note title link and omits theme ID
    r_thm = client.get(f"/theme/{thm.id}")
    assert r_thm.status_code == 200
    thm_visible = html.unescape(re.sub(r"<[^>]+>", " ", r_thm.text))
    assert "Acme Edge Launch Note" in thm_visible
    assert thm.id not in thm_visible
    assert "id%3D" not in r_thm.text
