"""Offline unit tests for ontology_registry, read-only audit, suggestion sync, and CLI."""

from __future__ import annotations

import json
import math
from pathlib import Path

from typer.testing import CliRunner

from stock_ontology.audit import run_ontology_audit
from stock_ontology.cli import app
from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.registry import (
    CompanySpec,
    create_minimal_registry,
    load_registry,
    normalize_ticker,
    save_registry,
)

DIM = 16


def _unit_vec(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[idx % DIM] = 1.0
    return v


def _norm_vec(values: list[float]) -> list[float]:
    padded = list(values) + [0.0] * (DIM - len(values))
    norm = math.sqrt(sum(x * x for x in padded)) or 1.0
    return [x / norm for x in padded]


def _seed_audit_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nodes_and_vecs = [
            (
                Node(
                    id="ent_nvda",
                    node_type="entity",
                    name="NVIDIA",
                    summary="AI GPU leader.",
                    aliases=["NVDA"],
                    facets={"entity_type": "company", "ticker": "NVDA", "sector": "Semiconductors"},
                ),
                _unit_vec(0),
            ),
            (
                Node(
                    id="ent_aapl",
                    node_type="entity",
                    name="Apple Inc.",
                    summary="Consumer devices.",
                    aliases=["AAPL", "Apple"],
                    facets={"entity_type": "company", "ticker": "AAPL"},
                ),
                _unit_vec(1),
            ),
            (
                Node(
                    id="ent_vrt",
                    node_type="entity",
                    name="Vertiv",
                    summary="Liquid cooling.",
                    aliases=["VRT", "Vertiv Holdings Co."],
                    facets={"entity_type": "company", "ticker": "NYSE: VRT"},
                ),
                _unit_vec(2),
            ),
            (
                Node(
                    id="ent_amd",
                    node_type="entity",
                    name="AMD",
                    summary="Data center GPU challenger.",
                    aliases=[],
                    facets={"entity_type": "company", "ticker": "AMD"},
                ),
                _unit_vec(3),
            ),
            (
                Node(
                    id="ent_dell",
                    node_type="entity",
                    name="Dell",
                    summary="Server OEM.",
                    aliases=["HPE"],
                    facets={"entity_type": "company"},
                ),
                _unit_vec(4),
            ),
            (
                Node(
                    id="ent_fab20",
                    node_type="entity",
                    name="Fab 20",
                    summary="2nm fab in Hsinchu.",
                    aliases=["Fab 22"],
                    facets={"entity_type": "institution"},
                ),
                _unit_vec(5),
            ),
            (
                Node(
                    id="ent_glj",
                    node_type="entity",
                    name="GLJ Research",
                    summary="Independent research firm.",
                    aliases=["Gordon Johnson"],
                    facets={"entity_type": "institution"},
                ),
                _unit_vec(6),
            ),
            (
                Node(
                    id="ent_citi",
                    node_type="entity",
                    name="Citi",
                    summary="Sell-side bank.",
                    aliases=["Citigroup"],
                    facets={"entity_type": "institution"},
                ),
                _unit_vec(7),
            ),
            (
                Node(
                    id="ent_pcc",
                    node_type="entity",
                    name="Private Cloud Compute",
                    summary="Confidential inference cluster.",
                    aliases=["PCC"],
                    facets={"entity_type": "product"},
                ),
                _unit_vec(8),
            ),
            (
                Node(
                    id="ent_blackwell",
                    node_type="entity",
                    name="Blackwell GPU",
                    summary="NVIDIA GPU architecture.",
                    aliases=[],
                    facets={"entity_type": "product"},
                ),
                _unit_vec(9),
            ),
            (
                Node(
                    id="ent_kenji",
                    node_type="entity",
                    name="Kenji Sato",
                    summary="Engineer.",
                    aliases=[],
                    facets={"entity_type": "person", "role": "engineer"},
                ),
                _unit_vec(10),
            ),
            (
                Node(
                    id="thm_div",
                    node_type="theme",
                    name="Semiconductor Supply Chain Diversification",
                    summary="Geographic diversification of chip fabs.",
                    facets={"stage": "consensus"},
                ),
                _norm_vec([1.0, 0.0, 0.0, 0.0]),
            ),
            (
                Node(
                    id="thm_hedge",
                    node_type="theme",
                    name="Supply Chain Geopolitical Hedging",
                    summary="Shifting assembly and silicon sourcing to hedge geopolitical risk.",
                    facets={"stage": "consensus"},
                ),
                _norm_vec([0.96, 0.28, 0.0, 0.0]),
            ),
            (
                Node(
                    id="thm_quantum",
                    node_type="theme",
                    name="Quantum Computing Risk",
                    summary="Long-dated quantum cryptography risk.",
                    facets={"stage": "emerging"},
                ),
                _norm_vec([0.0, 0.0, 1.0, 0.0]),
            ),
            (
                Node(
                    id="evt_legacy",
                    node_type="event",
                    name="Q3 Earnings Beat",
                    summary="Legacy event missing sentiment facet.",
                    facets={"event_type": "earnings", "status": "occurred"},
                    source_doc_id="doc_1",
                ),
                _unit_vec(11),
            ),
            (
                Node(
                    id="evt_new",
                    node_type="event",
                    name="New Product Launch",
                    summary="Event with explicit sentiment.",
                    facets={"event_type": "news", "status": "occurred", "sentiment": "positive"},
                    source_doc_id="doc_1",
                ),
                _unit_vec(12),
            ),
            (
                Node(
                    id="vw_analyst",
                    node_type="view",
                    name="Desk Buy NVIDIA",
                    summary="Buy view with drifted facet key.",
                    facets={
                        "view_type": "analyst_report",
                        "stance": "buy",
                        "catalyst_to_watch": "Q4 ramp",
                    },
                    source_doc_id="doc_1",
                ),
                _unit_vec(13),
            ),
        ]

        for node, vec in nodes_and_vecs:
            db.upsert_node(node, embedding=vec)

        edges = [
            Edge(
                id="ed_about",
                from_id="evt_legacy",
                to_id="ent_nvda",
                relation="ABOUT",
                source_doc_id="doc_1",
            ),
            Edge(
                id="ed_about_2",
                from_id="evt_new",
                to_id="ent_amd",
                relation="ABOUT",
                source_doc_id="doc_1",
            ),
            Edge(
                id="ed_partner",
                from_id="ent_vrt",
                to_id="ent_nvda",
                relation="COMPETES_WITH",
            ),
            Edge(
                id="ed_has_emp",
                from_id="ent_nvda",
                to_id="ent_kenji",
                relation="HAS_EMPLOYEE",
            ),
            Edge(
                id="ed_works_rev",
                from_id="ent_nvda",
                to_id="ent_kenji",
                relation="WORKS_AT",
            ),
            Edge(
                id="ed_ben_rev",
                from_id="thm_div",
                to_id="ent_vrt",
                relation="BENEFITS_FROM",
            ),
            Edge(
                id="ed_produces",
                from_id="ent_nvda",
                to_id="ent_blackwell",
                relation="PRODUCES",
            ),
            Edge(
                id="ed_thm_co",
                from_id="ent_aapl",
                to_id="thm_hedge",
                relation="EXPOSED_TO",
            ),
        ]
        for edge in edges:
            db.upsert_edge(edge)


def test_minimal_registry_save_load_and_resolution(tmp_path: Path) -> None:
    reg = create_minimal_registry()
    reg_path = tmp_path / "ontology_registry.json"
    save_registry(reg, reg_path)
    loaded = load_registry(reg_path)

    assert loaded.version == 1
    assert len(loaded.relations) == 11
    assert len(loaded.companies) == 5
    assert len(loaded.themes) == 5

    assert normalize_ticker("NYSE: VRT") == "VRT"
    assert normalize_ticker("SU.PA") == "SU.PA"
    assert normalize_ticker("2454.TW") == "2454.TW"
    assert normalize_ticker("  ") is None
    assert normalize_ticker(None) is None

    exact_rel = loaded.resolve_relation("ABOUT")
    assert exact_rel is not None
    assert exact_rel.canonical == "ABOUT"
    assert exact_rel.match_kind == "exact"
    assert exact_rel.flip_direction is False

    alias_rel = loaded.resolve_relation("competes_with")
    assert alias_rel is not None
    assert alias_rel.canonical == "COMPETE"
    assert alias_rel.match_kind == "alias"
    assert alias_rel.flip_direction is False

    sup_rel = loaded.resolve_relation("SUPPLIES_TO")
    assert sup_rel is not None
    assert sup_rel.canonical == "BUY"
    assert sup_rel.match_kind == "inverse"
    assert sup_rel.flip_direction is True

    cust_rel = loaded.resolve_relation("CUSTOMER_OF")
    assert cust_rel is not None
    assert cust_rel.canonical == "BUY"
    assert cust_rel.match_kind == "alias"
    assert cust_rel.flip_direction is False

    ben_rel = loaded.resolve_relation("BENEFITS_FROM")
    assert ben_rel is not None
    assert ben_rel.canonical == "EXPOSED_TO"
    assert ben_rel.match_kind == "alias"
    assert ben_rel.flip_direction is False
    assert ben_rel.default_facets == {"sentiment": "positive"}

    hurt_rel = loaded.resolve_relation("HURT_BY")
    assert hurt_rel is not None
    assert hurt_rel.canonical == "EXPOSED_TO"
    assert hurt_rel.match_kind == "alias"
    assert hurt_rel.flip_direction is False
    assert hurt_rel.default_facets == {"sentiment": "negative"}

    sub_rel = loaded.resolve_relation("SUBSIDIARY_OF")
    assert sub_rel is not None
    assert sub_rel.canonical == "OWNS"
    assert sub_rel.match_kind == "inverse"
    assert sub_rel.flip_direction is True

    inv_rel = loaded.resolve_relation("HAS_EMPLOYEE")
    assert inv_rel is not None
    assert inv_rel.canonical == "WORKS_AT"
    assert inv_rel.match_kind == "inverse"
    assert inv_rel.flip_direction is True

    assert loaded.resolve_relation("PARTNER_WITH") is None
    assert loaded.resolve_relation("PRODUCES") is None

    canon_sup = loaded.canonicalize_edge(
        "SUPPLIES_TO",
        from_id="ent_vrt",
        from_type="entity",
        from_entity_type="company",
        to_id="ent_nvda",
        to_type="entity",
        to_entity_type="company",
    )
    assert canon_sup.relation == "BUY"
    assert canon_sup.from_id == "ent_nvda"
    assert canon_sup.to_id == "ent_vrt"
    assert canon_sup.flipped is True
    assert canon_sup.matched is True

    canon_comp = loaded.canonicalize_edge(
        "COMPETES_WITH",
        from_id="ent_z",
        from_type="entity",
        from_entity_type="company",
        to_id="ent_a",
        to_type="entity",
        to_entity_type="company",
    )
    assert canon_comp.relation == "COMPETE"
    assert canon_comp.symmetric is True
    assert (canon_comp.from_id, canon_comp.to_id) == ("ent_a", "ent_z")

    canon_ben = loaded.canonicalize_edge(
        "BENEFITS_FROM",
        from_id="thm_ai",
        from_type="theme",
        to_id="ent_vrt",
        to_type="entity",
        to_entity_type="company",
    )
    assert canon_ben.relation == "EXPOSED_TO"
    assert (canon_ben.from_id, canon_ben.to_id) == ("ent_vrt", "thm_ai")
    assert canon_ben.facets["sentiment"] == "positive"

    canon_oov = loaded.canonicalize_edge(
        "PRODUCES",
        from_id="ent_nvda",
        from_type="entity",
        from_entity_type="company",
        to_id="ent_blackwell",
        to_type="entity",
        to_entity_type="product",
    )
    assert canon_oov.matched is False
    assert canon_oov.relation == "PRODUCES"

    by_ticker = loaded.resolve_company("Vertiv Holdings Co.", ticker="NYSE: VRT")
    assert by_ticker is not None
    assert by_ticker.spec.name == "Vertiv"
    assert by_ticker.match_kind == "ticker"

    by_exact = loaded.resolve_company("NVIDIA")
    assert by_exact is not None
    assert by_exact.match_kind == "exact"

    by_alias = loaded.resolve_company("Apple Inc.")
    assert by_alias is not None
    assert by_alias.spec.name == "Apple"
    assert by_alias.match_kind == "alias"

    assert loaded.resolve_company("AMD", ticker="AMD") is None

    thm_exact = loaded.resolve_theme("Enterprise AI Monetization")
    assert thm_exact is not None and thm_exact.match_kind == "exact"

    thm_alias = loaded.resolve_theme("AI Data Center Power Bottleneck")
    assert thm_alias is not None
    assert thm_alias.spec.name == "AI Data Center Power & Cooling"
    assert thm_alias.match_kind == "alias"

    assert loaded.resolve_theme("Quantum Computing Risk") is None
    assert loaded.resolve_facet_key("view", "catalyst_to_watch") == "catalysts_to_watch"
    assert loaded.resolve_facet_key("view", "stance") == "stance"


def test_audit_detects_unmapped_drift_direction_and_false_merges(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    _seed_audit_db(db_path)
    reg = create_minimal_registry()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        before_stats = ro_db.get_stats()
        report = run_ontology_audit(ro_db, reg)
        assert ro_db.get_stats() == before_stats

    s = report.summary
    assert s.total_edges == 8
    assert s.mapped_exact_edges == 4
    assert s.mapped_alias_edges == 2
    assert s.mapped_inverse_edges == 1
    assert s.unmapped_edges == 1
    assert s.distinct_unmapped_relations == 1
    assert s.direction_issue_edges == 2

    # Valid HAS_EMPLOYEE (company -> person) passes inverse WORKS_AT validation; only reversed WORKS_AT & BENEFITS_FROM fail.
    dir_rels = {(d.relation, d.issue_type) for d in report.direction_issues}
    assert dir_rels == {
        ("WORKS_AT", "reversed_direction"),
        ("BENEFITS_FROM", "reversed_direction"),
    }

    assert [r.name for r in report.unmapped_relations] == ["PRODUCES"]
    assert report.unmapped_relations[0].edge_count == 1
    assert report.unmapped_relations[0].observed_signatures[0].from_type == "entity:company"
    assert report.unmapped_relations[0].observed_signatures[0].to_type == "entity:product"

    assert s.total_companies == 5
    assert s.mapped_companies == 3
    assert s.unmapped_companies == 2
    assert {c.name for c in report.unmapped_companies} == {"AMD", "Dell"}

    assert s.total_themes == 3
    assert s.mapped_themes == 1
    assert s.unmapped_themes == 2
    assert report.unmapped_themes[0].name == "Supply Chain Geopolitical Hedging"
    assert report.unmapped_themes[0].nearest_official is not None
    assert report.unmapped_themes[0].nearest_official.name == "Semiconductor Supply Chain Diversification"
    assert report.unmapped_themes[0].nearest_official.distance < 0.1

    assert len(report.near_duplicate_themes) == 1
    pair = report.near_duplicate_themes[0]
    assert {pair.node_a_name, pair.node_b_name} == {
        "Semiconductor Supply Chain Diversification",
        "Supply Chain Geopolitical Hedging",
    }

    suspicious = {(sa.node_name, sa.alias): sa.reason for sa in report.suspicious_aliases}
    assert suspicious[("Dell", "HPE")] == "disjoint_name_and_not_ticker"
    assert suspicious[("Fab 20", "Fab 22")] == "conflicting_numeric_identifier"
    assert suspicious[("GLJ Research", "Gordon Johnson")] == "disjoint_name_and_not_ticker"
    assert ("Citi", "Citigroup") not in suspicious
    assert ("Private Cloud Compute", "PCC") not in suspicious

    assert len(report.ticker_normalization_issues) == 1
    assert report.ticker_normalization_issues[0].raw_ticker == "NYSE: VRT"
    assert report.ticker_normalization_issues[0].normalized_ticker == "VRT"

    assert len(report.facet_alias_hits) == 1
    assert report.facet_alias_hits[0].raw_key == "catalyst_to_watch"
    assert report.facet_alias_hits[0].canonical_key == "catalysts_to_watch"

    assert s.events_missing_sentiment == 1
    assert s.total_events == 2
    assert s.views_missing_sentiment == 1
    assert s.total_views == 1


def test_audit_detects_owns_reciprocal_contradiction(tmp_path: Path) -> None:
    db_path = tmp_path / "reciprocal_owns.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_a", node_type="entity", name="Alpha", summary="a", facets={"entity_type": "company"}),
            embedding=_unit_vec(0),
        )
        db.upsert_node(
            Node(id="ent_b", node_type="entity", name="Beta", summary="b", facets={"entity_type": "company"}),
            embedding=_unit_vec(1),
        )
        db.upsert_edge(Edge(id="ed_1", from_id="ent_a", to_id="ent_b", relation="OWNS", source_doc_id="doc_1"))
        db.upsert_edge(Edge(id="ed_2", from_id="ent_b", to_id="ent_a", relation="OWNS", source_doc_id="doc_2"))

    reg = create_minimal_registry()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True, registry=reg) as ro_db:
        report = run_ontology_audit(ro_db, reg)

    assert report.summary.reciprocal_contradiction_pairs == 1
    assert len(report.reciprocal_contradictions) == 1
    rc = report.reciprocal_contradictions[0]
    assert rc.relation == "OWNS"
    assert {rc.node_a_id, rc.node_b_id} == {"ent_a", "ent_b"}
    assert rc.forward_count == 1
    assert rc.reverse_count == 1


