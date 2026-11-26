"""Offline end-to-end tests for the one-directional ingestion & consensus pipeline."""

from __future__ import annotations

import hashlib
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from stock_ontology.db import OntologyDB
from stock_ontology.models import (
    ConsensusSynthesis,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedTheme,
    ExtractedView,
    ExtractionResult,
    FacetKV,
    Node,
)
from stock_ontology.pipeline import IngestionPipeline, ReembedReport, reembed_all_nodes
from stock_ontology.services.errors import ServiceError

DIM = 32
REPO_DATA_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_data"


def _deterministic_embed(text: str, dim: int = DIM) -> list[float]:
    lowered = text.lower()
    vec = [0.0] * dim
    # Anchor specific concepts so semantic-similarity canonicalization is deterministic.
    anchors = [
        ("nvidia", 0),
        ("nvda", 0),
        ("vertiv", 1),
        ("vrt", 1),
        ("tsmc", 2),
        ("tsm", 2),
        ("power bottleneck", 3),
        ("liquid cooling", 4),
        ("cowos", 5),
        ("aircool", 6),
        ("eaton", 7),
    ]
    matched_anchor = False
    for term, bucket in anchors:
        if term in lowered:
            vec[bucket] += 10.0
            matched_anchor = True

    if not matched_anchor:
        digest = hashlib.sha256(lowered.encode("utf-8")).digest()
        for i in range(dim):
            vec[i] = (digest[i % len(digest)] / 255.0) - 0.5

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakePipelineLLM:
    """Deterministic offline LLMClient stub for pipeline verification."""

    def __init__(self) -> None:
        self.extract_calls: list[str] = []
        self.consensus_calls: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_deterministic_embed(t) for t in texts]

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        rel_path = source_meta["file_path"]
        self.extract_calls.append(rel_path)

        if "2026-10-15_q3_preview" in rel_path:
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="Fabless AI GPU leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA"), FacetKV(key="sector", value="Semis")],
                    ),
                    ExtractedEntity(
                        temp_id="e_tsmc",
                        name="TSMC",
                        summary="Leading-edge foundry.",
                        aliases=["TSM"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="TSM")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev1",
                        name="Blackwell NVL72 Q4 Ramp",
                        summary="NVIDIA is ramping GB200 NVL72 racks in Q4; 2026 hyperscaler capex +18% YoY.",
                        event_type="fact",
                        event_date="2026-10-15",
                        status="occurred",
                        facets=[FacetKV(key="source_kind", value="analyst_report")],
                    )
                ],
                views=[
                    ExtractedView(
                        temp_id="vw1",
                        name="Morgan Tech: Buy NVDA",
                        summary="High-conviction Buy on >85% AI training share and CUDA moat; watch 120kW rack power.",
                        view_type="analyst_report",
                        stance="buy",
                        support_strength="strong",
                        conviction="high",
                        as_of="2026-10-15",
                        facets=[FacetKV(key="author", value="Morgan Tech Research")],
                    )
                ],
                themes=[],
                edges=[
                    ExtractedEdge(from_ref="ev1", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw1", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev1", to_ref="vw1", relation="SUPPORTS"),
                    ExtractedEdge(from_ref="e_tsmc", to_ref="e_nvda", relation="SUPPLIES_TO"),
                ],
            )

        if "2026-11-10_supply_chain_call" in rel_path:
            delayed = "MAJOR DELAY" in text
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="AI GPU leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA")],
                    ),
                    ExtractedEntity(
                        temp_id="e_kenji",
                        name="Kenji Sato",
                        summary="Senior Thermal Engineer at Taiwan ODM.",
                        aliases=[],
                        entity_type="person",
                        facets=[
                            FacetKV(key="role", value="supply_chain_engineer"),
                            FacetKV(key="credibility", value="high"),
                        ],
                    ),
                    ExtractedEntity(
                        temp_id="e_vrt",
                        name="Vertiv",
                        summary="Data center liquid cooling and power infrastructure provider.",
                        aliases=["VRT"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="VRT")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_call",
                        name="GB200 Rack Thermal Call" if not delayed else "GB200 Major Rack Delay",
                        summary=(
                            "120kW GB200 racks require direct-to-chip liquid cooling; Vertiv is qualified CDU supplier."
                            if not delayed
                            else "MAJOR DELAY: Hyperscalers pushing out Q1 GB200 rack deliveries by 2 quarters."
                        ),
                        event_type="meeting",
                        event_date="2026-11-10",
                        status="occurred",
                        facets=[FacetKV(key="source_kind", value="meeting_note")],
                    )
                ],
                views=[
                    ExtractedView(
                        temp_id="vw_rumor",
                        name="Colo Substation Delay Rumor" if not delayed else "Bearish Delay View",
                        summary=(
                            "Small colocation customers may slip 4-6 weeks on transformer lead times."
                            if not delayed
                            else "Near-term NVDA shipments likely slip significantly."
                        ),
                        view_type="rumor" if not delayed else "channel_check",
                        stance="cautious" if not delayed else "bearish",
                        support_strength="weak" if not delayed else "strong",
                        conviction="low" if not delayed else "high",
                        as_of="2026-11-10",
                    )
                ],
                themes=[
                    ExtractedTheme(
                        temp_id="t_power",
                        name="AI Data Center Power Bottleneck",
                        summary="Grid power and rack thermal density constraints.",
                        stage="accelerating",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_call", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_rumor", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev_call", to_ref="e_kenji", relation="AUTHORED_BY"),
                    ExtractedEdge(from_ref="ev_call", to_ref="t_power", relation="RELATES_TO"),
                    ExtractedEdge(from_ref="e_vrt", to_ref="t_power", relation="BENEFITS_FROM"),
                ],
            )

        if "2026-11-05_cowos_capacity_note" in rel_path:
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_tsmc",
                        name="TSMC",
                        summary="Foundry and CoWoS packaging leader.",
                        aliases=["TSM"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="TSM")],
                    ),
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="AI GPU leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_cowos",
                        name="TSMC Doubling CoWoS Capacity",
                        summary="TSMC targeting 2x monthly CoWoS wafer capacity by mid-2026; NVDA ~55-60% share.",
                        event_type="fact",
                        event_date="2026-11-05",
                    )
                ],
                views=[
                    ExtractedView(
                        temp_id="vw_tsm",
                        name="Internal Desk: Bullish TSMC",
                        summary="Near-monopoly pricing power on AI wafers and CoWoS.",
                        view_type="pm_view",
                        stance="bullish",
                        support_strength="strong",
                        conviction="high",
                        as_of="2026-11-05",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_cowos", to_ref="e_tsmc", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_tsm", to_ref="e_tsmc", relation="ABOUT"),
                    ExtractedEdge(from_ref="e_tsmc", to_ref="e_nvda", relation="SUPPLIES_TO"),
                ],
            )

        if "2026-11-12_liquid_cooling_brief" in rel_path:
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_vrt",
                        name="Vertiv",
                        summary="Liquid cooling and power infrastructure provider.",
                        aliases=["VRT"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="VRT")],
                    )
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_vrt",
                        name="Vertiv Orders +37% YoY",
                        summary="Organic orders +37% YoY with record $7.4B backlog; December Investor Day ahead.",
                        event_type="fact",
                        event_date="2026-11-12",
                    )
                ],
                views=[
                    ExtractedView(
                        temp_id="vw_vrt",
                        name="Industrial Desk: Buy Vertiv",
                        summary="Direct beneficiary of rack power density doubling.",
                        view_type="analyst_report",
                        stance="buy",
                        support_strength="strong",
                        conviction="high",
                        as_of="2026-11-12",
                    )
                ],
                themes=[
                    ExtractedTheme(
                        temp_id="t_power",
                        name="AI Data Center Power Bottleneck",
                        summary="Power and thermal density constraints in AI clusters.",
                        stage="accelerating",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_vrt", to_ref="e_vrt", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_vrt", to_ref="e_vrt", relation="ABOUT"),
                    ExtractedEdge(from_ref="e_vrt", to_ref="t_power", relation="BENEFITS_FROM"),
                ],
            )

        if "2026-11-14_ai_power_bottleneck" in rel_path:
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_vrt",
                        name="Vertiv",
                        summary="Liquid cooling leader.",
                        aliases=["VRT"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="VRT")],
                    ),
                    ExtractedEntity(
                        temp_id="e_etn",
                        name="Eaton",
                        summary="Electrical switchgear and transformer provider.",
                        aliases=["ETN"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="ETN")],
                    ),
                    ExtractedEntity(
                        temp_id="e_airc",
                        name="Legacy AirCool Corp",
                        summary="Air-only data center cooling vendor.",
                        aliases=["AIRC"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="AIRC")],
                    ),
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="AI compute leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_theme",
                        name="AI Cluster Shift to Power-Bound",
                        summary="AI data centers are shifting from compute-bound to power-and-thermal-bound.",
                        event_type="news",
                        event_date="2026-11-14",
                    )
                ],
                themes=[
                    ExtractedTheme(
                        temp_id="t_power",
                        name="AI Data Center Power Bottleneck",
                        summary="Grid interconnect queues and >100kW/rack cooling bottlenecks.",
                        stage="accelerating",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_theme", to_ref="t_power", relation="RELATES_TO"),
                    ExtractedEdge(from_ref="e_vrt", to_ref="t_power", relation="BENEFITS_FROM"),
                    ExtractedEdge(from_ref="e_etn", to_ref="t_power", relation="BENEFITS_FROM"),
                    ExtractedEdge(from_ref="e_nvda", to_ref="t_power", relation="EXPOSED_TO"),
                    ExtractedEdge(from_ref="e_airc", to_ref="t_power", relation="HURT_BY"),
                ],
            )

        # Fallback for custom added test files (e.g., vector-merge test).
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_custom",
                    name="Nvidia Corporation",
                    summary="Fabless GPU and AI platform giant.",
                    aliases=[],
                    entity_type="company",
                )
            ],
            events=[
                ExtractedEvent(
                    temp_id="ev_custom",
                    name="Custom Note Observation",
                    summary=text.strip()[:120],
                    event_type="fact",
                    event_date="2026-11-20",
                )
            ],
            edges=[ExtractedEdge(from_ref="ev_custom", to_ref="e_custom", relation="ABOUT")],
        )

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis:
        self.consensus_calls.append(company.name)
        has_major_delay = any("MAJOR DELAY" in ev.summary for ev in events)
        stance = "hold" if has_major_delay else "buy"
        support_ids = [ev.id for ev in events[:2]]
        contradict_ids = [vw.id for vw in views if vw.facets.get("stance") in ("cautious", "bearish")]
        return ConsensusSynthesis(
            stance=stance,
            support_strength="moderate" if has_major_delay else "strong",
            conviction="medium" if has_major_delay else "high",
            summary=f"Synthesized {stance.upper()} view for {company.name} across {len(events)} events and {len(views)} views.",
            pillars=[
                f"{company.name} core demand remains durable",
                "Execution & supply/power pacing stays on track",
            ],
            supporting_node_ids=support_ids,
            contradicting_node_ids=contradict_ids,
            facets=[FacetKV(key="synthesized_from_count", value=str(len(events) + len(views)))],
        )


