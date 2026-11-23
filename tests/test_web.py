"""Offline tests for the 1990s Library web UI, dynamic facet pages, and Clippy read-only chat."""

from __future__ import annotations

import dataclasses
import html
import math
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from stock_ontology.audit import run_ontology_audit
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import LANG_COOKIE_NAME, SUPPORTED_LANGUAGE_CODES, get_language_spec, translate
from stock_ontology.llm import AgentTurn, ToolCall
from stock_ontology.models import ConsensusSynthesis, Edge, ExtractionResult, Node
from stock_ontology.registry import create_minimal_registry, save_registry
from stock_ontology.web import create_app

DIM = 16


def _unit_vec(idx: int) -> list[float]:
    vec = [0.0] * DIM
    vec[idx % DIM] = 1.0
    return vec


def _seed_web_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU and NVLink rack platform leader.",
            aliases=["NVDA"],
            facets={
                "entity_type": "company",
                "ticker": "NVDA",
                "sector": "Semiconductors",
                "custom_metric": "42GW",
            },
        )
        tsmc = Node(
            id="ent_tsmc",
            node_type="entity",
            name="TSMC",
            summary="Leading-edge foundry and CoWoS supplier.",
            aliases=["TSM"],
            facets={"entity_type": "company", "ticker": "TSM", "sector": "Semiconductors"},
        )
        kenji = Node(
            id="ent_kenji",
            node_type="entity",
            name="Kenji Sato",
            summary="Senior thermal engineer at Taiwan ODM.",
            facets={
                "entity_type": "person",
                "role": "supply_chain_engineer",
                "organization": "Taiwan ODM",
                "credibility": "high",
                "specialty": "Liquid Cooling CDUs",
            },
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power and rack cooling density constraints.",
            facets={"stage": "accelerating", "horizon": "12-24m"},
        )
        ev = Node(
            id="evt_q3",
            node_type="event",
            name="Blackwell Rack Ramp",
            summary="GB200 NVL72 shipping in Q4.",
            facets={
                "event_type": "fact",
                "event_date": "2026-10-15",
                "status": "occurred",
                "source": {"file_path": "NVDA/2026-10-15_q3.md"},
            },
            source_doc_id="doc_1",
        )
        vw = Node(
            id="vw_analyst",
            node_type="view",
            name="Morgan Buy View",
            summary="Buy on CUDA moat.",
            facets={
                "view_type": "analyst_report",
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-10-15",
                "source": {"file_path": "NVDA/2026-10-15_q3.md"},
            },
            source_doc_id="doc_1",
        )
        cons = Node(
            id="vw_cons_nvda",
            node_type="view",
            name="Consensus: Buy NVIDIA",
            summary="Maintain Buy driven by hyperscaler capex.",
            facets={
                "view_type": "consensus",
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-11-20",
                "pillars": ["Hyperscaler capex >20%", "Rack thermal issues stay localized"],
            },
        )

        for idx, n in enumerate([nvda, tsmc, kenji, theme, ev, vw]):
            db.upsert_node(n, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="vw_analyst", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed5", from_id="evt_q3", to_id="ent_kenji", relation="AUTHORED_BY", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_consensus_view("ent_nvda", cons, _unit_vec(7), ["evt_q3", "vw_analyst", "thm_power"], [])


class FakeWebLLM:
    def __init__(self) -> None:
        self.seen_system_instructions: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vec(0) for _ in texts]

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        self.seen_system_instructions.append(system_instruction)
        last = messages[-1]
        if last["role"] == "user":
            return AgentTurn(
                tool_calls=[ToolCall(name="get_entity_overview", args={"entity_name_or_id": "NVDA"})]
            )
        if last["role"] == "tool":
            payload = last["responses"][0]["response"]
            stance = payload["consensus"]["facets"]["stance"]
            prior_turns = sum(1 for m in messages if m["role"] == "user")
            return AgentTurn(
                text=f"NVDA consensus is {stance}. Conversation user turns={prior_turns}."
            )
        return AgentTurn(text="Ready.")


def test_web_home_entity_theme_search_and_clippy_chat(tmp_path: Path) -> None:
    db_path = tmp_path / "web.db"
    _seed_web_db(db_path)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
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

    # 4. Theme page: affected companies only.
    r_theme = client.get("/theme/thm_power")
    assert r_theme.status_code == 200
    assert "Affected Companies" in r_theme.text
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
    assert "buy" in body1["reply"].lower()
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


