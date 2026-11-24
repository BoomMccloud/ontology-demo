"""Offline tests for the Research module: overview, companies, themes, and entity and theme pages."""

from __future__ import annotations

import dataclasses
import html
import re
from pathlib import Path

from fastapi.testclient import TestClient
from web_support import (
    DIM,
    RAW_FACET_TOKEN,
    TEMPLATES_DIR,
    FakeWebLLM,
    raw_facet_paths,
    template_closure,
    unit_vec,
)

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.web import create_app


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
            db.upsert_node(n, embedding=unit_vec(idx))

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
            db.upsert_node(comp, embedding=unit_vec(idx))
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
                db.upsert_consensus_view(comp.id, cons, unit_vec(idx), [], [])

        for idx in range(7):
            thm = Node(
                id=f"thm_{idx:02d}",
                node_type="theme",
                name=f"Secular Theme {idx:02d}",
                summary=f"Theme narrative {idx:02d}",
                facets={"stage": "accelerating"},
            )
            db.upsert_node(thm, embedding=unit_vec(idx))
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
            db.upsert_node(n, embedding=unit_vec(idx))
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
            db.upsert_node(n, embedding=unit_vec(idx))
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
        db.upsert_consensus_view("ent_tsmc", old_cons, unit_vec(8), ["evt_old"], [])
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
        db.upsert_consensus_view("ent_tsmc", new_cons, unit_vec(9), ["evt_capex"], ["vw_rumor"])


def test_entity_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """Entity pages render from typed presentation models, never raw ontology facets."""
    from stock_ontology.web.research.views import build_entity_context

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
    assert '<span class="badge badge-bearish">bearish</span>' in views
    assert '<span class="badge badge-negative">negative</span>' in views
    assert '<span class="badge badge-strong">strong</span>' in views
    assert "rumor" in views and "2026-11-12" in views
    assert "Conviction: medium" in views and "Author: Bo Kim" in views
    assert "Prior Superseded Consensus History (1)" in text
    assert '<span class="badge">neutral</span>' in text and "2026-09-01" in text
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
    assert "Pricing Rumor" in t_views and '<span class="badge badge-bearish">bearish</span>' in t_views

    # 2. The view model hands templates presentation models only.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        for entity_id in ("ent_tsmc", "ent_wei", "ent_asml"):
            ctx = build_entity_context(db, entity_id, data_dir=tmp_path, lang="en")
            assert raw_facet_paths(ctx) == [], entity_id
            assert dataclasses.is_dataclass(ctx["entity"]), entity_id
            for key in ("events", "views", "themes", "related_entities", "prior_consensuses"):
                assert all(dataclasses.is_dataclass(item) for item in ctx[key]), (entity_id, key)
        tsmc_ctx = build_entity_context(db, "ent_tsmc", data_dir=tmp_path, lang="en")
        assert dataclasses.is_dataclass(tsmc_ctx["consensus"])
        assert len(tsmc_ctx["events"]) == 2 and len(tsmc_ctx["prior_consensuses"]) == 1

    # 3. No template the entity page renders reads raw facets.
    closure = template_closure("entity.html")
    assert "partials/section_events.html" in closure and "partials/facet_header.html" in closure
    offenders = sorted(
        name for name in closure if RAW_FACET_TOKEN.search((TEMPLATES_DIR / name).read_text(encoding="utf-8"))
    )
    assert offenders == []