def test_pipeline_ingest_idempotent_edit_delete_and_resolution(tmp_path: Path) -> None:
    data_copy = tmp_path / "data"
    shutil.copytree(REPO_DATA_DIR, data_copy)
    db_path = tmp_path / "ontology.db"
    llm = FakePipelineLLM()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_copy)

        # 1. Initial ingest of 5 seeded notes.
        r1 = pipeline.run()
        assert r1.files_scanned == 5
        assert r1.files_processed == 5
        assert r1.files_deleted == 0
        assert len(llm.extract_calls) == 5

        # Alias/entity/theme resolution should deduplicate NVIDIA/NVDA, TSMC/TSM, Vertiv/VRT, and the shared theme.
        entities = db.list_nodes(node_type="entity", limit=100)
        company_names = [
            e.name for e in entities if e.facets.get("entity_type") == "company"
        ]
        assert len(company_names) == len(set(company_names))
        assert set(company_names) >= {"NVIDIA", "TSMC", "Vertiv", "Eaton", "Legacy AirCool Corp"}

        themes = db.list_nodes(node_type="theme", limit=100)
        assert len(themes) == 1
        assert themes[0].name == "AI Data Center Power Bottleneck"

        nvda = db.find_by_name_or_alias("NVDA", node_type="entity")
        assert nvda is not None
        cons1 = db.get_entity_consensus(nvda.id)
        assert cons1 is not None
        assert cons1.facets["stance"] == "bullish"
        assert len(cons1.facets["pillars"]) == 2

        # 2. Second run with unchanged files must skip all 5 with 0 LLM calls.
        llm.extract_calls.clear()
        llm.consensus_calls.clear()
        r2 = pipeline.run()
        assert r2.files_scanned == 5
        assert r2.files_processed == 0
        assert r2.files_skipped == 5
        assert llm.extract_calls == []
        assert llm.consensus_calls == []

        # 3. Registry-alias merge: "Nvidia Corporation" (an official registry alias, not yet a node alias) merges into NVIDIA.
        custom_note = data_copy / "_general" / "2026-11-20_alias_merge.md"
        custom_note.write_text("Nvidia Corporation sees strong inference demand.", encoding="utf-8")
        r3 = pipeline.run()
        assert r3.files_processed == 1
        nvda_reloaded = db.get_node(nvda.id)
        assert nvda_reloaded is not None
        assert "Nvidia Corporation" in nvda_reloaded.aliases
        # Still only 1 NVIDIA company entity.
        assert sum(
            1 for e in db.list_nodes(node_type="entity", limit=100) if "nvidia" in e.name.lower()
        ) == 1

        # 4. Edit a file -> old doc artifacts purged, consensus updated and supersedes prior.
        call_file = data_copy / "NVDA" / "2026-11-10_supply_chain_call.md"
        call_file.write_text("MAJOR DELAY in GB200 rack delivery.", encoding="utf-8")
        r4 = pipeline.run()
        assert r4.files_processed == 1
        cons2 = db.get_entity_consensus(nvda.id)
        assert cons2 is not None
        assert cons2.id != cons1.id
        assert cons2.facets["stance"] == "neutral"
        old_cons = db.get_node(cons1.id)
        assert old_cons is not None and old_cons.facets["status"] == "superseded"

        # 5. Delete a company's sole note -> cleans artifacts and marks consensus stale.
        tsmc_note = data_copy / "TSMC" / "2026-11-05_cowos_capacity_note.md"
        tsmc_note.unlink()
        r5 = pipeline.run()
        assert r5.files_deleted == 1
        assert "TSMC/2026-11-05_cowos_capacity_note.md" not in db.get_ingestion_log()
        tsmc = db.find_by_name_or_alias("TSMC", node_type="entity")
        assert tsmc is not None
        assert db.get_entity_consensus(tsmc.id) is None


class _AnalystFolderFakeLLM(FakePipelineLLM):
    """Fake LLM that simulates multi-company analyst-folder and flat-file notes."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        rel_path = source_meta["file_path"]
        self.extract_calls.append(rel_path)

        if rel_path == "JASON/2026-11-21_semis_wrap.md":
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_jason",
                        name="Jason",
                        summary="Equity research analyst covering semiconductors and AI infrastructure.",
                        aliases=[],
                        entity_type="person",
                        facets=[FacetKV(key="role", value="analyst"), FacetKV(key="credibility", value="high")],
                    ),
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="AI GPU platform leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA")],
                    ),
                    ExtractedEntity(
                        temp_id="e_tsmc",
                        name="TSMC",
                        summary="Leading-edge foundry and CoWoS packaging provider.",
                        aliases=["TSM"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="TSM")],
                    ),
                    ExtractedEntity(
                        temp_id="e_vrt",
                        name="Vertiv",
                        summary="Data center thermal and power infrastructure supplier.",
                        aliases=["VRT"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="VRT")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_multi",
                        name="AI Silicon & Packaging Supply Check",
                        summary="TSMC CoWoS expansion paces NVIDIA Rubin shipments while Vertiv supplies liquid cooling.",
                        event_type="fact",
                        event_date="2026-11-21",
                    ),
                    ExtractedEvent(
                        temp_id="ev_macro_theme",
                        name="Grid Queue Bottleneck Update",
                        summary="Hyperscale data center buildouts continue shifting toward power-constrained regions.",
                        event_type="news",
                        event_date="2026-11-21",
                    ),
                ],
                views=[
                    ExtractedView(
                        temp_id="vw_jason",
                        name="Jason: Constructive on AI Supply Chain",
                        summary="Stay constructive across NVIDIA, TSMC, and Vertiv as rack power density rises.",
                        view_type="pm_view",
                        stance="bullish",
                        support_strength="strong",
                        conviction="high",
                        as_of="2026-11-21",
                    )
                ],
                themes=[
                    ExtractedTheme(
                        temp_id="t_power",
                        name="AI Data Center Power Bottleneck",
                        summary="Grid power and rack cooling density constraints.",
                        stage="accelerating",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_multi", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev_multi", to_ref="e_tsmc", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev_multi", to_ref="e_vrt", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev_multi", to_ref="e_jason", relation="AUTHORED_BY"),
                    ExtractedEdge(from_ref="vw_jason", to_ref="e_nvda", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_jason", to_ref="e_tsmc", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_jason", to_ref="e_vrt", relation="ABOUT"),
                    ExtractedEdge(from_ref="vw_jason", to_ref="e_jason", relation="AUTHORED_BY"),
                    # Theme-only event: intentionally no ABOUT edge to any entity.
                    ExtractedEdge(from_ref="ev_macro_theme", to_ref="t_power", relation="RELATES_TO"),
                    ExtractedEdge(from_ref="ev_macro_theme", to_ref="e_jason", relation="AUTHORED_BY"),
                    ExtractedEdge(from_ref="e_tsmc", to_ref="e_nvda", relation="SUPPLIES_TO"),
                ],
            )

        if rel_path == "analysts/sarah/2026-11-21_power_note.md":
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_sarah",
                        name="Sarah",
                        summary="Industrials and power research analyst.",
                        aliases=[],
                        entity_type="person",
                        facets=[FacetKV(key="role", value="analyst"), FacetKV(key="credibility", value="high")],
                    ),
                    ExtractedEntity(
                        temp_id="e_vrt",
                        name="Vertiv",
                        summary="Data center liquid cooling supplier.",
                        aliases=["VRT"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="VRT")],
                    ),
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_sarah",
                        name="Vertiv Liquid Cooling Order Check",
                        summary="Channel checks show steady liquid cooling demand at Vertiv.",
                        event_type="meeting",
                        event_date="2026-11-21",
                    )
                ],
                edges=[
                    ExtractedEdge(from_ref="ev_sarah", to_ref="e_vrt", relation="ABOUT"),
                    ExtractedEdge(from_ref="ev_sarah", to_ref="e_sarah", relation="AUTHORED_BY"),
                ],
            )

        if rel_path == "2026-11-21_flat_note.md":
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        temp_id="e_nvda",
                        name="NVIDIA",
                        summary="AI GPU platform leader.",
                        aliases=["NVDA"],
                        entity_type="company",
                        facets=[FacetKV(key="ticker", value="NVDA")],
                    )
                ],
                events=[
                    ExtractedEvent(
                        temp_id="ev_flat",
                        name="NVIDIA Flat Note Check",
                        summary="Root-level note confirming stable GPU lead times.",
                        event_type="fact",
                        event_date="2026-11-21",
                    )
                ],
                edges=[ExtractedEdge(from_ref="ev_flat", to_ref="e_nvda", relation="ABOUT")],
            )

        raise AssertionError(f"Unexpected file path in test: {rel_path}")  # noqa: TRY003


def test_pipeline_decouples_folders_from_companies(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "JASON").mkdir(parents=True)
    (data_dir / "analysts" / "sarah").mkdir(parents=True)

    (data_dir / "JASON" / "2026-11-21_semis_wrap.md").write_text(
        "Jason's weekly note covering NVDA, TSMC, Vertiv, and power bottleneck.",
        encoding="utf-8",
    )
    (data_dir / "analysts" / "sarah" / "2026-11-21_power_note.md").write_text(
        "Sarah's check on Vertiv liquid cooling orders.",
        encoding="utf-8",
    )
    (data_dir / "2026-11-21_flat_note.md").write_text(
        "Flat root note on NVIDIA GPU lead times.",
        encoding="utf-8",
    )

    db_path = tmp_path / "ontology.db"
    llm = _AnalystFolderFakeLLM()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)
        report = pipeline.run()
        assert report.files_scanned == 3
        assert report.files_processed == 3

        entities = db.list_nodes(node_type="entity", limit=100)
        company_names = {
            e.name
            for e in entities
            if str(e.facets.get("entity_type", "")).lower() == "company"
        }
        assert company_names == {"NVIDIA", "TSMC", "Vertiv"}
        for forbidden in ("JASON", "Jason", "analysts", "sarah", "Sarah"):
            assert forbidden not in company_names
        assert all(e.facets.get("ticker") != "JASON" for e in entities)

        for analyst_name in ("Jason", "Sarah"):
            analyst = db.find_by_name_or_alias(analyst_name, node_type="entity")
            assert analyst is not None
            assert analyst.facets.get("entity_type") == "person"
            assert db.get_entity_consensus(analyst.id) is None
            incident = db.get_incident_edges(analyst.id)
            assert any(edge["relation"] == "AUTHORED_BY" for edge in incident)

        macro_ev = db.find_by_name_or_alias("Grid Queue Bottleneck Update", node_type="event")
        assert macro_ev is not None
        assert not any(
            edge["relation"] == "ABOUT" for edge in db.get_incident_edges(macro_ev.id)
        )
        assert macro_ev.facets["source"]["file_path"] == "JASON/2026-11-21_semis_wrap.md"
        assert macro_ev.facets["source"]["folder"] == "JASON"

        sarah_ev = db.find_by_name_or_alias("Vertiv Liquid Cooling Order Check", node_type="event")
        assert sarah_ev is not None
        assert sarah_ev.facets["source"]["file_path"] == "analysts/sarah/2026-11-21_power_note.md"
        assert sarah_ev.facets["source"]["folder"] == "analysts/sarah"

        flat_ev = db.find_by_name_or_alias("NVIDIA Flat Note Check", node_type="event")
        assert flat_ev is not None
        assert flat_ev.facets["source"]["file_path"] == "2026-11-21_flat_note.md"
        assert "folder" not in flat_ev.facets["source"]

        for comp_name in ("NVIDIA", "TSMC", "Vertiv"):
            comp = db.find_by_name_or_alias(comp_name, node_type="entity")
            assert comp is not None
            cons = db.get_entity_consensus(comp.id)
            assert cons is not None
            assert cons.facets["stance"] == "bullish"


class _FailingDocFakeLLM(FakePipelineLLM):
    """Simulates a single failing note (e.g. content filter) mid-ingest."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        if "2026-11-12_liquid_cooling_brief" in source_meta["file_path"]:
            raise RuntimeError("Simulated DashScope data_inspection_failed")  # noqa: TRY003
        return super().extract_document(
            text=text,
            source_meta=source_meta,
            existing_catalog=existing_catalog,
            known_facets=known_facets,
        )


