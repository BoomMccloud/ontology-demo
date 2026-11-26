"""Offline worker integration tests: an agent drives notes, jobs, and reads through CLI JSON."""

from __future__ import annotations

import json
import time
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import stock_ontology.cli as cli_module
from stock_ontology.config import Settings
from stock_ontology.models import (
    ConsensusSynthesis,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedEvent,
    ExtractionResult,
    Node,
)
from stock_ontology.web import create_app

DIM = 8
COMPANY = "Acme Robotics"
EVENT = "Acme Q3 orders up 40%"
CONSENSUS_SUMMARY = "Acme demand is accelerating on Q3 orders."
LIVE_KEY_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_AP_SOUTHEAST_1_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_COMPAT_API_KEY",
)


class _WorkerKilled(BaseException):
    """Stands in for the worker process dying; nothing in the worker may catch it."""


class _JourneyLLM:
    """Offline fake: one company and event per note; the first consensus call kills the worker."""

    def __init__(self) -> None:
        self.extract_calls: list[str] = []
        self.consensus_calls: list[str] = []

    def format_chain_summary(self) -> str:
        return "fake"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]

    def extract_document(self, *, source_meta: dict[str, Any], **_: Any) -> ExtractionResult:
        self.extract_calls.append(str(source_meta["file_path"]))
        return ExtractionResult(
            entities=[
                ExtractedEntity(
                    temp_id="e_acme", name=COMPANY, summary="Warehouse robots.", entity_type="company"
                )
            ],
            events=[
                ExtractedEvent(
                    temp_id="ev_q3",
                    name=EVENT,
                    summary="Acme reported Q3 orders up 40% year over year.",
                    event_type="fact",
                    event_date="2026-11-20",
                )
            ],
            edges=[ExtractedEdge(from_ref="ev_q3", to_ref="e_acme", relation="ABOUT")],
        )

    def synthesize_consensus(self, *, company: Node, events: list[Node], **_: Any) -> ConsensusSynthesis:
        self.consensus_calls.append(company.name)
        if len(self.consensus_calls) == 1:
            raise _WorkerKilled
        return ConsensusSynthesis(
            stance="buy",
            support_strength="strong",
            conviction="high",
            summary=CONSENSUS_SUMMARY,
            pillars=["Orders growth"],
            supporting_node_ids=[ev.id for ev in events],
        )


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_agent_journey_through_cli_json_survives_worker_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = tmp_path / "ontology.db"
    for var in LIVE_KEY_VARS:
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("EMBEDDING_DIM", str(DIM))
    monkeypatch.setenv("ONTOLOGY_DB", str(db_path))
    monkeypatch.setenv("ONTOLOGY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ONTOLOGY_REGISTRY", str(tmp_path / "missing_registry.json"))
    llm = _JourneyLLM()
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: llm)
    runner = CliRunner()

    saved = _json(
        runner.invoke(
            cli_module.app,
            ["note", "save", "--title", "Acme Q3 check", "--text", "Acme Q3 orders rose 40%.", "--json"],
        )
    )
    note_file = saved["file"]
    assert (data_dir / note_file).is_file()

    job_id = _json(runner.invoke(cli_module.app, ["process", note_file, "--json"]))["job_id"]
    assert job_id

    # First worker run extracts, then dies inside consensus while holding its claim.
    with pytest.raises(_WorkerKilled):
        runner.invoke(
            cli_module.app, ["worker", "--once", "--lease-seconds", "2"], catch_exceptions=False
        )
    time.sleep(2.5)  # Let the dead worker's lease expire.

    restarted = runner.invoke(cli_module.app, ["worker", "--once", "--lease-seconds", "60"])
    assert restarted.exit_code == 0, restarted.output

    status = _json(runner.invoke(cli_module.app, ["status", job_id, "--json"]))
    assert status["state"] == "succeeded"
    assert llm.extract_calls == [note_file]
    assert llm.consensus_calls == [COMPANY, COMPANY]

    overview = _json(runner.invoke(cli_module.app, ["entity", COMPANY, "--json"]))
    assert overview["entity"]["name"] == COMPANY
    assert overview["consensus"]["summary"] == CONSENSUS_SUMMARY
    assert overview["consensus"]["stale"] is False
    cited = {(ev["name"], ev["source"]["file"]) for ev in overview["events"]}
    assert cited == {(EVENT, note_file)}

    settings = Settings(
        db_path=db_path, embedding_dim=DIM, data_dir=data_dir, registry_path=tmp_path / "missing_registry.json"
    )
    page = TestClient(create_app(settings, llm=llm)).get(f"/entity/{overview['entity']['id']}")
    assert page.status_code == 200
    html = unescape(page.text)
    assert CONSENSUS_SUMMARY in html
    assert EVENT in html
    assert note_file in html


# ---------------------------------------------------------------------------
# Builder-owned supporting tests (proposal `modular-worker`). The protected witness above
# is unchanged; everything below exercises the job store, worker, and CLI contract directly.
# ---------------------------------------------------------------------------