def test_web_renders_sentiment_badges_and_edge_overrides(tmp_path: Path) -> None:
    db_path = tmp_path / "web_sentiment.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Consumer devices.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        qcom = Node(
            id="ent_qcom",
            node_type="entity",
            name="Qualcomm",
            summary="Mobile modem supplier.",
            aliases=["QCOM"],
            facets={"entity_type": "company", "ticker": "QCOM"},
        )
        theme = Node(
            id="thm_edge",
            node_type="theme",
            name="Custom Silicon Transition",
            summary="In-house modem shift.",
            facets={"stage": "accelerating"},
        )
        evt_modem = Node(
            id="evt_modem",
            node_type="event",
            name="In-House Modem Launch",
            summary="Apple switches to internal modem.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-18",
                "status": "occurred",
                "sentiment": "mixed",
                "source": {"file_path": "AAPL/2026-11-18_modem.md"},
            },
            source_doc_id="doc_1",
        )
        vw_rumor = Node(
            id="vw_rumor",
            node_type="view",
            name="Modem Loss Rumor",
            summary="Channel rumor warns on QCOM share loss.",
            facets={
                "view_type": "rumor",
                "stance": "cautious",
                "sentiment": "negative",
                "support_strength": "weak",
                "conviction": "medium",
                "as_of": "2026-11-19",
                "source": {"file_path": "QCOM/2026-11-19_rumor.md"},
            },
            source_doc_id="doc_2",
        )
        evt_legacy = Node(
            id="evt_legacy",
            node_type="event",
            name="Legacy Product Fact",
            summary="Earlier unannotated observation.",
            facets={
                "event_type": "fact",
                "event_date": "2026-09-01",
                "status": "occurred",
                "source": {"file_path": "AAPL/2026-09-01_old.md"},
            },
            source_doc_id="doc_0",
        )

        for idx, n in enumerate([aapl, qcom, theme, evt_modem, vw_rumor, evt_legacy]):
            db.upsert_node(n, embedding=_unit_vec(idx))

        db.upsert_edge(
            Edge(
                id="ed_aapl",
                from_id="evt_modem",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_qcom",
                from_id="evt_modem",
                to_id="ent_qcom",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(id="ed_thm", from_id="evt_modem", to_id="thm_edge", relation="RELATES_TO", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed_vw", from_id="vw_rumor", to_id="ent_qcom", relation="ABOUT", source_doc_id="doc_2", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed_leg", from_id="evt_legacy", to_id="ent_aapl", relation="ABOUT", source_doc_id="doc_0", facets={"basis": "extracted"})
        )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    r_ask = client.get("/ask")
    assert r_ask.status_code == 200
    assert "Count negative news &amp; rumors" in r_ask.text

    r_aapl = client.get("/entity/ent_aapl")
    assert r_aapl.status_code == 200
    assert "badge-positive" in r_aapl.text
    assert "entity impact (overall: mixed)" in r_aapl.text
    assert "Legacy Product Fact" in r_aapl.text

    r_qcom = client.get("/entity/ent_qcom")
    assert r_qcom.status_code == 200
    assert "badge-negative" in r_qcom.text
    assert "entity impact (overall: mixed)" in r_qcom.text

    r_theme = client.get("/theme/thm_edge")
    assert r_theme.status_code == 200
    assert "badge-mixed" in r_theme.text


def test_web_nav_and_advanced_search_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "web_adv_search.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Consumer devices.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        qcom = Node(
            id="ent_qcom",
            node_type="entity",
            name="Qualcomm",
            summary="Mobile modem supplier.",
            aliases=["QCOM"],
            facets={"entity_type": "company", "ticker": "QCOM"},
        )
        evt_modem = Node(
            id="evt_modem",
            node_type="event",
            name="In-House Modem Launch",
            summary="Apple switches to internal modem.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-18",
                "status": "occurred",
                "sentiment": "mixed",
                "source": {"file_path": "AAPL/2026-11-18_modem.md"},
            },
            source_doc_id="doc_1",
        )
        vw_rumor = Node(
            id="vw_rumor",
            node_type="view",
            name="Modem Loss Rumor",
            summary="Channel rumor warns on QCOM share loss.",
            facets={
                "view_type": "rumor",
                "stance": "cautious",
                "sentiment": "negative",
                "support_strength": "weak",
                "conviction": "medium",
                "as_of": "2026-11-19",
                "source": {"file_path": "QCOM/2026-11-19_rumor.md"},
            },
            source_doc_id="doc_2",
        )
        evt_legacy = Node(
            id="evt_legacy",
            node_type="event",
            name="Legacy Product Fact",
            summary="Earlier unannotated observation.",
            facets={
                "event_type": "fact",
                "event_date": "2026-09-01",
                "status": "occurred",
                "source": {"file_path": "AAPL/2026-09-01_old.md"},
            },
            source_doc_id="doc_0",
        )
        for idx, n in enumerate([aapl, qcom, evt_modem, vw_rumor, evt_legacy]):
            db.upsert_node(n, embedding=_unit_vec(idx))
        db.upsert_edge(
            Edge(
                id="ed_aapl",
                from_id="evt_modem",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_qcom",
                from_id="evt_modem",
                to_id="ent_qcom",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(id="ed_vw", from_id="vw_rumor", to_id="ent_qcom", relation="ABOUT", source_doc_id="doc_2", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed_leg", from_id="evt_legacy", to_id="ent_aapl", relation="ABOUT", source_doc_id="doc_0", facets={"basis": "extracted"})
        )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # Left rail navigation on 1997 portal + minimal / (no 8-field advanced-search-panel on /).
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert 'aria-current="page" data-nav="overview">&rsaquo; Overview<' in r_home.text
    assert ">Companies<" in r_home.text
    assert ">Themes<" in r_home.text
    assert ">Notes<" in r_home.text
    assert ">Ontology<" in r_home.text
    assert ">Search<" in r_home.text
    assert "advanced-search-panel" not in r_home.text
    assert 'id="rail-q"' in r_home.text

    # /search expands the integrated Advanced Search panel
    r_search_blank = client.get("/search")
    assert r_search_blank.status_code == 200
    assert ">Overview<" in r_search_blank.text
    assert '<details class="advanced-search-panel" open>' in r_search_blank.text

    # Filter-only searches (empty q)
    r_neg = client.get("/search", params={"sentiment": "negative"})
    assert r_neg.status_code == 200
    assert "Modem Loss Rumor" in r_neg.text
    assert "Legacy Product Fact" not in r_neg.text

    r_rumor = client.get("/search", params={"node_type": "view", "subtype": "rumor", "stance": "cautious"})
    assert r_rumor.status_code == 200
    assert "Modem Loss Rumor" in r_rumor.text
    assert "In-House Modem Launch" not in r_rumor.text

    # Entity-specific sentiment edge override filtering
    r_aapl_pos = client.get("/search", params={"entity_id": "ent_aapl", "sentiment": "positive"})
    assert r_aapl_pos.status_code == 200
    assert "In-House Modem Launch" in r_aapl_pos.text

    r_qcom_neg = client.get("/search", params={"entity_id": "ent_qcom", "sentiment": "negative"})
    assert r_qcom_neg.status_code == 200
    assert "In-House Modem Launch" in r_qcom_neg.text
    assert "Modem Loss Rumor" in r_qcom_neg.text

    # Date range + source file + keyword-only mode
    r_date = client.get(
        "/search",
        params={"q": "Legacy", "date_from": "2026-08-01", "date_to": "2026-09-30", "source_file": "AAPL/", "search_mode": "keyword"},
    )
    assert r_date.status_code == 200
    assert "Legacy Product Fact" in r_date.text
    assert "In-House Modem Launch" not in r_date.text
    assert "keyword" in r_date.text


def test_web_catalog_screen_by_company_and_person_and_safety(tmp_path: Path) -> None:
    db_path = tmp_path / "web_catalog.db"
    _seed_web_db(db_path)

    # Add a corporate CEO (must be excluded from By Author) and a research analyst
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        ceo = Node(
            id="ent_jensen_ceo",
            node_type="entity",
            name="Jensen Huang",
            summary="CEO of NVIDIA.",
            facets={"entity_type": "person", "role": "CEO", "organization": "NVIDIA"},
        )
        analyst = Node(
            id="ent_stacy_analyst",
            node_type="entity",
            name="Stacy Rasgon",
            summary="Semiconductor analyst.",
            facets={"entity_type": "person", "role": "Analyst", "organization": "Bernstein"},
        )
        db.upsert_node(ceo, embedding=_unit_vec(8))
        db.upsert_node(analyst, embedding=_unit_vec(9))
        db.upsert_edge(
            Edge(
                id="ed_ceo_authored",
                from_id="evt_q3",
                to_id="ent_jensen_ceo",
                relation="AUTHORED_BY",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_analyst_authored",
                from_id="vw_analyst",
                to_id="ent_stacy_analyst",
                relation="AUTHORED_BY",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )

    data_dir = tmp_path / "data"
    nvda_dir = data_dir / "NVDA"
    tsmc_dir = data_dir / "TSMC"
    nvda_dir.mkdir(parents=True)
    tsmc_dir.mkdir(parents=True)

    nvda_note = (
        "# NVDA Q3 Preview\n\n"
        "Blackwell rack ramp <script>alert(1)</script> update.\n\n"
        "| Metric | Value |\n"
        "| :--- | :--- |\n"
        "| Growth | Strong<br>Sequential |\n\n"
        "- Point one with **bold**\n"
    )
    (nvda_dir / "2026-10-15_q3.md").write_text(nvda_note, encoding="utf-8")
    (tsmc_dir / "2026-11-05_note.md").write_text(
        "# TSMC CoWoS Note\n\n**Author:** Internal Semi Desk\n\nField call with Kenji Sato on CoWoS packaging capacity.\n",
        encoding="utf-8",
    )
    # Files that must NEVER be served
    (data_dir / ".hidden.md").write_text("secret hidden", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside data dir", encoding="utf-8")

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # 1. Default Catalog view (Option 1 Company root: single-pane, no 2nd sidebar, no file duplication)
    r_cat = client.get("/catalog")
    assert r_cat.status_code == 200
    assert "Research Notes" in r_cat.text
    assert "NVIDIA" in r_cat.text
    assert "TSMC" in r_cat.text
    assert "By Company (2)" in r_cat.text
    assert "By Author (3)" in r_cat.text
    assert "All Notes (2)" in r_cat.text
    assert "NVDA Q3 Preview" not in r_cat.text
    assert "TSMC CoWoS Note" not in r_cat.text
    assert "portal-frame-wide" not in r_cat.text
    assert "catalog-explorer" not in r_cat.text
    assert "dir-tree" not in r_cat.text
    assert "[DIR]" not in r_cat.text
    assert "[UP]" not in r_cat.text
    assert "Index:" in r_cat.text
    assert "data/NVDA/" not in r_cat.text
    assert "INGESTED" not in r_cat.text
    assert "synced with DB" not in r_cat.text
    assert "ev /" not in r_cat.text

    # 1a. Company quick-filter Index bar
    r_co_alpha = client.get("/catalog", params={"view": "company", "alpha": "N"})
    assert r_co_alpha.status_code == 200
    assert "NVIDIA" in r_co_alpha.text
    assert "TSMC" not in r_co_alpha.text

    # 1b. Company directory drill-down (top breadcrumb, no ../ row, only that folder's notes)
    r_nvda_dir = client.get("/catalog", params={"view": "company", "dir": "NVDA"})
    assert r_nvda_dir.status_code == 200
    assert "catalog-path-bar" in r_nvda_dir.text
    assert "../" not in r_nvda_dir.text
    assert "[UP]" not in r_nvda_dir.text
    assert "NVDA Q3 Preview" in r_nvda_dir.text
    assert "TSMC CoWoS Note" not in r_nvda_dir.text

    # 2. Catalog By Author view (includes analysts & explicit note authors, excludes CEOs)
    r_author = client.get("/catalog", params={"view": "author"})
    assert r_author.status_code == 200
    assert "[DIR]" not in r_author.text
    assert "Index:" in r_author.text
    assert "Kenji Sato" in r_author.text
    assert "Stacy Rasgon" in r_author.text
    assert "Internal Semi Desk" in r_author.text
    assert "Jensen Huang" not in r_author.text

    # 2a. Author quick-filter Index bar
    r_auth_alpha = client.get("/catalog", params={"view": "author", "alpha": "S"})
    assert r_auth_alpha.status_code == 200
    assert "Stacy Rasgon" in r_auth_alpha.text
    assert "Kenji Sato" not in r_auth_alpha.text

    # Backward-compatible ?view=person alias
    r_person = client.get("/catalog", params={"view": "person"})
    assert r_person.status_code == 200
    assert "Stacy Rasgon" in r_person.text
    assert "Jensen Huang" not in r_person.text

    # Drill-down into an author shows top breadcrumb (no ../ row) and both authored and mentioned notes
    r_kenji = client.get("/catalog", params={"view": "author", "author": "Kenji Sato"})
    assert r_kenji.status_code == 200
    assert "catalog-path-bar" in r_kenji.text
    assert "../" not in r_kenji.text
    assert "[UP]" not in r_kenji.text
    assert "NVDA Q3 Preview" in r_kenji.text
    assert "TSMC CoWoS Note" in r_kenji.text
    # How a note was matched to its author is internal; the page doesn't show it.
    assert "badge-reason" not in r_kenji.text

    # 2b. All Notes flat index + quick-filter Index bar
    r_all = client.get("/catalog", params={"view": "all"})
    assert r_all.status_code == 200
    assert "Index:" in r_all.text
    assert "NVDA Q3 Preview" in r_all.text
    assert "TSMC CoWoS Note" in r_all.text

    r_all_alpha = client.get("/catalog", params={"view": "all", "alpha": "T"})
    assert r_all_alpha.status_code == 200
    assert "TSMC CoWoS Note" in r_all_alpha.text
    assert "NVDA Q3 Preview" not in r_all_alpha.text

    # 3. Safe Markdown rendered note view (XSS escaped, full-width reading pane)
    r_note = client.get("/catalog", params={"file": "NVDA/2026-10-15_q3.md"})
    assert r_note.status_code == 200
    assert "<h1>NVDA Q3 Preview</h1>" in r_note.text
    assert '<table class="catalog-table note-table">' in r_note.text
    assert "Strong<br>Sequential" in r_note.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r_note.text
    assert "<script>alert(1)</script>" not in r_note.text
    assert "Raw Source" not in r_note.text
    assert "Jensen Huang" not in r_note.text

    # 4. Raw source format toggle
    r_raw = client.get("/catalog", params={"file": "NVDA/2026-10-15_q3.md", "format": "raw"})
    assert r_raw.status_code == 200
    assert '<pre class="note-raw-pre">' in r_raw.text
    assert "# NVDA Q3 Preview" in r_raw.text

    # 5. Path traversal and hidden file blocks -> 404
    for bad_path in ("../secret.txt", "/etc/passwd", ".hidden.md", "missing.md", "NVDA\\2026-10-15_q3.md"):
        assert client.get("/catalog", params={"file": bad_path}).status_code == 404

    # 6. Graceful empty state when data_dir does not exist
    missing_settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path / "no_such_dir")
    missing_client = TestClient(create_app(missing_settings, llm=FakeWebLLM()))
    r_empty = missing_client.get("/catalog")
    assert r_empty.status_code == 200
    assert "No Research Notes Found" in r_empty.text
    assert "stock-ontology ingest" not in r_empty.text


def test_web_ontology_view_screen_4_structures_and_tabs(tmp_path: Path) -> None:
    db_path = tmp_path / "web_ontology.db"
    _seed_web_db(db_path)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        before_stats = ro.get_stats()

    # Default /ontology screen (Entity tab + 4 structure cards + SVG blueprint)
    r_ont = client.get("/ontology")
    assert r_ont.status_code == 200
    assert "4-Node Stock Ontology &amp; Unified Edges" in r_ont.text
    assert "<svg" in r_ont.text
    assert "1. Entity" in r_ont.text
    assert "2. Event" in r_ont.text
    assert "3. View" in r_ont.text
    assert "4. Theme" in r_ont.text
    assert "NVIDIA" in r_ont.text
    assert "custom_metric" in r_ont.text

    # Subtype filter on entity tab
    r_ont_person = client.get("/ontology", params={"tab": "entity", "subtype": "person"})
    assert r_ont_person.status_code == 200
    assert "Kenji Sato" in r_ont_person.text
    assert "ent_nvda" not in r_ont_person.text

    # Other structure tabs + Unified Edges tab
    r_event = client.get("/ontology", params={"tab": "event"})
    assert r_event.status_code == 200
    assert "Blackwell Rack Ramp" in r_event.text

    r_view = client.get("/ontology", params={"tab": "view"})
    assert r_view.status_code == 200
    assert "Morgan Buy View" in r_view.text
    assert "Consensus: Buy NVIDIA" in r_view.text

    r_theme = client.get("/ontology", params={"tab": "theme"})
    assert r_theme.status_code == 200
    assert "AI Data Center Power Bottleneck" in r_theme.text

    r_edges = client.get("/ontology", params={"tab": "edges"})
    assert r_edges.status_code == 200
    assert "Edge Schema Triples" in r_edges.text
    assert "SUPPLIES_TO" in r_edges.text
    assert "AUTHORED_BY" in r_edges.text

    # Strictly read-only verification
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        assert ro.get_stats() == before_stats


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGE_CODES)
def test_web_multilingual_pages_preserve_original_notes(tmp_path: Path, lang: str) -> None:
    db_path = tmp_path / f"web_i18n_{lang}.db"
    _seed_web_db(db_path)

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
    assert "badge-buy" in r_home.text
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
    assert translate("theme.affected_companies", lang=lang) in theme_text
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
    r_ont = client.get("/ontology", params={"lang": lang})
    assert r_ont.status_code == 200
    ont_text = html.unescape(r_ont.text)
    assert translate("ontology.structures_heading", lang=lang) in ont_text
    assert translate("ontology.struct_entity_title", lang=lang) in ont_text
    assert "custom_metric" in r_ont.text


def test_web_language_switching_cookie_header_chat_and_open_redirect_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "web_lang_switch.db"
    _seed_web_db(db_path)

    llm = FakeWebLLM()
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=llm)
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


def _norm_vec(values: list[float]) -> list[float]:
    padded = list(values) + [0.0] * (DIM - len(values))
    norm = math.sqrt(sum(x * x for x in padded)) or 1.0
    return [x / norm for x in padded]


def test_web_ontology_view_connected_to_registry_and_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "web_reg_ontology.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA", "sector": "Semiconductors"},
        )
        vrt = Node(
            id="ent_vrt",
            node_type="entity",
            name="Vertiv",
            summary="Liquid cooling provider.",
            aliases=["VRT"],
            facets={"entity_type": "company", "ticker": "NYSE: VRT"},
        )
        amd = Node(
            id="ent_amd",
            node_type="entity",
            name="AMD",
            summary="Data center GPU challenger.",
            facets={"entity_type": "company", "ticker": "AMD"},
        )
        dell = Node(
            id="ent_dell",
            node_type="entity",
            name="Dell",
            summary="Server OEM.",
            aliases=["HPE"],
            facets={"entity_type": "company"},
        )
        kenji = Node(
            id="ent_kenji",
            node_type="entity",
            name="Kenji Sato",
            summary="Thermal engineer.",
            facets={"entity_type": "person", "role": "engineer"},
        )
        blackwell = Node(
            id="ent_blackwell",
            node_type="entity",
            name="Blackwell GPU",
            summary="Data center GPU.",
            facets={"entity_type": "product"},
        )
        thm_official_alias = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Rack power and cooling constraints.",
            facets={"stage": "accelerating"},
        )
        thm_unmapped_close = Node(
            id="thm_grid",
            node_type="theme",
            name="Grid-to-Chip Power & Thermal Enablement",
            summary="Utility power and thermal integration.",
            facets={"stage": "accelerating"},
        )
        ev_q3 = Node(
            id="evt_q3",
            node_type="event",
            name="Q3 Earnings",
            summary="Strong data center growth.",
            facets={"event_type": "earnings", "status": "occurred"},
            source_doc_id="doc_1",
        )
        vw_note = Node(
            id="vw_note",
            node_type="view",
            name="Desk Buy Note",
            summary="Bullish GPU demand.",
            facets={
                "view_type": "analyst_report",
                "stance": "buy",
                "catalyst_to_watch": "Rubin ramp",
            },
            source_doc_id="doc_1",
        )

        nodes_vecs = [
            (nvda, _unit_vec(0)),
            (vrt, _unit_vec(1)),
            (amd, _unit_vec(2)),
            (dell, _unit_vec(3)),
            (kenji, _unit_vec(4)),
            (blackwell, _unit_vec(5)),
            (thm_official_alias, _norm_vec([1.0, 0.0, 0.0])),
            (thm_unmapped_close, _norm_vec([0.96, 0.28, 0.0])),
            (ev_q3, _unit_vec(8)),
            (vw_note, _unit_vec(9)),
        ]
        for node, vec in nodes_vecs:
            db.upsert_node(node, embedding=vec)

        for edge in (
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="ed2", from_id="vw_note", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="ed3", from_id="ent_vrt", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"}),
            Edge(id="ed4", from_id="ent_vrt", to_id="ent_nvda", relation="COMPETES_WITH", facets={"basis": "extracted"}),
            Edge(id="ed5", from_id="ent_nvda", to_id="ent_kenji", relation="HAS_EMPLOYEE", facets={"basis": "extracted"}),
            Edge(id="ed6", from_id="ent_nvda", to_id="ent_kenji", relation="WORKS_AT", facets={"basis": "extracted"}),
            Edge(id="ed7", from_id="thm_power", to_id="ent_vrt", relation="BENEFITS_FROM", facets={"basis": "extracted"}),
            Edge(id="ed8", from_id="ent_nvda", to_id="ent_blackwell", relation="PRODUCES", facets={"basis": "extracted"}),
        ):
            db.upsert_edge(edge)

    reg_path = tmp_path / "ontology_registry.json"
    reg = create_minimal_registry()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        audit_rep = run_ontology_audit(ro, reg)
        before_stats = ro.get_stats()
    reg.sync_suggestions(
        audit_rep.unmapped_relations,
        audit_rep.unmapped_companies,
        audit_rep.unmapped_themes,
    )
    save_registry(reg, reg_path)
    reg_before_bytes = reg_path.read_bytes()

    settings = Settings(
        db_path=db_path,
        embedding_dim=DIM,
        data_dir=tmp_path,
        registry_path=reg_path,
    )
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # 1. /api/health reports loaded registry metadata & pending suggestion counts.
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    health_reg = r_health.json()["registry"]
    assert health_reg["loaded"] is True
    assert health_reg["official_relations"] == 11
    assert health_reg["pending_suggestions"] == {"relations": 1, "companies": 2, "themes": 1}

    # 2. /ontology renders Registry overview KPIs, badges, and bidirectional SVG entity<->theme count.
    r_ont = client.get("/ontology")
    assert r_ont.status_code == 200
    assert "REGISTRY v1" in r_ont.text
    assert "Official Ontology Registry &amp; Live Audit" in r_ont.text
    assert "OFFICIAL" in r_ont.text
    assert "UNMAPPED" in r_ont.text
    assert "BENEFITS_FROM ↔ (1)" in html.unescape(r_ont.text)

    # 3. Registry status filter on entity tab (official vs unmapped).
    r_ent_off = client.get("/ontology", params={"tab": "entity", "reg_status": "official"})
    assert r_ent_off.status_code == 200
    assert "ent_nvda" in r_ent_off.text
    assert "ent_amd" not in r_ent_off.text

    r_ent_unm = client.get("/ontology", params={"tab": "entity", "reg_status": "unmapped"})
    assert r_ent_unm.status_code == 200
    assert "ent_amd" in r_ent_unm.text
    assert "ent_nvda" not in r_ent_unm.text

    # 4. Theme tab shows aliased official mapping and unmapped nearest-official cosine distance.
    r_thm = client.get("/ontology", params={"tab": "theme"})
    assert r_thm.status_code == 200
    assert "AI Data Center Power &amp; Cooling" in r_thm.text
    assert "Grid-to-Chip Power &amp; Thermal Enablement" in r_thm.text
    assert "d=" in r_thm.text

    # 5. Edges tab shows OFFICIAL, ALIAS, INVERSE (HAS_EMPLOYEE), REVERSED (WORKS_AT), UNMAPPED (PRODUCES).
    r_edges = client.get("/ontology", params={"tab": "edges"})
    assert r_edges.status_code == 200
    for badge_text in ("OFFICIAL", "ALIAS", "INVERSE", "REVERSED", "UNMAPPED"):
        assert badge_text in r_edges.text
    assert "COMPETES_WITH" in r_edges.text
    assert "HAS_EMPLOYEE" in r_edges.text
    assert "PRODUCES" in r_edges.text

    # 6. Official Registry tab lists official definitions + live DB match links.
    r_reg = client.get("/ontology", params={"tab": "registry"})
    assert r_reg.status_code == 200
    assert "Official Edge Relations (11)" in r_reg.text
    assert "BUY" in r_reg.text
    assert "WORKS_AT" in r_reg.text
    assert "/entity/ent_nvda" in r_reg.text
    assert "/entity/ent_vrt" in r_reg.text
    assert "/theme/thm_power" in r_reg.text
    assert "catalyst_to_watch" in r_reg.text

    # 7. Audit & Suggestions tab lists unmapped items, reversed edges, suspicious aliases, ticker & facet drift.
    r_audit = client.get("/ontology", params={"tab": "audit"})
    assert r_audit.status_code == 200
    assert "PRODUCES" in r_audit.text
    assert "AMD" in r_audit.text
    assert "Grid-to-Chip Power &amp; Thermal Enablement" in r_audit.text
    assert "reversed_direction" in r_audit.text
    assert "HPE" in r_audit.text
    assert "NYSE: VRT" in r_audit.text
    assert "catalyst_to_watch" in r_audit.text

    # 8. Missing registry graceful fallback.
    missing_settings = Settings(
        db_path=db_path,
        embedding_dim=DIM,
        data_dir=tmp_path,
        registry_path=tmp_path / "missing_registry.json",
    )
    missing_client = TestClient(create_app(missing_settings, llm=FakeWebLLM()))
    assert missing_client.get("/ontology").status_code == 200
    assert "NO REGISTRY" in missing_client.get("/ontology").text
    assert missing_client.get("/ontology", params={"tab": "registry"}).status_code == 200
    assert missing_client.get("/ontology", params={"tab": "audit"}).status_code == 200
    r_missing_health = missing_client.get("/api/health")
    assert r_missing_health.status_code == 200
    assert r_missing_health.json()["registry"]["loaded"] is False

    # 9. DB stats and ontology_registry.json remain completely untouched.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        assert ro.get_stats() == before_stats
    assert reg_path.read_bytes() == reg_before_bytes