def test_pipeline_continues_and_records_errors_on_single_file_failure(tmp_path: Path) -> None:
    data_copy = tmp_path / "data"
    shutil.copytree(REPO_DATA_DIR, data_copy)
    db_path = tmp_path / "resilience.db"
    llm = _FailingDocFakeLLM()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_copy)
        report = pipeline.run()

        assert report.files_scanned == 5
        assert report.files_processed == 4
        assert len(report.errors) == 1
        assert report.errors[0][0] == "VRT/2026-11-12_liquid_cooling_brief.md"
        assert "data_inspection_failed" in report.errors[0][1]

        # Consensus synthesis still succeeded for unaffected companies like NVIDIA.
        nvda = db.find_by_name_or_alias("NVDA", node_type="entity")
        assert nvda is not None
        assert db.get_entity_consensus(nvda.id) is not None


class _SentimentFakeLLM(FakePipelineLLM):
    """Fake LLM testing sentiment normalization on events, views, consensus, and edges."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_nvda",
                    name="NVIDIA",
                    summary="AI GPU leader.",
                    aliases=["NVDA"],
                    entity_type="company",
                    facets=[FacetKV(key="ticker", value="NVDA")],
                ),
                ExtractedEntity(
                    temp_id="e_amd",
                    name="AMD",
                    summary="CPU and GPU competitor.",
                    aliases=["AMD"],
                    entity_type="company",
                    facets=[FacetKV(key="ticker", value="AMD")],
                ),
            ],
            events=[
                ExtractedEvent(
                    temp_id="ev_neg",
                    name="Packaging Delay Rumor",
                    summary="Rumor of minor packaging delay.",
                    event_type="news",
                    event_date="2026-11-21",
                    status="rumored",
                    sentiment="Negative",
                ),
                ExtractedEvent(
                    temp_id="ev_default",
                    name="Routine Filing",
                    summary="Standard quarterly filing.",
                    event_type="fact",
                    event_date="2026-11-20",
                ),
            ],
            views=[
                ExtractedView(
                    temp_id="vw_derived",
                    name="Bullish Desk View",
                    summary="Strong demand.",
                    view_type="pm_view",
                    stance="bullish",
                    as_of="2026-11-21",
                ),
                ExtractedView(
                    temp_id="vw_mixed",
                    name="Mixed Analyst Take",
                    summary="Near-term caution but long-term positive.",
                    view_type="analyst_report",
                    stance="cautious",
                    sentiment="MIXED",
                    as_of="2026-11-21",
                ),
            ],
            edges=[
                ExtractedEdge(
                    from_ref="ev_neg",
                    to_ref="e_nvda",
                    relation="ABOUT",
                    facets=[FacetKV(key="sentiment", value="Negative")],
                ),
                ExtractedEdge(
                    from_ref="ev_neg",
                    to_ref="e_amd",
                    relation="ABOUT",
                    facets=[FacetKV(key="sentiment", value="Positive")],
                ),
                ExtractedEdge(
                    from_ref="ev_default",
                    to_ref="e_nvda",
                    relation="ABOUT",
                    facets=[FacetKV(key="sentiment", value="unknown_junk")],
                ),
                ExtractedEdge(from_ref="vw_derived", to_ref="e_nvda", relation="ABOUT"),
                ExtractedEdge(from_ref="vw_mixed", to_ref="e_amd", relation="ABOUT"),
            ],
        )

    def synthesize_consensus(
        self,
        *,
        company: Node,
        events: list[Node],
        views: list[Node],
        themes: list[Node],
        prior_consensus: Node | None,
    ) -> ConsensusSynthesis:
        stance = "hold" if company.name == "AMD" else "buy"
        return ConsensusSynthesis(
            stance=stance,
            support_strength="moderate",
            conviction="medium",
            summary=f"Consensus {stance} for {company.name}.",
            pillars=["Demand remains steady"],
            supporting_node_ids=[ev.id for ev in events],
            contradicting_node_ids=[],
        )


def test_pipeline_normalizes_event_view_consensus_and_edge_sentiment(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-11-21_sentiment_note.md").write_text(
        "Packaging rumor negative for NVDA, positive for AMD.",
        encoding="utf-8",
    )
    db_path = tmp_path / "sentiment.db"
    llm = _SentimentFakeLLM()

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)
        report = pipeline.run()
        assert report.files_processed == 1

        ev_neg = db.find_by_name_or_alias("Packaging Delay Rumor", node_type="event")
        ev_def = db.find_by_name_or_alias("Routine Filing", node_type="event")
        vw_der = db.find_by_name_or_alias("Bullish Desk View", node_type="view")
        vw_mix = db.find_by_name_or_alias("Mixed Analyst Take", node_type="view")
        assert ev_neg is not None and ev_neg.facets["sentiment"] == "negative"
        assert ev_def is not None and ev_def.facets["sentiment"] == "neutral"
        assert vw_der is not None and vw_der.facets["sentiment"] == "positive"
        assert vw_mix is not None and vw_mix.facets["sentiment"] == "mixed"

        nvda = db.find_by_name_or_alias("NVDA", node_type="entity")
        amd = db.find_by_name_or_alias("AMD", node_type="entity")
        assert nvda is not None and amd is not None

        nvda_cons = db.get_entity_consensus(nvda.id)
        amd_cons = db.get_entity_consensus(amd.id)
        assert nvda_cons is not None and nvda_cons.facets["sentiment"] == "positive"
        assert amd_cons is not None and amd_cons.facets["sentiment"] == "neutral"

        # Edge sentiment normalized and invalid edge sentiment dropped.
        nvda_edges = {
            e["neighbor"]["id"]: e["facets"] for e in db.get_incident_edges(nvda.id)
        }
        assert nvda_edges[ev_neg.id]["sentiment"] == "negative"
        assert "sentiment" not in nvda_edges[ev_def.id]

        amd_sig = db.query_entity_signals(amd.id, sentiments=["positive"], categories=["news"])
        assert amd_sig["total_matched"] == 1
        assert amd_sig["items"][0]["id"] == ev_neg.id
        assert amd_sig["items"][0]["sentiment_source"] == "edge"


class _ReembedFakeProvider:
    def __init__(self, name: str, embedding_model: str) -> None:
        self.name = name
        self.embedding_model = embedding_model


class _ReembedFakeLLM:
    def __init__(self) -> None:
        self.last_embedding_provider = "gemini"
        self.embedding_providers = [_ReembedFakeProvider("gemini", "gemini-embedding-2")]
        self.seen_texts: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.seen_texts = list(texts)
        vectors: list[list[float]] = []
        for idx, _ in enumerate(texts):
            vec = [0.0] * DIM
            vec[(idx + 10) % DIM] = 1.0
            vectors.append(vec)
        return vectors


def test_reembed_all_nodes(tmp_path: Path) -> None:
    db_path = tmp_path / "reembed.db"
    initial_vec_a = [1.0] + [0.0] * (DIM - 1)
    initial_vec_b = [0.0, 1.0] + [0.0] * (DIM - 2)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        n1 = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Edge AI consumer device ecosystem.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        n2 = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU and NVLink rack platform leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        db.upsert_node(n1, embedding=initial_vec_a)
        db.upsert_node(n2, embedding=initial_vec_b)

        fake_llm = _ReembedFakeLLM()
        report = reembed_all_nodes(db, fake_llm)  # type: ignore[arg-type]

        assert isinstance(report, ReembedReport)
        assert report.total_nodes == 2
        assert report.reembedded == 2
        assert report.provider == "gemini"
        assert report.model == "gemini-embedding-2"
        assert report.embedding_dim == DIM
        assert len(fake_llm.seen_texts) == 2

        # list_all_nodes orders by id ASC: ent_aapl -> bucket 10, ent_nvda -> bucket 11.
        probe_nvda = [0.0] * DIM
        probe_nvda[11] = 1.0
        matches = db.vector_search(probe_nvda, limit=2)
        assert matches[0][0].id == "ent_nvda"
        assert matches[0][1] < 1e-5

        meta = db.get_all_metadata()
        assert meta["embedding_provider"] == "gemini"
        assert meta["embedding_model"] == "gemini-embedding-2"
        assert meta["embedding_dim"] == str(DIM)
        assert "reembedded_at" in meta



# ---------------------------------------------------------------------------
# Ingestion write integrity
# ---------------------------------------------------------------------------


def _count_nodes_for_file(db: OntologyDB, rel_path: str) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE json_extract(facets_json, '$.source.file_path') = ?",
        (rel_path,),
    ).fetchone()
    return int(row[0])


def _count_rows_for_doc(db: OntologyDB, doc_id: str) -> tuple[int, int]:
    nodes = db.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE source_doc_id = ?", (doc_id,)
    ).fetchone()[0]
    edges = db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE source_doc_id = ?", (doc_id,)
    ).fetchone()[0]
    return int(nodes), int(edges)


def _entities_named(db: OntologyDB, name: str) -> list[Node]:
    return [
        n
        for n in db.list_all_nodes()
        if n.node_type == "entity" and n.name.strip().casefold() == name.casefold()
    ]


class _MidNoteFailureFakeLLM(FakePipelineLLM):
    """Extracts a new company with two events; while `fail` is set, the second event's
    embedding is malformed so the write fails after the first doc-scoped node is stored."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if self.fail and "POISON" in t:
                out.append([0.0] * (DIM - 1))
            else:
                out.append(_deterministic_embed(t))
        return out

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_zeta",
                    name="Zeta Optics",
                    summary="Optical interconnect supplier.",
                    aliases=["ZOPT"],
                    entity_type="company",
                    facets=[FacetKV(key="sector", value="Optics")],
                )
            ],
            events=[
                ExtractedEvent(
                    temp_id="ev1", name="Zeta Order Win", summary="Won a hyperscaler order.", event_type="fact"
                ),
                ExtractedEvent(
                    temp_id="ev2", name="Zeta POISON Launch", summary="Launched a new module.", event_type="fact"
                ),
            ],
            edges=[
                ExtractedEdge(from_ref="ev1", to_ref="e_zeta", relation="ABOUT"),
                ExtractedEdge(from_ref="ev2", to_ref="e_zeta", relation="ABOUT"),
            ],
        )


