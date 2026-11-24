"""Background worker: the only code that opens `ontology.db` for writing.

Adapters submit jobs to the command spool (`services.ProcessingService`). The worker moves
submissions into the `jobs` table, claims the most urgent due job under a lease, runs its
executor, and records the outcome. Every graph commit made for a job checks that the claim is
still held, so an attempt whose lease expired cannot publish. A change of the applied registry
reopens the connection and retries; other failures retry three times with exponential backoff
from 60 seconds, except invalid input and conflicts, which fail at once.

The registry rollout preview also lives here because it writes a disposable copy.
Registry publication is a job too, though it changes only the registry file.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from stock_ontology.config import NoteConflictError, Settings, note_revision
from stock_ontology.db import TERMINAL_STATES, Job, LeaseLostError, OntologyDB, RegistryChangedError
from stock_ontology.models import Edge, Node
from stock_ontology.pipeline import IngestionPipeline, IngestReport, reembed_all_nodes, reembed_nodes
from stock_ontology.registry import (
    OntologyRegistry,
    RegistryPublication,
    RegistrySuggestions,
    load_registry,
    normalize_name_key,
    normalize_ticker,
    save_registry_json,
)
from stock_ontology.repair import RepairReport, repair_ontology, validate_rollout
from stock_ontology.services import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    NotesService,
    ProcessingService,
    RegistryService,
    ServiceError,
    job_priority,
)
from stock_ontology.services.notes import has_changes
from stock_ontology.services.corrections import review_note_correction
from stock_ontology.services.processing import process_job_id
from stock_ontology.services.registry import changed_fields, unique_labels

logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 900
# Reopen-and-retry limit when the applied registry keeps changing under one attempt.
REGISTRY_REOPENS = 3


class _Superseded(Exception):
    """The note changed after this job was queued; a job for the current revision replaces it."""


def load_suggestions(path: Path, fallback: RegistrySuggestions) -> RegistrySuggestions:
    if not path.exists():
        return fallback
    return RegistrySuggestions.model_validate(json.loads(path.read_text(encoding="utf-8"))["suggestions"])


def load_repair_registry(registry_path: Path) -> OntologyRegistry:
    """The published registry with its pending suggestions, as `repair` reviews it."""
    reg = load_registry(registry_path)
    reg.suggestions = load_suggestions(registry_path.with_suffix(".suggestions.json"), reg.suggestions)
    return reg


def _rows_digest(rows: list[str]) -> str:
    return sha256(json.dumps(rows).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


@dataclass(frozen=True)
class RolloutPlan:
    """A repair previewed on a copy, and the state it must still match when applied."""

    before: list[str]
    after: list[str]
    planned: RepairReport
    applied_version: int | None
    old_revision: str | None
    old_stamp: str | None
    published_revision: str
    record_diff: list[dict[str, Any]] | None = None

    def job_payload(self, settings: Settings, *, adoption: bool, reembed: bool = False) -> dict[str, Any]:
        return {
            "registry_path": str(settings.registry_path), "data_dir": str(settings.data_dir),
            "adoption": adoption, "reembed": reembed, "published_revision": self.published_revision,
            "old_revision": self.old_revision, "old_stamp": self.old_stamp,
            "before": _rows_digest(self.before), "after": _rows_digest(self.after),
            "plan": sha256(json.dumps([self.before, self.after]).encode("utf-8")).hexdigest(),
            "planned": _jsonable(asdict(self.planned)),
            **({"browser_record": True} if self.record_diff is not None else {}),
        }


def _rollout_record_metadata(
    db: OntologyDB, applied: OntologyRegistry, target: OntologyRegistry,
) -> list[dict[str, Any]]:
    """Update uniquely linked metadata without repairing unrelated data."""
    editable = {"version", "companies", "themes"}
    current_other = {key: value for key, value in applied.official_definitions().items() if key not in editable}
    target_other = {key: value for key, value in target.official_definitions().items() if key not in editable}
    if current_other != target_other or any(
        len(getattr(applied, group)) != len(getattr(target, group)) for group in ("companies", "themes")
    ):
        raise ServiceError("conflict", "This revision requires a full CLI registry apply.")

    diff = []
    for group, node_type in (("companies", "entity"), ("themes", "theme")):
        for old, new in zip(getattr(applied, group), getattr(target, group), strict=True):
            edits = changed_fields(old.model_dump(), new.model_dump())
            if not edits:
                continue
            nodes = db.list_nodes(node_type=node_type, limit=-1)
            matches = []
            for node in nodes:
                if node_type == "entity":
                    if node.facets.get("entity_type") != "company":
                        continue
                    ticker = node.facets.get("ticker")
                    match = applied.resolve_company(node.name, ticker=str(ticker) if ticker else None, aliases=node.aliases)
                else:
                    match = applied.resolve_theme(node.name, aliases=node.aliases)
                if match is not None and match.spec == old:
                    matches.append(node)

            entry: dict[str, Any] = {"record": old.name, "changes": edits, "effect": "registry_only"}
            if len(matches) > 1:
                entry["effect"] = "ambiguous"
            elif matches:
                node = matches[0]
                requested = {edit["field"]: edit["after"] for edit in edits}
                introduced = set(map(normalize_name_key, [requested.get("name", ""), *requested.get("aliases", [])])) - {""}
                ticker = normalize_ticker(requested.get("ticker"))
                if any(
                    other.id != node.id and (
                        introduced & set(map(normalize_name_key, [other.name, *other.aliases]))
                        or ticker and node_type == "entity"
                        and other.facets.get("entity_type") == "company"
                        and normalize_ticker(str(other.facets.get("ticker") or "")) == ticker
                    )
                    for other in nodes
                ):
                    entry["effect"] = "ambiguous"
                else:
                    aliases = node.aliases
                    name = requested.get("name", node.name)
                    if "aliases" in requested or name != node.name:
                        removed = set(map(normalize_name_key, old.aliases)) - set(map(normalize_name_key, new.aliases))
                        aliases = unique_labels(
                            [alias for alias in node.aliases if normalize_name_key(alias) not in removed]
                            + list(requested.get("aliases", [])), excluding=name,
                        )
                    facets = node.facets.copy()
                    for field in ("ticker", "sector", "stage"):
                        if field in requested:
                            if requested[field] is None:
                                facets.pop(field, None)
                            else:
                                facets[field] = requested[field]
                    if (name, aliases, facets) != (node.name, node.aliases, node.facets):
                        original_values = {"name": node.name, "aliases": node.aliases, **node.facets}
                        update_values = {"name": name, "aliases": aliases, **facets}
                        graph_changes = changed_fields(
                            original_values, {key: update_values.get(key) for key in ("name", "aliases", "ticker", "sector", "stage")}
                        )
                        with db.checking_against(target):
                            db.upsert_node(node.model_copy(update={"name": name, "aliases": aliases, "facets": facets}))
                        entry.update(effect="linked", graph_id=node.id, graph_changes=graph_changes)
            diff.append(entry)
    return diff


def plan_rollout(
    settings: Settings, target: OntologyRegistry, *, adoption: bool, browser_record: bool = False,
) -> RolloutPlan:
    """Run the repair on a disposable copy of the database and report the row diff."""
    published_revision = load_registry(settings.registry_path).revision()
    if adoption and published_revision != target.revision():
        raise ValueError("The published registry changed. Run a new preview.")  # noqa: TRY003
    with tempfile.TemporaryDirectory(prefix="ontology-rollout-") as temp_dir:
        copy_path = Path(temp_dir) / "preview.db"
        with OntologyDB(settings.db_path, embedding_dim=settings.embedding_dim, read_only=True) as source:
            source.copy_to(copy_path)
        with OntologyDB(copy_path, embedding_dim=settings.embedding_dim) as preview:
            applied = preview.applied_registry()
            old_revision = applied.revision() if applied else None
            old_stamp = preview.get_metadata("registry_version")
            if adoption and applied and old_revision != target.revision() and (
                not target.publications or target.publications[-1].revision != target.revision()
            ):
                raise ValueError("Publish this registry proposal using registry-publish before applying it.")  # noqa: TRY003
            if not adoption and (old_revision or old_stamp) and (
                old_revision != target.revision() if applied else old_stamp != target.schema_stamp()
            ):
                raise ValueError("Use registry-apply to review and adopt a different registry version.")  # noqa: TRY003
            before = preview.registry_rollout_rows()
            record_diff = None
            if browser_record:
                if not RegistryService.browser_publication(preview, target, applied):
                    raise ServiceError("conflict", "Only an outstanding browser record edit can be applied here.")
                assert applied is not None
                record_diff = _rollout_record_metadata(preview, applied, target)
                planned = RepairReport()
            else:
                planned = repair_ontology(preview, target, data_dir=settings.data_dir)
            validate_rollout(preview, target)
            after = preview.registry_rollout_rows()
    return RolloutPlan(
        before=before, after=after, planned=planned, applied_version=applied.version if applied else None,
        old_revision=old_revision, old_stamp=old_stamp, published_revision=published_revision, record_diff=record_diff,
    )


class Worker:
    """Claims and runs jobs. `run_once` drains due work; `run_until` waits for one job."""

    def __init__(
        self,
        settings: Settings,
        llm_factory: Callable[[Settings], Any],
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.llm_factory = llm_factory
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.processing = ProcessingService(settings)
        self._llm: Any = None

    # --- connections and the queue

    @contextmanager
    def open_store(self, settings: Settings | None = None) -> Iterator[OntologyDB]:
        """Open the writable database for one job attempt."""
        target = settings or self.settings
        with OntologyDB(target.db_path, embedding_dim=target.embedding_dim) as db:
            yield db

    def llm(self) -> Any:
        if self._llm is None:
            self._llm = self.llm_factory(self.settings)
        return self._llm

    def intake(self, db: OntologyDB) -> int:
        """Move spooled submissions into the jobs table."""
        moved = 0
        for submission in self.processing.read_spool():
            if submission.op == "enqueue":
                db.jobs.insert(
                    job_id=submission.job_id, kind=submission.kind, target=submission.target,
                    revision=submission.revision, priority=job_priority(submission.kind),
                    payload=submission.payload or {}, created_at=submission.created_at or self.clock().isoformat(),
                    now=self.clock(),
                )
            elif submission.op == "retry":
                db.jobs.reopen(submission.job_id, self.clock())
            submission.path.unlink(missing_ok=True)
            moved += 1
        return moved

    def run_once(self, *, scan: bool = True) -> int:
        """Recover and run every due job, then (with `scan`) queue and run a scan for note changes."""
        with self.open_store() as db:
            self.intake(db)
        ran = self._drain()
        if scan and self._queue_scan():
            ran += self._drain()
        return ran

    def run_until(self, job_id: str, *, poll_seconds: float = 1.0) -> Job:
        """Run the worker loop in this process until `job_id` reaches a terminal state."""
        while True:
            with self.open_store() as db:
                self.intake(db)
            self._drain()
            with self.open_store() as db:
                job = db.jobs.get(job_id)
            if job is None:
                raise ServiceError("not_found", f"Job not found: {job_id}")
            if job.state in TERMINAL_STATES:
                return job
            due = job.next_attempt_at if job.state == "queued" else job.lease_expires_at
            wait = (datetime.fromisoformat(due) - self.clock()).total_seconds() if due else poll_seconds
            time.sleep(min(max(wait, 0.05), poll_seconds * 5))

    def run_forever(self, interval_seconds: float) -> None:
        """The long-running worker: recover pending jobs, scan for changes, sleep, repeat."""
        while True:
            try:
                self.run_once(scan=True)
            except Exception:  # noqa: BLE001 - one failing tick must not stop the worker
                logger.exception("Worker tick failed; retrying after %s seconds", interval_seconds)
            time.sleep(interval_seconds)

    def _drain(self) -> int:
        ran = 0
        while True:
            with self.open_store() as db:
                job = db.jobs.claim(self.clock(), self.lease_seconds, max_attempts=MAX_ATTEMPTS)
            if job is None:
                return ran
            self._execute(job)
            ran += 1

    def _queue_scan(self) -> bool:
        """Queue one ingest scan when notes changed on disk or a consensus refresh is still pending."""
        with self.open_store() as db:
            if db.jobs.has_active("ingest"):
                return False
            if not db.jobs.pending_consensus() and not has_changes(Path(self.settings.data_dir), db.get_ingestion_log()):
                return False
            now = self.clock()
            db.jobs.insert(
                job_id=f"job_scan_{now.strftime('%Y%m%dT%H%M%S%f')}", kind="ingest", target="", revision="",
                priority=job_priority("scan"), payload={"scan": True}, created_at=now.isoformat(), now=now,
            )
        return True

    # --- one attempt

    def _execute(self, job: Job) -> None:
        for _ in range(REGISTRY_REOPENS):
            try:
                with self.open_store() as db:
                    result = self._run(db, job)
                    if result is not None:
                        with db.transaction():
                            db.jobs.check_claim(job.job_id, job.claim_id or "", self.clock(), self.lease_seconds)
                            db.jobs.finish(job.job_id, job.claim_id or "", result, self.clock())
            except RegistryChangedError:
                logger.info("Applied registry changed during %s; reopening", job.job_id)
                continue
            except LeaseLostError:
                logger.warning("Lost the claim on %s; another worker owns it", job.job_id)
                return
            except _Superseded:
                return
            except ServiceError as exc:
                self._fail(job, exc.code, exc.message, terminal=True)
                return
            except NoteConflictError as exc:
                self._fail(job, "conflict", str(exc), terminal=True)
                return
            except FileNotFoundError as exc:
                self._fail(job, "not_found", str(exc), terminal=True)
                return
            except ValueError as exc:
                self._fail(job, "invalid", str(exc), terminal=True)
                return
            except Exception as exc:  # noqa: BLE001 - transient: provider, network, or database
                logger.warning("Job %s attempt %d failed: %s", job.job_id, job.attempts, exc)
                self._fail(job, "transient", str(exc), terminal=False)
                return
            else:
                return
        self._fail(job, "transient", "The applied registry kept changing.", terminal=False)

    def _fail(self, job: Job, code: str, error: str, *, terminal: bool) -> None:
        now = self.clock()
        retry_at = None
        if not terminal and job.attempts < MAX_ATTEMPTS:
            retry_at = now + timedelta(seconds=BACKOFF_SECONDS * 2 ** (job.attempts - 1))
        if not terminal and retry_at is None:
            code = "failed"
        with self.open_store() as db:
            db.jobs.fail(job.job_id, job.claim_id or "", code=code, error=error[:2000], retry_at=retry_at, now=now)

    def _check(self, db: OntologyDB, job: Job) -> None:
        db.jobs.check_claim(job.job_id, job.claim_id or "", self.clock(), self.lease_seconds)

    def _run(self, db: OntologyDB, job: Job) -> dict[str, Any] | None:
        """Run one attempt. Returns the result to record, or None when the executor finished the job."""
        if job.kind == "process":
            return self._run_process(db, job)
        if job.kind.startswith("note."):
            return self._run_correction(db, job)
        if job.kind == "ingest":
            return self._run_ingest(db, job)
        if job.kind == "reembed":
            return self._run_reembed(db, job)
        if job.kind in ("repair", "registry.apply"):
            return self._run_rollout(db, job)
        if job.kind == "registry.apply.preview":
            target = load_registry(self.settings.registry_path)
            plan = plan_rollout(self.settings, target, adoption=True, browser_record=True)
            return {
                "confirmation": job.payload["confirmation"], "diff": (plan.record_diff or [])[:100],
                "version": target.version, "_plan": plan.job_payload(self.settings, adoption=True),
            }
        if job.kind == "registry.publish":
            return self._run_publish(db, job)
        raise ServiceError("invalid", f"Unknown job kind: {job.kind}")

    # --- graph jobs

    def _pipeline(self, db: OntologyDB, job: Job, settings: Settings | None = None, note: Path | None = None) -> IngestionPipeline:
        target = settings or self.settings
        registry = RegistryService(target).get_applied(db)
        pipeline = IngestionPipeline(db, self.llm(), target.data_dir, registry=registry)

        def commit_check(revisions: dict[str, int]) -> None:
            self._check(db, job)
            if note is not None and note_revision(note.read_text(encoding="utf-8")) != job.revision:
                raise NoteConflictError
            if revisions:
                db.jobs.record_companies(job.job_id, revisions)

        pipeline.commit_check = commit_check
        return pipeline

    def _wrote(self, db: OntologyDB, job: Job) -> None:
        with db.transaction():
            self._check(db, job)
            db.jobs.set_stage(job.job_id, "consensus")

    def _finish_consensus(self, db: OntologyDB, pipeline: IngestionPipeline, job: Job) -> list[str]:
        """Check each company this job's write queued reached that revision. A resumed attempt (the
        write committed earlier) refreshes them first; a fresh one already refreshed after its write."""
        current = db.jobs.get(job.job_id)
        waiting = current.companies if current else {}

        def unfinished() -> list[str]:
            return sorted(
                company_id for company_id, revision in waiting.items()
                if int((db.jobs.consensus_state(company_id) or {}).get("completed_revision", 0)) < revision
            )

        report = IngestReport()
        if job.stage == "consensus":
            pipeline._refresh_consensus(unfinished(), report)
        left = unfinished()
        if left:
            errors = "; ".join(err for _, err in report.errors) or "newer evidence arrived"
            raise RuntimeError(f"Consensus refresh incomplete for {', '.join(left)}: {errors}")  # noqa: TRY003
        return report.consensus_updated_for

    def _run_process(self, db: OntologyDB, job: Job) -> dict[str, Any]:
        notes = NotesService(self.settings, self.processing)
        path = notes.resolve(job.target)
        if job.stage == "write":
            current = note_revision(path.read_text(encoding="utf-8"))
            if current != job.revision:
                self._supersede(db, job, current)
            pipeline = self._pipeline(db, job, note=path)
            try:
                pipeline.process_note(path.resolve())
            except NoteConflictError:
                current = note_revision(path.read_text(encoding="utf-8"))
                if current != job.revision:
                    self._supersede(db, job, current)
                raise
            self._wrote(db, job)
        else:
            pipeline = self._pipeline(db, job)
        updated = self._finish_consensus(db, pipeline, job)
        return {"file": job.target, "revision": job.revision, "consensus_updated_for": updated}

    def _supersede(self, db: OntologyDB, job: Job, revision: str) -> None:
        now = self.clock()
        with db.transaction():
            self._check(db, job)
            db.jobs.supersede(job.job_id, job.claim_id or "", "The note changed; a newer job processes it.", now)
            db.jobs.insert(
                job_id=process_job_id(job.target, revision), kind="process", target=job.target, revision=revision,
                priority=job_priority("process"), payload={"file": job.target}, created_at=now.isoformat(), now=now,
            )
        raise _Superseded

    def _run_correction(self, db: OntologyDB, job: Job) -> dict[str, Any]:
        params = job.payload
        path = NotesService(self.settings, self.processing).resolve(job.target).resolve()
        pipeline = self._pipeline(db, job)
        if job.kind == "note.ontology.correction":
            return self._run_ontology_correction(db, job, pipeline, path)
        if job.stage == "write":
            expected = params.get("expected_hash")
            if job.kind == "note.relink":
                pipeline.relink_note_entity(
                    path, params["entity_id"], params.get("replacement_id"), params.get("new_entity"), expected
                )
            elif job.kind == "note.entity.add":
                pipeline.add_note_entity(path, params["entity_id"], expected)
            elif job.kind == "note.entity.delete":
                pipeline.delete_note_entity(path, params["entity_id"], expected)
            elif job.kind == "note.relationship":
                pipeline.correct_note_relationship(
                    path, params["edge_id"], params["relation"], bool(params.get("reverse")), expected,
                    from_id=params.get("from_id"), to_id=params.get("to_id"),
                )
            elif job.kind == "note.relationship.add":
                pipeline.add_note_relationship(
                    path, params["from_id"], params["relation"], params["to_id"], expected, facets=params.get("facets"),
                )
            elif job.kind == "note.relationship.delete":
                pipeline.delete_note_relationship(path, params["edge_id"], expected)
            else:
                raise ServiceError("invalid", f"Unknown correction: {job.kind}")
            self._wrote(db, job)
        updated = self._finish_consensus(db, pipeline, job)
        return {"file": job.target, "consensus_updated_for": updated}

    def _run_ontology_correction(
        self, db: OntologyDB, job: Job, pipeline: IngestionPipeline, path: Path,
    ) -> dict[str, Any]:
        reviewed = job.payload
        if job.stage == "write":
            with db.transaction(immediate=True):
                self._check(db, job)
                fresh = review_note_correction(db, path, self.settings.data_dir, **reviewed["request"])
                if fresh != reviewed:
                    raise ServiceError("conflict", "The source or graph changed after review.")
                doc_id = fresh["doc_id"]
                affected = db.get_doc_affected_company_ids(doc_id)
                if person := fresh["person"]:
                    previous = Node.model_validate(person["before"])
                    db.upsert_node(previous.model_copy(update={
                        key: person[key] for key in ("name", "aliases", "facets")
                    }))
                for update in fresh["edges"]:
                    before, values = update["before"], update["after"]
                    if before:
                        db.update_edge(before["edge_id"], **values)
                    else:
                        db.upsert_edge(Edge(id=f"edge_{uuid.uuid4().hex}", source_doc_id=doc_id, **values))
                    added = {values["from_id"], values["to_id"]} - {before.get("from_id"), before.get("to_id")}
                    db.add_note_entities(doc_id, tuple(
                        node.id for node in db.get_nodes(sorted(added)) if node.node_type == "entity"
                    ))
                if pipeline._current_note_doc(path, fresh["expected_hash"]) != doc_id:
                    raise NoteConflictError
                affected.update(db.get_doc_affected_company_ids(doc_id))
                pipeline._evidence_changed(affected)
                self._wrote(db, job)
        updated = self._finish_consensus(db, pipeline, replace(job, stage="consensus"))
        return {"file": job.target, "consensus_updated_for": updated}

    def _operator_settings(self, job: Job) -> Settings:
        updates: dict[str, Any] = {}
        for key in ("data_dir", "registry_path"):
            if job.payload.get(key):
                updates[key] = Path(job.payload[key])
        return self.settings.model_copy(update=updates)

    def _run_ingest(self, db: OntologyDB, job: Job) -> dict[str, Any]:
        settings = self._operator_settings(job)
        pipeline = self._pipeline(db, job, settings=settings)
        report = IngestReport()
        if job.stage == "write":
            report = pipeline.run(
                force=bool(job.payload.get("force")), rebuild_consensus=bool(job.payload.get("rebuild_consensus"))
            )
            self._wrote(db, job)
        # Retry refreshes an earlier run left pending (a killed worker, or newer evidence).
        pipeline._refresh_consensus(db.jobs.pending_consensus(), report)
        return _jsonable(asdict(report))

    def _run_reembed(self, db: OntologyDB, job: Job) -> dict[str, Any]:
        updates: dict[str, Any] = {"llm_fallback_enabled": bool(job.payload.get("allow_fallback"))}
        if job.payload.get("provider"):
            updates["embedding_providers"] = [job.payload["provider"]]
        llm = self.llm_factory(self.settings.model_copy(update=updates))
        try:
            self._check_now(db, job)
            report = reembed_all_nodes(db, llm)
        finally:
            close = getattr(llm, "close", None)
            if callable(close):
                close()
        return _jsonable(asdict(report))

    def _check_now(self, db: OntologyDB, job: Job) -> None:
        with db.transaction():
            self._check(db, job)

    # --- registry jobs (each finishes its job inside the transaction that changes the registry)

    def _run_rollout(self, db: OntologyDB, job: Job) -> None:
        params = job.payload
        settings = self._operator_settings(job)
        registry_path = Path(settings.registry_path)
        adoption = job.kind == "registry.apply"
        target = load_registry(registry_path) if adoption else load_repair_registry(registry_path)
        with db.transaction(immediate=True):
            self._check(db, job)
            current = db.applied_registry()
            if (
                load_registry(registry_path).revision() != params["published_revision"]
                or (current.revision() if current else None) != params["old_revision"]
                or db.get_metadata("registry_version") != params["old_stamp"]
                or _rows_digest(db.registry_rollout_rows()) != params["before"]
            ):
                raise ValueError("Registry or database changed during review. Run a new preview.")  # noqa: TRY003
            if params.get("browser_record"):
                if not RegistryService.browser_publication(db, target, current):
                    raise ServiceError("conflict", "Only an outstanding browser record edit can be applied here.")
                assert current is not None
                _rollout_record_metadata(db, current, target)
                result = RepairReport()
            else:
                result = repair_ontology(db, target, data_dir=settings.data_dir)
            validate_rollout(db, target)
            if _rows_digest(db.registry_rollout_rows()) != params["after"] or _jsonable(asdict(result)) != params["planned"]:
                raise ValueError("The migration result changed during review. Run a new preview.")  # noqa: TRY003
            if adoption:
                db.record_registry_adoption(target, params["old_revision"], params["plan"])
            db.jobs.finish(job.job_id, job.claim_id or "", {"report": _jsonable(asdict(result)), "reembedded": 0}, self.clock())
        if params.get("reembed") and result.merged_survivor_ids:
            with self.open_store() as fresh:
                reembedded = reembed_nodes(fresh, self.llm_factory(settings), result.merged_survivor_ids)
                with fresh.transaction():
                    fresh.jobs.record_result(job.job_id, {"report": _jsonable(asdict(result)), "reembedded": reembedded})
        return None

    def _run_publish(self, db: OntologyDB, job: Job) -> None:
        """Write the reviewed proposal as the published registry. It changes only the registry
        file; the job finishes in the same write transaction that serializes it with other jobs."""
        params = job.payload
        registry_path = Path(params.get("registry_path", self.settings.registry_path))
        with db.transaction(immediate=True):
            self._check(db, job)
            current = load_registry(registry_path)
            if current.revision() != params["current_revision"]:
                raise ValueError("The published registry changed during review. Preview the proposal again.")  # noqa: TRY003
            browser_edit = params.get("browser_record")
            if browser_edit:
                expected = RegistryService(self.settings).review_record_edit(db, **browser_edit)
                if expected["payload"]["proposed"] != params["proposed"]:
                    raise ServiceError("conflict", "The reviewed registry record edit changed.")
                proposed = OntologyRegistry.model_validate(params["proposed"])
            else:
                proposed = load_registry(Path(params["proposal_path"]))
            if proposed.revision() != params["proposed_revision"]:
                raise ValueError("The proposal changed during review. Preview it again.")  # noqa: TRY003
            suggestion_path = registry_path.with_suffix(".suggestions.json")
            if not suggestion_path.exists():
                save_registry_json({"suggestions": current.suggestions.model_dump(mode="json")}, suggestion_path)
            official = proposed.official_definitions()
            publication = RegistryPublication(
                version=proposed.version,
                revision=proposed.revision(),
                previous_revision=current.revision(),
                confirmed_at=datetime.now(UTC).isoformat(),
            )
            official["publications"] = [item.model_dump(mode="json") for item in [*current.publications, publication]]
            save_registry_json(official, registry_path)
            db.jobs.finish(job.job_id, job.claim_id or "", {"version": proposed.version}, self.clock())