def test_web_1997_home_minimal_link_cap(tmp_path: Path) -> None:
    db_path = tmp_path / "web_minimal_cap.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        for idx in range(12):
            comp = Node(
                id=f"ent_co_{idx:02d}",
                node_type="entity",
                name=f"Company {idx:02d}",
                summary=f"Summary for company {idx:02d}",
                facets={"entity_type": "company", "ticker": f"TK{idx:02d}"},
            )
            db.upsert_node(comp, embedding=_unit_vec(idx))
            if idx < 6:
                cons = Node(
                    id=f"vw_cons_{idx:02d}",
                    node_type="view",
                    name=f"Consensus: Buy Company {idx:02d}",
                    summary="Buy thesis.",
                    facets={
                        "view_type": "consensus",
                        "stance": "buy",
                        "conviction": "high",
                        "as_of": "2026-11-21",
                    },
                )
                db.upsert_consensus_view(comp.id, cons, _unit_vec(idx), [], [])

        for idx in range(7):
            thm = Node(
                id=f"thm_{idx:02d}",
                node_type="theme",
                name=f"Secular Theme {idx:02d}",
                summary=f"Theme narrative {idx:02d}",
                facets={"stage": "accelerating"},
            )
            db.upsert_node(thm, embedding=_unit_vec(idx))
            for c_idx in range(max(1, 4 - idx)):
                db.upsert_edge(
                    Edge(
                        id=f"ed_{idx}_{c_idx}",
                        from_id=f"ent_co_{c_idx:02d}",
                        to_id=thm.id,
                        relation="EXPOSED_TO", facets={"basis": "extracted"},
                    )
                )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))

    r_home = client.get("/")
    assert r_home.status_code == 200
    home_text = html.unescape(r_home.text)
    assert "Coverage Desk" not in r_home.text
    assert "All companies »" in home_text
    assert "All themes »" in home_text
    assert "Company 11" not in r_home.text
    assert "Secular Theme 06" not in r_home.text
    # The cap covers the <main> workspace only; the shell navigation is codified separately.
    main_html = r_home.text.split('<main class="portal-pane">', 1)[1].split("</main>", 1)[0]
    assert len(re.findall(r"<a\b", main_html)) <= 25

    r_all_co = client.get("/companies")
    assert r_all_co.status_code == 200
    assert "Company 11" in r_all_co.text

    r_all_th = client.get("/themes")
    assert r_all_th.status_code == 200
    assert "Secular Theme 06" in r_all_th.text


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
            db.upsert_node(n, embedding=_unit_vec(idx))
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






