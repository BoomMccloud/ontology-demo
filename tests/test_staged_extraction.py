"""Three ordered extraction runs per note: entities and themes, then events, then views."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stock_ontology.db import OntologyDB
from stock_ontology.llm import EXTRACTION_STAGES, build_stage_prompt
from stock_ontology.llm.base import BaseLLMProvider
from stock_ontology.llm.prompts import STAGE_SCHEMAS, STAGE_SYSTEM_PROMPTS
from stock_ontology.models import (
    ConsensusSynthesis,
    EntityStageResult,
    EventStageResult,
    ExtractionResult,
    ViewStageResult,
)
from stock_ontology.pipeline import MAX_EXTRACTION_ATTEMPTS, IngestionPipeline
from stock_ontology.registry import load_registry

DIM = 8
SHIPPED = Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _entities(**overrides: Any) -> dict[str, Any]:
    payload = {
        "entities": [
            {"temp_id": "e1", "name": "Acme", "summary": "c", "entity_type": "company",
             "facets": [{"key": "sector", "value": "Tech"}]},
            {"temp_id": "e2", "name": "Jo Lee", "summary": "p", "entity_type": "person",
             "facets": [{"key": "role", "value": "Analyst"}, {"key": "organization", "value": "Acme"}]},
        ],
        "themes": [{"temp_id": "t1", "name": "AI Capex", "summary": "t", "stage": "emerging"}],
        "edges": [
            {"from_ref": "e2", "to_ref": "e1", "relation": "WORKS_AT"},
            {"from_ref": "e1", "to_ref": "t1", "relation": "EXPOSED_TO",
             "facets": [{"key": "sentiment", "value": "positive"}]},
        ],
    }
    return {**payload, **overrides}


def _events(**overrides: Any) -> dict[str, Any]:
    payload = {
        "events": [{"temp_id": "e1", "name": "Acme beat", "summary": "Beat.", "event_type": "earnings"}],
        "edges": [{"from_ref": "e1", "to_ref": "r1.e1", "relation": "ABOUT"}],
    }
    return {**payload, **overrides}


def _views(*facets: dict[str, str]) -> dict[str, Any]:
    return {
        "views": [{"temp_id": "e1", "name": "Jo on Acme", "summary": "Buy.", "view_type": "analyst_report",
                   "stance": "bullish", "facets": list(facets)}],
        "edges": [
            {"from_ref": "e1", "to_ref": "r1.e1", "relation": "ABOUT"},
            {"from_ref": "e1", "to_ref": "r1.e2", "relation": "AUTHORED_BY"},
            {"from_ref": "r2.e1", "to_ref": "e1", "relation": "SUPPORTS"},
        ],
    }


class _StageLLM:
    """Returns scripted payloads per stage; the last payload for a stage repeats."""

    def __init__(self, **scripts: list[dict[str, Any]]) -> None:
        self.scripts = {"entities": [_entities()], "events": [_events()], "views": [_views()], **scripts}
        self.calls: list[str] = []
        self.priors: dict[str, ExtractionResult] = {}

    def format_chain_summary(self) -> str:
        return "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]

    def extract_document(self, **_: Any) -> ExtractionResult:
        raise AssertionError("a staged client must not make the single-call extraction")  # noqa: TRY003

    def extract_stage(self, *, stage: str, prior: ExtractionResult, **_: Any) -> ExtractionResult:
        count = self.calls.count(stage)
        self.calls.append(stage)
        self.priors[stage] = prior
        script = self.scripts[stage]
        return ExtractionResult.model_validate(script[min(count, len(script) - 1)])

    def synthesize_consensus(self, **_: Any) -> ConsensusSynthesis:
        return ConsensusSynthesis(stance="bullish", support_strength="moderate", conviction="medium", summary="s", pillars=["p"])


def _ingest(tmp_path: Path, llm: _StageLLM) -> tuple[Any, Path]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "note.md").write_text("Acme note.", encoding="utf-8")
    reg = load_registry(SHIPPED)
    db_path = tmp_path / "o.db"
    with OntologyDB(db_path, embedding_dim=DIM, registry=reg) as db:
        report = IngestionPipeline(db, llm, data, registry=reg).run()
    return report, db_path


def _relations(db_path: Path) -> list[str]:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        return sorted(r[0] for r in db.conn.execute("SELECT relation FROM edges WHERE json_extract(facets_json, '$.basis') = 'extracted'"))


def test_runs_go_in_order_and_each_sees_what_earlier_runs_resolved(tmp_path: Path) -> None:
    llm = _StageLLM()
    report, db_path = _ingest(tmp_path, llm)
    assert report.errors == [] and llm.calls == list(EXTRACTION_STAGES)
    assert llm.priors["entities"].entities == []
    assert [n.temp_id for n in llm.priors["events"].entities] == ["r1.e1", "r1.e2"]
    assert [n.temp_id for n in llm.priors["events"].themes] == ["r1.t1"]
    assert llm.priors["events"].events == []
    assert [n.temp_id for n in llm.priors["views"].events] == ["r2.e1"]
    assert _relations(db_path) == ["ABOUT", "ABOUT", "AUTHORED_BY", "EXPOSED_TO", "SUPPORTS", "WORKS_AT"]


def test_same_temp_id_in_different_runs_does_not_collide(tmp_path: Path) -> None:
    report, db_path = _ingest(tmp_path, _StageLLM())
    assert report.errors == [] and report.unresolved_edge_refs == 0
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        kinds = sorted(n.node_type for n in db.list_all_nodes() if n.node_type in ("event", "entity"))
    assert kinds == ["entity", "entity", "event"]


def test_stage_schemas_only_allow_the_node_types_each_run_owns() -> None:
    assert set(EntityStageResult.model_fields) == {"entities", "themes", "edges"}
    assert set(EventStageResult.model_fields) == {"events", "edges"}
    assert set(ViewStageResult.model_fields) == {"views", "edges"}
    assert list(STAGE_SCHEMAS) == list(EXTRACTION_STAGES) == list(STAGE_SYSTEM_PROMPTS)


def test_bad_view_value_repeats_only_the_view_run(tmp_path: Path) -> None:
    bad = _views({"key": "target_price", "value": "$650"})
    good = _views({"key": "target_price", "value": "USD 650"})
    llm = _StageLLM(views=[bad, good])
    report, db_path = _ingest(tmp_path, llm)
    assert report.errors == [] and llm.calls == ["entities", "events", "views", "views"]
    assert report.extraction_retries == {"views": 1}
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        view = next(n for n in db.list_all_nodes() if n.node_type == "view" and n.source_doc_id)
    assert view.facets["target_price"] == {"amount": 650, "currency": "USD"}


def test_bad_event_repeats_the_event_and_view_runs(tmp_path: Path) -> None:
    bad = _events(events=[{"temp_id": "e1", "name": "x" * 201, "summary": "s", "event_type": "news"}])
    llm = _StageLLM(events=[bad, _events()])
    report, _ = _ingest(tmp_path, llm)
    assert report.errors == [] and llm.calls == ["entities", "events", "views", "events", "views"]
    assert report.extraction_retries == {"events": 1}


def test_bad_entity_repeats_every_run(tmp_path: Path) -> None:
    bad = _entities(edges=[{"from_ref": "e1", "to_ref": "t1", "relation": "EXPOSED_TO"}])
    llm = _StageLLM(entities=[bad, _entities()])
    report, _ = _ingest(tmp_path, llm)
    assert report.errors == [] and llm.calls == [*EXTRACTION_STAGES, *EXTRACTION_STAGES]
    assert report.extraction_retries == {"entities": 1}


def test_note_fails_atomically_after_the_retry_cap(tmp_path: Path) -> None:
    llm = _StageLLM(views=[_views({"key": "view_type", "value": "x"}) | {"views": [{"temp_id": "v", "name": "x" * 201, "summary": "s", "view_type": "rumor"}]}])
    report, db_path = _ingest(tmp_path, llm)
    assert llm.calls.count("views") == MAX_EXTRACTION_ATTEMPTS and llm.calls.count("entities") == 1
    assert [path for path, _ in report.errors] == ["note.md"]
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.list_all_nodes() == [] and db.get_ingestion_log() == {}


def test_missing_reference_is_counted_and_the_note_is_kept(tmp_path: Path) -> None:
    events = _events(edges=[
        {"from_ref": "e1", "to_ref": "r1.e1", "relation": "ABOUT"},
        {"from_ref": "e1", "to_ref": "Nobody Inc", "relation": "ABOUT"},
    ])
    report, _ = _ingest(tmp_path, _StageLLM(events=[events]))
    assert report.errors == [] and report.unresolved_edge_refs == 1


def test_existing_catalog_id_in_run_one_is_reused_not_duplicated(tmp_path: Path) -> None:
    first = _StageLLM()
    _, db_path = _ingest(tmp_path, first)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        acme = next(n for n in db.list_all_nodes() if n.name == "Acme")
    reused = _entities()
    reused["entities"][0]["temp_id"] = acme.id
    reused["edges"] = [{"from_ref": "e2", "to_ref": acme.id, "relation": "WORKS_AT"}]
    views = _views()
    views["edges"] = [{"from_ref": "e1", "to_ref": acme.id, "relation": "ABOUT"}]
    events = _events(edges=[{"from_ref": "e1", "to_ref": acme.id, "relation": "ABOUT"}])
    second = _StageLLM(entities=[reused], events=[events], views=[views])
    (tmp_path / "data" / "note2.md").write_text("Second note.", encoding="utf-8")
    reg = load_registry(SHIPPED)
    with OntologyDB(db_path, embedding_dim=DIM, registry=reg) as db:
        report = IngestionPipeline(db, second, tmp_path / "data", registry=reg).run()
        assert report.errors == [] and report.unresolved_edge_refs == 0
        assert sum(n.name == "Acme" for n in db.list_all_nodes()) == 1
    assert second.priors["events"].entities[0].temp_id == acme.id


def test_client_without_stages_still_makes_one_extraction_call(tmp_path: Path) -> None:
    class OneCall(_StageLLM):
        extract_stage = None  # type: ignore[assignment]

        def extract_document(self, **_: Any) -> ExtractionResult:
            self.calls.append("document")
            return ExtractionResult.model_validate(_entities())

    llm = OneCall()
    report, _ = _ingest(tmp_path, llm)
    assert report.errors == [] and llm.calls == ["document"]


class _Provider(BaseLLMProvider):
    name = "stub"
    chat_model = "stub"

    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def is_configured(self) -> bool:
        return True

    def generate_structured(self, *, system_instruction: str, prompt: str, schema: type[Any]) -> Any:
        self.seen = {"system": system_instruction, "prompt": prompt, "schema": schema}
        return schema()

    def generate_agent_reply(self, **_: Any) -> Any:
        raise NotImplementedError


@pytest.mark.parametrize("stage", EXTRACTION_STAGES)
def test_provider_uses_each_runs_prompt_and_schema(stage: str) -> None:
    provider = _Provider()
    result = provider.extract_stage(
        stage=stage, text="Doc.", source_meta={}, existing_catalog="", known_facets={}, prior=ExtractionResult()
    )
    assert isinstance(result, ExtractionResult)
    assert provider.seen["schema"] is STAGE_SCHEMAS[stage]
    assert provider.seen["system"] == STAGE_SYSTEM_PROMPTS[stage]


def test_stage_prompt_lists_resolved_ids() -> None:
    prior = ExtractionResult.model_validate(_entities())
    prompt = build_stage_prompt(text="Doc.", source_meta={}, existing_catalog="", known_facets={}, prior=prior)
    assert "- [e1] (entity:company) Acme" in prompt and "- [t1] (theme) AI Capex" in prompt


def test_entity_prompt_asks_for_employers_and_deal_values() -> None:
    prompt = STAGE_SYSTEM_PROMPTS["entities"]
    assert "WORKS_AT" in prompt and "EVERY person" in prompt and "transaction_value" in prompt
    assert "Do not extract products" in prompt


def test_consensus_prompt_keeps_summary_inside_the_registry_limit() -> None:
    from stock_ontology.llm.prompts import CONSENSUS_SYSTEM_PROMPT

    limit = load_registry(SHIPPED).metadata_max_length["summary"]
    assert "under 900 characters" in CONSENSUS_SYSTEM_PROMPT and 900 < limit