def test_pipeline_mid_note_failure_leaves_no_rows_and_rerun_yields_one_copy(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "ZOPT").mkdir(parents=True)
    rel = "ZOPT/2026-11-21_order_win.md"
    (data_dir / rel).write_text("Zeta Optics won an order and launched a module.", encoding="utf-8")
    llm = _MidNoteFailureFakeLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)

        failed = pipeline.run()
        assert [path for path, _ in failed.errors] == [rel]
        # The failed new note leaves no log entry and no doc-scoped or canonical rows behind.
        assert rel not in db.get_ingestion_log()
        assert _count_nodes_for_file(db, rel) == 0
        assert db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0
        assert _entities_named(db, "Zeta Optics") == []

        llm.fail = False
        healthy = pipeline.run()
        assert healthy.errors == []
        log = db.get_ingestion_log()
        assert rel in log
        doc_id = log[rel]["doc_id"]
        # Exactly one set of artifacts for the note after the rerun.
        assert _count_rows_for_doc(db, doc_id) == (2, 2)
        assert _count_nodes_for_file(db, rel) == 2
        assert len(_entities_named(db, "Zeta Optics")) == 1


class _RelationAliasFakeLLM(FakePipelineLLM):
    """Emits a registered inverse (HAS_EMPLOYEE) and a registered alias (COMPETES_WITH)."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="e_acme", name="Acme Robotics", summary="Robot maker.", entity_type="company"),
                ExtractedEntity(temp_id="e_beta", name="Beta Motion", summary="Actuator maker.", entity_type="company"),
                ExtractedEntity(temp_id="p_jane", name="Jane Roe", summary="Acme CFO.", entity_type="person"),
            ],
            edges=[
                ExtractedEdge(from_ref="e_acme", to_ref="p_jane", relation="HAS_EMPLOYEE"),
                ExtractedEdge(from_ref="e_acme", to_ref="e_beta", relation="competes with"),
            ],
        )


def test_pipeline_stores_registered_alias_and_inverse_relations_canonically(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "acme_note.md").write_text("Acme hired Jane Roe and partnered with Beta.", encoding="utf-8")

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        report = IngestionPipeline(db, _RelationAliasFakeLLM(), data_dir).run()
        assert report.errors == []

        acme = _entities_named(db, "Acme Robotics")[0]
        beta = _entities_named(db, "Beta Motion")[0]
        jane = _entities_named(db, "Jane Roe")[0]
        edges = {
            (r["from_id"], r["relation"], r["to_id"])
            for r in db.conn.execute("SELECT from_id, relation, to_id FROM edges").fetchall()
        }
        # HAS_EMPLOYEE (company -> person) is the registered inverse of WORKS_AT: flipped.
        assert (jane.id, "WORKS_AT", acme.id) in edges
        # COMPETES_WITH is a registered alias of COMPETE (canonical symmetric order).
        assert (acme.id, "COMPETE", beta.id) in edges
        assert {rel for _, rel, _ in edges}.isdisjoint({"HAS_EMPLOYEE", "COMPETES_WITH"})


class _LegacyRefFakeLLM(FakePipelineLLM):
    """Re-mentions an old entity by alias and references it by name from an edge."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult(
            entities=[
                ExtractedEntity(temp_id="e_lgc", name="LGC", summary="Legacy holdco.", entity_type="company")
            ],
            events=[ExtractedEvent(temp_id="ev1", name="LGC Dividend", summary="Raised its dividend.", event_type="fact")],
            edges=[ExtractedEdge(from_ref="ev1", to_ref="Legacy Corp", relation="ABOUT")],
        )


def test_pipeline_resolves_old_entity_past_5000_newer_nodes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "lgc_note.md").write_text("LGC raised its dividend.", encoding="utf-8")
    old = datetime(2020, 1, 1, tzinfo=UTC)
    orthogonal = [0.0] * DIM
    orthogonal[DIM - 1] = 1.0

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(
                id="ent_legacy",
                node_type="entity",
                name="Legacy Corp",
                summary="Legacy holdco.",
                aliases=["LGC"],
                facets={"entity_type": "company"},
                created_at=old,
                updated_at=old,
            ),
            embedding=orthogonal,
        )
        with db.conn:
            db.conn.executemany(
                "INSERT INTO nodes (id, node_type, name, summary, aliases_json, facets_json, "
                "source_doc_id, created_at, updated_at) VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?)",
                [
                    (
                        f"filler_{kind}_{i}",
                        kind,
                        f"Filler {kind} {i}",
                        "filler",
                        '{"entity_type": "person"}' if kind == "entity" else "{}",
                        None if kind == "entity" else "doc_filler",
                        datetime.now(UTC).isoformat(),
                        datetime.now(UTC).isoformat(),
                    )
                    for kind in ("event", "entity")
                    for i in range(5001)
                ],
            )

        report = IngestionPipeline(db, _LegacyRefFakeLLM(), data_dir).run()
        assert report.errors == []

        companies = [
            n
            for n in db.list_all_nodes()
            if n.node_type == "entity" and n.facets.get("entity_type") == "company"
        ]
        # The alias "LGC" resolves to the old entity instead of creating a duplicate.
        assert [n.id for n in companies] == ["ent_legacy"]
        doc_id = db.get_ingestion_log()["lgc_note.md"]["doc_id"]
        targets = {
            r["to_id"]
            for r in db.conn.execute(
                "SELECT to_id FROM edges WHERE source_doc_id = ?", (doc_id,)
            ).fetchall()
        }
        # The by-name edge reference "Legacy Corp" also resolves to the old entity.
        assert "ent_legacy" in targets


def test_pipeline_reports_non_utf8_note_and_ingests_the_rest(tmp_path: Path) -> None:
    data_copy = tmp_path / "data"
    shutil.copytree(REPO_DATA_DIR, data_copy)
    (data_copy / "_general").mkdir(exist_ok=True)
    (data_copy / "_general" / "bad_encoding.md").write_bytes(b"\xff\xfe\xfa not utf-8 \x80\x81")

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, FakePipelineLLM(), data_copy)
        try:
            report = pipeline.run()
        except UnicodeDecodeError as exc:
            pytest.fail(f"run() aborted on a non-UTF-8 note instead of reporting it: {exc}")

        assert [path for path, _ in report.errors] == ["_general/bad_encoding.md"]
        assert report.files_processed == 5
        assert len(db.get_ingestion_log()) == 5


# ---------------------------------------------------------------------------
# Ingestion follow-ups: unchanged and moved notes, consensus targets, catalog
# ---------------------------------------------------------------------------


def _record_data_reads(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> list[str]:
    """Record every file under `data_dir` opened through pathlib or builtin open."""
    import builtins
    import io

    root = data_dir.resolve()
    reads: list[str] = []

    def _note(target: Any) -> None:
        try:
            resolved = Path(target).resolve()
        except TypeError:
            return
        if resolved.is_relative_to(root):
            reads.append(resolved.relative_to(root).as_posix())

    orig_read_text = Path.read_text
    orig_read_bytes = Path.read_bytes
    orig_path_open = Path.open
    orig_open = builtins.open

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        _note(self)
        return orig_read_text(self, *args, **kwargs)

    def read_bytes(self: Path) -> bytes:
        _note(self)
        return orig_read_bytes(self)

    def path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        _note(self)
        return orig_path_open(self, *args, **kwargs)

    def any_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, Path)):
            _note(file)
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(builtins, "open", any_open)
    monkeypatch.setattr(io, "open", any_open)
    return reads


def test_pipeline_rerun_does_not_read_unchanged_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_copy = tmp_path / "data"
    shutil.copytree(REPO_DATA_DIR, data_copy)
    llm = FakePipelineLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_copy)
        first = pipeline.run()
        assert first.errors == []
        assert first.files_processed == 5

        llm.extract_calls.clear()
        reads = _record_data_reads(monkeypatch, data_copy)
        second = pipeline.run()
        monkeypatch.undo()

        assert second.errors == []
        assert second.files_scanned == 5
        assert second.files_skipped == 5
        assert llm.extract_calls == []
        assert sorted(set(reads)) == [], (
            "unchanged notes (same size and mtime) were read again on rerun"
        )


def test_pipeline_moved_note_keeps_doc_and_skips_extraction(tmp_path: Path) -> None:
    data_copy = tmp_path / "data"
    shutil.copytree(REPO_DATA_DIR, data_copy)
    old_rel = "TSMC/2026-11-05_cowos_capacity_note.md"
    new_rel = "archive/2026-11-05_cowos_capacity_note.md"
    llm = FakePipelineLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_copy)
        assert pipeline.run().errors == []
        old_doc_id = db.get_ingestion_log()[old_rel]["doc_id"]
        before = _count_rows_for_doc(db, old_doc_id)
        assert before[0] > 0
        assert _count_nodes_for_file(db, old_rel) == before[0]

        (data_copy / "archive").mkdir()
        (data_copy / old_rel).rename(data_copy / new_rel)
        llm.extract_calls.clear()
        report = pipeline.run()

        assert report.errors == []
        assert llm.extract_calls == [], "a moved note with identical content was re-extracted"
        log = db.get_ingestion_log()
        assert old_rel not in log
        assert log[new_rel]["doc_id"] == old_doc_id
        # Exactly one artifact set, now pointing at the new path and folder.
        assert _count_rows_for_doc(db, old_doc_id) == before
        assert _count_nodes_for_file(db, old_rel) == 0
        assert _count_nodes_for_file(db, new_rel) == before[0]
        folders = {
            r[0]
            for r in db.conn.execute(
                "SELECT json_extract(facets_json, '$.source.folder') FROM nodes WHERE source_doc_id = ?",
                (old_doc_id,),
            ).fetchall()
        }
        assert folders == {"archive"}


