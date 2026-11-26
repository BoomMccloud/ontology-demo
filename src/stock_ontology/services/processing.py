"""Job submission and status: the command spool and the job rows the worker writes.

Adapters never write `ontology.db`. A submission is a small JSON file in the command spool
next to the database (`<db>.commands/`), published with an atomic rename. The worker moves
each one into the `jobs` table and is the only process that changes job state. A note's
processing job ID is derived from the note path and content revision, so duplicate requests
for one revision share a job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_ontology.config import Settings, note_revision
from stock_ontology.db import Job, read_jobs
from stock_ontology.search import resolve_safe_note_path
from stock_ontology.services.errors import ServiceError

logger = logging.getLogger(__name__)

# Attempts per job revision, and the first retry delay; each later retry doubles it.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 60

@dataclass(frozen=True)
class JobKind:
    """How one job kind is queued: its claim `priority` (lower runs first) and who may `submit` it:
    `correction` (the note reader and Ontology page), `operator` (CLI and registry actions),
    `process` (note extraction), or `retired` (no longer submitted; already-queued jobs still run)."""

    priority: int
    submit: str


# The one table of job kinds. The worker keys its executors by it and refuses to start when they
# disagree; a submission or spooled job of a kind not listed here is refused as `invalid`.
JOB_KINDS: dict[str, JobKind] = {
    **{kind: JobKind(0, "correction") for kind in (
        "note.relink", "note.entity.add", "note.entity.delete", "note.ontology.correction",
    )},
    # Note-reader relationship corrections are now reviewed at submit and queued as
    # `note.ontology.correction`. Jobs of these kinds queued before that still run, first.
    **{kind: JobKind(0, "retired") for kind in ("note.relationship", "note.relationship.add", "note.relationship.delete")},
    **{kind: JobKind(10, "operator") for kind in (
        "ingest", "reembed", "repair", "registry.publish", "registry.apply", "registry.apply.preview",
    )},
    "process": JobKind(20, "process"),
}
PROCESS_KIND = "process"
# A notes scan is an `ingest` job queued by the worker itself, after note extraction.
SCAN_PRIORITY = 20


def job_priority(kind: str) -> int:
    """Lower runs first: reader corrections, then operator commands, then note extraction."""
    return JOB_KINDS[kind].priority


def _declared(kind: str, submit: str) -> bool:
    entry = JOB_KINDS.get(kind)
    return entry is not None and entry.submit == submit


def spool_dir(db_path: Path | str) -> Path:
    return Path(f"{db_path}.commands")


@dataclass(frozen=True)
class JobRef:
    job_id: str
    state: str


@dataclass(frozen=True)
class Submission:
    """One spooled command: `enqueue` a job, or `retry` a failed one."""

    path: Path
    op: str
    job_id: str
    kind: str = ""
    target: str = ""
    revision: str = ""
    payload: dict[str, Any] | None = None
    created_at: str = ""


def resolve_note(data_dir: Path, file: str) -> Path:
    """The note file at `file` under `data_dir`, or a `not_found` error."""
    path = resolve_safe_note_path(data_dir, file)
    if path is None or not path.is_file():
        raise ServiceError("not_found", f"Note not found: {file}", key="service_error.note_missing", params={"file": file})
    return path


def _recorded_status(job: Job, spooled: list[Submission]) -> dict[str, Any]:
    """A recorded job's status, showing a spooled retry as the fresh job `JobStore.reopen` will store."""
    status = job.to_status()
    if status["state"] == "failed" and any(s.op == "retry" for s in spooled):
        status.update(state="queued", attempts=0, error_code=None, error=None)
    return status


def process_job_id(file: str, revision: str) -> str:
    return "job_" + hashlib.sha256(f"{PROCESS_KIND}\0{file}\0{revision}".encode()).hexdigest()[:24]


