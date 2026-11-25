"""Job and consensus-refresh rows: the worker's claims, leases, retries, and refresh revisions.

`JobStore` runs on an `OntologyDB` connection, so a job's state changes commit in the same
transaction as the graph writes they describe. A claim carries a random `claim_id` and a lease;
`check_claim` inside a commit refuses an attempt whose claim was lost or whose lease expired.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, closing, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

TERMINAL_STATES = ("succeeded", "failed", "superseded")


class LeaseLostError(Exception):
    """This attempt no longer holds its job: the lease expired or another worker reclaimed it."""


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    target: str
    revision: str
    priority: int
    state: str
    stage: str
    attempts: int
    next_attempt_at: str
    claim_id: str | None
    lease_expires_at: str | None
    payload: dict[str, Any]
    companies: dict[str, int]
    result: dict[str, Any] | None
    error_code: str | None
    error: str | None
    created_at: str
    updated_at: str

    def to_status(self) -> dict[str, Any]:
        """Public status; result keys starting with `_` are worker-private and left out."""
        result = {k: v for k, v in self.result.items() if not k.startswith("_")} if self.result else self.result
        return {
            "job_id": self.job_id, "kind": self.kind, "target": self.target, "revision": self.revision,
            "state": self.state, "stage": self.stage, "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at, "error_code": self.error_code, "error": self.error,
            "companies": sorted(self.companies), "result": result,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"], kind=row["kind"], target=row["target"], revision=row["revision"],
        priority=row["priority"], state=row["state"], stage=row["stage"], attempts=row["attempts"],
        next_attempt_at=row["next_attempt_at"], claim_id=row["claim_id"],
        lease_expires_at=row["lease_expires_at"], payload=json.loads(row["payload_json"] or "{}"),
        companies=json.loads(row["companies_json"] or "{}"),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error_code=row["error_code"], error=row["error"], created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _missing_table(exc: sqlite3.OperationalError) -> bool:
    return "no such table" in str(exc)


class JobStore:
    """Reads and writes `jobs` and `consensus_refresh` on one connection."""

    def __init__(
        self, conn: sqlite3.Connection, transaction: Callable[..., AbstractContextManager[None]]
    ) -> None:
        self._conn = conn
        self._transaction = transaction

    # --- reads (also on read-only connections, and on databases created before these tables)

    def _select(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        try:
            return self._conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError as exc:
            if _missing_table(exc):
                return []
            raise

    def get(self, job_id: str) -> Job | None:
        rows = self._select("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        return _row_to_job(rows[0]) if rows else None

    def list(self, *, kind: str | None = None, target: str | None = None) -> list[Job]:
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if target is not None:
            clauses.append("target = ?")
            params.append(target)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return [_row_to_job(r) for r in self._select(f"SELECT * FROM jobs {where} ORDER BY created_at, rowid", params)]  # noqa: S608

    def latest(self, *, target: str) -> Job | None:
        rows = self._select("SELECT * FROM jobs WHERE target = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (target,))
        return _row_to_job(rows[0]) if rows else None

    def consensus_state(self, company_id: str) -> dict[str, Any] | None:
        rows = self._select("SELECT * FROM consensus_refresh WHERE company_id = ?", (company_id,))
        return dict(rows[0]) if rows else None

    def list_consensus_refresh(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._select("SELECT * FROM consensus_refresh ORDER BY company_id")]

    def consensus_target(self, company_id: str) -> int:
        state = self.consensus_state(company_id)
        return int(state["target_revision"]) if state else 0

    def pending_consensus(self) -> list[str]:
        """Companies whose consensus refresh is still owed and not marked failed."""
        rows = self._select(
            "SELECT company_id FROM consensus_refresh "
            "WHERE state = 'pending' AND completed_revision < target_revision ORDER BY company_id"
        )
        return [str(r["company_id"]) for r in rows]

    def has_active(self, kind: str) -> bool:
        """Whether a job of `kind` is queued or running."""
        return bool(self._select(
            "SELECT 1 FROM jobs WHERE kind = ? AND state IN ('queued', 'running') LIMIT 1", (kind,)
        ))

    # --- writes (worker only)

    def insert(
        self, *, job_id: str, kind: str, target: str, revision: str, priority: int,
        payload: dict[str, Any], created_at: str, now: datetime,
    ) -> bool:
        """Add a submitted job; an existing `job_id` (a duplicate request) is kept as is."""
        with self._transaction():
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO jobs (job_id, kind, target, revision, priority, state, next_attempt_at, "
                "payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, kind, target, revision, priority, now.isoformat(), json.dumps(payload),
                 created_at, now.isoformat()),
            )
            return cur.rowcount == 1

    def reopen(self, job_id: str, now: datetime) -> bool:
        """An explicit retry: a failed job is queued again with a fresh attempt budget."""
        with self._transaction():
            cur = self._conn.execute(
                "UPDATE jobs SET state = 'queued', attempts = 0, next_attempt_at = ?, claim_id = NULL, "
                "lease_expires_at = NULL, error_code = NULL, error = NULL, updated_at = ? "
                "WHERE job_id = ? AND state = 'failed'",
                (now.isoformat(), now.isoformat(), job_id),
            )
            return cur.rowcount == 1

    def claim(self, now: datetime, lease_seconds: float, *, max_attempts: int = 3) -> Job | None:
        """Claim the most urgent due job, or reclaim one whose lease expired."""
        stamp = now.isoformat()
        with self._transaction(immediate=True):
            while True:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE (state = 'queued' AND next_attempt_at <= ?) "
                    "OR (state = 'running' AND lease_expires_at <= ?) "
                    "ORDER BY priority, created_at, rowid LIMIT 1",
                    (stamp, stamp),
                ).fetchone()
                if row is None:
                    return None
                if row["state"] == "running" and row["attempts"] >= max_attempts:
                    self._conn.execute(
                        "UPDATE jobs SET state = 'failed', claim_id = NULL, lease_expires_at = NULL, "
                        "error_code = 'failed', error = COALESCE(error, 'The worker lost this job.'), updated_at = ? "
                        "WHERE job_id = ?",
                        (stamp, row["job_id"]),
                    )
                    continue
                claim_id = uuid.uuid4().hex
                self._conn.execute(
                    "UPDATE jobs SET state = 'running', attempts = attempts + 1, claim_id = ?, "
                    "lease_expires_at = ?, updated_at = ? WHERE job_id = ?",
                    (claim_id, (now + timedelta(seconds=lease_seconds)).isoformat(), stamp, row["job_id"]),
                )
                claimed = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
                return _row_to_job(claimed)

    def check_claim(self, job_id: str, claim_id: str, now: datetime, lease_seconds: float) -> None:
        """Inside a commit: refuse a lost or expired claim, otherwise extend its lease."""
        with self._transaction():
            row = self._conn.execute(
                "SELECT claim_id, state, lease_expires_at FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if (
                row is None or row["claim_id"] != claim_id or row["state"] != "running"
                or row["lease_expires_at"] is None or row["lease_expires_at"] <= now.isoformat()
            ):
                raise LeaseLostError(job_id)
            self._conn.execute(
                "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                ((now + timedelta(seconds=lease_seconds)).isoformat(), job_id),
            )

    def record_companies(self, job_id: str, revisions: dict[str, int]) -> None:
        """Remember the consensus revisions this job's committed write is waiting for."""
        with self._transaction():
            row = self._conn.execute("SELECT companies_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            companies = json.loads(row["companies_json"] or "{}") if row else {}
            for company_id, revision in revisions.items():
                companies[company_id] = max(int(revision), int(companies.get(company_id, 0)))
            self._conn.execute(
                "UPDATE jobs SET companies_json = ?, stage = 'consensus' WHERE job_id = ?",
                (json.dumps(companies, sort_keys=True), job_id),
            )

    def record_result(self, job_id: str, result: dict[str, Any]) -> None:
        with self._transaction():
            self._conn.execute("UPDATE jobs SET result_json = ? WHERE job_id = ?", (json.dumps(result), job_id))

    def set_stage(self, job_id: str, stage: str) -> None:
        with self._transaction():
            self._conn.execute("UPDATE jobs SET stage = ? WHERE job_id = ?", (stage, job_id))

    def _close(self, job_id: str, claim_id: str, sets: str, params: tuple[Any, ...], now: datetime) -> bool:
        with self._transaction():
            cur = self._conn.execute(
                f"UPDATE jobs SET {sets}, claim_id = NULL, lease_expires_at = NULL, updated_at = ? "  # noqa: S608
                "WHERE job_id = ? AND claim_id = ? AND state = 'running'",
                (*params, now.isoformat(), job_id, claim_id),
            )
            return cur.rowcount == 1

    def finish(self, job_id: str, claim_id: str, result: dict[str, Any] | None, now: datetime) -> bool:
        return self._close(
            job_id, claim_id, "state = 'succeeded', result_json = ?, error_code = NULL, error = NULL",
            (json.dumps(result) if result is not None else None,), now,
        )

    def fail(
        self, job_id: str, claim_id: str, *, code: str, error: str, retry_at: datetime | None, now: datetime
    ) -> bool:
        """Record a failed attempt: queued again at `retry_at`, or terminal when it is None."""
        if retry_at is None:
            return self._close(job_id, claim_id, "state = 'failed', error_code = ?, error = ?", (code, error), now)
        return self._close(
            job_id, claim_id, "state = 'queued', next_attempt_at = ?, error_code = ?, error = ?",
            (retry_at.isoformat(), code, error), now,
        )

    def supersede(self, job_id: str, claim_id: str, error: str, now: datetime) -> bool:
        return self._close(job_id, claim_id, "state = 'superseded', error_code = 'conflict', error = ?", (error,), now)

    def mark_consensus_pending(self, company_ids: Iterable[str], now: datetime | None = None) -> dict[str, int]:
        """Advance each company's refresh target; call inside the evidence write's transaction."""
        now = now or datetime.now(UTC)
        revisions: dict[str, int] = {}
        with self._transaction():
            for company_id in sorted(set(company_ids)):
                self._conn.execute(
                    "INSERT INTO consensus_refresh (company_id, target_revision, completed_revision, state, updated_at) "
                    "VALUES (?, 1, 0, 'pending', ?) ON CONFLICT(company_id) DO UPDATE SET "
                    "target_revision = target_revision + 1, state = 'pending', error = NULL, "
                    "updated_at = excluded.updated_at",
                    (company_id, now.isoformat()),
                )
                revisions[company_id] = self.consensus_target(company_id)
        return revisions

    def complete_consensus(self, company_id: str, revision: int, now: datetime) -> None:
        """Record a published (or retired) consensus for the evidence revision it read."""
        with self._transaction():
            self._conn.execute(
                "INSERT INTO consensus_refresh (company_id, target_revision, completed_revision, state, updated_at) "
                "VALUES (?, ?, ?, 'current', ?) ON CONFLICT(company_id) DO UPDATE SET "
                "completed_revision = MAX(completed_revision, excluded.completed_revision), "
                "state = CASE WHEN excluded.completed_revision >= target_revision THEN 'current' ELSE state END, "
                "error = CASE WHEN excluded.completed_revision >= target_revision THEN NULL ELSE error END, "
                "updated_at = excluded.updated_at",
                (company_id, revision, revision, now.isoformat()),
            )

    def fail_consensus(self, company_id: str, error: str, now: datetime) -> None:
        with self._transaction():
            self._conn.execute(
                "UPDATE consensus_refresh SET state = 'failed', error = ?, updated_at = ? "
                "WHERE company_id = ? AND completed_revision < target_revision",
                (error[:500], now.isoformat(), company_id),
            )


@contextmanager
def read_jobs(db_path: str | Path) -> Iterator[JobStore | None]:
    """Read job rows on a plain read-only connection, or None when the database does not exist.

    A status poll needs neither sqlite-vec nor the applied registry, so it skips `OntologyDB`."""
    from stock_ontology.db.storage import BUSY_TIMEOUT_MS  # storage imports this module

    if not Path(db_path).exists():
        yield None
        return
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON;")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
        yield JobStore(conn, lambda **_: nullcontext())