def test_web_chat_endpoint_uses_only_agent_chat() -> None:
    import ast

    import stock_ontology.web.app as web_app

    tree = ast.parse(Path(web_app.__file__).read_text(encoding="utf-8"))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "chat_endpoint"
    ]
    assert len(handlers) == 1
    handler = handlers[0]

    agent_names = {
        target.id
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "OntologyAgent"
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert agent_names, "chat_endpoint must construct an OntologyAgent"

    attrs = {
        node.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in agent_names
    }
    assert attrs == {"chat"}

    # The agent object is used only as the receiver of `.chat`, never passed or read otherwise.
    chat_receivers = {
        id(node.value)
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and node.attr == "chat"
    }
    other_uses = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
        and node.id in agent_names
        and isinstance(node.ctx, ast.Load)
        and id(node) not in chat_receivers
    ]
    assert other_uses == []


def test_home_themes_table_counts_companies_views_and_events(tmp_path: Path) -> None:
    db_path = tmp_path / "themes_table.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(id="thm_grid", node_type="theme", name="Grid Buildout", summary="s", facets={"stage": "emerging"}),
            Node(id="ent_a", node_type="entity", name="Alpha Power", summary="s", facets={"entity_type": "company", "ticker": "ALP"}),
            Node(id="ent_b", node_type="entity", name="Beta Wire", summary="s", facets={"entity_type": "company", "ticker": "BTW"}),
            Node(id="vw_1", node_type="view", name="Grid Bull Case", summary="s", facets={"view_type": "analyst_report"}),
            Node(id="vw_2", node_type="view", name="Grid Bear Case", summary="s", facets={"view_type": "analyst_report"}),
            Node(id="evt_1", node_type="event", name="Interconnect Queue Report", summary="s", facets={"event_type": "fact"}),
        ]
        for idx, n in enumerate(nodes):
            db.upsert_node(n, embedding=_unit_vec(idx))
        for edge in [
            Edge(id="e1", from_id="ent_a", to_id="thm_grid", relation="EXPOSED_TO", facets={"basis": "extracted"}),
            Edge(id="e2", from_id="ent_b", to_id="thm_grid", relation="EXPOSED_TO", facets={"basis": "extracted"}),
            Edge(id="e3", from_id="vw_1", to_id="thm_grid", relation="SUPPORTS", facets={"basis": "extracted"}),
            # A second edge to the same view must not double-count it.
            Edge(id="e4", from_id="vw_1", to_id="thm_grid", relation="ABOUT", facets={"basis": "extracted"}),
            Edge(id="e5", from_id="vw_2", to_id="thm_grid", relation="CONTRADICTS", facets={"basis": "extracted"}),
            Edge(id="e6", from_id="evt_1", to_id="thm_grid", relation="ABOUT", facets={"basis": "extracted"}),
        ]:
            db.upsert_edge(edge)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))
    r_home = client.get("/")
    assert r_home.status_code == 200

    theme_section = r_home.text.split('aria-label="Browse by Investment Theme"', 1)[1]
    assert '<table class="portal-table">' in theme_section
    assert ">Affected Companies<" in theme_section
    assert ">Views<" in theme_section
    assert ">Events<" in theme_section
    row = theme_section.split('href="/theme/thm_grid"', 1)[1].split("</tr>", 1)[0]
    counts = re.findall(r'<td class="mono u-num">(\d+)</td>', row)
    assert counts == ["2", "2", "1"]