class ProcessingService:
    """Submit jobs, report their status, and reopen failed ones."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.spool = spool_dir(settings.db_path)

    # --- submission

    def _write(self, op: str, job_id: str, record: dict[str, Any]) -> None:
        self.spool.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns():020d}-{op}-{job_id}.json"
        fd, tmp = tempfile.mkstemp(prefix=".submit-", suffix=".tmp", dir=self.spool)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"op": op, "job_id": job_id, **record}, handle)
            os.replace(tmp, self.spool / name)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _submit(self, job_id: str, kind: str, target: str, revision: str, payload: dict[str, Any]) -> JobRef:
        self._write("enqueue", job_id, {
            "kind": kind, "target": target, "revision": revision, "payload": payload,
            "created_at": datetime.now(UTC).isoformat(),
        })
        return JobRef(job_id, "queued")

    def _note_revision(self, file: str) -> str:
        return note_revision(resolve_note(Path(self.settings.data_dir), file).read_text(encoding="utf-8"))

    def request_processing(self, file: str) -> JobRef:
        """Queue extraction and consensus for the note's current revision, reopening it if it failed."""
        revision = self._note_revision(file)
        job_id = process_job_id(file, revision)
        existing = self._find(job_id)
        if existing is not None:
            # The job id is fixed per revision, so asking again for a failed revision is a retry.
            if existing["state"] == "failed":
                return self._reopen(job_id)
            return JobRef(job_id, existing["state"])
        return self._submit(job_id, PROCESS_KIND, file, revision, {"file": file})

    def submit_correction(self, kind: str, file: str, params: dict[str, Any]) -> JobRef:
        """Queue a note-reader correction; the worker checks the note revision at commit."""
        if not _declared(kind, "correction"):
            raise ServiceError("invalid", f"Unknown correction: {kind}")
        self._note_revision(file)
        return self._submit(
            f"job_{uuid.uuid4().hex}", kind, file, str(params.get("expected_hash") or ""), {"file": file, **params}
        )

    def submit_operator(self, kind: str, params: dict[str, Any]) -> JobRef:
        if not _declared(kind, "operator"):
            raise ServiceError("invalid", f"Unknown operator job: {kind}")
        return self._submit(f"job_{uuid.uuid4().hex}", kind, "", "", params)

    def submit_reviewed_rollout(self, preview_job_id: str, confirmation: str) -> JobRef:
        """Queue the private plan from a completed worker preview owned by the caller's review."""
        job = self._job(preview_job_id)
        if (
            job is None or job.kind != "registry.apply.preview" or job.state != "succeeded"
            or not job.result or job.result.get("confirmation") != confirmation
        ):
            raise ServiceError("conflict", "The worker has not completed this registry preview.", key="service_error.preview_pending")
        return self.submit_operator("registry.apply", job.result["_plan"])

    def retry(self, job_id: str) -> JobRef:
        status = self.get_status(job_id)
        if status["state"] != "failed":
            raise ServiceError("conflict", f"Only a failed job can be retried; this one is {status['state']}.", key="service_error.retry_not_failed", params={"state": status["state"]}, enums={"state": "job_state"})
        return self._reopen(job_id)

    def _reopen(self, job_id: str) -> JobRef:
        self._write("retry", job_id, {})
        return JobRef(job_id, "queued")

    # --- status

    def _job(self, job_id: str) -> Job | None:
        with read_jobs(self.settings.db_path) as jobs:
            return jobs.get(job_id) if jobs is not None else None

    def _spooled(self, job_id: str) -> list[Submission]:
        return self.read_spool(f"*-{job_id}.json")

    def _find(self, job_id: str) -> dict[str, Any] | None:
        job = self._job(job_id)
        spooled = self._spooled(job_id)
        if job is not None:
            return _recorded_status(job, spooled)
        enqueued = next((s for s in spooled if s.op == "enqueue"), None)
        if enqueued is None:
            return None
        return {
            "job_id": job_id, "kind": enqueued.kind, "target": enqueued.target, "revision": enqueued.revision,
            "state": "queued", "stage": "write", "attempts": 0, "next_attempt_at": enqueued.created_at,
            "error_code": None, "error": None, "companies": [], "result": None,
            "created_at": enqueued.created_at, "updated_at": enqueued.created_at,
        }

    def get_status(self, job_id: str) -> dict[str, Any]:
        status = self._find(job_id)
        if status is None:
            raise ServiceError("not_found", f"Job not found: {job_id}", key="service_error.job_missing", params={"job_id": job_id})
        return status

    def latest_for_note(self, file: str) -> dict[str, Any] | None:
        """The most recent job for a note, spooled or recorded."""
        candidates: list[dict[str, Any]] = []
        with read_jobs(self.settings.db_path) as jobs:
            job = jobs.latest(target=file) if jobs is not None else None
        if job is not None:
            candidates.append(_recorded_status(job, self._spooled(job.job_id)))
        spooled = [s for s in self.read_spool() if s.op == "enqueue" and s.target == file]
        if spooled:
            found = self._find(spooled[-1].job_id)
            if found is not None:
                candidates.append(found)
        return max(candidates, key=lambda status: status["created_at"]) if candidates else None

    # --- spool access for the worker

    def has_submissions(self) -> bool:
        """Whether any submission waits in the spool, without reading it."""
        return self.spool.is_dir() and next(self.spool.glob("*.json"), None) is not None

    def read_spool(self, pattern: str = "*.json", *, quarantine: bool = False) -> list[Submission]:
        """Parsed submissions. Submissions are published by atomic rename, so one that does not
        parse is corrupt, not half-written: skip it, and with `quarantine` (the worker's intake)
        rename it to `.bad` so it stops matching `has_submissions`."""
        if not self.spool.is_dir():
            return []
        found: list[Submission] = []
        for path in sorted(self.spool.glob(pattern)):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            except ValueError:
                record = None
            if not isinstance(record, dict):
                if quarantine:
                    logger.warning("Moving unreadable spool submission %s aside as .bad", path.name)
                    path.replace(path.with_suffix(".bad"))
                continue
            found.append(Submission(
                path=path, op=record.get("op", ""), job_id=record.get("job_id", ""),
                kind=record.get("kind", ""), target=record.get("target", ""),
                revision=record.get("revision", ""), payload=record.get("payload") or {},
                created_at=record.get("created_at", ""),
            ))
        return found