def test_sync_suggestions_idempotent_and_preserves_admin_decisions(tmp_path: Path) -> None:
    db_path = tmp_path / "sync.db"
    _seed_audit_db(db_path)
    reg = create_minimal_registry()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        report1 = run_ontology_audit(ro_db, reg)

    sum1 = reg.sync_suggestions(
        report1.unmapped_relations,
        report1.unmapped_companies,
        report1.unmapped_themes,
        now_iso="2026-11-22T09:00:00+00:00",
    )
    assert sum1.added == 5  # 1 relation + 2 companies + 2 themes
    assert sum1.pending_relations == 1
    assert sum1.pending_companies == 2
    assert sum1.pending_themes == 2

    # Idempotent re-sync adds nothing.
    sum2 = reg.sync_suggestions(
        report1.unmapped_relations,
        report1.unmapped_companies,
        report1.unmapped_themes,
        now_iso="2026-11-22T09:05:00+00:00",
    )
    assert sum2.added == 0
    assert sum2.updated == 5

    # Simulate admin rejecting PRODUCES and approving AMD into official companies.
    prod_sug = next(s for s in reg.suggestions.relations if s.name == "PRODUCES")
    prod_sug.status = "rejected"
    prod_sug.reviewer_note = "Too specific; fold into product link."
    reg.companies.append(CompanySpec(name="AMD", ticker="AMD", sector="Semiconductors"))

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro_db:
        report2 = run_ontology_audit(ro_db, reg)

    sum3 = reg.sync_suggestions(
        report2.unmapped_relations,
        report2.unmapped_companies,
        report2.unmapped_themes,
        now_iso="2026-11-22T09:10:00+00:00",
    )
    assert sum3.added == 0
    assert sum3.auto_resolved == 1
    assert sum3.preserved_decided == 1

    prod_after = next(s for s in reg.suggestions.relations if s.name == "PRODUCES")
    assert prod_after.status == "rejected"
    assert prod_after.reviewer_note == "Too specific; fold into product link."

    amd_after = next(s for s in reg.suggestions.companies if s.name == "AMD")
    assert amd_after.status == "approved"
    assert amd_after.mapped_to == "AMD"
    assert sum3.pending_companies == 1