# ---------------------------------------------------------------------------
# Presentation-model contract for the entity page (proposal `company-view-separation`)
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "stock_ontology" / "web" / "templates"
RAW_FACET_KEYS = ("facets", "edge_facets")
# Attribute or key access to `facets` / `edge_facets`. Prepared pairs such as
# `company_facets` and translation keys such as `'facets.col_value'` don't match.
RAW_FACET_TOKEN = re.compile(r"""\.(?:edge_)?facets\b|\[\s*['"](?:edge_)?facets['"]\s*\]""")


def _template_closure(name: str) -> set[str]:
    """Return `name` plus every template it includes, followed transitively."""
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        text = (TEMPLATES_DIR / current).read_text(encoding="utf-8")
        pending.extend(re.findall(r'{%-?\s*include\s+"([^"]+)"', text))
    return seen


def _raw_facet_paths(value: Any, path: str = "ctx") -> list[str]:
    """List every place in a template context where a raw facets mapping is still reachable."""
    found: list[str] = []
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            if field.name in RAW_FACET_KEYS:
                found.append(f"{path}.{field.name}")
            found.extend(_raw_facet_paths(getattr(value, field.name), f"{path}.{field.name}"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in RAW_FACET_KEYS:
                found.append(f"{path}[{key!r}]")
            found.extend(_raw_facet_paths(item, f"{path}[{key!r}]"))
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            found.extend(_raw_facet_paths(item, f"{path}[{idx}]"))
    return found


def _seed_presentation_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(
                id="ent_tsmc",
                node_type="entity",
                name="TSMC",
                summary="Leading-edge foundry.",
                aliases=["TSM", "Taiwan Semi"],
                facets={"entity_type": "company", "ticker": "TSM", "sector": "Semiconductors"},
            ),
            Node(
                id="ent_asml",
                node_type="entity",
                name="ASML",
                summary="Lithography tools.",
                facets={"entity_type": "company", "ticker": "ASML"},
            ),
            Node(
                id="ent_wei",
                node_type="entity",
                name="C.C. Wei",
                summary="TSMC chief executive.",
                facets={"entity_type": "person", "role": "ceo", "organization": "TSMC"},
            ),
            Node(
                id="thm_ai",
                node_type="theme",
                name="AI Accelerator Demand",
                summary="Accelerator capacity race.",
                facets={"stage": "accelerating"},
            ),
            Node(
                id="evt_capex",
                node_type="event",
                name="Capex Raise",
                summary="TSMC raises capex guidance.",
                facets={
                    "event_type": "news",
                    "event_date": "2026-11-10",
                    "status": "occurred",
                    "sentiment": "mixed",
                    "source": {"file_path": "TSMC/2026-11-10_capex.md", "author": "Ana Lee", "kind": "meeting"},
                },
                source_doc_id="doc_c",
            ),
            Node(
                id="evt_old",
                node_type="event",
                name="Fab Visit",
                summary="Earlier site visit.",
                facets={"event_type": "fact", "event_date": "2026-08-01", "status": "occurred"},
                source_doc_id="doc_o",
            ),
            Node(
                id="vw_rumor",
                node_type="view",
                name="Pricing Rumor",
                summary="Channel hears wafer price hikes.",
                facets={
                    "view_type": "rumor",
                    "stance": "cautious",
                    "sentiment": "negative",
                    "support_strength": "strong",
                    "conviction": "medium",
                    "as_of": "2026-11-12",
                    "source": {"file_path": "TSMC/2026-11-12_rumor.md", "author": "Bo Kim"},
                },
                source_doc_id="doc_r",
            ),
        ]
        for idx, n in enumerate(nodes):
            db.upsert_node(n, embedding=_unit_vec(idx))
        for edge in [
            Edge(id="p1", from_id="evt_capex", to_id="ent_tsmc", relation="ABOUT", facets={"sentiment": "positive", "basis": "extracted"}, source_doc_id="doc_c"),
            Edge(id="p2", from_id="evt_old", to_id="ent_tsmc", relation="ABOUT", source_doc_id="doc_o", facets={"basis": "extracted"}),
            Edge(id="p3", from_id="vw_rumor", to_id="ent_tsmc", relation="ABOUT", source_doc_id="doc_r", facets={"basis": "extracted"}),
            Edge(id="p4", from_id="ent_tsmc", to_id="thm_ai", relation="EXPOSED_TO", facets={"sentiment": "positive", "basis": "extracted"}),
            Edge(id="p5", from_id="ent_asml", to_id="ent_tsmc", relation="SUPPLIES_TO", facets={"basis": "extracted"}),
            Edge(id="p6", from_id="ent_wei", to_id="ent_tsmc", relation="WORKS_AT", facets={"basis": "extracted"}),
            Edge(id="p7", from_id="evt_capex", to_id="thm_ai", relation="RELATES_TO", facets={"sentiment": "positive", "basis": "extracted"}, source_doc_id="doc_c"),
            Edge(id="p8", from_id="vw_rumor", to_id="thm_ai", relation="CONTRADICTS", source_doc_id="doc_r", facets={"basis": "extracted"}),
        ]:
            db.upsert_edge(edge)
        old_cons = Node(
            id="vw_cons_old",
            node_type="view",
            name="Consensus: Hold TSMC",
            summary="Hold pending capex clarity.",
            facets={"stance": "hold", "as_of": "2026-09-01", "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_tsmc", old_cons, _unit_vec(8), ["evt_old"], [])
        new_cons = Node(
            id="vw_cons_new",
            node_type="view",
            name="Consensus: Buy TSMC",
            summary="Buy on AI demand.",
            facets={
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-11-15",
                "pillars": ["AI wafer demand"], "view_type": "analyst_report",
            },
        )
        db.upsert_consensus_view("ent_tsmc", new_cons, _unit_vec(9), ["evt_capex"], ["vw_rumor"])


def test_entity_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """Entity pages render from typed presentation models, never raw ontology facets."""
    from stock_ontology.web.viewmodels import build_entity_context

    db_path = tmp_path / "presentation.db"
    _seed_presentation_db(db_path)
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))

    # 1. The rendered pages still show what the ontology holds.
    page = client.get("/entity/ent_tsmc")
    assert page.status_code == 200
    text = page.text
    assert '<span class="mono">(TSM)</span>' in text
    assert "TSM, Taiwan Semi" in text
    events = text.split('id="sec-events"', 1)[1].split("</section>", 1)[0]
    capex = events.split('id="node-evt_capex"', 1)[1].split("</tr>", 1)[0]
    assert '<div class="mono">2026-11-10</div>' in capex
    assert '<span class="badge">news</span>' in capex
    assert '<span class="badge badge-positive">positive</span>' in capex
    assert '<div class="source-cite">occurred</div>' in capex
    assert "entity impact (overall: mixed)" in capex
    assert "Author: Ana Lee" in capex and "Kind: meeting" in capex
    fab = events.split('id="node-evt_old"', 1)[1].split("</tr>", 1)[0]
    assert "entity impact" not in fab
    views = text.split('id="sec-views"', 1)[1].split("</section>", 1)[0]
    assert '<span class="badge badge-cautious">cautious</span>' in views
    assert '<span class="badge badge-negative">negative</span>' in views
    assert '<span class="badge badge-strong">strong</span>' in views
    assert "rumor" in views and "2026-11-12" in views
    assert "Conviction: medium" in views and "Author: Bo Kim" in views
    assert "Prior Superseded Consensus History (1)" in text
    assert '<span class="badge">hold</span>' in text and "2026-09-01" in text
    themes = text.split('id="sec-themes"', 1)[1].split("</section>", 1)[0]
    assert '<span class="badge badge-accelerating">accelerating</span>' in themes
    assert '<span class="badge badge-positive">positive</span>' in themes
    related = text.split('id="sec-related"', 1)[1].split("</section>", 1)[0]
    assert "ASML" in related and "C.C. Wei" in related
    assert '<td class="mono">person</td>' in related

    theme_page = client.get("/theme/thm_ai")
    assert theme_page.status_code == 200
    t_events = theme_page.text.split('id="sec-events"', 1)[1].split("</section>", 1)[0]
    assert "Capex Raise" in t_events and '<span class="badge badge-positive">positive</span>' in t_events
    assert "Author: Ana Lee" in t_events
    t_views = theme_page.text.split('id="sec-views"', 1)[1].split("</section>", 1)[0]
    assert "Pricing Rumor" in t_views and '<span class="badge badge-cautious">cautious</span>' in t_views

    # 2. The view model hands templates presentation models only.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        for entity_id in ("ent_tsmc", "ent_wei", "ent_asml"):
            ctx = build_entity_context(db, entity_id, data_dir=tmp_path, lang="en")
            assert _raw_facet_paths(ctx) == [], entity_id
            assert dataclasses.is_dataclass(ctx["entity"]), entity_id
            for key in ("events", "views", "themes", "related_entities", "prior_consensuses"):
                assert all(dataclasses.is_dataclass(item) for item in ctx[key]), (entity_id, key)
        tsmc_ctx = build_entity_context(db, "ent_tsmc", data_dir=tmp_path, lang="en")
        assert dataclasses.is_dataclass(tsmc_ctx["consensus"])
        assert len(tsmc_ctx["events"]) == 2 and len(tsmc_ctx["prior_consensuses"]) == 1

    # 3. No template the entity page renders reads raw facets.
    closure = _template_closure("entity.html")
    assert "partials/section_events.html" in closure and "partials/facet_header.html" in closure
    offenders = sorted(
        name for name in closure if RAW_FACET_TOKEN.search((TEMPLATES_DIR / name).read_text(encoding="utf-8"))
    )
    assert offenders == []