class _RolledBackNoteFakeLLM(_MidNoteFailureFakeLLM):
    """First note ingests Zeta Optics cleanly; the second mentions it and then fails mid-write."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        event_name = "Zeta POISON Launch" if "poison" in source_meta["file_path"] else "Zeta Order Win"
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_zeta",
                    name="Zeta Optics",
                    summary="Optical interconnect supplier.",
                    aliases=["ZOPT"],
                    entity_type="company",
                )
            ],
            events=[ExtractedEvent(temp_id="ev1", name=event_name, summary="Zeta update.", event_type="fact")],
            edges=[ExtractedEdge(from_ref="ev1", to_ref="e_zeta", relation="ABOUT")],
        )


def test_pipeline_rolled_back_note_adds_no_consensus_target(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "zeta_order.md").write_text("Zeta Optics won an order.", encoding="utf-8")
    llm = _RolledBackNoteFakeLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)
        first = pipeline.run()
        assert first.errors == []
        assert first.consensus_updated_for == ["Zeta Optics"]

        (data_dir / "zeta_poison.md").write_text("Zeta Optics launched a module.", encoding="utf-8")
        llm.consensus_calls.clear()
        report = pipeline.run()

        assert [path for path, _ in report.errors] == ["zeta_poison.md"]
        assert "zeta_poison.md" not in db.get_ingestion_log()
        # The only note touching Zeta in this run rolled back, so its consensus is not rebuilt.
        assert llm.consensus_calls == [], (
            "a rolled-back note still added its company to the consensus targets"
        )
        assert report.consensus_updated_for == []


class _CatalogCaptureFakeLLM(FakePipelineLLM):
    def __init__(self) -> None:
        super().__init__()
        self.catalogs: list[str] = []

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        self.catalogs.append(existing_catalog)
        return ExtractionResult()


def test_pipeline_catalog_lists_old_entities_named_in_note(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "old_names.md").write_text(
        "Legacy Corp raised its dividend; OMGH trimmed guidance.", encoding="utf-8"
    )
    old = datetime(2020, 1, 1, tzinfo=UTC)
    now_iso = datetime.now(UTC).isoformat()
    llm = _CatalogCaptureFakeLLM()

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        for node_id, name, aliases in (
            ("ent_legacy", "Legacy Corp", ["LGC"]),
            ("ent_omega", "Omega Holdings", ["OMGH"]),
        ):
            db.upsert_node(
                Node(
                    id=node_id,
                    node_type="entity",
                    name=name,
                    summary=f"{name} summary.",
                    aliases=aliases,
                    facets={"entity_type": "company"},
                    created_at=old,
                    updated_at=old,
                )
            )
        with db.conn:
            db.conn.executemany(
                "INSERT INTO nodes (id, node_type, name, summary, aliases_json, facets_json, "
                "source_doc_id, created_at, updated_at) "
                "VALUES (?, 'entity', ?, 'filler', '[]', '{\"entity_type\": \"person\"}', NULL, ?, ?)",
                [(f"filler_entity_{i}", f"Filler Person {i}", now_iso, now_iso) for i in range(600)],
            )

        report = IngestionPipeline(db, llm, data_dir).run()
        assert report.errors == []
        assert len(llm.catalogs) == 1
        catalog = llm.catalogs[0]
        # Matched by name, and by alias, despite 600 newer entities.
        assert "[ent_legacy]" in catalog, "entity named in the note is missing from the catalog"
        assert "[ent_omega]" in catalog, "entity whose alias appears in the note is missing from the catalog"


# ---------------------------------------------------------------------------
# Proof witnesses: exact-entity-merge (ingestion merges only on exact or registry match)
# ---------------------------------------------------------------------------


def _unit(values: dict[int, float], dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    for idx, val in values.items():
        vec[idx] = val
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class _ExactMergeFakeLLM(FakePipelineLLM):
    """Embeds AMD within the old 0.15 cosine distance of NVIDIA and "Nvidia Corporation" far from it."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            if "amd" in lowered or "advanced micro devices" in lowered:
                # cos(AMD, NVIDIA) = 10 / sqrt(109) ~ 0.958 -> distance ~ 0.042 < 0.15.
                out.append(_unit({0: 10.0, 9: 3.0}))
            elif "nvidia corporation" in lowered:
                # Orthogonal to NVIDIA: only an exact or registry match can merge it.
                out.append(_unit({12: 1.0}))
            else:
                out.append(_deterministic_embed(text))
        return out

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        rel_path = source_meta["file_path"]
        self.extract_calls.append(rel_path)
        if rel_path == "nvda.md":
            entity = ExtractedEntity(
                temp_id="e_nvda",
                name="NVIDIA",
                summary="AI GPU platform leader.",
                aliases=["NVDA"],
                entity_type="company",
                facets=[FacetKV(key="ticker", value="NVDA")],
            )
        elif rel_path == "amd.md":
            entity = ExtractedEntity(
                temp_id="e_amd",
                name="AMD",
                summary="Advanced Micro Devices, GPU and CPU designer.",
                aliases=[],
                entity_type="company",
                facets=[FacetKV(key="ticker", value="AMD")],
            )
        elif rel_path == "nvidia_corp.md":
            entity = ExtractedEntity(
                temp_id="e_nvcorp",
                name="Nvidia Corporation",
                summary="Maker of accelerated computing chips.",
                aliases=[],
                entity_type="company",
            )
        else:
            raise AssertionError(f"unexpected note {rel_path}")  # noqa: TRY003
        return ExtractionResult(entities=[entity])


def _ingest_one_by_one(tmp_path: Path, llm: FakePipelineLLM, notes: list[str]) -> OntologyDB:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False)
    pipeline = IngestionPipeline(db, llm, data_dir)
    for note in notes:
        (data_dir / note).write_text(f"Note {note}.", encoding="utf-8")
        report = pipeline.run()
        assert report.errors == [], report.errors
        assert report.files_processed == 1
    return db


def test_pipeline_does_not_merge_distinct_company_by_embedding_distance(tmp_path: Path) -> None:
    db = _ingest_one_by_one(tmp_path, _ExactMergeFakeLLM(), ["nvda.md", "amd.md"])
    try:
        nvidia = _entities_named(db, "NVIDIA")
        assert len(nvidia) == 1
        amd = _entities_named(db, "AMD")
        assert len(amd) == 1, (
            "AMD was merged into an existing node because its embedding is near NVIDIA; "
            "ingestion must only merge on exact or registry matches"
        )
        assert amd[0].id != nvidia[0].id
        assert "AMD" not in nvidia[0].aliases
    finally:
        db.close()


def test_pipeline_merges_registry_alias_without_embedding_similarity(tmp_path: Path) -> None:
    db = _ingest_one_by_one(tmp_path, _ExactMergeFakeLLM(), ["nvda.md", "nvidia_corp.md"])
    try:
        nvidia = _entities_named(db, "NVIDIA")
        assert len(nvidia) == 1
        assert _entities_named(db, "Nvidia Corporation") == [], (
            "'Nvidia Corporation' is a registry alias of NVIDIA but was stored as its own node"
        )
        assert "Nvidia Corporation" in nvidia[0].aliases
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Proof witnesses: official-edge-facets (every stored edge carries `basis`)
# ---------------------------------------------------------------------------


class _BasisFakeLLM(FakePipelineLLM):
    """One NVIDIA note whose LLM output tries to set `basis` itself, plus free-form edge facets."""

    def extract_document(
        self,
        *,
        text: str,
        source_meta: dict[str, Any],
        existing_catalog: str,
        known_facets: dict[str, list[str]],
    ) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_nvda",
                    name="NVIDIA",
                    summary="AI GPU leader.",
                    aliases=["NVDA"],
                    entity_type="company",
                    facets=[FacetKV(key="ticker", value="NVDA")],
                ),
            ],
            events=[
                ExtractedEvent(
                    temp_id="ev_ramp",
                    name="Rack Ramp Update",
                    summary=text.strip()[:120],
                    event_type="news",
                    event_date="2026-11-21",
                ),
            ],
            views=[
                ExtractedView(
                    temp_id="vw_caution",
                    name="Cautious Channel Check",
                    summary="Rack deliveries may slip.",
                    view_type="channel_check",
                    stance="cautious",
                    as_of="2026-11-21",
                ),
            ],
            themes=[
                ExtractedTheme(
                    temp_id="t_power",
                    name="AI Data Center Power Bottleneck",
                    summary="Power and thermal constraints.",
                    stage="accelerating",
                )
            ],
            edges=[
                ExtractedEdge(
                    from_ref="ev_ramp",
                    to_ref="e_nvda",
                    relation="ABOUT",
                    facets=[
                        FacetKV(key="basis", value="synthesized"),
                        FacetKV(key="role", value="primary_subject"),
                        FacetKV(key="confidence", value="high"),
                        FacetKV(key="product_type", value="gpu_rack"),
                    ],
                ),
                ExtractedEdge(
                    from_ref="vw_caution",
                    to_ref="e_nvda",
                    relation="ABOUT",
                    facets=[FacetKV(key="basis", value="Synthesized")],
                ),
                ExtractedEdge(from_ref="ev_ramp", to_ref="t_power", relation="RELATES_TO"),
                ExtractedEdge(from_ref="e_nvda", to_ref="t_power", relation="EXPOSED_TO"),
            ],
        )


def _stored_edges(db: OntologyDB) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        """
        SELECT e.relation, e.facets_json, e.source_doc_id,
               n1.node_type AS from_type, n1.facets_json AS from_facets,
               n2.node_type AS to_type, n2.facets_json AS to_facets
        FROM edges e JOIN nodes n1 ON n1.id = e.from_id JOIN nodes n2 ON n2.id = e.to_id
        """
    ).fetchall()
    import json

    def _is_consensus(node_type: str, facets_json: str) -> bool:
        return node_type == "view" and json.loads(facets_json).get("view_type") == "consensus"

    return [
        {
            "relation": r["relation"],
            "facets": json.loads(r["facets_json"]),
            "source_doc_id": r["source_doc_id"],
            "touches_consensus": _is_consensus(r["from_type"], r["from_facets"])
            or _is_consensus(r["to_type"], r["to_facets"]),
        }
        for r in rows
    ]