def test_cli_audit_command_reads_ro_and_syncs_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "cli_audit.db"
    reg_path = tmp_path / "ontology_registry.json"
    _seed_audit_db(db_path)
    save_registry(create_minimal_registry(), reg_path)

    runner = CliRunner()

    # 1. --no-sync-suggestions --json should not modify registry file.
    res_json = runner.invoke(
        app,
        [
            "audit",
            "--db",
            str(db_path),
            "--registry",
            str(reg_path),
            "--no-sync-suggestions",
            "--json",
        ],
    )
    assert res_json.exit_code == 0, res_json.output
    parsed = json.loads(res_json.output)
    assert parsed["sync"] is None
    assert parsed["report"]["summary"]["unmapped_companies"] == 2
    assert len(load_registry(reg_path).suggestions.companies) == 0

    # 2. Default sync writes pending suggestions to registry without mutating DB.
    res_sync = runner.invoke(
        app,
        [
            "audit",
            "--db",
            str(db_path),
            "--registry",
            str(reg_path),
        ],
    )
    assert res_sync.exit_code == 0, res_sync.output
    assert "Ontology Audit:" in res_sync.output
    updated_reg = load_registry(reg_path)
    assert len(updated_reg.suggestions.relations) == 1
    assert len(updated_reg.suggestions.companies) == 2
    assert len(updated_reg.suggestions.themes) == 2
