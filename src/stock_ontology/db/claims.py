"""Claim graph rows: theses, thesis memberships, catalysts, and predictions.

The claim graph records the team's beliefs and sits outside the ontology. Claim rows point at
ontology nodes by ID (a thesis at its theme, a membership at its company); no ontology row
points at a claim. `ClaimStore` runs on an `OntologyDB` connection, and only the worker's claim
jobs write through it. Reads work on read-only connections and on databases created before
these tables existed.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any

from stock_ontology.db.schema import now_iso

# A watching membership is stored as a candidate, and its catalyst carries an entry prediction.
CANDIDATE = "candidate"
ENTRY = "entry"


def _missing_table(exc: sqlite3.OperationalError) -> bool:
    return "no such table" in str(exc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ClaimStore:
    """Reads and writes the `claim_*` tables on one connection."""

    def __init__(
        self, conn: sqlite3.Connection, transaction: Callable[..., AbstractContextManager[None]]
    ) -> None:
        self._conn = conn
        self._transaction = transaction

    def _select(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        try:
            return self._conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError as exc:
            if _missing_table(exc):
                return []
            raise

    # --- reads

    def get_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        rows = self._select("SELECT * FROM claim_theses WHERE id = ?", (thesis_id,))
        return dict(rows[0]) if rows else None

    def list_theses(self, theme_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._select(
            "SELECT * FROM claim_theses WHERE theme_id = ? ORDER BY created_at, id", (theme_id,)
        )]

    def _with_catalysts(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        """Attach each membership's entry catalyst (event, by-date, expected effect) or None."""
        out = [dict(r) for r in rows]
        if not out:
            return out
        placeholders = ", ".join("?" for _ in out)
        catalysts: dict[str, dict[str, Any]] = {}
        for r in self._select(
            "SELECT c.id, c.membership_id, c.event, c.by_date, p.expected_effect "
            "FROM claim_catalysts c JOIN claim_predictions p ON p.catalyst_id = c.id "
            f"WHERE p.direction = ? AND c.membership_id IN ({placeholders}) "  # noqa: S608
            "ORDER BY c.created_at, c.id, p.created_at, p.id",
            [ENTRY, *(m["id"] for m in out)],
        ):
            catalysts.setdefault(str(r["membership_id"]), {
                "id": r["id"], "event": r["event"], "by_date": r["by_date"], "expected_effect": r["expected_effect"],
            })
        for membership in out:
            membership["catalyst"] = catalysts.get(str(membership["id"]))
        return out

    def get_membership(self, membership_id: str) -> dict[str, Any] | None:
        found = self._with_catalysts(self._select("SELECT * FROM claim_memberships WHERE id = ?", (membership_id,)))
        return found[0] if found else None

    def find_membership(self, thesis_id: str, company_id: str) -> dict[str, Any] | None:
        found = self._with_catalysts(self._select(
            "SELECT * FROM claim_memberships WHERE thesis_id = ? AND company_id = ?", (thesis_id, company_id)
        ))
        return found[0] if found else None

    def list_memberships(self, thesis_id: str) -> list[dict[str, Any]]:
        return self._with_catalysts(self._select(
            "SELECT * FROM claim_memberships WHERE thesis_id = ? ORDER BY created_at, id", (thesis_id,)
        ))

    def company_memberships(self, company_id: str) -> list[dict[str, Any]]:
        """The company's memberships, each with its thesis `statement` and `theme_id`."""
        return self._with_catalysts(self._select(
            "SELECT m.*, t.statement, t.theme_id FROM claim_memberships m "
            "JOIN claim_theses t ON t.id = m.thesis_id WHERE m.company_id = ? "
            "ORDER BY t.created_at, t.id",
            (company_id,),
        ))

    def covered_company_ids(self, theme_id: str) -> set[str]:
        """Companies with a membership in any thesis on the theme."""
        return {str(r["company_id"]) for r in self._select(
            "SELECT DISTINCT m.company_id FROM claim_memberships m "
            "JOIN claim_theses t ON t.id = m.thesis_id WHERE t.theme_id = ?",
            (theme_id,),
        )}

    # --- writes (worker claim jobs only)

    def add_thesis(self, theme_id: str, statement: str) -> str:
        thesis_id = _new_id("ths")
        now = now_iso()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO claim_theses (id, theme_id, statement, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (thesis_id, theme_id, statement, now, now),
            )
        return thesis_id

    def edit_thesis(self, thesis_id: str, statement: str) -> bool:
        with self._transaction():
            cur = self._conn.execute(
                "UPDATE claim_theses SET statement = ?, updated_at = ? WHERE id = ?", (statement, now_iso(), thesis_id)
            )
        return cur.rowcount > 0

    def remove_thesis(self, thesis_id: str) -> bool:
        """Delete the thesis; its memberships, catalysts, and predictions cascade."""
        with self._transaction():
            cur = self._conn.execute("DELETE FROM claim_theses WHERE id = ?", (thesis_id,))
        return cur.rowcount > 0

    def _set_entry_catalyst(self, membership_id: str, event: str, by_date: str, expected_effect: str) -> None:
        """Update the membership's entry catalyst and prediction, or create them."""
        now = now_iso()
        current = self._select(
            "SELECT c.id AS catalyst_id, p.id AS prediction_id FROM claim_catalysts c "
            "JOIN claim_predictions p ON p.catalyst_id = c.id "
            "WHERE c.membership_id = ? AND p.direction = ? ORDER BY c.created_at, c.id, p.created_at, p.id LIMIT 1",
            (membership_id, ENTRY),
        )
        if current:
            self._conn.execute(
                "UPDATE claim_catalysts SET event = ?, by_date = ?, updated_at = ? WHERE id = ?",
                (event, by_date, now, current[0]["catalyst_id"]),
            )
            self._conn.execute(
                "UPDATE claim_predictions SET expected_effect = ?, updated_at = ? WHERE id = ?",
                (expected_effect, now, current[0]["prediction_id"]),
            )
            return
        catalyst_id = _new_id("cat")
        self._conn.execute(
            "INSERT INTO claim_catalysts (id, membership_id, event, by_date, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (catalyst_id, membership_id, event, by_date, now, now),
        )
        self._conn.execute(
            "INSERT INTO claim_predictions (id, catalyst_id, direction, expected_effect, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id("prd"), catalyst_id, ENTRY, expected_effect, now, now),
        )

    def add_membership(
        self, thesis_id: str, company_id: str, status: str, reason: str,
        catalyst: tuple[str, str, str] | None = None,
    ) -> str:
        """Add a membership; a candidate's catalyst (event, by-date, expected effect) commits with it."""
        membership_id = _new_id("mbr")
        now = now_iso()
        with self._transaction():
            self._conn.execute(
                "INSERT INTO claim_memberships (id, thesis_id, company_id, status, reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (membership_id, thesis_id, company_id, status, reason, now, now),
            )
            if catalyst is not None:
                self._set_entry_catalyst(membership_id, *catalyst)
        return membership_id

    def edit_membership(
        self, membership_id: str, status: str, reason: str, catalyst: tuple[str, str, str] | None = None,
    ) -> bool:
        """Change status and reason, and set the entry catalyst when given. Other catalysts stay."""
        with self._transaction():
            cur = self._conn.execute(
                "UPDATE claim_memberships SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
                (status, reason, now_iso(), membership_id),
            )
            if cur.rowcount and catalyst is not None:
                self._set_entry_catalyst(membership_id, *catalyst)
        return cur.rowcount > 0

    def remove_membership(self, membership_id: str) -> bool:
        with self._transaction():
            cur = self._conn.execute("DELETE FROM claim_memberships WHERE id = ?", (membership_id,))
        return cur.rowcount > 0

    def repoint_node(self, loser_id: str, survivor_id: str) -> None:
        """Move claims on a merged node to its survivor, inside the caller's merge transaction.

        When the survivor already has a membership in the same thesis, the survivor's membership
        stays and takes over the loser's catalysts; the loser's membership is then dropped.
        """
        self._conn.execute("UPDATE claim_theses SET theme_id = ? WHERE theme_id = ?", (survivor_id, loser_id))
        for row in self._conn.execute(
            "SELECT l.id AS loser, s.id AS survivor FROM claim_memberships l "
            "JOIN claim_memberships s ON s.thesis_id = l.thesis_id AND s.company_id = ? "
            "WHERE l.company_id = ?",
            (survivor_id, loser_id),
        ).fetchall():
            self._conn.execute(
                "UPDATE claim_catalysts SET membership_id = ? WHERE membership_id = ?", (row["survivor"], row["loser"])
            )
            self._conn.execute("DELETE FROM claim_memberships WHERE id = ?", (row["loser"],))
        self._conn.execute("UPDATE claim_memberships SET company_id = ? WHERE company_id = ?", (survivor_id, loser_id))
