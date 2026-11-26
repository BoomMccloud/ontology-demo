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
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    `process` (note extraction), `claim` (thesis and membership writes from the claim forms), or `retired` (no longer submitted; already-queued jobs still run)."""

    priority: int
    submit: str


PROCESS_KIND = "process"
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
    # Claim graph writes: the team's theses and thesis memberships, outside the ontology.
    **{kind: JobKind(0, "claim") for kind in (
        "claim.thesis.add", "claim.thesis.edit", "claim.thesis.remove",
        "claim.membership.add", "claim.membership.edit", "claim.membership.remove",
    )},
    PROCESS_KIND: JobKind(20, "process"),
}
# A notes scan is an `ingest` job queued by the worker itself, after note extraction.
SCAN_PRIORITY = 20


def job_priority(kind: str) -> int:
    """Lower runs first: reader corrections and claim writes, then operator commands, then note extraction."""
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


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MEMBERSHIP_FIELDS = ("status", "reason", "catalyst_event", "catalyst_by", "expected_effect")


def _invalid(message: str) -> ServiceError:
    return ServiceError("invalid", message)


def _claim_text(params: dict[str, Any], key: str, *, required: bool = False) -> str:
    value = params.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _invalid(f"{key} must be text.")
    value = value.strip()
    if required and not value:
        raise _invalid(f"{key} is required.")
    return value


def claim_date(value: str) -> str:
    """A real calendar date written YYYY-MM-DD, or an `invalid` error."""
    if not _ISO_DATE.fullmatch(value):
        raise _invalid("catalyst_by must be a date written YYYY-MM-DD.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _invalid("catalyst_by must be a real date.") from exc


def check_membership(fields: dict[str, Any]) -> dict[str, str]:
    """Validate a whole membership. *In* needs a written reason. *Watching* needs the event it waits
    for, a by-date, and why it would move the company in. Returns the cleaned fields."""
    status = fields.get("status")
    if status not in ("in", "watching"):
        raise _invalid("status must be in or watching.")
    cleaned = {key: _claim_text(fields, key) for key in MEMBERSHIP_FIELDS if key != "status"}
    cleaned["status"] = status
    if status == "in":
        if not cleaned["reason"]:
            raise _invalid("An in decision needs a written reason.")
        return {**cleaned, "catalyst_event": "", "catalyst_by": "", "expected_effect": ""}
    for key in ("catalyst_event", "catalyst_by", "expected_effect"):
        if not cleaned[key]:
            raise _invalid(f"Watching needs {key}.")
    cleaned["catalyst_by"] = claim_date(cleaned["catalyst_by"])
    return cleaned


def check_claim(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate a claim write's shape and return the payload to queue. The worker checks that the
    referenced theme, company, thesis, or membership exists, and rechecks an edit as a whole."""
    if kind == "claim.thesis.add":
        return {"theme_id": _claim_text(params, "theme_id", required=True),
                "statement": _claim_text(params, "statement", required=True)}
    if kind == "claim.thesis.edit":
        return {"thesis_id": _claim_text(params, "thesis_id", required=True),
                "statement": _claim_text(params, "statement", required=True)}
    if kind == "claim.thesis.remove":
        return {"thesis_id": _claim_text(params, "thesis_id", required=True)}
    if kind == "claim.membership.add":
        return {"thesis_id": _claim_text(params, "thesis_id", required=True),
                "company_id": _claim_text(params, "company_id", required=True),
                **check_membership(params)}
    if kind == "claim.membership.edit":
        if "thesis_id" in params or "company_id" in params:
            raise _invalid("A membership's thesis and company can't change; remove it and add a new one.")
        changes: dict[str, Any] = {key: _claim_text(params, key) for key in MEMBERSHIP_FIELDS if key in params}
        if "status" in changes and changes["status"] not in ("in", "watching"):
            raise _invalid("status must be in or watching.")
        if changes.get("catalyst_by"):
            changes["catalyst_by"] = claim_date(changes["catalyst_by"])
        return {"membership_id": _claim_text(params, "membership_id", required=True), **changes}
    if kind == "claim.membership.remove":
        return {"membership_id": _claim_text(params, "membership_id", required=True)}
    raise _invalid(f"Unknown claim write: {kind}")


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
        if not _declared(PROCESS_KIND, "process"):
            raise ServiceError("invalid", f"Unknown job kind: {PROCESS_KIND}")
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

    def submit_claim(self, kind: str, params: dict[str, Any]) -> JobRef:
        """Queue a claim graph write; the result carries `thesis_id` or `membership_id`."""
        if not _declared(kind, "claim"):
            raise ServiceError("invalid", f"Unknown claim write: {kind}")
        return self._submit(f"job_{uuid.uuid4().hex}", kind, "", "", check_claim(kind, params))

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
        parse, or cannot be read, is corrupt, not half-written: skip it, and with `quarantine` (the
        worker's intake) rename it to `.bad` so it stops matching `has_submissions`. One removed
        while being read is gone, not corrupt."""
        if not self.spool.is_dir():
            return []
        found: list[Submission] = []
        for path in sorted(self.spool.glob(pattern)):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                record = None
            if not isinstance(record, dict):
                if quarantine:
                    logger.warning("Moving unreadable spool submission %s aside as .bad", path.name)
                    try:
                        path.replace(path.with_suffix(".bad"))
                    except OSError:
                        logger.exception("Could not move spool submission %s aside", path.name)
                continue
            found.append(Submission(
                path=path, op=record.get("op", ""), job_id=record.get("job_id", ""),
                kind=record.get("kind", ""), target=record.get("target", ""),
                revision=record.get("revision", ""), payload=record.get("payload") or {},
                created_at=record.get("created_at", ""),
            ))
        return found