# --- Generic ontology search (ledger: docs/proposals/ontology-search.md) ---
#
# Page contract the search page exposes, used by the witnesses below:
#   - the best-match card is one element with `data-best-match`, `data-result-id`, and
#     `data-match-reason`;
#   - every listed ontology item is an element with `data-result-id` and `data-match-reason`
#     (one of name, alias, relationship, note, semantic);
#   - every grepped note passage is an element with `data-note-file` (path relative to
#     ONTOLOGY_DATA_DIR), `data-note-line` (1-based), and `data-match-reason="note"`;
#   - the agent note is one element with `data-agent-column` and `data-agent-query`
#     (the search word, empty when there is none); clippy.js moves it into the Clippy dock.

_SEARCH_NOTE_FILE = "Notes/2026-11-10_channel_check.md"
_SEARCH_EVENT_FILE = "NVDA/2026-11-01_q3.md"
_SEARCH_ATTRS = ("data-result-id", "data-note-file", "data-agent-", "data-best-match")


def _search_tags(page: str) -> list[dict[str, str]]:
    """Attributes of start tags carrying search-page data attributes, in document order."""
    tags: list[dict[str, str]] = []
    for match in re.finditer(r"<[a-zA-Z][^>]*>", page):
        raw = match.group(0)
        if not any(marker in raw for marker in _SEARCH_ATTRS):
            continue
        pairs = re.findall(r'([\w:-]+)(?:\s*=\s*"([^"]*)")?', raw[1:-1])[1:]
        tags.append({name: html.unescape(value) for name, value in pairs})
    return tags