import sqlite3  # noqa: E402
import sys  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from stock_ontology.db import LeaseLostError, OntologyDB  # noqa: E402
from stock_ontology.registry import create_minimal_registry, save_registry  # noqa: E402
from stock_ontology.services import ProcessingService  # noqa: E402
from stock_ontology.worker import Worker  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _ScriptLLM:
    """Offline fake whose extraction and synthesis can run a hook first."""

    def __init__(
        self,
        *,
        on_extract: Callable[[int], None] | None = None,
        on_consensus: Callable[[int, Node], None] | None = None,
        summary: str = CONSENSUS_SUMMARY,
    ) -> None:
        self.on_extract = on_extract
        self.on_consensus = on_consensus
        self.summary = summary
        self.extract_calls: list[str] = []
        self.consensus_calls: list[str] = []

    def format_chain_summary(self) -> str:
        return "fake"

    def close(self) -> None:
        return None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]

    def extract_document(self, *, source_meta: dict[str, Any], text: str, **_: Any) -> ExtractionResult:
        self.extract_calls.append(str(source_meta["file_path"]))
        if self.on_extract is not None:
            self.on_extract(len(self.extract_calls))
        return ExtractionResult(
            entities=[ExtractedEntity(temp_id="e_acme", name=COMPANY, summary="Robots.", entity_type="company")],
            events=[
                ExtractedEvent(
                    temp_id="ev", name=text.strip().splitlines()[0][:80], summary="Evidence.",
                    event_type="fact", event_date="2026-11-20",
                )
            ],
            edges=[ExtractedEdge(from_ref="ev", to_ref="e_acme", relation="ABOUT")],
        )

    def synthesize_consensus(self, *, company: Node, events: list[Node], **_: Any) -> ConsensusSynthesis:
        self.consensus_calls.append(company.name)
        if self.on_consensus is not None:
            self.on_consensus(len(self.consensus_calls), company)
        return ConsensusSynthesis(
            stance="buy", support_strength="strong", conviction="high", summary=self.summary,
            pillars=["Orders growth"], supporting_node_ids=[ev.id for ev in events],
        )


def _workspace(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return Settings(
        db_path=tmp_path / "ontology.db", embedding_dim=DIM, data_dir=data_dir,
        registry_path=tmp_path / "missing_registry.json",
    )


def _note(settings: Settings, name: str, text: str) -> Path:
    path = settings.data_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def _worker(settings: Settings, llm: Any, clock: _Clock, lease: int = 30) -> Worker:
    return Worker(settings, llm_factory=lambda _settings: llm, lease_seconds=lease, clock=clock)


def _read(settings: Settings) -> OntologyDB:
    return OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True)


