"""Offline cross-boundary witnesses for minimal canonical entity & theme relationships."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from stock_ontology.agent import OntologyAgent
from stock_ontology.audit import run_ontology_audit
from stock_ontology.cli import app as cli_app
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import LOCALES_DIR, SUPPORTED_LANGUAGE_CODES, load_catalogs
from stock_ontology.llm import AgentTurn, ToolCall
from stock_ontology.models import (
    ConsensusSynthesis,
    Edge,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedTheme,
    ExtractionResult,
    FacetKV,
    Node,
)
from stock_ontology.pipeline import IngestionPipeline
from stock_ontology.registry import create_minimal_registry, load_registry, save_registry
from stock_ontology.repair import repair_ontology
from stock_ontology.web import create_app

DIM = 32
REPO_ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

EXPECTED_OFFICIAL_RELATIONS = {
    "ABOUT",
    "AUTHORED_BY",
    "SUPPORTS",
    "CONTRADICTS",
    "SUPERSEDES",
    "RELATES_TO",
    "BUY",
    "COMPETE",
    "OWNS",
    "WORKS_AT",
    "EXPOSED_TO",
}


def _unit_vec(idx: int, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    vec[idx % dim] = 1.0
    return vec


def _deterministic_embed(text: str, dim: int = DIM) -> list[float]:
    """Produce well-separated deterministic embeddings so distinct test nodes never falsely merge."""
    anchors = [
        ("acme ai", 0),
        ("beta fab", 1),
        ("gamma corp", 2),
        ("delta inc", 3),
        ("omega holdings", 4),
        ("epsilon chips", 5),
        ("alice chen", 6),
        ("bob kim", 7),
        ("zeta labs", 8),
        ("power cooling", 9),
        ("export curbs", 10),
        ("domestic reshoring", 11),
        ("edge inference", 12),
        ("capex cycle", 13),
        ("vertiv", 14),
        ("tsmc", 15),
        ("ai power", 16),
    ]
    lowered = text.lower()
    vec = [0.0] * dim
    matched = False
    for term, bucket in anchors:
        if term in lowered:
            vec[bucket] += 10.0
            matched = True
    if not matched:
        digest = hashlib.sha256(lowered.encode("utf-8")).digest()
        for i in range(dim):
            vec[i] = (digest[i % len(digest)] / 255.0) - 0.5
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _extract_section_tbody(page_html: str, section_id: str) -> str:
    pattern = (
        rf'<section\b[^>]*id="{re.escape(section_id)}"[^>]*>.*?<tbody>(.*?)</tbody>.*?</section>'
    )
    match = re.search(pattern, page_html, flags=re.DOTALL)
    assert match is not None, f"Missing <section id='{section_id}'> tbody in HTML"
    return html.unescape(match.group(1))


def _extract_all_tbodies(page_html: str) -> list[str]:
    return [
        html.unescape(m.group(1))
        for m in re.finditer(r"<tbody>(.*?)</tbody>", page_html, flags=re.DOTALL)
    ]


class _FakeWebAndAgentLLM:
    def __init__(self, script_overview_entity: str = "Vertiv") -> None:
        self.script_overview_entity = script_overview_entity

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_embed(t) for t in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **_: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        last = messages[-1]
        if last["role"] == "user":
            return AgentTurn(
                tool_calls=[
                    ToolCall(
                        name="get_entity_overview",
                        args={"entity_name_or_id": self.script_overview_entity},
                    )
                ]
            )
        if last["role"] == "tool":
            payload = last["responses"][0]["response"]
            theme_rels = [t.get("relation") for t in payload.get("themes", [])]
            peer_rels = [r.get("relation") for r in payload.get("related_entities", [])]
            return AgentTurn(
                text=(
                    f"themes={len(theme_rels)}:{theme_rels}; "
                    f"peers={len(peer_rels)}:{peer_rels}"
                )
            )
        return AgentTurn(text="OK")


def _seed_read_consolidation_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(
                id="ent_vrt",
                node_type="entity",
                name="Vertiv",
                summary="Data center thermal and power infrastructure.",
                aliases=["VRT"],
                facets={"entity_type": "company", "ticker": "VRT"},
            ),
            Node(
                id="ent_nvda",
                node_type="entity",
                name="NVIDIA",
                summary="AI GPU leader.",
                aliases=["NVDA"],
                facets={"entity_type": "company", "ticker": "NVDA"},
            ),
            Node(
                id="ent_tsmc",
                node_type="entity",
                name="TSMC",
                summary="Semiconductor foundry.",
                aliases=["TSM"],
                facets={"entity_type": "company", "ticker": "TSM"},
            ),
            Node(
                id="ent_schn",
                node_type="entity",
                name="Schneider Electric",
                summary="Power and cooling peer.",
                facets={"entity_type": "company", "ticker": "SU.PA"},
            ),
            Node(
                id="ent_parent",
                node_type="entity",
                name="Emerson HoldCo",
                summary="Industrial parent company.",
                facets={"entity_type": "company", "ticker": "EMR"},
            ),
            Node(
                id="ent_sub",
                node_type="entity",
                name="CoolTech Sub",
                summary="Liquid cooling subsidiary.",
                facets={"entity_type": "company", "ticker": "COOL"},
            ),
            Node(
                id="ent_jane",
                node_type="entity",
                name="Jane Doe",
                summary="Thermal engineering lead.",
                facets={"entity_type": "person", "role": "Thermal Lead"},
            ),
            Node(
                id="thm_power",
                node_type="theme",
                name="AI Data Center Power & Cooling",
                summary="Rack density and liquid cooling constraints.",
                facets={"stage": "accelerating"},
            ),
            Node(
                id="thm_tariff",
                node_type="theme",
                name="Supply Chain Tariff Risk",
                summary="Cross-border tariff headwinds.",
                facets={"stage": "emerging"},
            ),
            Node(
                id="thm_capex",
                node_type="theme",
                name="Hyperscaler Capex Cycle",
                summary="Mixed near-term capex digestion vs long-term growth.",
                facets={"stage": "consensus"},
            ),
            Node(
                id="evt_rack",
                node_type="event",
                name="Liquid Cooling Rack Order",
                summary="New CDU order for high-density AI racks.",
                facets={
                    "event_type": "fact",
                    "event_date": "2026-10-20",
                    "sentiment": "positive",
                    "source": {"file_path": "VRT/2026-10-20_rack.md"},
                },
                source_doc_id="doc_1",
            ),
        ]
        for idx, node in enumerate(nodes):
            db.upsert_node(node, embedding=_unit_vec(idx))

        edges = [
            # Multi-doc duplicate + reversed + RELATES_TO theme links on Vertiv -> positive
            Edge(id="e_vp1", from_id="ent_vrt", to_id="thm_power", relation="BENEFITS_FROM", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_vp2", from_id="thm_power", to_id="ent_vrt", relation="BENEFITS_FROM", source_doc_id="doc_2", facets={"basis": "extracted"}),
            Edge(id="e_vp3", from_id="ent_vrt", to_id="thm_power", relation="RELATES_TO", source_doc_id="doc_3", facets={"basis": "extracted"}),
            Edge(
                id="e_vp4",
                from_id="ent_vrt",
                to_id="thm_power",
                relation="EXPOSED_TO",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_4",
            ),
            # Indirect event link to thm_power
            Edge(id="e_ev_vrt", from_id="evt_rack", to_id="ent_vrt", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_ev_pwr", from_id="evt_rack", to_id="thm_power", relation="RELATES_TO", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Negative theme exposure across docs (one reversed)
            Edge(id="e_vt1", from_id="ent_vrt", to_id="thm_tariff", relation="HURT_BY", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_vt2", from_id="thm_tariff", to_id="ent_vrt", relation="HURT_BY", source_doc_id="doc_2", facets={"basis": "extracted"}),
            # Mixed theme exposure across docs
            Edge(id="e_vc1", from_id="ent_vrt", to_id="thm_capex", relation="BENEFITS_FROM", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_vc2", from_id="ent_vrt", to_id="thm_capex", relation="HURT_BY", source_doc_id="doc_2", facets={"basis": "extracted"}),
            # Second affected company on thm_power
            Edge(id="e_np1", from_id="ent_nvda", to_id="thm_power", relation="BENEFITS_FROM", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(
                id="e_np2",
                from_id="ent_nvda",
                to_id="thm_power",
                relation="EXPOSED_TO",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_2",
            ),
            # Entity-to-entity multi-doc/inverse/symmetric links on Vertiv
            Edge(id="e_buy1", from_id="ent_vrt", to_id="ent_tsmc", relation="CUSTOMER_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_buy2", from_id="ent_tsmc", to_id="ent_vrt", relation="SUPPLIES_TO", source_doc_id="doc_2", facets={"basis": "extracted"}),
            Edge(id="e_sell1", from_id="ent_nvda", to_id="ent_vrt", relation="CUSTOMER_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_sell2", from_id="ent_vrt", to_id="ent_nvda", relation="SUPPLIES_TO", source_doc_id="doc_2", facets={"basis": "extracted"}),
            Edge(id="e_cmp1", from_id="ent_vrt", to_id="ent_schn", relation="COMPETES_WITH", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_cmp2", from_id="ent_schn", to_id="ent_vrt", relation="COMPETES_WITH", source_doc_id="doc_2", facets={"basis": "extracted"}),
            Edge(id="e_own_sub", from_id="ent_sub", to_id="ent_vrt", relation="SUBSIDIARY_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_own_par1", from_id="ent_vrt", to_id="ent_parent", relation="SUBSIDIARY_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_own_par2", from_id="ent_parent", to_id="ent_vrt", relation="OWNS", source_doc_id="doc_2", facets={"basis": "extracted"}),
            Edge(id="e_emp1", from_id="ent_vrt", to_id="ent_jane", relation="HAS_EMPLOYEE", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_emp2", from_id="ent_vrt", to_id="ent_jane", relation="WORKS_AT", source_doc_id="doc_2", facets={"basis": "extracted"}),
        ]
        for edge in edges:
            db.upsert_edge(edge)


# ---------------------------------------------------------------------------
# Witness 1: Read-side consolidation & natural UX labels + find_theme_companies
# ---------------------------------------------------------------------------


def test_read_side_consolidation_and_natural_ux_labels(tmp_path: Path) -> None:
    db_path = tmp_path / "read_consolidation.db"
    reg_path = tmp_path / "ontology_registry.json"
    _seed_read_consolidation_db(db_path)
    save_registry(create_minimal_registry(), reg_path)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        ov_vrt = ro.get_entity_overview("ent_vrt")
        themes_by_id = {t["id"]: t for t in ov_vrt["themes"]}
        assert len(ov_vrt["themes"]) == 3
        assert set(themes_by_id.keys()) == {"thm_power", "thm_tariff", "thm_capex"}
        for thm in ov_vrt["themes"]:
            assert thm["relation"] == "EXPOSED_TO"

        def _polarity(thm_item: dict[str, Any]) -> Any:
            return thm_item.get("exposure_sentiment") or thm_item.get("edge_facets", {}).get("sentiment")

        assert _polarity(themes_by_id["thm_power"]) == "positive"
        assert _polarity(themes_by_id["thm_tariff"]) == "negative"
        assert _polarity(themes_by_id["thm_capex"]) == "mixed"

        peers_by_id = {p["id"]: p for p in ov_vrt["related_entities"]}
        assert len(ov_vrt["related_entities"]) == 6
        assert set(peers_by_id.keys()) == {
            "ent_tsmc",
            "ent_nvda",
            "ent_schn",
            "ent_sub",
            "ent_parent",
            "ent_jane",
        }
        assert (peers_by_id["ent_tsmc"]["relation"], peers_by_id["ent_tsmc"]["direction"]) == ("BUY", "outgoing")
        assert (peers_by_id["ent_nvda"]["relation"], peers_by_id["ent_nvda"]["direction"]) == ("BUY", "incoming")
        assert (peers_by_id["ent_schn"]["relation"], peers_by_id["ent_schn"]["direction"]) == ("COMPETE", "mutual")
        assert (peers_by_id["ent_sub"]["relation"], peers_by_id["ent_sub"]["direction"]) == ("OWNS", "outgoing")
        assert (peers_by_id["ent_parent"]["relation"], peers_by_id["ent_parent"]["direction"]) == ("OWNS", "incoming")
        assert (peers_by_id["ent_jane"]["relation"], peers_by_id["ent_jane"]["direction"]) == ("WORKS_AT", "incoming")

        ov_jane = ro.get_entity_overview("ent_jane")
        assert len(ov_jane["related_entities"]) == 1
        assert ov_jane["related_entities"][0]["id"] == "ent_vrt"
        assert ov_jane["related_entities"][0]["relation"] == "WORKS_AT"
        assert ov_jane["related_entities"][0]["direction"] == "outgoing"

        theme_res = ro.find_theme_companies("thm_power")
        first_by_id = {row["company"]["id"]: row for row in theme_res["companies"]}
        assert len(theme_res["companies"]) == 2
        assert set(first_by_id.keys()) == {"ent_vrt", "ent_nvda"}

        vrt_direct = [lk for lk in first_by_id["ent_vrt"]["links"] if lk["via"] == "direct"]
        nvda_direct = [lk for lk in first_by_id["ent_nvda"]["links"] if lk["via"] == "direct"]
        assert len(vrt_direct) == 1
        assert vrt_direct[0]["relation"] == "EXPOSED_TO"
        assert (vrt_direct[0].get("exposure_sentiment") or vrt_direct[0].get("facets", {}).get("sentiment")) == "positive"
        assert len(nvda_direct) == 1
        assert nvda_direct[0]["relation"] == "EXPOSED_TO"

        assert "second_order" not in theme_res

        bfs = ro.traverse_bfs("ent_vrt", max_hops=1)
        bfs_vrt_thm = [
            e for e in bfs["edges"] if {e["from_id"], e["to_id"]} == {"ent_vrt", "thm_power"}
        ]
        assert len(bfs_vrt_thm) == 1
        assert (bfs_vrt_thm[0]["from_id"], bfs_vrt_thm[0]["relation"], bfs_vrt_thm[0]["to_id"]) == (
            "ent_vrt",
            "EXPOSED_TO",
            "thm_power",
        )
        bfs_vrt_schn = [
            e for e in bfs["edges"] if {e["from_id"], e["to_id"]} == {"ent_vrt", "ent_schn"}
        ]
        assert len(bfs_vrt_schn) == 1
        assert bfs_vrt_schn[0]["relation"] == "COMPETE"

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path, registry_path=reg_path)
    client = TestClient(create_app(settings, llm=_FakeWebAndAgentLLM()))

    r_vrt = client.get("/entity/ent_vrt")
    assert r_vrt.status_code == 200
    sec_themes = _extract_section_tbody(r_vrt.text, "sec-themes")
    assert sec_themes.count("AI Data Center Power & Cooling") == 1
    assert sec_themes.count("Supply Chain Tariff Risk") == 1
    assert sec_themes.count("Hyperscaler Capex Cycle") == 1
    assert "exposed to" in sec_themes.lower()
    for pol in ("positive", "negative", "mixed"):
        assert pol in sec_themes.lower()
    for legacy in ("BENEFITS_FROM", "HURT_BY", "RELATES_TO"):
        assert legacy not in sec_themes

    sec_related = _extract_section_tbody(r_vrt.text, "sec-related")
    for name in ("TSMC", "NVIDIA", "Schneider Electric", "CoolTech Sub", "Emerson HoldCo", "Jane Doe"):
        assert sec_related.count(name) == 1
    for label in ("buys from", "sells to", "competes with", "owned by", "employs"):
        assert label in sec_related.lower()
    assert re.search(r"\bowns\b", sec_related.lower()) is not None
    for forbidden in (
        "(outgoing)",
        "(incoming)",
        "SUPPLIES_TO",
        "CUSTOMER_OF",
        "COMPETES_WITH",
        "SUBSIDIARY_OF",
        "HAS_EMPLOYEE",
    ):
        assert forbidden not in sec_related

    r_jane = client.get("/entity/ent_jane")
    assert r_jane.status_code == 200
    jane_related = _extract_section_tbody(r_jane.text, "sec-related")
    assert jane_related.count("Vertiv") == 1
    assert "works at" in jane_related.lower()
    assert "HAS_EMPLOYEE" not in jane_related

    r_theme = client.get("/theme/thm_power")
    assert r_theme.status_code == 200
    tbodies = _extract_all_tbodies(r_theme.text)
    first_tbody = tbodies[0]
    assert first_tbody.count("Vertiv") == 1
    assert first_tbody.count("NVIDIA") == 1
    assert "exposed to" in first_tbody.lower()
    assert "positive" in first_tbody.lower()
    assert "BENEFITS_FROM" not in first_tbody

    # The theme page lists affected companies only; their peers and suppliers are not shown.
    for name in ("TSMC", "Schneider Electric", "Emerson HoldCo", "CoolTech Sub"):
        assert name not in r_theme.text


# ---------------------------------------------------------------------------
# Witness 2: Write-side normalization, OOV queueing, & directed catalog
# ---------------------------------------------------------------------------


class _WriteNormalizationFakeLLM:
    def __init__(self) -> None:
        self.catalogs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_embed(t) for t in texts]

    def extract_document(self, *, existing_catalog: str, **_: Any) -> ExtractionResult:
        self.catalogs.append(existing_catalog)
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="c_buyer", name="Acme AI", summary="AI server OEM.", entity_type="company"),
                ExtractedEntity(temp_id="c_seller", name="Beta Fab", summary="Chip foundry.", entity_type="company"),
                ExtractedEntity(temp_id="c_comp1", name="Gamma Corp", summary="Peer 1.", entity_type="company"),
                ExtractedEntity(temp_id="c_comp2", name="Delta Inc", summary="Peer 2.", entity_type="company"),
                ExtractedEntity(temp_id="c_parent", name="Omega Holdings", summary="Parent holdco.", entity_type="company"),
                ExtractedEntity(temp_id="c_child", name="Epsilon Chips", summary="Subsidiary.", entity_type="company"),
                ExtractedEntity(temp_id="p_alice", name="Alice Chen", summary="VP Eng.", entity_type="person"),
                ExtractedEntity(temp_id="p_bob", name="Bob Kim", summary="CTO.", entity_type="person"),
                ExtractedEntity(temp_id="c_org", name="Zeta Labs", summary="Research lab.", entity_type="company"),
            ],
            themes=[
                ExtractedTheme(temp_id="t_pos", name="Power Cooling", summary="Cooling demand.", stage="accelerating"),
                ExtractedTheme(temp_id="t_neg", name="Export Curbs", summary="Tariff & export risk.", stage="accelerating"),
                ExtractedTheme(temp_id="t_rev", name="Domestic Reshoring", summary="US fab buildout.", stage="accelerating"),
                ExtractedTheme(temp_id="t_rel", name="Edge Inference", summary="On-device inference.", stage="accelerating"),
                ExtractedTheme(temp_id="t_mix", name="Capex Cycle", summary="Mixed capex cycle.", stage="accelerating"),
            ],
            edges=[
                ExtractedEdge(from_ref="c_seller", to_ref="c_buyer", relation="SUPPLIES_TO"),
                ExtractedEdge(from_ref="c_buyer", to_ref="c_parent", relation="CUSTOMER_OF"),
                ExtractedEdge(from_ref="c_comp2", to_ref="c_comp1", relation="COMPETES_WITH"),
                ExtractedEdge(from_ref="c_comp1", to_ref="c_comp2", relation="COMPETES_WITH"),
                ExtractedEdge(from_ref="c_child", to_ref="c_parent", relation="SUBSIDIARY_OF"),
                ExtractedEdge(from_ref="c_org", to_ref="p_alice", relation="HAS_EMPLOYEE"),
                ExtractedEdge(from_ref="c_org", to_ref="p_bob", relation="WORKS_AT"),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_pos", relation="BENEFITS_FROM"),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_pos", relation="RELATES_TO"),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_neg", relation="HURT_BY"),
                ExtractedEdge(
                    from_ref="t_rev",
                    to_ref="c_buyer",
                    relation="EXPOSED_TO",
                    facets=[FacetKV(key="sentiment", value="positive")],
                ),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_rel", relation="RELATES_TO"),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_mix", relation="BENEFITS_FROM"),
                ExtractedEdge(from_ref="c_buyer", to_ref="t_mix", relation="HURT_BY"),
                ExtractedEdge(from_ref="c_buyer", to_ref="c_seller", relation="PARTNERS_WITH"),
            ],
        )

    def synthesize_consensus(self, **_: Any) -> ConsensusSynthesis:
        return ConsensusSynthesis(stance="neutral", support_strength="weak", conviction="low", summary="Neutral.")


def test_write_side_normalization_oov_queueing_and_catalog_signatures(tmp_path: Path) -> None:
    reg = create_minimal_registry()
    assert {spec.name for spec in reg.relations} == EXPECTED_OFFICIAL_RELATIONS
    repo_reg = load_registry(REPO_ROOT / "ontology_registry.json")
    assert {spec.name for spec in repo_reg.relations} == EXPECTED_OFFICIAL_RELATIONS

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "note.md").write_text("Research update across supply chain.", encoding="utf-8")

    db_path = tmp_path / "write_norm.db"
    llm = _WriteNormalizationFakeLLM()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=reg).run()
        assert report.errors == []

        assert len(llm.catalogs) == 1
        catalog_lines = llm.catalogs[0].splitlines()
        for rel in ("BUY", "OWNS", "WORKS_AT", "EXPOSED_TO"):
            assert any(rel in line and "->" in line for line in catalog_lines), (
                f"Expected directed signature for {rel} in extraction catalog"
            )
        assert "COMPETE" in llm.catalogs[0]

        by_name = {n.name: n.id for n in db.list_all_nodes()}
        rows = db.conn.execute("SELECT from_id, relation, to_id, facets_json FROM edges").fetchall()
        triples = {(r["from_id"], r["relation"], r["to_id"]) for r in rows}

        assert (by_name["Acme AI"], "BUY", by_name["Beta Fab"]) in triples
        assert (by_name["Acme AI"], "BUY", by_name["Omega Holdings"]) in triples
        assert (by_name["Omega Holdings"], "OWNS", by_name["Epsilon Chips"]) in triples
        assert (by_name["Alice Chen"], "WORKS_AT", by_name["Zeta Labs"]) in triples
        assert (by_name["Bob Kim"], "WORKS_AT", by_name["Zeta Labs"]) in triples
        assert (by_name["Acme AI"], "EXPOSED_TO", by_name["Edge Inference"]) in triples
        assert (by_name["Acme AI"], "PARTNERS_WITH", by_name["Beta Fab"]) in triples

        compete_rows = [
            r for r in rows
            if r["relation"] == "COMPETE"
            and {r["from_id"], r["to_id"]} == {by_name["Gamma Corp"], by_name["Delta Inc"]}
        ]
        assert len(compete_rows) == 1
        assert compete_rows[0]["from_id"] < compete_rows[0]["to_id"]

        def _edge_facets(theme_name: str) -> dict[str, Any]:
            matched = [
                json.loads(r["facets_json"])
                for r in rows
                if r["from_id"] == by_name["Acme AI"]
                and r["relation"] == "EXPOSED_TO"
                and r["to_id"] == by_name[theme_name]
            ]
            assert len(matched) == 1
            return matched[0]

        assert _edge_facets("Power Cooling").get("sentiment") == "positive"
        assert _edge_facets("Export Curbs").get("sentiment") == "negative"
        assert _edge_facets("Domestic Reshoring").get("sentiment") == "positive"
        assert _edge_facets("Capex Cycle").get("sentiment") == "mixed"

        stored_rels = {r["relation"] for r in rows}
        assert stored_rels.isdisjoint(
            {"SUPPLIES_TO", "CUSTOMER_OF", "COMPETES_WITH", "SUBSIDIARY_OF", "HAS_EMPLOYEE", "BENEFITS_FROM", "HURT_BY"}
        )

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        audit_rep = run_ontology_audit(ro, reg)

    assert audit_rep.summary.direction_issue_edges == 0
    assert [r.name for r in audit_rep.unmapped_relations] == ["PARTNERS_WITH"]
    sync_sum = reg.sync_suggestions(
        audit_rep.unmapped_relations,
        audit_rep.unmapped_companies,
        audit_rep.unmapped_themes,
    )
    assert sync_sum.pending_relations == 1
    partner_sug = next(s for s in reg.suggestions.relations if s.name == "PARTNERS_WITH")
    assert partner_sug.status == "pending"


# ---------------------------------------------------------------------------
# Witness 3: Registry-driven repair & contradiction audit
# ---------------------------------------------------------------------------


def test_registry_driven_repair_and_reciprocal_contradiction_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_repair.db"
    reg = create_minimal_registry()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes = [
            Node(id="ent_a", node_type="entity", name="Acme Corp", summary="A.", facets={"entity_type": "company"}),
            Node(id="ent_b", node_type="entity", name="Beta Inc", summary="B.", facets={"entity_type": "company"}),
            Node(id="ent_c", node_type="entity", name="Gamma Ltd", summary="C.", facets={"entity_type": "company"}),
            Node(id="ent_d", node_type="entity", name="Delta Corp", summary="D.", facets={"entity_type": "company"}),
            Node(id="ent_parent", node_type="entity", name="HoldCo", summary="Parent.", facets={"entity_type": "company"}),
            Node(id="ent_child", node_type="entity", name="SubCo", summary="Sub.", facets={"entity_type": "company"}),
            Node(id="ent_p1", node_type="entity", name="Alice", summary="Analyst.", facets={"entity_type": "person"}),
            Node(id="ent_p2", node_type="entity", name="Bob", summary="Engineer.", facets={"entity_type": "person"}),
            Node(id="thm_1", node_type="theme", name="Power Cooling", summary="T1.", facets={"stage": "accelerating"}),
            Node(id="thm_2", node_type="theme", name="Tariff Risk", summary="T2.", facets={"stage": "accelerating"}),
            Node(id="thm_3", node_type="theme", name="AI Capex", summary="T3.", facets={"stage": "accelerating"}),
            Node(id="thm_4", node_type="theme", name="Grid Expansion", summary="T4.", facets={"stage": "accelerating"}),
        ]
        for idx, node in enumerate(nodes):
            db.upsert_node(node, embedding=_unit_vec(idx))

        db.upsert_ingestion_log("notes/doc1.md", "doc_1", "h1", "2026-11-22T00:00:00+00:00")
        db.upsert_ingestion_log("notes/doc2.md", "doc_2", "h2", "2026-11-22T00:00:00+00:00")

        legacy_edges = [
            # SUPPLIES_TO + CUSTOMER_OF in same doc collapse to single (ent_a, BUY, ent_b)
            Edge(id="e_sup", from_id="ent_b", to_id="ent_a", relation="SUPPLIES_TO", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_cust", from_id="ent_a", to_id="ent_b", relation="CUSTOMER_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Opposite COMPETES_WITH in same doc collapse to single canonical-order COMPETE
            Edge(id="e_cmp_ba", from_id="ent_b", to_id="ent_a", relation="COMPETES_WITH", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_cmp_ab", from_id="ent_a", to_id="ent_b", relation="COMPETES_WITH", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # SUBSIDIARY_OF -> OWNS
            Edge(id="e_sub", from_id="ent_child", to_id="ent_parent", relation="SUBSIDIARY_OF", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # HAS_EMPLOYEE & reversed WORKS_AT -> person WORKS_AT org
            Edge(id="e_emp", from_id="ent_a", to_id="ent_p1", relation="HAS_EMPLOYEE", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_wrk_rev", from_id="ent_a", to_id="ent_p2", relation="WORKS_AT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Same-doc duplicate theme links with earliest ID empty-facets RELATES_TO must preserve facets on collapse
            Edge(id="e_01_rel", from_id="ent_a", to_id="thm_1", relation="RELATES_TO", facets={"basis": "extracted"}, source_doc_id="doc_1"),
            Edge(id="e_02_ben", from_id="ent_a", to_id="thm_1", relation="BENEFITS_FROM", facets={"basis": "extracted"}, source_doc_id="doc_1"),
            Edge(
                id="e_03_rev",
                from_id="thm_1",
                to_id="ent_a",
                relation="EXPOSED_TO",
                facets={"evidence": "rack power", "basis": "extracted"},
                source_doc_id="doc_1",
            ),
            # HURT_BY -> EXPOSED_TO negative
            Edge(id="e_hurt", from_id="ent_a", to_id="thm_2", relation="HURT_BY", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # BENEFITS_FROM + HURT_BY in same doc -> mixed
            Edge(id="e_mix_1", from_id="ent_a", to_id="thm_3", relation="BENEFITS_FROM", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_mix_2", from_id="ent_a", to_id="thm_3", relation="HURT_BY", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Entity-theme RELATES_TO -> EXPOSED_TO
            Edge(id="e_rel_4", from_id="ent_a", to_id="thm_4", relation="RELATES_TO", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Unmapped relation kept intact
            Edge(id="e_unm", from_id="ent_a", to_id="ent_c", relation="PARTNERS_WITH", source_doc_id="doc_1", facets={"basis": "extracted"}),
            # Reciprocal BUY contradiction across docs (must not guess direction)
            Edge(id="e_rcp_1", from_id="ent_c", to_id="ent_d", relation="SUPPLIES_TO", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="e_rcp_2", from_id="ent_d", to_id="ent_c", relation="SUPPLIES_TO", source_doc_id="doc_2", facets={"basis": "extracted"}),
        ]
        for edge in legacy_edges:
            db.upsert_edge(edge)

        rep1 = repair_ontology(db, reg)
        assert rep1.total_changes > 0

        rows = db.conn.execute(
            "SELECT from_id, relation, to_id, facets_json, source_doc_id FROM edges ORDER BY from_id, relation, to_id"
        ).fetchall()
        triples = [(r["from_id"], r["relation"], r["to_id"]) for r in rows]

        assert triples.count(("ent_a", "BUY", "ent_b")) == 1
        assert triples.count(("ent_a", "COMPETE", "ent_b")) == 1
        assert ("ent_b", "COMPETE", "ent_a") not in triples
        assert ("ent_parent", "OWNS", "ent_child") in triples
        assert ("ent_p1", "WORKS_AT", "ent_a") in triples
        assert ("ent_p2", "WORKS_AT", "ent_a") in triples
        assert ("ent_a", "PARTNERS_WITH", "ent_c") in triples
        assert ("ent_d", "BUY", "ent_c") in triples
        assert ("ent_c", "BUY", "ent_d") in triples
        assert ("ent_a", "EXPOSED_TO", "thm_4") in triples

        t1_rows = [r for r in rows if (r["from_id"], r["relation"], r["to_id"]) == ("ent_a", "EXPOSED_TO", "thm_1")]
        assert len(t1_rows) == 1
        t1_facets = json.loads(t1_rows[0]["facets_json"])
        assert t1_facets.get("sentiment") == "positive"
        assert t1_facets.get("evidence") == "rack power"

        t2_rows = [r for r in rows if (r["from_id"], r["relation"], r["to_id"]) == ("ent_a", "EXPOSED_TO", "thm_2")]
        assert len(t2_rows) == 1
        assert json.loads(t2_rows[0]["facets_json"]).get("sentiment") == "negative"

        t3_rows = [r for r in rows if (r["from_id"], r["relation"], r["to_id"]) == ("ent_a", "EXPOSED_TO", "thm_3")]
        assert len(t3_rows) == 1
        assert json.loads(t3_rows[0]["facets_json"]).get("sentiment") == "mixed"

        assert {rel for _, rel, _ in triples}.isdisjoint(
            {"SUPPLIES_TO", "CUSTOMER_OF", "COMPETES_WITH", "SUBSIDIARY_OF", "HAS_EMPLOYEE", "BENEFITS_FROM", "HURT_BY", "RELATES_TO"}
        )

        snapshot_after_first = [tuple(r) for r in rows]
        rep2 = repair_ontology(db, reg)
        assert rep2.total_changes == 0
        rows_after_second = [
            tuple(r)
            for r in db.conn.execute(
                "SELECT from_id, relation, to_id, facets_json, source_doc_id FROM edges ORDER BY from_id, relation, to_id"
            ).fetchall()
        ]
        assert rows_after_second == snapshot_after_first

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        audit_rep = run_ontology_audit(ro, reg)

    assert audit_rep.summary.reciprocal_contradiction_pairs == 1
    assert len(audit_rep.reciprocal_contradictions) == 1
    contradiction_blob = json.dumps(audit_rep.reciprocal_contradictions[0].model_dump())
    assert "BUY" in contradiction_blob
    assert ("ent_c" in contradiction_blob or "Gamma Ltd" in contradiction_blob)
    assert ("ent_d" in contradiction_blob or "Delta Corp" in contradiction_blob)
    assert [r.name for r in audit_rep.unmapped_relations] == ["PARTNERS_WITH"]
    assert audit_rep.summary.direction_issue_edges == 0


# ---------------------------------------------------------------------------
# Guardrail 1: Strictly read-only OntologyAgent, Web UI, inspect, and audit
# ---------------------------------------------------------------------------


def test_guardrail_read_only_agent_web_inspect_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "guardrail_ro.db"
    reg_path = tmp_path / "ontology_registry.json"
    _seed_read_consolidation_db(db_path)
    reg = create_minimal_registry()
    save_registry(reg, reg_path)
    reg_bytes_before = reg_path.read_bytes()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as rw_db:
        nodes_before = [tuple(r) for r in rw_db.conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()]
        edges_before = [tuple(r) for r in rw_db.conn.execute("SELECT * FROM edges ORDER BY id").fetchall()]
        with pytest.raises(ValueError, match="read-only"):
            OntologyAgent(rw_db, _FakeWebAndAgentLLM())

    llm = _FakeWebAndAgentLLM(script_overview_entity="Vertiv")
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        assert ro_db.conn.execute("PRAGMA query_only").fetchone()[0] == 1
        agent = OntologyAgent(ro_db, llm)
        reply = agent.ask("Summarize Vertiv relationships")
        assert "EXPOSED_TO" in reply
        assert "BUY" in reply
        audit_rep = run_ontology_audit(ro_db, reg)
        assert audit_rep.summary.total_edges > 0

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path, registry_path=reg_path)
    client = TestClient(create_app(settings, llm=llm))
    for path in ("/entity/ent_vrt", "/theme/thm_power", "/ontology", "/ontology?tab=edges", "/ontology?tab=audit"):
        assert client.get(path).status_code == 200
    assert client.post("/api/chat", json={"message": "Check Vertiv"}).status_code == 200

    monkeypatch.setenv("EMBEDDING_DIM", str(DIM))
    monkeypatch.setenv("ONTOLOGY_REGISTRY", str(reg_path))
    runner = CliRunner()
    res_inspect = runner.invoke(cli_app, ["inspect", "Vertiv", "--db", str(db_path)])
    assert res_inspect.exit_code == 0, res_inspect.output
    inspect_norm = " ".join(res_inspect.stdout.split())
    assert "buys from" in inspect_norm.lower()
    assert "exposed to" in inspect_norm.lower()
    assert "SUPPLIES_TO" not in inspect_norm
    assert "BENEFITS_FROM" not in inspect_norm

    res_audit = runner.invoke(
        cli_app,
        ["audit", "--db", str(db_path), "--registry", str(reg_path), "--no-sync-suggestions", "--json"],
    )
    assert res_audit.exit_code == 0, res_audit.output

    assert reg_path.read_bytes() == reg_bytes_before
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_after:
        nodes_after = [tuple(r) for r in ro_after.conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()]
        edges_after = [tuple(r) for r in ro_after.conn.execute("SELECT * FROM edges ORDER BY id").fetchall()]
        assert nodes_after == nodes_before
        assert edges_after == edges_before


# ---------------------------------------------------------------------------
# Guardrail 2: Event/view dedup consistency & single-note deletion retention
# ---------------------------------------------------------------------------


class _TwoNoteDeletionFakeLLM:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_embed(t) for t in texts]

    def extract_document(self, *, source_meta: dict[str, Any], **_: Any) -> ExtractionResult:
        rel_path = source_meta["file_path"]
        is_a = "note_a" in rel_path
        evt_id = "ev_a" if is_a else "ev_b"
        evt_name = "Note A Event" if is_a else "Note B Event"
        supply_edge = (
            ExtractedEdge(from_ref="c_vrt", to_ref="c_tsmc", relation="CUSTOMER_OF")
            if is_a
            else ExtractedEdge(from_ref="c_tsmc", to_ref="c_vrt", relation="SUPPLIES_TO")
        )
        theme_edge = (
            ExtractedEdge(from_ref="c_vrt", to_ref="t_pwr", relation="BENEFITS_FROM")
            if is_a
            else ExtractedEdge(
                from_ref="c_vrt",
                to_ref="t_pwr",
                relation="EXPOSED_TO",
                facets=[FacetKV(key="sentiment", value="positive")],
            )
        )
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="c_vrt", name="Vertiv", summary="Cooling infra.", entity_type="company"),
                ExtractedEntity(temp_id="c_tsmc", name="TSMC", summary="Foundry.", entity_type="company"),
            ],
            themes=[
                ExtractedTheme(temp_id="t_pwr", name="AI Power", summary="Power bottleneck.", stage="accelerating"),
            ],
            events=[
                ExtractedEvent(temp_id=evt_id, name=evt_name, summary=f"Fact from {rel_path}.", sentiment="positive", event_type="fact"),
            ],
            edges=[
                ExtractedEdge(from_ref=evt_id, to_ref="c_vrt", relation="ABOUT"),
                supply_edge,
                theme_edge,
            ],
        )

    def synthesize_consensus(self, **_: Any) -> ConsensusSynthesis:
        return ConsensusSynthesis(stance="buy", support_strength="moderate", conviction="medium", summary="Bullish.")


def test_guardrail_event_view_dedup_and_single_note_deletion_retention(tmp_path: Path) -> None:
    dedup_db_path = tmp_path / "ev_dedup.db"
    with OntologyDB(dedup_db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(id="ent_nvda", node_type="entity", name="NVIDIA", summary="GPU.", facets={"entity_type": "company"})
        evt = Node(
            id="evt_multi",
            node_type="event",
            name="Rack Ramp",
            summary="Blackwell shipping.",
            facets={"event_type": "fact", "event_date": "2026-10-15", "sentiment": "neutral"},
            source_doc_id="doc_1",
        )
        vw = Node(
            id="vw_multi",
            node_type="view",
            name="Margin Risk",
            summary="Watch GM.",
            facets={"view_type": "analyst_report", "as_of": "2026-10-16", "stance": "hold", "sentiment": "neutral"},
            source_doc_id="doc_1",
        )
        for idx, node in enumerate([nvda, evt, vw]):
            db.upsert_node(node, embedding=_unit_vec(idx))
        # Secondary non-ABOUT edge inserted first, ABOUT edge with entity-level sentiment override second.
        db.upsert_edge(Edge(id="e_m1", from_id="evt_multi", to_id="ent_nvda", relation="MENTIONS", source_doc_id="doc_1", facets={"basis": "extracted"}))
        db.upsert_edge(
            Edge(
                id="e_a1",
                from_id="evt_multi",
                to_id="ent_nvda",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(Edge(id="e_m2", from_id="vw_multi", to_id="ent_nvda", relation="MENTIONS", source_doc_id="doc_1", facets={"basis": "extracted"}))
        db.upsert_edge(
            Edge(
                id="e_a2",
                from_id="vw_multi",
                to_id="ent_nvda",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )

    with OntologyDB(dedup_db_path, embedding_dim=DIM, read_only=True) as ro:
        ov = ro.get_entity_overview("ent_nvda")
        sig = ro.query_entity_signals("ent_nvda")
        assert len(ov["events"]) == 1
        assert ov["events"][0]["id"] == "evt_multi"
        assert ov["events"][0]["relation"] == "ABOUT"
        assert ov["events"][0]["effective_sentiment"] == "positive"

        assert len(ov["views"]) == 1
        assert ov["views"][0]["id"] == "vw_multi"
        assert ov["views"][0]["relation"] == "ABOUT"
        assert ov["views"][0]["effective_sentiment"] == "negative"

        assert {it["id"] for it in sig["items"]} == {"evt_multi", "vw_multi"}
        assert {it["id"] for it in ov["events"] + ov["views"]} == {it["id"] for it in sig["items"]}

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    note_a = data_dir / "note_a.md"
    note_b = data_dir / "note_b.md"
    note_a.write_text("Note A: Vertiv buys from TSMC and benefits from AI Power.", encoding="utf-8")
    note_b.write_text("Note B: TSMC supplies to Vertiv; Vertiv exposed to AI Power.", encoding="utf-8")

    del_db_path = tmp_path / "delete_retention.db"
    reg = create_minimal_registry()
    with OntologyDB(del_db_path, embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, _TwoNoteDeletionFakeLLM(), data_dir, registry=reg)
        rep1 = pipeline.run()
        assert rep1.errors == []

        vrt_id = db.find_by_name_or_alias("Vertiv", node_type="entity").id
        tsmc_id = db.find_by_name_or_alias("TSMC", node_type="entity").id
        pwr_id = db.find_by_name_or_alias("AI Power", node_type="theme").id
        ov1 = db.get_entity_overview(vrt_id)
        assert [p["id"] for p in ov1["related_entities"]] == [tsmc_id]
        assert ov1["related_entities"][0]["relation"] == "BUY"
        assert [t["id"] for t in ov1["themes"]] == [pwr_id]
        assert ov1["themes"][0]["relation"] == "EXPOSED_TO"

        note_a.unlink()
        rep2 = pipeline.run()
        assert rep2.files_deleted == 1

        ov2 = db.get_entity_overview(vrt_id)
        assert [ev["name"] for ev in ov2["events"]] == ["Note B Event"]
        assert [p["id"] for p in ov2["related_entities"]] == [tsmc_id]
        assert ov2["related_entities"][0]["relation"] == "BUY"
        assert ov2["related_entities"][0]["direction"] == "outgoing"
        assert [t["id"] for t in ov2["themes"]] == [pwr_id]
        assert ov2["themes"][0]["relation"] == "EXPOSED_TO"
        assert (
            ov2["themes"][0].get("exposure_sentiment")
            or ov2["themes"][0].get("edge_facets", {}).get("sentiment")
        ) == "positive"


# ---------------------------------------------------------------------------
# Guardrail 3: 6-locale key/placeholder parity & no mention-count badges in UI
# ---------------------------------------------------------------------------


def test_guardrail_locale_parity_and_no_mention_count_badges(tmp_path: Path) -> None:
    assert SUPPORTED_LANGUAGE_CODES == ("en", "zh", "ko", "ja", "es", "fr")
    load_catalogs.cache_clear()
    catalogs = load_catalogs()
    assert set(catalogs.keys()) == set(SUPPORTED_LANGUAGE_CODES)

    en_data = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
    en_keys = set(en_data.keys())
    for code in SUPPORTED_LANGUAGE_CODES:
        raw = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
        assert set(raw.keys()) == en_keys, f"{code}.json key parity failed"
        for key, value in raw.items():
            assert isinstance(value, str) and value.strip(), f"{code}.json empty key {key}"
            assert "&amp;" not in value and "&lt;" not in value and "&gt;" not in value
            assert set(PLACEHOLDER_RE.findall(value)) == set(PLACEHOLDER_RE.findall(en_data[key]))

    db_path = tmp_path / "i18n_ui.db"
    reg_path = tmp_path / "ontology_registry.json"
    _seed_read_consolidation_db(db_path)
    save_registry(create_minimal_registry(), reg_path)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path, registry_path=reg_path)
    client = TestClient(create_app(settings, llm=_FakeWebAndAgentLLM()))

    r_en = client.get("/entity/ent_vrt?lang=en")
    assert r_en.status_code == 200
    en_themes = _extract_section_tbody(r_en.text, "sec-themes")
    en_related = _extract_section_tbody(r_en.text, "sec-related")
    assert en_themes.count("AI Data Center Power & Cooling") == 1
    assert en_related.count("TSMC") == 1
    # thm_power has 4 raw edges; ent_tsmc/ent_nvda/etc. have 2 raw edges -> no mention-count badges allowed.
    for forbidden_badge in ("4x", "4×", "(4)", "2x", "2×", "(2)", "mentions", "mentioned"):
        assert forbidden_badge not in en_themes.lower()
        assert forbidden_badge not in en_related.lower()

    r_theme_en = client.get("/theme/thm_power?lang=en")
    assert r_theme_en.status_code == 200
    t_bodies = _extract_all_tbodies(r_theme_en.text)
    assert t_bodies[0].count("Vertiv") == 1
    for forbidden_badge in ("4x", "4×", "(4)", "2x", "2×", "(2)", "mentions", "mentioned"):
        assert forbidden_badge not in t_bodies[0].lower()

    for code in ("zh", "ko", "ja", "es", "fr"):
        r_loc = client.get(f"/entity/ent_vrt?lang={code}")
        assert r_loc.status_code == 200
        loc_themes = _extract_section_tbody(r_loc.text, "sec-themes")
        loc_related = _extract_section_tbody(r_loc.text, "sec-related")
        assert loc_themes.count("AI Data Center Power & Cooling") == 1
        assert loc_related.count("TSMC") == 1
        for raw_rel in ("EXPOSED_TO", "BUY", "OWNS", "WORKS_AT", "SUPPLIES_TO", "BENEFITS_FROM"):
            assert raw_rel not in loc_themes
            assert raw_rel not in loc_related
        assert "buys from" not in loc_related.lower()
        assert "exposed to" not in loc_themes.lower()