def test_theme_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """Theme pages render from typed presentation models, never raw ontology facets."""
    from stock_ontology.web.research.views import build_theme_context

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
    first = text.split('aria-label="Exposed Companies"', 1)[1].split("</section>", 1)[0]
    assert '<a href="/entity/ent_tsmc"><strong>TSMC</strong></a>' in first
    assert '<span class="mono">(TSM)</span>' in first
    assert '<span class="badge badge-positive">positive</span>' in first
    assert "badge-bullish" not in first, "the company's overall stance is not theme exposure"
    assert "(direct)" not in first
    assert ">Capex Raise</a>" in first
    assert ">Pricing Rumor</a>" in first
    assert "&rarr;" not in first
    # ASML only supplies TSMC, so it is not a company the theme affects.
    assert "ent_asml" not in text

    # 2. The view model hands templates presentation models only.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        ctx = build_theme_context(db, "thm_ai", data_dir=tmp_path, lang="en")
    assert raw_facet_paths(ctx) == []
    assert dataclasses.is_dataclass(ctx["theme"])
    for key in ("exposed_companies", "events", "views"):
        assert ctx[key] and all(dataclasses.is_dataclass(item) for item in ctx[key]), key

    # 3. No template the theme page renders reads raw facets.
    closure = template_closure("theme.html")
    assert "partials/section_events.html" in closure and "partials/facet_generic_table.html" in closure
    offenders = sorted(
        name for name in closure if RAW_FACET_TOKEN.search((TEMPLATES_DIR / name).read_text(encoding="utf-8"))
    )
    assert offenders == []


def test_theme_page_separates_stated_exposure_from_evidence_mentions(tmp_path: Path) -> None:
    from stock_ontology.web.research.views import build_theme_context

    db_path = tmp_path / "theme_split.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(id="thm_x", node_type="theme", name="Packaging", summary="s", facets={"stage": "emerging"}),
            Node(id="ent_exp", node_type="entity", name="Exposed Co", summary="s", facets={"entity_type": "company"}),
            Node(id="ent_men", node_type="entity", name="Mentioned Co", summary="s", facets={"entity_type": "company"}),
            Node(
                id="evt_x",
                node_type="event",
                name="Yield Miss",
                summary="s",
                facets={"event_type": "fact", "event_date": "2026-11-01", "sentiment": "negative"},
            ),
        ]
        for idx, node in enumerate(nodes):
            db.upsert_node(node, embedding=unit_vec(idx))
        for doc_id, file_path in (("doc_a", "X/a.md"), ("doc_b", "X/b.md")):
            db.upsert_ingestion_log(file_path, doc_id, doc_id)
        for edge in [
            Edge(id="e1", from_id="ent_exp", to_id="thm_x", relation="EXPOSED_TO",
                 facets={"basis": "extracted", "sentiment": "positive"}, source_doc_id="doc_a"),
            Edge(id="e2", from_id="ent_exp", to_id="thm_x", relation="EXPOSED_TO",
                 facets={"basis": "extracted", "sentiment": "mixed"}, source_doc_id="doc_b"),
            Edge(id="e3", from_id="evt_x", to_id="thm_x", relation="RELATES_TO", facets={"basis": "extracted"}),
            Edge(id="e4", from_id="evt_x", to_id="ent_exp", relation="ABOUT",
                 facets={"basis": "extracted", "sentiment": "positive"}),
            Edge(id="e5", from_id="evt_x", to_id="ent_men", relation="ABOUT", facets={"basis": "extracted"}),
        ]:
            db.upsert_edge(edge)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        ctx = build_theme_context(db, "thm_x", lang="en")

    assert [row.company.name for row in ctx["exposed_companies"]] == ["Exposed Co"]
    assert [row.company.name for row in ctx["mentioned_companies"]] == ["Mentioned Co"]
    exposed = ctx["exposed_companies"][0]
    assert exposed.exposure == "mixed"
    assert sorted(note.sentiment for note in exposed.notes) == ["mixed", "positive"], "each note keeps its stance"
    assert exposed.evidence[0].sentiment == "positive", "the company's ABOUT edge sets evidence sentiment"
    mentioned = ctx["mentioned_companies"][0]
    assert mentioned.exposure is None and mentioned.notes == ()
    assert mentioned.evidence[0].sentiment is None, "the event's own sentiment is not company exposure"


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
            db.upsert_node(n, embedding=unit_vec(idx))
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
        db.upsert_consensus_view("ent_msft", cons, unit_vec(9), ["thm_eai"], [])


def test_theme_readers_skip_synthesized_edges(tmp_path: Path) -> None:
    from stock_ontology.web.research.views import build_entity_context, build_theme_context

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
    companies = {row.company.name for row in [*ctx["exposed_companies"], *ctx["mentioned_companies"]]}
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