def test_job_claim_holds_a_lease_and_is_reclaimed_after_expiry(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    ref = ProcessingService(settings).request_processing("a.md")
    worker = _worker(settings, _ScriptLLM(), clock)
    with worker.open_store() as db:
        worker.intake(db)
        first = db.jobs.claim(clock(), 30)
        assert first is not None and first.job_id == ref.job_id and first.claim_id
        assert db.jobs.claim(clock(), 30) is None, "a live lease must not be claimed twice"
        db.jobs.check_claim(first.job_id, first.claim_id, clock(), 30)

        clock.advance(31)
        with pytest.raises(LeaseLostError):
            db.jobs.check_claim(first.job_id, first.claim_id, clock(), 30)
        second = db.jobs.claim(clock(), 30)
        assert second is not None and second.job_id == ref.job_id
        assert second.claim_id != first.claim_id and second.attempts == 2
        with pytest.raises(LeaseLostError):
            db.jobs.check_claim(first.job_id, first.claim_id, clock(), 30)
        db.jobs.check_claim(second.job_id, second.claim_id, clock(), 30)


def test_attempt_whose_lease_expired_cannot_commit_extraction(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    llm = _ScriptLLM(on_extract=lambda _n: clock.advance(31))
    ref = ProcessingService(settings).request_processing("a.md")

    _worker(settings, llm, clock).run_once(scan=False)

    with _read(settings) as db:
        assert db.get_note_state("a.md") is None, "an expired attempt committed its extraction"
        assert db.jobs.list_consensus_refresh() == []
    assert llm.extract_calls == ["a.md"] * 3
    assert ProcessingService(settings).get_status(ref.job_id)["state"] == "failed"


def test_late_consensus_attempt_cannot_publish_over_newer_evidence(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()

    def newer_evidence(call: int, company: Node) -> None:
        if call == 1:
            with OntologyDB(settings.db_path, embedding_dim=DIM) as other, other.transaction():
                other.jobs.mark_consensus_pending([company.id])

    llm = _ScriptLLM(on_consensus=newer_evidence)
    ref = ProcessingService(settings).request_processing("a.md")
    _worker(settings, llm, clock).run_once(scan=False)

    with _read(settings) as db:
        company = db.find_by_name_or_alias(COMPANY, node_type="entity")
        assert company is not None
        assert db.get_entity_consensus(company.id) is None, "a late attempt published consensus"
        refresh = db.jobs.consensus_state(company.id)
        assert refresh is not None
        assert (refresh["target_revision"], refresh["completed_revision"], refresh["state"]) == (2, 0, "pending")
    assert ProcessingService(settings).get_status(ref.job_id)["state"] == "queued"

    clock.advance(61)
    _worker(settings, llm, clock).run_once(scan=False)
    with _read(settings) as db:
        assert db.get_entity_consensus(company.id) is not None
        refresh = db.jobs.consensus_state(company.id)
        assert (refresh["completed_revision"], refresh["state"]) == (2, "current")
    assert llm.extract_calls == ["a.md"]
    assert ProcessingService(settings).get_status(ref.job_id)["state"] == "succeeded"


def test_registry_change_during_a_job_reopens_and_retries(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    adopted = create_minimal_registry()
    adopted.version += 1

    def adopt_registry(call: int) -> None:
        if call == 1:
            with OntologyDB(settings.db_path, embedding_dim=DIM) as other:
                other.record_registry_adoption(adopted, None, "test")

    llm = _ScriptLLM(on_extract=adopt_registry)
    ref = ProcessingService(settings).request_processing("a.md")
    _worker(settings, llm, clock).run_once(scan=False)

    status = ProcessingService(settings).get_status(ref.job_id)
    assert status["state"] == "succeeded", status
    assert status["attempts"] == 1, "a registry change must not consume the retry budget"
    with _read(settings) as db:
        assert db.get_note_state("a.md") is not None
        assert db.registry.revision() == adopted.revision()


def test_consensus_refresh_rows_commit_with_extraction_and_roll_back_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    original = OntologyDB.upsert_ingestion_log
    calls: list[int] = []

    def fail_once(self: OntologyDB, *args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk full")
        original(self, *args, **kwargs)

    monkeypatch.setattr(OntologyDB, "upsert_ingestion_log", fail_once)
    llm = _ScriptLLM()
    ref = ProcessingService(settings).request_processing("a.md")
    _worker(settings, llm, clock).run_once(scan=False)

    with _read(settings) as db:
        assert db.get_note_state("a.md") is None
        assert db.jobs.list_consensus_refresh() == [], "a rolled-back extraction left refresh rows"
        assert db.jobs.get(ref.job_id).companies == {}
    assert ProcessingService(settings).get_status(ref.job_id)["state"] == "queued"

    clock.advance(61)
    _worker(settings, llm, clock).run_once(scan=False)
    with _read(settings) as db:
        rows = db.jobs.list_consensus_refresh()
        assert [(row["target_revision"], row["completed_revision"], row["state"]) for row in rows] == [
            (1, 1, "current")
        ]
    assert ProcessingService(settings).get_status(ref.job_id)["state"] == "succeeded"


def test_corrections_are_claimed_ahead_of_earlier_extraction(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    _note(settings, "b.md", "Beta note\n")
    clock = _Clock()
    service = ProcessingService(settings)
    extraction = service.request_processing("a.md")
    correction = service.submit_correction(
        "note.entity.delete", "b.md", {"entity_id": "entity_x", "expected_hash": None}
    )
    worker = _worker(settings, _ScriptLLM(), clock)
    with worker.open_store() as db:
        worker.intake(db)
        first = db.jobs.claim(clock(), 30)
        second = db.jobs.claim(clock(), 30)
    assert first is not None and second is not None
    assert (first.job_id, second.job_id) == (correction.job_id, extraction.job_id)
    # Reader relationship jobs queued before they were retired still run ahead of extraction.
    from stock_ontology.services.processing import JOB_KINDS, job_priority

    retired = [kind for kind, entry in JOB_KINDS.items() if entry.submit == "retired"]
    assert retired and {job_priority(kind) for kind in retired} == {job_priority("note.entity.delete")}


# --- proposal `job-kind-registry`: one table of job kinds

_DECLARED_KINDS = {
    **{kind: (0, "correction") for kind in (
        "note.relink", "note.entity.add", "note.entity.delete", "note.ontology.correction",
    )},
    **{kind: (0, "retired") for kind in ("note.relationship", "note.relationship.add", "note.relationship.delete")},
    **{kind: (10, "operator") for kind in (
        "ingest", "reembed", "repair", "registry.publish", "registry.apply", "registry.apply.preview",
    )},
    "process": (20, "process"),
}


def _job_kinds() -> dict[str, Any]:
    from stock_ontology.services import processing

    table = getattr(processing, "JOB_KINDS", None)
    assert isinstance(table, dict), "services.processing.JOB_KINDS must be the one table of job kinds"
    return table


def test_spooled_job_of_an_undeclared_kind_fails_invalid_at_intake_and_is_never_claimed(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    clock = _Clock()
    service = ProcessingService(settings)
    service.spool.mkdir(parents=True)
    (service.spool / "00000000000000000001-enqueue-job_unknown.json").write_text(json.dumps({
        "op": "enqueue", "job_id": "job_unknown", "kind": "note.unknown", "target": "a.md", "revision": "",
        "payload": {"file": "a.md"}, "created_at": clock().isoformat(),
    }), encoding="utf-8")

    worker = _worker(settings, _ScriptLLM(), clock)
    with worker.open_store() as db:
        worker.intake(db)
        claimed = db.jobs.claim(clock(), 30)
    assert claimed is None, f"an undeclared kind must never be claimed, got {claimed and claimed.kind}"
    assert not service.has_submissions()
    status = service.get_status("job_unknown")
    assert (status["state"], status["error_code"]) == ("failed", "invalid")
    assert "note.unknown" in (status["error"] or "")


def test_worker_construction_fails_when_executors_and_the_kind_table_disagree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _workspace(tmp_path)
    table = _job_kinds()
    _worker(settings, _ScriptLLM(), _Clock())  # the shipped table and executors agree

    monkeypatch.setitem(table, "note.undeclared.executor", table["note.relink"])
    with pytest.raises(Exception, match="note.undeclared.executor"):
        _worker(settings, _ScriptLLM(), _Clock())
    monkeypatch.delitem(table, "note.undeclared.executor")

    monkeypatch.delitem(table, "reembed")
    with pytest.raises(Exception, match="reembed"):
        _worker(settings, _ScriptLLM(), _Clock())


def test_kind_table_declares_each_kind_once_with_its_priority_and_submitter(tmp_path: Path) -> None:
    from stock_ontology.services import ServiceError
    from stock_ontology.services.processing import job_priority

    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    service = ProcessingService(settings)
    for kind in ("note.relationship.add", "note.unknown"):
        with pytest.raises(ServiceError) as refused:
            service.submit_correction(kind, "a.md", {"expected_hash": None})
        assert (refused.value.code, refused.value.message) == ("invalid", f"Unknown correction: {kind}")
    with pytest.raises(ServiceError) as refused:
        service.submit_operator("note.relink", {})
    assert (refused.value.code, refused.value.message) == ("invalid", "Unknown operator job: note.relink")

    table = _job_kinds()
    assert {kind: (entry.priority, entry.submit) for kind, entry in table.items()} == _DECLARED_KINDS
    assert {kind: job_priority(kind) for kind in table} == {kind: entry.priority for kind, entry in table.items()}


def test_three_attempts_with_exponential_backoff_and_a_new_revision_resets_the_budget(
    tmp_path: Path,
) -> None:
    settings = _workspace(tmp_path)
    note = _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()

    def provider_down(_call: int) -> None:
        raise RuntimeError("provider down")

    llm = _ScriptLLM(on_extract=provider_down)
    service = ProcessingService(settings)
    ref = service.request_processing("a.md")
    worker = _worker(settings, llm, clock)

    worker.run_once(scan=False)
    status = service.get_status(ref.job_id)
    assert (status["state"], status["attempts"]) == ("queued", 1)
    assert status["next_attempt_at"] == (clock() + timedelta(seconds=60)).isoformat()
    assert "provider down" in status["error"]

    clock.advance(59)
    worker.run_once(scan=False)
    assert len(llm.extract_calls) == 1, "a job ran before its backoff elapsed"
    clock.advance(1)
    worker.run_once(scan=False)
    status = service.get_status(ref.job_id)
    assert (status["state"], status["attempts"]) == ("queued", 2)
    assert status["next_attempt_at"] == (clock() + timedelta(seconds=120)).isoformat()

    clock.advance(120)
    worker.run_once(scan=False)
    assert service.get_status(ref.job_id)["state"] == "failed"
    clock.advance(10_000)
    worker.run_once(scan=False)
    assert len(llm.extract_calls) == 3

    assert service.retry(ref.job_id).job_id == ref.job_id
    worker.run_once(scan=False)
    status = service.get_status(ref.job_id)
    assert (status["state"], status["attempts"]) == ("queued", 1), "retry reopens with a fresh budget"

    note.write_text("Alpha note, revised\n", encoding="utf-8")
    newer = service.request_processing("a.md")
    assert newer.job_id != ref.job_id
    assert service.get_status(newer.job_id)["attempts"] == 0
    assert service.request_processing("a.md").job_id == newer.job_id, "duplicate requests share a job"


def test_processing_an_unchanged_note_again_reopens_its_failed_job(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()

    def provider_down(_call: int) -> None:
        raise RuntimeError("provider down")

    llm = _ScriptLLM(on_extract=provider_down)
    service = ProcessingService(settings)
    ref = service.request_processing("a.md")
    worker = _worker(settings, llm, clock)
    for _ in range(3):
        worker.run_once(scan=False)
        clock.advance(10_000)
    assert service.get_status(ref.job_id)["state"] == "failed"

    again = service.request_processing("a.md")
    assert (again.job_id, again.state) == (ref.job_id, "queued")
    pending = service.get_status(ref.job_id)
    assert (pending["state"], pending["attempts"], pending["error"]) == ("queued", 0, None), (
        "a pending retry must not look like a failed attempt, or the page shows the old error"
    )
    worker.run_once(scan=False)
    status = service.get_status(ref.job_id)
    assert len(llm.extract_calls) == 4, "the reopened job did not run"
    assert (status["state"], status["attempts"]) == ("queued", 1), "a fresh attempt budget"


def test_a_pending_retry_reports_the_status_the_reopen_stores(tmp_path: Path) -> None:
    """Guards `_recorded_status` against drifting from what `JobStore.reopen` writes."""
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()

    def provider_down(_call: int) -> None:
        raise RuntimeError("provider down")

    service = ProcessingService(settings)
    ref = service.request_processing("a.md")
    worker = _worker(settings, _ScriptLLM(on_extract=provider_down), clock)
    for _ in range(3):
        worker.run_once(scan=False)
        clock.advance(10_000)
    assert service.get_status(ref.job_id)["state"] == "failed"

    service.request_processing("a.md")
    pending = service.get_status(ref.job_id)
    assert service.latest_for_note("a.md") == pending
    with worker.open_store() as db:
        worker.intake(db)
    stored = service.get_status(ref.job_id)

    # `reopen` restamps these two with the worker's clock; every other field must already match.
    restamped = {"next_attempt_at", "updated_at"}
    assert {k: v for k, v in pending.items() if k not in restamped} == {
        k: v for k, v in stored.items() if k not in restamped
    }


def test_stale_consensus_keeps_its_date_and_citations_until_replaced(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    failing = {"on": False}

    def maybe_fail(_call: int, _company: Node) -> None:
        if failing["on"]:
            raise RuntimeError("synthesis unavailable")

    llm = _ScriptLLM(on_consensus=maybe_fail)
    service = ProcessingService(settings)
    service.request_processing("a.md")
    _worker(settings, llm, clock).run_once(scan=False)
    runner = CliRunner()
    env = {
        "ONTOLOGY_DB": str(settings.db_path), "ONTOLOGY_DATA_DIR": str(settings.data_dir),
        "ONTOLOGY_REGISTRY": str(settings.registry_path), "EMBEDDING_DIM": str(DIM),
    }
    before = _json(runner.invoke(cli_module.app, ["entity", COMPANY, "--json"], env=env))
    assert before["consensus"]["stale"] is False

    failing["on"] = True
    _note(settings, "b.md", "Beta note\n")
    service.request_processing("b.md")
    _worker(settings, llm, clock).run_once(scan=False)

    after = _json(runner.invoke(cli_module.app, ["entity", COMPANY, "--json"], env=env))
    assert after["consensus"]["stale"] is True
    assert after["consensus"]["summary"] == before["consensus"]["summary"]
    assert after["consensus"]["as_of"] == before["consensus"]["as_of"]
    assert after["consensus"]["citations"] == before["consensus"]["citations"]
    assert {ev["source"]["file"] for ev in after["events"]} == {"a.md", "b.md"}

    page = TestClient(create_app(settings, llm=llm)).get(f"/entity/{after['entity']['id']}", params={"lang": "en"})
    assert page.status_code == 200
    assert 'data-consensus-stale' in page.text
    assert CONSENSUS_SUMMARY in unescape(page.text)


@contextmanager
def _writable_opens(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> Iterator[list[tuple[str, bool]]]:
    """Record (calling module, read_only) for every OntologyDB opened on `db_path`."""
    seen: list[tuple[str, bool]] = []
    original = OntologyDB.__init__

    def record(self: OntologyDB, path: Any, *args: Any, **kwargs: Any) -> None:
        if str(path) != ":memory:" and Path(path).resolve() == db_path.resolve():
            caller = sys._getframe(1).f_globals.get("__name__", "?")
            seen.append((caller, bool(kwargs.get("read_only", args[1] if len(args) > 1 else False))))
        original(self, path, *args, **kwargs)

    monkeypatch.setattr(OntologyDB, "__init__", record)
    yield seen


def _cli_env(settings: Settings, registry_path: Path) -> dict[str, str]:
    return {
        "ONTOLOGY_DB": str(settings.db_path), "ONTOLOGY_DATA_DIR": str(settings.data_dir),
        "ONTOLOGY_REGISTRY": str(registry_path), "EMBEDDING_DIM": str(DIM),
        **{var: "" for var in LIVE_KEY_VARS},
    }


def test_operator_commands_write_only_through_claimed_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    registry_path = tmp_path / "ontology_registry.json"
    save_registry(create_minimal_registry(), registry_path)
    proposal = create_minimal_registry()
    proposal.version += 1
    proposal_path = tmp_path / "proposal.json"
    save_registry(proposal, proposal_path)
    llm = _ScriptLLM()
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: llm)
    env = _cli_env(settings, registry_path)
    runner = CliRunner()
    db_options = ["--db", str(settings.db_path)]
    reg_options = [*db_options, "--registry", str(registry_path)]

    def latest(kind: str) -> Any:
        with _read(settings) as db:
            jobs = db.jobs.list(kind=kind)
        assert jobs, f"no {kind} job recorded"
        return jobs[-1]

    commands: list[tuple[str, list[str], str | None]] = [
        ("ingest", ["ingest", *db_options, "--data-dir", str(settings.data_dir)], None),
        ("ingest", ["ingest", *db_options, "--rebuild-consensus"], None),
        ("reembed", ["reembed", *db_options], None),
        ("registry.apply", ["registry-apply", *reg_options], "y\n"),
        ("repair", ["repair", *reg_options, "--json"], "y\n"),
        ("registry.publish", ["registry-publish", str(proposal_path), *reg_options], "y\n"),
        ("registry.apply", ["registry-apply", *reg_options], "y\n"),
    ]
    for kind, args, answer in commands:
        with _writable_opens(monkeypatch, settings.db_path) as opens:
            result = runner.invoke(cli_module.app, args, input=answer, env=env)
        monkeypatch.undo()
        monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: llm)
        assert result.exit_code == 0, (args, result.output)
        writers = {caller for caller, read_only in opens if not read_only}
        assert writers == {"stock_ontology.worker"}, (args, opens)
        assert latest(kind).state == "succeeded", args

    assert llm.consensus_calls == [COMPANY, COMPANY], "rebuild-consensus re-synthesized every company"
    with _read(settings) as db:
        assert db.registry.version == proposal.version

    _note(settings, "b.md", "Beta note\n")
    with _writable_opens(monkeypatch, settings.db_path) as opens:
        queued = runner.invoke(cli_module.app, ["ingest", *db_options, "--no-wait", "--json"], env=env)
    monkeypatch.undo()
    assert queued.exit_code == 0, queued.output
    assert [read_only for _, read_only in opens if not read_only] == []
    job_id = json.loads(queued.stdout)["job_id"]
    assert _json(runner.invoke(cli_module.app, ["status", job_id, "--json"], env=env))["state"] == "queued"


def test_cli_reads_are_read_only_and_errors_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _workspace(tmp_path)
    llm = _ScriptLLM()
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: llm)
    env = _cli_env(settings, settings.registry_path)
    runner = CliRunner()
    saved = _json(runner.invoke(
        cli_module.app, ["note", "save", "--title", "Alpha", "--text", "Alpha note", "--json"], env=env
    ))
    assert saved["job_id"]
    assert runner.invoke(cli_module.app, ["worker", "--once"], env=env).exit_code == 0

    with _writable_opens(monkeypatch, settings.db_path) as opens:
        listed = _json(runner.invoke(cli_module.app, ["note", "list", "--json"], env=env))
        status = _json(runner.invoke(cli_module.app, ["status", saved["job_id"], "--json"], env=env))
        overview = _json(runner.invoke(cli_module.app, ["entity", COMPANY, "--json"], env=env))
        missing = runner.invoke(cli_module.app, ["status", "job_missing", "--json"], env=env)
        unknown = runner.invoke(cli_module.app, ["entity", "Nobody Inc", "--json"], env=env)
        bad_note = runner.invoke(cli_module.app, ["process", "../escape.md", "--json"], env=env)
        inspect = runner.invoke(cli_module.app, ["inspect", COMPANY], env=env)
    monkeypatch.undo()
    assert opens and all(read_only for _, read_only in opens), opens
    assert inspect.exit_code == 0, inspect.output
    assert [(note["file"], note["status"]) for note in listed["notes"]] == [(saved["file"], "ingested")]
    assert status["state"] == "succeeded" and status["kind"] == "process"
    assert overview["entity"]["name"] == COMPANY
    for result, code, exit_code in ((missing, "not_found", 3), (unknown, "not_found", 3), (bad_note, "not_found", 3)):
        assert result.exit_code == exit_code, result.output
        assert json.loads(result.stdout)["error"]["code"] == code


def test_consensus_attempt_whose_lease_expired_during_synthesis_cannot_publish(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    _note(settings, "a.md", "Alpha note\n")
    clock = _Clock()
    late_summary = "Late attempt summary that must never publish."

    def slow_first_synthesis(call: int, _company: Node) -> None:
        if call == 1:
            llm.summary = late_summary
            clock.advance(31)  # The lease (30 s) expires while the first attempt synthesizes.
        else:
            llm.summary = CONSENSUS_SUMMARY

    llm = _ScriptLLM(on_consensus=slow_first_synthesis)
    ref = ProcessingService(settings).request_processing("a.md")
    _worker(settings, llm, clock).run_once(scan=False)

    with _read(settings) as db:
        company = db.find_by_name_or_alias(COMPANY, node_type="entity")
        assert company is not None
        views = [node.summary for node in db.list_nodes(node_type="view", limit=-1)]
        assert late_summary not in views, "the expired attempt published its consensus"
        consensus = db.get_entity_consensus(company.id)
        assert consensus is not None and consensus.summary == CONSENSUS_SUMMARY
        refresh = db.jobs.consensus_state(company.id)
        assert (refresh["target_revision"], refresh["completed_revision"], refresh["state"]) == (1, 1, "current")
    assert llm.consensus_calls == [COMPANY, COMPANY], "the reclaiming attempt must synthesize again"
    assert llm.extract_calls == ["a.md"]
    status = ProcessingService(settings).get_status(ref.job_id)
    assert (status["state"], status["attempts"]) == ("succeeded", 2)


@pytest.mark.parametrize(("graph_matches", "outcome"), [(0, "registry_only"), (2, "ambiguous")])
def test_browser_registry_edit_rollout_preserves_unmatched_graph(
    tmp_path: Path, graph_matches: int, outcome: str,
) -> None:
    from stock_ontology.services.registry import RegistryService

    settings = _workspace(tmp_path)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        for index in range(graph_matches):
            db.upsert_node(Node(
                id=f"nvda-{index}", name="NVIDIA", summary=f"Research {index}", node_type="entity",
                facets={"entity_type": "company", "ticker": "NVDA", "sector": "Semiconductors"},
            ))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
        expected_rows = db.registry_rollout_rows()

    jobs = ProcessingService(settings)
    service = RegistryService(settings)
    with _read(settings) as db:
        review = service.review_record_edit(db, "companies", "NVIDIA", {"sector": "Compute Systems"})
    submitted = jobs.submit_operator("registry.publish", review["payload"])
    worker = Worker(settings, llm_factory=lambda _settings: _ScriptLLM())
    worker.run_once(scan=False)
    assert jobs.get_status(submitted.job_id)["state"] == "succeeded"
    preview = jobs.submit_operator("registry.apply.preview", {"confirmation": "fixture-confirmation"})
    worker.run_once(scan=False)
    reviewed = jobs.get_status(preview.job_id)
    assert reviewed["state"] == "succeeded", reviewed
    assert reviewed["result"]["diff"][0]["effect"] == outcome
    assert "_plan" not in reviewed["result"]
    job = jobs.submit_reviewed_rollout(preview.job_id, "fixture-confirmation")
    worker.run_once(scan=False)
    assert jobs.get_status(job.job_id)["state"] == "succeeded"
    with _read(settings) as db:
        assert db.registry_rollout_rows() == expected_rows
        assert db.applied_registry().resolve_company("NVIDIA").spec.sector == "Compute Systems"


def test_browser_registry_preview_does_not_adopt_cli_publication(tmp_path: Path) -> None:
    settings = _workspace(tmp_path)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
    proposal = settings.registry_path.with_name("cli-proposal.json")
    update = registry.model_copy(update={"version": registry.version + 1})
    save_registry(update, proposal)
    jobs = ProcessingService(settings)
    publication = jobs.submit_operator("registry.publish", {
        "registry_path": str(settings.registry_path), "proposal_path": str(proposal),
        "proposed_revision": update.revision(), "current_revision": registry.revision(),
    })
    worker = Worker(settings, llm_factory=lambda _settings: _ScriptLLM())
    worker.run_once(scan=False)
    assert jobs.get_status(publication.job_id)["state"] == "succeeded"
    preview = jobs.submit_operator("registry.apply.preview", {"confirmation": "unrelated"})
    worker.run_once(scan=False)
    assert jobs.get_status(preview.job_id)["state"] == "failed"
    with _read(settings) as db:
        assert db.applied_registry().revision() == registry.revision()


def test_serve_registry_actions_require_loopback_and_disable_proxy_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    settings = _workspace(tmp_path)
    with OntologyDB(settings.db_path, embedding_dim=DIM):
        pass
    monkeypatch.setattr(cli_module, "_load_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(cli_module, "create_llm_client", lambda _settings: _JourneyLLM())
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda _app, **options: calls.append(options))
    runner = CliRunner()
    denied = runner.invoke(cli_module.app, ["serve", "--registry-actions", "--host", "0.0.0.0"])
    assert denied.exit_code != 0 and "literal loopback" in denied.output
    assert not calls
    enabled = runner.invoke(cli_module.app, ["serve", "--registry-actions", "--host", "127.0.0.1"])
    assert enabled.exit_code == 0, enabled.output
    assert calls == [{"host": "127.0.0.1", "port": 8000, "proxy_headers": False}]


def test_browser_registry_relationship_sources_include_theme_provenance(tmp_path: Path) -> None:
    import hashlib
    import re

    from stock_ontology.models import Edge

    settings = _workspace(tmp_path)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    name = registry.themes[0].name
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(Node(id="theme", name=name, summary="", node_type="theme",
                            source_doc_id="direct", facets={"stage": "accelerating"}))
        for key in ("anchor", "peer"):
            db.upsert_node(Node(id=key, name=key.title(), summary="", node_type="entity",
                                facets={"entity_type": "company"}))
        for key in ("direct", "evidence", "membership", "synthetic", "unrelated"):
            note = _note(settings, f"{key}.md", f"Source: {key}.\n")
            db.upsert_ingestion_log(note.name, key, hashlib.sha256(note.read_bytes()).hexdigest(),
                                    entity_ids=("theme",) if key == "membership" else ())
        for doc, basis in (("evidence", "extracted"), ("synthetic", "synthesized")):
            db.upsert_edge(Edge(id=doc, from_id="peer", to_id="theme", relation="EXPOSED_TO",
                                source_doc_id=doc, facets={"basis": basis, "sentiment": "positive"}))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    client = TestClient(create_app(settings, llm=_ScriptLLM(), note_actions=True))
    page = client.get("/ontology", params={"tab": "registry", "kind": "themes", "record": name})
    form = re.search(r'<form\b[^>]*\bdata-kind="relationship_add"[^>]*>(.*?)</form>', page.text, re.S)
    assert form is not None, page.text
    assert re.findall(r'<option\b[^>]*\bvalue="([^"]+)"', form[1]) == [
        "direct.md", "evidence.md", "membership.md",
    ]
    for doc in ("direct", "evidence", "membership", "synthetic", "unrelated"):
        review = client.post("/api/ontology/corrections/preview", json={
            "kind": "relationship_add", "record": "theme", "file": f"{doc}.md",
            "changes": {"from_id": "anchor", "to_id": "theme", "relation": "EXPOSED_TO",
                        "facets": {"sentiment": "positive"}},
        })
        assert review.status_code == (200 if doc in {"direct", "evidence", "membership"} else 409), review.text


class _StopWorker(BaseException):
    pass


def test_run_forever_continues_after_a_tick_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import stock_ontology.worker as worker_module

    worker = Worker(_workspace(tmp_path), llm_factory=lambda _settings: _ScriptLLM())
    calls: list[int] = []

    def flaky_run_once(*_args: Any, **_kwargs: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient failure in tick 1")  # noqa: TRY003
        raise _StopWorker

    monkeypatch.setattr(worker, "run_once", flaky_run_once)
    monkeypatch.setattr(worker_module.time, "sleep", lambda _s: None)
    with pytest.raises(_StopWorker):
        worker.run_forever(0)
    assert len(calls) == 2


def test_worker_applies_graph_changes_only_through_public_pipeline_methods() -> None:
    """The worker claims and runs jobs; graph edits and consensus rules belong to `IngestionPipeline`."""
    import ast
    import inspect

    import stock_ontology.worker as worker_module

    tree = ast.parse(inspect.getsource(worker_module))
    worker_class, = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Worker"]

    def is_pipeline_annotation(annotation: ast.expr | None) -> bool:
        return isinstance(annotation, ast.Name) and annotation.id == "IngestionPipeline"

    pipeline_names: set[str] = set()
    for node in ast.walk(worker_class):
        if isinstance(node, ast.arg) and is_pipeline_annotation(node.annotation):
            pipeline_names.add(node.arg)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            built = (isinstance(func, ast.Name) and func.id == "IngestionPipeline") or (
                isinstance(func, ast.Attribute) and func.attr == "_pipeline"
            )
            if built:
                pipeline_names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    assert "pipeline" in pipeline_names

    private_uses = sorted(
        f"line {node.lineno}: {node.value.id}.{node.attr}" for node in ast.walk(worker_class)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id in pipeline_names and node.attr.startswith("_")
    )
    graph_writes = sorted(
        f"line {node.lineno}: {node.func.attr}" for node in ast.walk(worker_class)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"upsert_node", "update_edge", "upsert_edge", "add_note_entities"}
    )
    assert {"private pipeline members": private_uses, "graph row writes": graph_writes} == {
        "private pipeline members": [], "graph row writes": [],
    }


class _LoopTime:
    """Fake `time` for `run_forever`: sleeping advances a monotonic clock and runs scheduled hooks."""

    def __init__(self, hooks: dict[float, Callable[[], None]], stop_at: float) -> None:
        self.now = 0.0
        self.hooks = dict(sorted(hooks.items()))
        self.stop_at = stop_at

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        for at in [at for at in self.hooks if at <= self.now]:
            self.hooks.pop(at)()
        if self.now >= self.stop_at:
            raise _StopWorker


def _run_service(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, hooks: dict[float, Callable[[], None]],
) -> tuple[_LoopTime, list[float], list[float]]:
    """Run the worker service loop on fake time; return it, the open times, and the job start times."""
    import stock_ontology.worker as worker_module

    loop = _LoopTime(hooks, stop_at=30)
    opens: list[float] = []
    starts: list[float] = []

    class CountingDB(OntologyDB):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            opens.append(loop.now)
            super().__init__(*args, **kwargs)

    worker = Worker(settings, llm_factory=lambda _settings: _ScriptLLM())
    execute = worker._execute

    def timed_execute(job: Any) -> None:
        starts.append(loop.now)
        execute(job)

    monkeypatch.setattr(worker_module, "OntologyDB", CountingDB)
    monkeypatch.setattr(worker_module, "time", loop)
    monkeypatch.setattr(worker, "_execute", timed_execute)
    with pytest.raises(_StopWorker):
        worker.run_forever(60)
    return loop, opens, starts


def test_idle_worker_opens_once_and_starts_a_spooled_job_within_two_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _workspace(tmp_path)
    refs: list[Any] = []

    def submit() -> None:
        _note(settings, "a.md", "Alpha note\n")
        refs.append(ProcessingService(settings).request_processing("a.md"))

    _loop, opens, starts = _run_service(monkeypatch, settings, {10: submit})

    assert [t for t in opens if t < 10] == [0], "an idle worker must open the database once, not per tick"
    assert len(starts) == 1 and 10 <= starts[0] <= 12, f"a spooled job must start within 2 s, started at {starts}"
    assert len(opens) == 2, "the job attempt adds exactly one open"
    assert ProcessingService(settings).get_status(refs[0].job_id)["state"] == "succeeded"


def test_reused_worker_connection_detects_a_registry_change_between_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _workspace(tmp_path)
    adopted = create_minimal_registry()
    adopted.version += 1
    refs: list[Any] = []

    def adopt() -> None:
        with OntologyDB(settings.db_path, embedding_dim=DIM) as other:
            other.record_registry_adoption(adopted, None, "test")

    def submit() -> None:
        _note(settings, "a.md", "Alpha note\n")
        refs.append(ProcessingService(settings).request_processing("a.md"))

    _loop, opens, starts = _run_service(monkeypatch, settings, {4: adopt, 10: submit})

    assert "Worker tick failed" not in caplog.text
    assert len(starts) == 1 and 10 <= starts[0] <= 12
    assert len([t for t in opens if t >= 10]) == 2, "the stale queue connection reopens once, then the attempt opens"
    status = ProcessingService(settings).get_status(refs[0].job_id)
    assert (status["state"], status["attempts"]) == ("succeeded", 1), status
    with _read(settings) as db:
        assert db.registry.revision() == adopted.revision()


def test_job_status_reads_skip_the_full_store_and_stay_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stock_ontology.db import read_jobs
    from stock_ontology.services import ServiceError

    settings = _workspace(tmp_path)
    service = ProcessingService(settings)
    with pytest.raises(ServiceError):
        service.get_status("job_missing")  # no database yet
    _note(settings, "a.md", "Alpha note\n")
    done = service.request_processing("a.md")
    _worker(settings, _ScriptLLM(), _Clock()).run_once(scan=False)
    _note(settings, "a.md", "Alpha note, revised\n")
    spooled = service.request_processing("a.md")
    expected = {done.job_id: service.get_status(done.job_id), spooled.job_id: service.get_status(spooled.job_id)}
    latest = service.latest_for_note("a.md")

    def no_full_store(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a status read must not open a full OntologyDB")

    monkeypatch.setattr(OntologyDB, "__init__", no_full_store)
    assert {job_id: service.get_status(job_id) for job_id in expected} == expected
    assert expected[done.job_id]["state"] == "succeeded" and expected[spooled.job_id]["state"] == "queued"
    assert service.latest_for_note("a.md") == latest
    with pytest.raises(ServiceError):
        service.get_status("job_missing")
    with read_jobs(settings.db_path) as jobs:
        assert jobs is not None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            jobs._conn.execute("DELETE FROM jobs")


def test_corrupt_spool_submission_is_moved_aside_so_the_idle_loop_stays_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _workspace(tmp_path)
    service = ProcessingService(settings)
    service.spool.mkdir(parents=True)
    (service.spool / "00000000000000000001-enqueue-job_bad.json").write_text("{not json", encoding="utf-8")
    (service.spool / "00000000000000000002-enqueue-job_list.json").write_text("[1]", encoding="utf-8")
    assert service.has_submissions()
    assert service.read_spool() == [], "a reader skips corrupt submissions"
    assert service.has_submissions(), "only the worker's intake moves them aside"

    runs: list[bool] = []
    run_once = Worker.run_once

    def counted_run_once(self: Worker, *, scan: bool = True) -> int:
        runs.append(scan)
        return run_once(self, scan=scan)

    monkeypatch.setattr(Worker, "run_once", counted_run_once)
    _run_service(monkeypatch, settings, {})

    assert runs == [True], f"a corrupt submission must not wake the loop every 2 s: {runs}"
    assert not service.has_submissions()
    assert sorted(p.name for p in service.spool.iterdir()) == [
        "00000000000000000001-enqueue-job_bad.bad", "00000000000000000002-enqueue-job_list.bad",
    ]
