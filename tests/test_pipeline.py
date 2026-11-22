"""Offline end-to-end tests for the one-directional ingestion & consensus pipeline."""

from __future__ import annotations

import hashlib
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import stock_ontology.pipeline as pipeline_module
from stock_ontology.db import OntologyDB
from stock_ontology.llm import AgentTurn
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

    def generate_agent_reply(
        self,
        *,
        system_instruction: str,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> AgentTurn:
        raise NotImplementedError("Not used in pipeline tests.")


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
        assert cons1.facets["stance"] == "buy"
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

        # 3. Vector-distance merge: a note referring to "Nvidia Corporation" (not in aliases yet) merges into NVIDIA.
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
        assert cons2.facets["stance"] == "hold"
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
            assert cons.facets["stance"] == "buy"


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
                )
            ],
            events=[
                ExtractedEvent(temp_id="ev1", name="Zeta Order Win", summary="Won a hyperscaler order."),
                ExtractedEvent(temp_id="ev2", name="Zeta POISON Launch", summary="Launched a new module."),
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
            events=[ExtractedEvent(temp_id="ev1", name="LGC Dividend", summary="Raised its dividend.")],
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


class _StopWatch(BaseException):
    pass


def test_pipeline_watch_continues_after_a_run_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    calls: list[int] = []

    with OntologyDB(tmp_path / "ontology.db", embedding_dim=DIM, read_only=False) as db:
        pipeline = IngestionPipeline(db, FakePipelineLLM(), data_dir)

        def flaky_run(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient failure in tick 1")  # noqa: TRY003
            raise _StopWatch

        monkeypatch.setattr(pipeline, "run", flaky_run)
        monkeypatch.setattr(pipeline_module.time, "sleep", lambda _s: None)
        try:
            pipeline.watch(interval_seconds=0)
        except _StopWatch:
            pass
        except RuntimeError as exc:
            pytest.fail(f"watch() stopped after a failing tick: {exc}")
        assert len(calls) == 2


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
            events=[ExtractedEvent(temp_id="ev1", name=event_name, summary="Zeta update.")],
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