def test_pipeline_sets_edge_basis_by_code_not_by_llm(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    note = data_dir / "NVDA" / "2026-11-21_basis_note.md"
    note.parent.mkdir(parents=True)
    note.write_text("NVIDIA rack ramp on track.", encoding="utf-8")
    llm = _BasisFakeLLM()

    with OntologyDB(tmp_path / "basis.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, llm, data_dir)
        assert pipeline.run().files_processed == 1
        # Editing the note re-synthesizes consensus, so the new view SUPERSEDES the old one.
        note.write_text("NVIDIA rack ramp slipping a quarter.", encoding="utf-8")
        assert pipeline.run().files_processed == 1

        edges = _stored_edges(db)
        synthesized_relations = {e["relation"] for e in edges if e["touches_consensus"]}
        assert {"ABOUT", "SUPPORTS", "CONTRADICTS", "SUPERSEDES"} <= synthesized_relations, synthesized_relations
        assert any(not e["touches_consensus"] for e in edges)

        wrong = [
            (e["relation"], e["touches_consensus"], e["facets"].get("basis"))
            for e in edges
            if e["facets"].get("basis") != ("synthesized" if e["touches_consensus"] else "extracted")
        ]
        assert wrong == [], f"edges with the wrong or missing basis (relation, consensus, basis): {wrong}"

        # Non-official edge facets are stored as before.
        about = [
            e["facets"] for e in edges if e["relation"] == "ABOUT" and e["facets"].get("role") == "primary_subject"
        ]
        assert len(about) == 1
        assert about[0]["confidence"] == "high"
        assert about[0]["product_type"] == "gpu_rack"


# ---------------------------------------------------------------------------
# typed-registry-schema: regeneration on schema failures, and the pipeline's registry
# ---------------------------------------------------------------------------

SHIPPED_REGISTRY = Path(__file__).resolve().parents[1] / "ontology_registry.json"


class _SchemaBreakingFakeLLM(FakePipelineLLM):
    """Returns `bad_events` (one per call) before a conforming event."""

    def __init__(self, bad_events: list[dict[str, Any]]) -> None:
        super().__init__()
        self.bad_events = bad_events

    def extract_document(self, *, text, source_meta, existing_catalog, known_facets) -> ExtractionResult:
        self.extract_calls.append(source_meta["file_path"])
        n = len(self.extract_calls)
        event = {"temp_id": "ev1", "name": "Kappa Ships", "summary": "Kappa shipped.", "event_type": "news"}
        if n <= len(self.bad_events):
            event = {**event, **self.bad_events[n - 1]}
        return ExtractionResult.model_validate(
            {
                "entities": [
                    {
                        "temp_id": "e1",
                        "name": "Kappa Inc",
                        "summary": "Kappa.",
                        "entity_type": "company",
                        "facets": [{"key": "sector", "value": "Hardware"}],
                    }
                ],
                "events": [event],
                "edges": [{"from_ref": "ev1", "to_ref": "e1", "relation": "ABOUT"}],
            }
        )


def _kappa_note(tmp_path: Path) -> tuple[Path, str]:
    data_dir = tmp_path / "data"
    (data_dir / "KAPA").mkdir(parents=True)
    rel = "KAPA/2026-11-20_ship.md"
    (data_dir / rel).write_text("Kappa shipped.", encoding="utf-8")
    return data_dir, rel


def test_pipeline_regenerates_out_of_vocabulary_subtype_and_wrong_kind_date(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    data_dir, rel = _kappa_note(tmp_path)
    llm = _SchemaBreakingFakeLLM([{"event_type": "gossip"}, {"event_date": "sometime soon"}])
    # The DB is opened without a registry, as the CLI does; the pipeline's registry is applied.
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        reg = load_registry(SHIPPED_REGISTRY)
        report = IngestionPipeline(db, llm, data_dir, registry=reg).run()
        assert report.errors == []
        # The unknown required subtype and the bad date each regenerate; the third extraction is clean.
        assert llm.extract_calls == [rel, rel, rel]
        assert report.invalid_facets_dropped == {}
        events = [n for n in db.list_all_nodes() if n.node_type == "event"]
        assert [e.facets["event_type"] for e in events] == ["news"]
        assert events[0].facets.get("event_date") != "sometime soon"
        assert db.get_metadata("registry_version") == reg.schema_stamp()


def test_pipeline_does_not_regenerate_for_non_schema_failures(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    data_dir = tmp_path / "data"
    (data_dir / "ZOPT").mkdir(parents=True)
    rel = "ZOPT/2026-11-21_order_win.md"
    (data_dir / rel).write_text("Zeta Optics won an order.", encoding="utf-8")
    llm = _MidNoteFailureFakeLLM()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=load_registry(SHIPPED_REGISTRY)).run()
    assert [path for path, _ in report.errors] == [rel]
    assert llm.extract_calls == [rel]


def test_extraction_catalog_lists_required_entity_facets_from_the_registry(tmp_path: Path) -> None:
    import json

    from stock_ontology.registry import load_registry

    raw = json.loads((Path(__file__).parents[1] / "ontology_registry.json").read_text(encoding="utf-8"))
    raw["facet_schema"]["node"]["entity:region"] = {"process_node": {"kind": "text", "required": True}}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        catalog = IngestionPipeline(db, FakePipelineLLM(), data_dir, registry=load_registry(path))._build_existing_catalog()
    assert "- company: sector" in catalog
    assert "- person: organization, role" in catalog
    assert "- region: process_node" in catalog


class _BadTargetConsensusFakeLLM(_SchemaBreakingFakeLLM):
    """Conforming extraction; the consensus synthesis carries a `target_price` that is not a number."""

    def __init__(self) -> None:
        super().__init__([])

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        syn = super().synthesize_consensus(**kwargs)
        return syn.model_copy(update={"facets": [*syn.facets, FacetKV(key="target_price", value="$650")]})


def test_consensus_synthesis_drops_uncoercible_optional_facet(tmp_path: Path) -> None:
    data_dir, _ = _kappa_note(tmp_path)
    llm = _BadTargetConsensusFakeLLM()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir).run()
        assert report.errors == []
        assert report.consensus_updated_for == ["Kappa Inc"]
        kappa = next(n for n in db.list_all_nodes() if n.name == "Kappa Inc")
        cons = db.get_entity_consensus(kappa.id)
        assert cons is not None
        assert "target_price" not in cons.facets and cons.facets["view_type"] == "consensus"


# ---------------------------------------------------------------------------
# registry-schema-v2: unmapped relations are skipped and counted; metadata limits regenerate
# ---------------------------------------------------------------------------


def _registry_with_name_limit(tmp_path: Path, limit: int):
    import json

    from stock_ontology.registry import load_registry

    raw = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    raw["metadata_max_length"]["name"] = limit
    path = tmp_path / "limited_registry.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_registry(path)


class _UnmappedEdgesFakeLLM(_SchemaBreakingFakeLLM):
    """Adds two FROBNICATES edges and one PARTNERS_WITH edge to every extraction."""

    def extract_document(self, *, text, source_meta, existing_catalog, known_facets) -> ExtractionResult:
        result = super().extract_document(
            text=text, source_meta=source_meta, existing_catalog=existing_catalog, known_facets=known_facets
        )
        extra = [
            ExtractedEdge(from_ref="ev1", to_ref="e1", relation="frobnicates"),
            ExtractedEdge(from_ref="e1", to_ref="ev1", relation="FROBNICATES"),
            ExtractedEdge(from_ref="ev1", to_ref="e1", relation="PARTNERS_WITH"),
        ]
        return result.model_copy(update={"edges": [*result.edges, *extra]})


def test_ingest_report_counts_pending_relations_once_per_kept_extraction(tmp_path: Path) -> None:
    import json

    data_dir, rel = _kappa_note(tmp_path)
    # The first extraction breaks the name limit and is regenerated; only the kept one is counted.
    llm = _UnmappedEdgesFakeLLM([{"name": "K" * 61}])
    reg = _registry_with_name_limit(tmp_path, 60)
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=reg).run()
        assert llm.extract_calls == [rel, rel]
        assert report.errors == []
        assert report.unmapped_relations_pending == {"FROBNICATES": 2, "PARTNERS_WITH": 1}
        relations = {r[0] for r in db.conn.execute("SELECT relation FROM edges")}
        assert relations.isdisjoint({"FROBNICATES", "PARTNERS_WITH"}) and "ABOUT" in relations
        # The count matches the rows held, each with its raw relation and the note's doc id.
        pending = db.conn.execute("SELECT relation, source_doc_id, facets_json FROM pending_edges").fetchall()
        assert sorted(r[0] for r in pending) == ["FROBNICATES", "PARTNERS_WITH", "frobnicates"]
        doc_id = db.get_ingestion_log()[rel]["doc_id"]
        assert {r[1] for r in pending} == {doc_id}
        assert all(json.loads(r[2])["basis"] == "extracted" for r in pending)
        assert rel in db.get_ingestion_log()


def test_over_length_name_regenerates_under_the_registry_declared_limit(tmp_path: Path) -> None:
    long_name = "K" * 61
    data_dir, rel = _kappa_note(tmp_path)
    llm = _SchemaBreakingFakeLLM([{"name": long_name}])
    with OntologyDB(tmp_path / "limited.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=_registry_with_name_limit(tmp_path, 60)).run()
        assert report.errors == [] and llm.extract_calls == [rel, rel]
        assert [n.name for n in db.list_all_nodes() if n.node_type == "event"] == ["Kappa Ships"]

    # The same extraction is within the shipped registry's limit, so the limit is the registry's, not code's.
    from stock_ontology.registry import load_registry

    llm = _SchemaBreakingFakeLLM([{"name": long_name}])
    with OntologyDB(tmp_path / "shipped.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=load_registry(SHIPPED_REGISTRY)).run()
        assert report.errors == [] and llm.extract_calls == [rel]
        assert [n.name for n in db.list_all_nodes() if n.node_type == "event"] == [long_name]


def test_over_length_summary_fails_the_note_after_the_regeneration_cap(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    data_dir, rel = _kappa_note(tmp_path)
    llm = _SchemaBreakingFakeLLM([{"summary": "s" * 1001}] * 3)
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        report = IngestionPipeline(db, llm, data_dir, registry=load_registry(SHIPPED_REGISTRY)).run()
        assert llm.extract_calls == [rel, rel, rel]
        assert [path for path, _ in report.errors] == [rel]
        assert rel not in db.get_ingestion_log()
        assert db.conn.execute("SELECT COUNT(*) FROM nodes WHERE node_type = 'event'").fetchone()[0] == 0


def test_reingesting_one_note_clears_only_its_own_pending_edges(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    data_dir = tmp_path / "data"
    (data_dir / "KAPA").mkdir(parents=True)
    notes = ["KAPA/a.md", "KAPA/b.md"]
    for rel in notes:
        (data_dir / rel).write_text(f"Kappa shipped ({rel}).", encoding="utf-8")
    reg = load_registry(SHIPPED_REGISTRY)
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        IngestionPipeline(db, _UnmappedEdgesFakeLLM([]), data_dir, registry=reg).run()
        log = db.get_ingestion_log()

        def pending_by_doc() -> dict[str, int]:
            rows = db.conn.execute("SELECT source_doc_id, COUNT(*) FROM pending_edges GROUP BY source_doc_id")
            return {str(r[0]): int(r[1]) for r in rows}

        assert pending_by_doc() == {log[notes[0]]["doc_id"]: 3, log[notes[1]]["doc_id"]: 3}
        (data_dir / notes[0]).write_text("Kappa shipped again.", encoding="utf-8")
        IngestionPipeline(db, _UnmappedEdgesFakeLLM([]), data_dir, registry=reg).run()
        log = db.get_ingestion_log()
        assert pending_by_doc() == {log[notes[0]]["doc_id"]: 3, log[notes[1]]["doc_id"]: 3}


def test_selected_note_cannot_replace_a_newer_batch_extraction(tmp_path: Path) -> None:
    from stock_ontology.config import NoteConflictError

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "note.md"
    path.write_text("A source note.", encoding="utf-8")
    db_path = tmp_path / "ontology.db"

    class OverlappingLLM(FakePipelineLLM):
        def extract_document(self, **kwargs: Any) -> ExtractionResult:
            with OntologyDB(db_path, embedding_dim=DIM) as concurrent:
                report = IngestionPipeline(concurrent, FakePipelineLLM(), data_dir).run()
                assert report.files_processed == 1
            return ExtractionResult()

    with OntologyDB(db_path, embedding_dim=DIM) as db:
        pipeline = IngestionPipeline(db, OverlappingLLM(), data_dir)
        with pytest.raises(NoteConflictError):
            pipeline.process_note(path)
        assert db.get_note_state("note.md")["entities_recorded"]
        pipeline.process_note(path)


def test_selected_note_rejects_source_change_while_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_ontology.config import NoteConflictError

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "note.md"
    path.write_text("A source note.", encoding="utf-8")

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        pipeline = IngestionPipeline(db, FakePipelineLLM(), data_dir)
        write_extraction = pipeline._write_extraction

        def change_source(**kwargs: Any) -> tuple[int, int, set[str]]:
            result = write_extraction(**kwargs)
            path.write_text("Updated while processing.", encoding="utf-8")
            return result

        monkeypatch.setattr(pipeline, "_write_extraction", change_source)
        with pytest.raises(NoteConflictError):
            pipeline.process_note(path)
        assert db.get_note_state("note.md") is None


def _reader_correction(
    pipeline: IngestionPipeline, path: Path, kind: str, *, edge_id: str = "", changes: dict[str, Any] | None = None,
) -> None:
    """Apply a note-reader relationship correction the way the reader's route and the worker do."""
    from stock_ontology.services.corrections import review_note_correction

    reviewed = review_note_correction(pipeline.db, path.resolve(), path.parent.resolve(),
                                      kind=kind, edge_id=edge_id, changes=changes or {})
    pipeline.apply_note_correction(path.resolve(), reviewed)


@pytest.mark.parametrize("action", ["relink", "swap"])
def test_note_correction_updates_only_current_note_edges(tmp_path: Path, action: str) -> None:
    from stock_ontology.models import Edge

    path = tmp_path / "note.md"
    path.write_text("Source", encoding="utf-8")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        for entity_id in ("company_a", "company_b", "company_c"):
            db.upsert_node(Node(id=entity_id, name=entity_id, node_type="entity", summary="",
                                facets={"entity_type": "company", "sector": "Industrial"}))
        db.upsert_ingestion_log("note.md", "note", content_hash,
                                entity_ids=("company_a", "company_b", "company_c"))
        db.upsert_edge(Edge(id="focus_edge", from_id="company_a", to_id="company_b", relation="OWNS",
                            facets={"basis": "extracted"}, source_doc_id="note"))
        db.upsert_edge(Edge(id="other_edge", from_id="company_a", to_id="company_c", relation="OWNS",
                            facets={"basis": "extracted"}, source_doc_id="note"))
        db.upsert_edge(Edge(id="peer_edge", from_id="company_a", to_id="company_b", relation="OWNS",
                            facets={"basis": "extracted"}, source_doc_id="peer"))
        peer = db.list_note_edges("peer")
        pipeline = IngestionPipeline(db, FakePipelineLLM(), tmp_path)

        if action == "relink":
            pipeline.relink_note_entity(path, "company_a", "company_b", None, content_hash)
            remaining, = db.list_note_edges("note")
            assert (remaining["from_id"], remaining["to_id"]) == ("company_b", "company_c")
            assert {node.id for node in db.list_note_entities("note")} == {"company_b", "company_c"}
        else:
            swap = {"relation": "OWNS", "from_id": "company_b", "to_id": "company_a"}
            _reader_correction(pipeline, path, "relationship", edge_id="focus_edge", changes=swap)
            # The corrected edge has a new ID, so the same form cannot swap it again.
            with pytest.raises(ServiceError) as missing:
                _reader_correction(pipeline, path, "relationship", edge_id="focus_edge", changes=swap)
            assert missing.value.key == "service_error.relationship_missing"
            assert {(edge["from_id"], edge["to_id"]) for edge in db.list_note_edges("note")} == {
                ("company_b", "company_a"), ("company_a", "company_c"),
            }
        assert db.list_note_edges("peer") == peer


def test_delete_note_relationship_removes_only_its_pending_edge(tmp_path: Path) -> None:
    from stock_ontology.models import Edge

    path = tmp_path / "note.md"
    path.write_text("Source", encoding="utf-8")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM) as db:
        for entity_id in ("left", "right"):
            db.upsert_node(Node(
                id=entity_id, name=entity_id, node_type="entity", summary="",
                facets={"entity_type": "company", "sector": "Industrial"},
            ))
        db.upsert_ingestion_log("note.md", "note", content_hash, entity_ids=("left", "right"))
        for doc_id, edge_id in (("note", "pending"), ("peer", "peer-pending")):
            db.insert_pending_edge(Edge(
                id=edge_id, from_id="left", to_id="right", relation="UNREVIEWED_RELATION",
                facets={"basis": "extracted"}, source_doc_id=doc_id,
            ))

        pipeline = IngestionPipeline(db, FakePipelineLLM(), tmp_path)
        with pytest.raises(ServiceError) as missing:
            _reader_correction(pipeline, path, "relationship_delete", edge_id="peer-pending")
        assert missing.value.key == "service_error.relationship_missing"
        _reader_correction(pipeline, path, "relationship_delete", edge_id="pending")

        assert db.list_note_edges("note", pending=True) == []
        assert [edge["edge_id"] for edge in db.list_note_edges("peer", pending=True)] == ["peer-pending"]


def test_add_note_relationship_accepts_required_fields_from_shipped_registry(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    registry_path = Path(__file__).resolve().parents[1] / "ontology_registry.json"
    registry = load_registry(registry_path)
    path = tmp_path / "note.md"
    path.write_text("Source", encoding="utf-8")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(Node(
            id="company", name="Sample company", node_type="entity", summary="",
            facets={"entity_type": "company", "sector": "Industrials"},
        ))
        db.upsert_node(Node(
            id="theme", name="Sample theme", node_type="theme", summary="",
            facets={"stage": "emerging"},
        ))
        db.upsert_ingestion_log("note.md", "note", content_hash, entity_ids=())
        pipeline = IngestionPipeline(db, FakePipelineLLM(), tmp_path)

        add = {"from_id": "company", "relation": "EXPOSED_TO", "to_id": "theme"}
        for facets in ({}, {"facets": {"sentiment": "invalid"}}):
            with pytest.raises(ServiceError, match="sentiment") as refused:
                _reader_correction(pipeline, path, "relationship_add", changes={**add, **facets})
            assert refused.value.code == "invalid"
        assert db.list_note_edges("note") == []

        _reader_correction(pipeline, path, "relationship_add", changes={**add, "facets": {"sentiment": "positive"}})
        edge, = db.list_note_edges("note")
        assert (edge["relation"], edge["facets"]["sentiment"]) == ("EXPOSED_TO", "positive")


def test_registry_person_identity_correction_survives_matching_extraction(tmp_path: Path) -> None:
    from stock_ontology.config import Settings
    from stock_ontology.registry import create_minimal_registry, save_registry
    from stock_ontology.services.corrections import review_note_correction
    from stock_ontology.services.processing import ProcessingService
    from stock_ontology.worker import Worker

    class PersonLLM(FakePipelineLLM):
        def extract_document(self, **_: Any) -> ExtractionResult:
            return ExtractionResult(entities=[ExtractedEntity(
                temp_id="local-person", name="Old Research Name", summary="Analyst",
                entity_type="person", facets=[FacetKV(key="role", value="Former Role")],
            )])

    settings = Settings(db_path=tmp_path / "db.sqlite", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    note = tmp_path / "source.md"
    note.write_text("A note about Old Research Name.", encoding="utf-8")
    llm = PersonLLM()
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        IngestionPipeline(db, llm, tmp_path, registry=registry).process_note(note)
        old = db.find_by_name_or_alias("Old Research Name")
        assert old is not None
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry, read_only=True) as db:
        payload = review_note_correction(db, note, tmp_path, kind="person", record=old.id,
                                         changes={"name": "Corrected Research Name"}, keep_previous_name=True)
    jobs = ProcessingService(settings)
    ref = jobs.submit_correction("note.ontology.correction", note.name, payload)
    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    assert jobs.get_status(ref.job_id)["state"] == "succeeded"
    note.write_text("A revised note about Old Research Name.", encoding="utf-8")
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        IngestionPipeline(db, llm, tmp_path, registry=registry).process_note(note)
        node, = db.list_nodes(node_type="entity")
        assert (node.id, node.name) == (old.id, "Corrected Research Name")
        assert "Old Research Name" in node.aliases


# --- Author accuracy (docs/proposals/author-accuracy.md)

SHIPPED_REGISTRY = Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _person(temp_id: str, name: str, **facets: str) -> ExtractedEntity:
    return ExtractedEntity(
        temp_id=temp_id, name=name, summary=f"{name}, a market commentator.", entity_type="person",
        facets=[FacetKV(key=key, value=value) for key, value in facets.items()],
    )


def _company(temp_id: str, name: str, ticker: str) -> ExtractedEntity:
    return ExtractedEntity(
        temp_id=temp_id, name=name, summary=f"{name} makes widgets.", entity_type="company",
        facets=[FacetKV(key="ticker", value=ticker), FacetKV(key="sector", value="Industrials")],
    )


def _authored_view(temp_id: str, name: str, view_type: str, about: str, author: str) -> tuple[ExtractedView, list[ExtractedEdge]]:
    view = ExtractedView(
        temp_id=temp_id, name=name, summary=f"{name} says demand is turning.", view_type=view_type,
        stance="buy", support_strength="moderate", conviction="medium", as_of="2026-11-20",
    )
    return view, [
        ExtractedEdge(from_ref=temp_id, to_ref=about, relation="ABOUT"),
        ExtractedEdge(from_ref=temp_id, to_ref=author, relation="AUTHORED_BY"),
    ]


def _extraction(entities: list[ExtractedEntity], authored: list[tuple[ExtractedView, list[ExtractedEdge]]]) -> ExtractionResult:
    return ExtractionResult(
        entities=entities,
        views=[view for view, _ in authored],
        edges=[edge for _, edges in authored for edge in edges],
    )


def _set_person_facets(db: OntologyDB, name: str, **facets: str) -> Node:
    """Test setup only: stands in for the hand-set value the app stores on a person."""
    node = db.find_by_name_or_alias(name, node_type="entity")
    assert node is not None, name
    updated = node.model_copy(update={"facets": {**node.facets, **facets}})
    db.upsert_node(updated, _deterministic_embed(name))
    return updated


def _json_entries_with_id(text: str, node_id: str) -> list[dict[str, Any]]:
    """Every JSON object in `text`, at any depth, whose `id` is `node_id`."""
    import json

    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("id") == node_id and value not in found:
                found.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for index, char in enumerate(text):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(text, index)
            except ValueError:
                continue
            walk(value)
    return found


def _accuracy_values(value: Any) -> set[str]:
    """Every value stored under an `accuracy` key, at any depth."""
    if isinstance(value, dict):
        out = {str(v) for k, v in value.items() if k == "accuracy"}
        for item in value.values():
            out |= _accuracy_values(item)
        return out
    if isinstance(value, list):
        return set().union(*(_accuracy_values(item) for item in value)) if value else set()
    return set()


class _ConsensusWireProvider:
    """Offline provider: scripted extraction, and the real `BaseLLMProvider.synthesize_consensus`,
    so consensus goes through the real prompt builders. Records what is sent to the model."""

    def __new__(cls, extraction: ExtractionResult) -> Any:
        from stock_ontology.llm.base import BaseLLMProvider

        class Provider(BaseLLMProvider):
            name = "offline"
            chat_model = "offline"
            extract_stage = None  # type: ignore[assignment]

            def __init__(self) -> None:
                self.consensus_requests: list[dict[str, str]] = []

            def is_configured(self) -> bool:
                return True

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [_deterministic_embed(t) for t in texts]

            def extract_document(self, **_: Any) -> ExtractionResult:
                return extraction

            def generate_structured(self, *, system_instruction: str, prompt: str, schema: type[Any]) -> Any:
                assert schema is ConsensusSynthesis, schema
                self.consensus_requests.append({"system": system_instruction, "prompt": prompt})
                return ConsensusSynthesis(
                    stance="buy", support_strength="moderate", conviction="medium",
                    summary="Offline synthesis.", pillars=["Demand holds", "Supply keeps pace"],
                    supporting_node_ids=[], contradicting_node_ids=[], facets=[],
                )

            def generate_agent_reply(self, **_: Any) -> Any:
                raise NotImplementedError

        return Provider()


def test_consensus_input_carries_rumor_author_accuracy_and_weighting_rule(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    registry = load_registry(SHIPPED_REGISTRY)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-11-20_acme_chatter.md").write_text("Chatter about Acme Widgets.", encoding="utf-8")
    rumor_low = _authored_view("v_ron", "Ron Hears Acme Order", "rumor", "e_acme", "p_ron")
    rumor_unrated = _authored_view("v_una", "Una Hears Acme Delay", "rumor", "e_acme", "p_una")
    report_rated = _authored_view("v_rita", "Rita Initiates Acme", "analyst_report", "e_acme", "p_rita")
    llm = _ConsensusWireProvider(_extraction(
        [
            _company("e_acme", "Acme Widgets", "ACMW"),
            # `credibility` is the note's self-description; it must play no part in the weighting.
            _person("p_ron", "Ron Rumorson", role="Trader", organization="Street Desk", credibility="high"),
            _person("p_una", "Una Unrated", role="Trader", organization="Floor Desk", credibility="low"),
            _person("p_rita", "Rita Rated", role="Analyst", organization="Rated Research"),
        ],
        [rumor_low, rumor_unrated, report_rated],
    ))

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, registry=registry) as db:
        pipeline = IngestionPipeline(db, llm, data_dir, registry=registry)
        first = pipeline.run()
        assert first.errors == [] and first.consensus_updated_for == ["Acme Widgets"]
        _set_person_facets(db, "Ron Rumorson", accuracy="low")
        _set_person_facets(db, "Rita Rated", accuracy="high")
        llm.consensus_requests.clear()
        report = pipeline.run(rebuild_consensus=True)
        assert report.consensus_updated_for == ["Acme Widgets"]
        views = {v.name: v.id for v in db.list_nodes(node_type="view", limit=100)}

    request, = llm.consensus_requests
    prompt = request["prompt"]

    def accuracy_shown(view_name: str) -> set[str]:
        entries = _json_entries_with_id(prompt, views[view_name])
        assert entries, f"{view_name} is missing from the consensus input"
        return set().union(*(_accuracy_values(entry) for entry in entries))

    assert accuracy_shown("Ron Hears Acme Order") == {"low"}, "a rumor must carry its author's accuracy"
    assert accuracy_shown("Una Hears Acme Delay") == {"unrated"}, (
        "a rumor by a person with no accuracy must show `unrated`, whatever the note's credibility says"
    )
    assert accuracy_shown("Rita Initiates Acme") == set(), "only rumors carry author accuracy"
    system = request["system"]
    assert "accuracy" in system.lower() and "unrated" in system, (
        "the synthesis instructions must state how author accuracy weighs rumors"
    )


def test_reingest_never_sets_or_changes_person_accuracy(tmp_path: Path) -> None:
    from stock_ontology.registry import load_registry

    class AccuracyClaimingLLM(FakePipelineLLM):
        def extract_document(self, **_: Any) -> ExtractionResult:
            return _extraction(
                [
                    _company("e_acme", "Acme Widgets", "ACMW"),
                    _person("p_ivy", "Ivy Insider", role="Trader", organization="Street Desk", accuracy="high"),
                ],
                [_authored_view("v_ivy", "Ivy Hears Acme Order", "rumor", "e_acme", "p_ivy")],
            )

    registry = load_registry(SHIPPED_REGISTRY)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    note = data_dir / "2026-11-20_ivy.md"
    note.write_text("Ivy says Acme has a big order.", encoding="utf-8")
    llm = AccuracyClaimingLLM()
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, registry=registry) as db:
        pipeline = IngestionPipeline(db, llm, data_dir, registry=registry)
        assert pipeline.run().errors == []
        ivy = db.find_by_name_or_alias("Ivy Insider", node_type="entity")
        assert ivy is not None
        assert "accuracy" not in ivy.facets, "extraction must not set a person's accuracy"

        _set_person_facets(db, "Ivy Insider", accuracy="low")
        note.write_text("Ivy says Acme has a bigger order.", encoding="utf-8")
        assert pipeline.run().errors == []
        ivy = db.find_by_name_or_alias("Ivy Insider", node_type="entity")
        assert ivy is not None and ivy.facets.get("accuracy") == "low", (
            "re-ingesting a note must not change a person's accuracy"
        )


def test_person_accuracy_correction_is_checked_stored_and_refreshes_all_their_rumors(tmp_path: Path) -> None:
    from stock_ontology.config import Settings
    from stock_ontology.registry import load_registry, save_registry
    from stock_ontology.services.corrections import review_note_correction
    from stock_ontology.services.errors import ServiceError
    from stock_ontology.services.processing import ProcessingService
    from stock_ontology.worker import Worker

    ron = _person("p_ron", "Ron Rumorson", role="Trader", organization="Street Desk", credibility="high")

    class TwoNotesLLM(FakePipelineLLM):
        def extract_document(self, *, source_meta: dict[str, Any], **_: Any) -> ExtractionResult:
            if "acme" in source_meta["file_path"]:
                company, view = _company("e_c", "Acme Widgets", "ACMW"), "Ron Hears Acme Order"
            else:
                company, view = _company("e_c", "Beta Gears", "BTAG"), "Ron Hears Beta Delay"
            return _extraction([company, ron], [_authored_view("v_ron", view, "rumor", "e_c", "p_ron")])

    settings = Settings(db_path=tmp_path / "ontology.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path / "data", embedding_dim=DIM)
    settings.data_dir.mkdir()
    registry = load_registry(SHIPPED_REGISTRY)
    save_registry(registry, settings.registry_path)
    acme_note = settings.data_dir / "2026-11-20_acme.md"
    acme_note.write_text("Ron on Acme.", encoding="utf-8")
    (settings.data_dir / "2026-11-21_beta.md").write_text("Ron on Beta.", encoding="utf-8")
    llm = TwoNotesLLM()
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        assert IngestionPipeline(db, llm, settings.data_dir, registry=registry).run().errors == []
        person = db.find_by_name_or_alias("Ron Rumorson", node_type="entity")
        assert person is not None

    def correct(changes: dict[str, Any]) -> dict[str, Any]:
        with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry, read_only=True) as db:
            payload = review_note_correction(db, acme_note, settings.data_dir, kind="person",
                                             record=person.id, changes=changes)
        jobs = ProcessingService(settings)
        ref = jobs.submit_correction("note.ontology.correction", acme_note.name, payload)
        Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
        status = jobs.get_status(ref.job_id)
        assert status["state"] == "succeeded", status
        return status

    def stored() -> dict[str, Any]:
        with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
            node = db.get_node(person.id)
            assert node is not None
            return node.facets

    # Corrected from the Acme note, the refresh still reaches Beta, where Ron's other rumor lives.
    status = correct({"accuracy": "low"})
    assert stored().get("accuracy") == "low"
    assert stored().get("credibility") == "high", "the LLM-set credibility must be left as it was"
    assert set(status["result"]["consensus_updated_for"]) >= {"Acme Widgets", "Beta Gears"}

    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry, read_only=True) as db:
        with pytest.raises(ServiceError):
            review_note_correction(db, acme_note, settings.data_dir, kind="person",
                                   record=person.id, changes={"accuracy": "excellent"})

    correct({"accuracy": None})
    assert "accuracy" not in stored(), "clearing accuracy must leave the person unrated"


def test_apply_note_correction_writes_reviewed_person_and_edges_and_queues_consensus(tmp_path: Path) -> None:
    """A reviewed `note.ontology.correction` payload applies through the public pipeline method."""
    from stock_ontology.config import NoteConflictError
    from stock_ontology.registry import load_registry
    from stock_ontology.services.corrections import review_note_correction

    ron = _person("p_ron", "Ron Rumorson", role="Trader", organization="Acme Widgets")

    class ThreeNotesLLM(FakePipelineLLM):
        def extract_document(self, *, source_meta: dict[str, Any], **_: Any) -> ExtractionResult:
            file = source_meta["file_path"]
            if "acme" in file:
                result = _extraction([_company("e_c", "Acme Widgets", "ACMW"), ron], [])
                result.edges.append(ExtractedEdge(
                    from_ref="p_ron", to_ref="e_c", relation="WORKS_AT", facets=[FacetKV(key="role", value="Trader")],
                ))
                return result
            if "beta" in file:
                return _extraction([_company("e_c", "Beta Gears", "BTAG"), ron],
                                   [_authored_view("v_ron", "Ron Hears Beta Delay", "rumor", "e_c", "p_ron")])
            return _extraction([_company("e_c", "Gamma Tools", "GMTL")], [])

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    acme_note = data_dir / "2026-11-20_acme.md"
    acme_note.write_text("Ron works at Acme.", encoding="utf-8")
    (data_dir / "2026-11-21_beta.md").write_text("Ron on Beta.", encoding="utf-8")
    (data_dir / "2026-11-22_gamma.md").write_text("Gamma Tools.", encoding="utf-8")
    registry = load_registry(SHIPPED_REGISTRY)
    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, registry=registry) as db:
        pipeline = IngestionPipeline(db, ThreeNotesLLM(), data_dir, registry=registry)
        assert pipeline.run().errors == []
        ids = {name: node.id for name in ("Ron Rumorson", "Acme Widgets", "Beta Gears", "Gamma Tools")
               if (node := db.find_by_name_or_alias(name, node_type="entity")) is not None}
        assert len(ids) == 4, ids
        doc_id = db.get_note_state("2026-11-20_acme.md")["doc_id"]
        works_at, = [row for row in db.list_note_edges(doc_id) if row["relation"] == "WORKS_AT"]
        assert works_at["to_id"] == ids["Acme Widgets"]

        reviewed = review_note_correction(db, acme_note, data_dir, kind="person", record=ids["Ron Rumorson"],
                                          changes={"organization": "Gamma Tools", "accuracy": "low"})
        assert reviewed["edges"], "the organization change must review the supporting WORKS_AT edge"

        def snapshot() -> tuple[Any, ...]:
            return (
                db.get_node(ids["Ron Rumorson"]), sorted(map(str, db.list_note_edges(doc_id))),
                {node.id for node in db.list_note_entities(doc_id)}, db.jobs.list_consensus_refresh(),
            )

        # The note changed after review: the correction conflicts and writes nothing.
        before = snapshot()
        acme_note.write_text("Ron works at Acme, revised.", encoding="utf-8")
        with pytest.raises(NoteConflictError):
            pipeline.apply_note_correction(acme_note, reviewed)
        assert snapshot() == before

        # The reviewed revision is back: the same payload now applies.
        acme_note.write_text("Ron works at Acme.", encoding="utf-8")
        targets = {company: db.jobs.consensus_target(ids[company])
                   for company in ("Acme Widgets", "Beta Gears", "Gamma Tools")}
        pipeline.apply_note_correction(acme_note, reviewed)

        person = db.get_node(ids["Ron Rumorson"])
        assert person is not None
        assert (person.facets.get("organization"), person.facets.get("accuracy")) == ("Gamma Tools", "low")
        works_at, = [row for row in db.list_note_edges(doc_id) if row["relation"] == "WORKS_AT"]
        # A new endpoint replaces the edge: a new ID, so a form opened before the correction no longer matches.
        before = reviewed["edges"][0]["before"]
        assert works_at["edge_id"] != before["edge_id"] and works_at["to_id"] == ids["Gamma Tools"]
        assert works_at["created_at"] == before["created_at"]
        assert ids["Gamma Tools"] in {node.id for node in db.list_note_entities(doc_id)}
        # Consensus is queued, not run: the note's companies before and after, and the companies of
        # Ron's rumor in another note (an accuracy change reweighs it), all wait for a refresh.
        pending = set(db.jobs.pending_consensus())
        for company, target in targets.items():
            assert db.jobs.consensus_target(ids[company]) > target, company
            assert ids[company] in pending, company