def _seed_search_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU platform leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple Inc.",
            summary="Consumer devices and services.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power and rack cooling density constraints.",
            facets={"stage": "accelerating"},
        )
        event = Node(
            id="evt_nvda_q3",
            node_type="event",
            name="Q3 Data Center Beat",
            summary="Data center revenue beat guidance.",
            facets={
                "event_type": "fact",
                "event_date": "2026-11-01",
                "status": "occurred",
                "source": {"file_path": _SEARCH_EVENT_FILE},
            },
            source_doc_id="doc_q3",
        )
        db.upsert_node(nvda, embedding=_unit_vec(1))
        db.upsert_node(aapl, embedding=_unit_vec(2))
        db.upsert_node(theme, embedding=_unit_vec(3))
        db.upsert_node(event, embedding=_unit_vec(4))
        db.upsert_edge(Edge(id="se1", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"}))
        db.upsert_edge(
            Edge(id="se2", from_id="evt_nvda_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_q3", facets={"basis": "extracted"})
        )
        # FakeWebLLM embeds every query as _unit_vec(0), so this consensus is the nearest vector.
        cons = Node(
            id="vw_cons_aapl",
            node_type="view",
            name="Consensus: Buy Apple Inc.",
            summary="Maintain Buy on services growth.",
            facets={"stance": "buy", "as_of": "2026-11-15", "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_aapl", cons, _unit_vec(0), [], [])


def _seed_search_notes(data_dir: Path) -> None:
    (data_dir / "Notes").mkdir(parents=True)
    (data_dir / _SEARCH_NOTE_FILE).write_text(
        "# Channel check\n\nChannel check: NVIDIA lead times shortened.\n",
        encoding="utf-8",
    )
    (data_dir / "NVDA").mkdir(parents=True)
    (data_dir / _SEARCH_EVENT_FILE).write_text(
        "# Q3 call\n\nNVIDIA data center revenue beat guidance.\n",
        encoding="utf-8",
    )


def _search_client(tmp_path: Path, llm: Any) -> tuple[TestClient, Path, Path]:
    db_path = tmp_path / "search.db"
    _seed_search_db(db_path)
    data_dir = tmp_path / "data"
    _seed_search_notes(data_dir)
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    return TestClient(create_app(settings, llm=llm)), db_path, data_dir


def test_web_search_entity_first_card_sections_notes_and_agent_column(tmp_path: Path) -> None:
    client, _, _ = _search_client(tmp_path, FakeWebLLM())

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    tags = _search_tags(r.text)

    # Best-match card: the entity whose name matches, labeled "name".
    best = [t for t in tags if "data-best-match" in t]
    assert len(best) == 1, "search page has no single best-match card"
    assert best[0].get("data-result-id") == "ent_nvda"
    assert best[0].get("data-match-reason") == "name"

    # The nearer vector hit is listed below the entity and says it matched semantically.
    items = [t for t in tags if "data-result-id" in t]
    order = [t["data-result-id"] for t in items]
    reason = {t["data-result-id"]: t.get("data-match-reason") for t in reversed(items)}
    assert "vw_cons_aapl" in order
    assert order.index("ent_nvda") < order.index("vw_cons_aapl")
    assert reason["vw_cons_aapl"] == "semantic"

    # Expansion from the matched entity through its edges.
    assert reason.get("thm_power") == "relationship"
    assert "evt_nvda_q3" in order

    # Grepped note passage with file and line; the event's own source line is not listed again.
    passages = [t for t in tags if "data-note-file" in t]
    note = [t for t in passages if t["data-note-file"] == _SEARCH_NOTE_FILE]
    assert len(note) == 1
    assert note[0].get("data-note-line") == "3"
    assert note[0].get("data-match-reason") == "note"
    assert "NVIDIA lead times shortened." in r.text
    assert all(t["data-note-file"] != _SEARCH_EVENT_FILE for t in passages)

    # Agent note for this search, carried into the shared Clippy dock (no pinned column).
    columns = [t for t in tags if "data-agent-column" in t]
    assert len(columns) == 1
    assert columns[0].get("data-agent-query") == "nvidia"
    assert not any("data-agent-detach" in t for t in tags)
    assert "/static/clippy.js" in r.text
    assert "/api/chat" in client.get("/static/clippy.js").text

    # No search word, no agent run.
    r_empty = client.get("/search")
    assert r_empty.status_code == 200
    assert all(not t.get("data-agent-query") for t in _search_tags(r_empty.text))


def test_web_search_reads_only_data_dir_notes_and_never_writes_db(tmp_path: Path) -> None:
    import hashlib

    client, db_path, data_dir = _search_client(tmp_path, FakeWebLLM())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("NVIDIA OUTSIDE-MARKER-1\n", encoding="utf-8")
    (data_dir / "linked.md").symlink_to(outside / "secret.md")
    (data_dir / ".hidden").mkdir()
    (data_dir / ".hidden" / "x.md").write_text("NVIDIA HIDDEN-DIR-MARKER-2\n", encoding="utf-8")
    (data_dir / ".dotnote.md").write_text("NVIDIA HIDDEN-FILE-MARKER-3\n", encoding="utf-8")
    (data_dir / "Notes" / "deck.pdf").write_text("NVIDIA UNSUPPORTED-MARKER-4\n", encoding="utf-8")

    def db_digest() -> tuple[str, int]:
        return hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns

    before = db_digest()

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    # Positive control: an in-scope note is grepped, so the exclusions below are meaningful.
    assert any(t.get("data-note-file") == _SEARCH_NOTE_FILE for t in _search_tags(r.text))

    markers = ("OUTSIDE-MARKER-1", "HIDDEN-DIR-MARKER-2", "HIDDEN-FILE-MARKER-3", "UNSUPPORTED-MARKER-4")
    for word in ("nvidia", "../outside/secret", "NVIDIA OUTSIDE", ".hidden", "*.md", "MARKER"):
        page = client.get("/search", params={"q": word})
        assert page.status_code == 200
        for marker in markers:
            assert marker not in page.text, f"{marker} leaked for search word {word!r}"

    assert db_digest() == before


class EmbeddingAndAgentDownWebLLM(FakeWebLLM):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider unavailable")

    def generate_agent_reply(self, **kwargs: Any) -> AgentTurn:
        raise RuntimeError("agent provider unavailable")


def test_web_search_functional_results_survive_embedding_and_agent_failure(tmp_path: Path) -> None:
    client, _, _ = _search_client(tmp_path, EmbeddingAndAgentDownWebLLM())

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    tags = _search_tags(r.text)
    assert [t.get("data-result-id") for t in tags if "data-best-match" in t] == ["ent_nvda"]
    assert any(t.get("data-note-file") == _SEARCH_NOTE_FILE for t in tags)
    assert [t.get("data-agent-query") for t in tags if "data-agent-column" in t] == ["nvidia"]

    # The agent run the column starts fails as a JSON error the column can show.
    r_chat = client.post("/api/chat", json={"message": "nvidia", "page_context": "Search: nvidia"})
    assert r_chat.status_code == 500
    assert r_chat.json()["error"]
    assert r_chat.json()["session_id"]


def test_web_search_note_links_jump_to_the_matching_line(tmp_path: Path) -> None:
    client, _, _ = _search_client(tmp_path, FakeWebLLM())

    page = client.get("/search", params={"q": "nvidia"}).text
    # A grepped passage, and the event folded onto its own note, both link to the raw note at that line.
    assert f"/catalog?file={_SEARCH_NOTE_FILE}&amp;format=raw#L3" in page
    assert f"/catalog?file={_SEARCH_EVENT_FILE}&amp;format=raw#L3" in page

    raw = client.get("/catalog", params={"file": _SEARCH_NOTE_FILE, "format": "raw"}).text
    assert '<span id="L3" class="note-line">Channel check: NVIDIA lead times shortened.' in raw
    assert '<span id="L1" class="note-line"># Channel check' in raw


def test_theme_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """Theme pages render from typed presentation models, never raw ontology facets."""
    from stock_ontology.web.viewmodels import build_theme_context

    db_path = tmp_path / "presentation.db"
    _seed_presentation_db(db_path)
    note = tmp_path / "TSMC" / "2026-11-10_capex.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Capex Raise Notes\n\nTSMC raises capex.\n", encoding="utf-8")
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))

    # 1. The rendered page still shows what the ontology holds.
    page = client.get("/theme/thm_ai")
    assert page.status_code == 200
    text = page.text
    assert '<span class="badge badge-accelerating">STAGE: accelerating</span>' in text
    first = text.split('aria-label="Affected Companies"', 1)[1].split("</section>", 1)[0]
    assert '<a href="/entity/ent_tsmc"><strong>TSMC</strong></a>' in first
    assert '<span class="mono">(TSM)</span>' in first
    assert '<span class="badge badge-buy">buy</span>' in first
    direct = first.split("exposed to", 1)[1].split("</li>", 1)[0]
    assert '<span class="badge badge-positive">positive</span>' in direct
    assert '<span class="source-cite">(direct)</span>' in direct
    assert "ABOUT &rarr; event: Capex Raise &rarr; RELATES_TO" in first
    assert '<a href="/catalog?file=TSMC/2026-11-10_capex.md">Capex Raise Notes</a>' in first
    assert "ABOUT &rarr; view: Pricing Rumor &rarr; CONTRADICTS" in first
    assert "[TSMC — Rumor (2026-11-12)]" in first
    # ASML only supplies TSMC, so it is not a company the theme affects.
    assert "ent_asml" not in text

    # 2. The view model hands templates presentation models only.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        ctx = build_theme_context(db, "thm_ai", data_dir=tmp_path, lang="en")
    assert _raw_facet_paths(ctx) == []
    assert dataclasses.is_dataclass(ctx["theme"])
    for key in ("companies", "events", "views"):
        assert ctx[key] and all(dataclasses.is_dataclass(item) for item in ctx[key]), key

    # 3. No template the theme page renders reads raw facets.
    closure = _template_closure("theme.html")
    assert "partials/section_events.html" in closure and "partials/facet_generic_table.html" in closure
    offenders = sorted(
        name for name in closure if RAW_FACET_TOKEN.search((TEMPLATES_DIR / name).read_text(encoding="utf-8"))
    )
    assert offenders == []


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGE_CODES)
def test_search_new_filter_chips_and_labels_in_every_locale(tmp_path: Path, lang: str) -> None:
    db_path = tmp_path / "chips.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_a", node_type="entity", name="Apple", summary="", facets={"entity_type": "company"}),
            embedding=_unit_vec(0),
        )
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))
    r = client.get(
        "/search",
        params={
            "lang": lang,
            "status": "event:upcoming",
            "support_strength": "weak",
            "conviction": "high",
            "relation": "ABOUT",
        },
    )
    assert r.status_code == 200
    page = html.unescape(r.text)
    pills = re.findall(r'<span class="filter-pill mono">([^<]*)</span>', page)
    assert len(pills) == 4
    for key in ("filter_status", "filter_support_strength", "filter_conviction", "filter_relation"):
        label = translate(f"search.{key}", lang=lang)
        assert label != f"search.{key}"
        assert any(p.startswith(f"{label}: ") for p in pills), key
    for key in (
        "status_label",
        "any_status",
        "optgroup_event_statuses",
        "optgroup_view_statuses",
        "support_strength_label",
        "any_support_strength",
        "conviction_label",
        "any_conviction",
        "relation_label",
        "any_relation",
    ):
        label = translate(f"search.{key}", lang=lang)
        assert label != f"search.{key}"
        assert label in page, key


# ---------------------------------------------------------------------------
# Presentation-model contract for the catalog note page (proposal `event-view-separation`)
# ---------------------------------------------------------------------------

NOTE_READER_TEMPLATE = "partials/note_reader.html"
NOTE_READER_NAMES = {"active_note", "t", "t_enum"}


def _non_model_paths(value: Any, path: str) -> list[str]:
    """List every place below `value` that is a raw dict, a list, or a mutable dataclass."""
    found: list[str] = []
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if not type(value).__dataclass_params__.frozen:
            found.append(f"{path} (mutable {type(value).__name__})")
        for field in dataclasses.fields(value):
            found.extend(_non_model_paths(getattr(value, field.name), f"{path}.{field.name}"))
    elif isinstance(value, dict):
        found.append(f"{path} (dict)")
    elif isinstance(value, list):
        found.append(f"{path} (list)")
    elif isinstance(value, tuple):
        for idx, item in enumerate(value):
            found.extend(_non_model_paths(item, f"{path}[{idx}]"))
    return found


def test_note_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """The catalog note page renders from a frozen presentation model built by a mapper."""
    import jinja2
    from jinja2 import meta

    from stock_ontology.web.catalog import build_catalog_context

    db_path = tmp_path / "web.db"
    _seed_web_db(db_path)
    data_dir = tmp_path / "data"
    (data_dir / "NVDA").mkdir(parents=True)
    (data_dir / "NVDA" / "2026-10-15_q3.md").write_text(
        "# NVDA Q3 Preview\n\nBlackwell <script>alert(1)</script> ramp.\n\nThird & last.\n", encoding="utf-8"
    )
    (data_dir / "NVDA" / "2026-09-01_old.md").write_text("# NVDA Older Note\n\nOld.\n", encoding="utf-8")
    (data_dir / "NVDA" / "2026-11-01_new.md").write_text("# NVDA Newer Note\n\nNew.\n", encoding="utf-8")
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))
    note_file = "NVDA/2026-10-15_q3.md"

    def reader(params: dict[str, str]) -> str:
        """The note reader section, with whitespace runs squashed so markup layout does not matter."""
        page = client.get("/catalog", params=params)
        assert page.status_code == 200
        section = page.text.split('<section aria-label="Raw Note Reader">', 1)[1].split("</section>", 1)[0]
        return re.sub(r"\s+>", ">", re.sub(r"[ \t\n]+", " ", section))

    # 1. The rendered note page still shows the note, its chips and its navigation.
    rendered = reader({"file": note_file})
    assert "<h2 class=\"u-bd-none u-m-0 u-p-0 u-fs-1p25rem\"> NVDA Q3 Preview </h2>" in rendered
    assert 'Company: <a href="/entity/ent_nvda"> NVIDIA (NVDA) </a>' in rendered
    assert 'Author: <a href="/entity/ent_kenji">Kenji Sato</a> </span>' in rendered
    assert '<a href="/catalog?view=company&amp;dir=NVDA" class="retro-link-btn">← Back to NVIDIA</a>' in rendered
    assert '<div class="note-rendered"><h1>NVDA Q3 Preview</h1>' in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered and "<script>" not in rendered
    assert '&laquo; <a href="/catalog?view=company&amp;dir=NVDA&amp;file=NVDA/2026-11-01_new.md"> NVDA Newer Note </a>' in rendered
    assert '<a href="/catalog?view=company&amp;dir=NVDA&amp;file=NVDA/2026-09-01_old.md"> NVDA Older Note </a> &raquo;' in rendered

    raw = reader({"view": "author", "author": "Kenji Sato", "file": note_file, "format": "raw"})
    assert '<a href="/catalog?view=author&amp;author=ent_kenji" class="retro-link-btn">← Back to Kenji Sato</a>' in raw
    assert '<span id="L3" class="note-line">Blackwell &lt;script&gt;alert(1)&lt;/script&gt; ramp. </span>' in raw
    assert '<span id="L5" class="note-line">Third &amp; last. </span></pre>' in raw
    assert "note-rendered" not in raw
    assert '<span class="source-cite">Start of list</span>' in raw and '<span class="source-cite">End of list</span>' in raw

    all_view = reader({"view": "all", "file": note_file})
    assert '<a href="/catalog?view=all" class="retro-link-btn">← Back to All Notes</a>' in all_view
    assert '<a href="/catalog?view=all&amp;file=NVDA/2026-11-01_new.md">' in all_view

    # 2. The view model hands the note reader one frozen presentation model, with no raw dicts or lists.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        for view, author in (("company", ""), ("author", "Kenji Sato"), ("all", "")):
            ctx = build_catalog_context(db, data_dir, view=view, selected_author=author, selected_file=note_file)
            note = ctx["active_note"]
            assert dataclasses.is_dataclass(note), view
            assert _non_model_paths(note, "active_note") == [], view

    # 3. The note reader is a partial that reads only that model, and catalog.html only includes it.
    catalog_src = (TEMPLATES_DIR / "catalog.html").read_text(encoding="utf-8")
    assert '{% include "' + NOTE_READER_TEMPLATE + '" %}' in catalog_src
    assert re.search(r"active_note\s*[.\[]", catalog_src) is None
    reader_src = (TEMPLATES_DIR / NOTE_READER_TEMPLATE).read_text(encoding="utf-8")
    names = meta.find_undeclared_variables(jinja2.Environment().parse(reader_src))
    assert names <= NOTE_READER_NAMES, sorted(names - NOTE_READER_NAMES)
    assert RAW_FACET_TOKEN.search(reader_src) is None


# ---------------------------------------------------------------------------
# Proof witnesses: official-edge-facets (theme readers skip `synthesized` edges)
# ---------------------------------------------------------------------------


def _seed_basis_theme_db(db_path: Path) -> None:
    def view(node_id: str, name: str, view_type: str) -> Node:
        return Node(
            id=node_id,
            node_type="view",
            name=name,
            summary=f"{name}.",
            facets={"view_type": view_type, "stance": "buy", "as_of": "2026-11-20"},
            source_doc_id="doc_b",
        )

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(
                id="ent_msft",
                node_type="entity",
                name="Microsoft",
                summary="Cloud and software.",
                facets={"entity_type": "company", "ticker": "MSFT"},
            ),
            Node(
                id="ent_orcl",
                node_type="entity",
                name="Oracle",
                summary="Database and cloud.",
                facets={"entity_type": "company", "ticker": "ORCL"},
            ),
            Node(
                id="thm_eai",
                node_type="theme",
                name="Enterprise AI Monetization",
                summary="Monetizing enterprise AI.",
                facets={"stage": "accelerating"},
            ),
            view("vw_extracted", "Extracted Seat Pricing View", "analyst_report"),
            view("vw_legacy", "Legacy Usage View", "pm_view"),
            view("vw_soft", "Soft Linked Copilot View", "analyst_report"),
        ]
        for idx, n in enumerate(nodes):
            db.upsert_node(n, embedding=_unit_vec(idx))
        edges = [
            ("eb1", "vw_extracted", "RELATES_TO", "thm_eai", {"basis": "extracted"}),
            ("eb2", "vw_extracted", "ABOUT", "ent_orcl", {"basis": "extracted"}),
            ("eb3", "vw_legacy", "RELATES_TO", "thm_eai", {}),  # no basis counts as extracted
            ("eb4", "vw_legacy", "ABOUT", "ent_orcl", {}),
            ("eb5", "vw_soft", "RELATES_TO", "thm_eai", {"basis": "synthesized"}),
            ("eb6", "vw_soft", "ABOUT", "ent_msft", {"basis": "extracted"}),
        ]
        for eid, src, rel, dst, facets in edges:
            stored = facets or {"basis": "extracted"}
            db.upsert_edge(Edge(id=eid, from_id=src, to_id=dst, relation=rel, facets=stored, source_doc_id="doc_b"))
        # eb3 and eb4 are legacy rows written before `basis` was required: strip it by raw SQL.
        with db.transaction():
            db.conn.execute(
                "UPDATE edges SET facets_json = json_remove(facets_json, '$.basis') WHERE id IN ('eb3', 'eb4')"
            )
        cons = Node(
            id="vw_cons_msft",
            node_type="view",
            name="Consensus: Buy Microsoft",
            summary="Copilot seats drive upside.",
            facets={"view_type": "consensus", "stance": "buy", "pillars": ["Copilot seat growth"]},
        )
        # The theme is LLM-picked evidence for Microsoft's consensus: a synthesized SUPPORTS edge.
        db.upsert_consensus_view("ent_msft", cons, _unit_vec(9), ["thm_eai"], [])


def test_theme_readers_skip_synthesized_edges(tmp_path: Path) -> None:
    from stock_ontology.web.viewmodels import build_entity_context, build_theme_context

    db_path = tmp_path / "basis_theme.db"
    _seed_basis_theme_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        # Guardrail: the company page still shows the consensus view with its pillars.
        msft_ctx = build_entity_context(db, "ent_msft", lang="en")
        assert msft_ctx["consensus"] is not None
        assert msft_ctx["consensus"].pillars == ("Copilot seat growth",)

        ctx = build_theme_context(db, "thm_eai", lang="en")

    view_names = {v.name for v in ctx["views"]}
    assert {"Extracted Seat Pricing View", "Legacy Usage View"} <= view_names
    assert "Consensus: Buy Microsoft" not in view_names
    assert "Soft Linked Copilot View" not in view_names, "a view linked to the theme only by a synthesized edge is listed"
    companies = {row.company.name for row in ctx["companies"]}
    assert "Oracle" in companies
    assert "Microsoft" not in companies, "Microsoft reaches the theme only through synthesized edges"


def test_find_theme_companies_skips_synthesized_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "basis_theme.db"
    _seed_basis_theme_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        theme_companies = db.find_theme_companies("thm_eai")

    via_ids = {link.get("via_node_id") for row in theme_companies["companies"] for link in row["links"]}
    assert {"vw_extracted", "vw_legacy"} <= via_ids
    assert "vw_cons_msft" not in via_ids
    assert "vw_soft" not in via_ids, "find_theme_companies links a company through a synthesized edge"
    names = {row["company"]["name"] for row in theme_companies["companies"]}
    assert names == {"Oracle"}, names
