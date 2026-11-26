"""The claim graph: theses and thesis memberships anchored to ontology themes and companies.

Ledger: docs/proposals/theme-catalysts-phase-1.md. Claim writes are spooled jobs submitted through
`ProcessingService.submit_claim` and applied by the worker. Pages read them from a read-only database.

Interface these witnesses fix:
  - `ProcessingService.submit_claim(kind, params) -> JobRef`, kinds:
      `claim.thesis.add`       {theme_id, statement}                  result {"thesis_id"}
      `claim.thesis.edit`      {thesis_id, statement}
      `claim.thesis.remove`    {thesis_id}
      `claim.membership.add`   {thesis_id, company_id, status: "in" | "watching", reason,
                                catalyst_event, catalyst_by (YYYY-MM-DD), expected_effect}
                                                                       result {"membership_id"}
      `claim.membership.edit`  {membership_id, <any add field but thesis_id and company_id>}
      `claim.membership.remove` {membership_id}
    A refused write raises `ServiceError("invalid", ...)` at submission or fails its job with
    `error_code == "invalid"`.
  - `build_thesis_context(db, thesis_id, lang=...)` in `stock_ontology.web.research.views`, raising
    `KeyError` for a missing thesis: `ctx["thesis"]` (`.id`, `.statement`, `.theme_id`) and
    `ctx["memberships"]` rows (`.id`, `.company.id`, `.company.name`, `.status` "in" | "candidate",
    `.reason`, `.catalyst` None or `.event`, `.by_date` ISO string, `.expected_effect`).
  - `build_theme_context(...)["theses"]` rows (`.id`, `.statement`); each `exposed_companies` row has
    `.suggested`, True when no thesis on the theme has a membership for that company.
  - `build_entity_context(...)["thesis_memberships"]` rows (`.thesis_id`, `.statement`, `.status`).
  - `GET /thesis/{thesis_id}` renders the thesis page; theme and company pages link to it with
    `href="/thesis/{thesis_id}"`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from web_support import DIM, FakeWebLLM, seed_web_db, unit_vec

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.models import Node
from stock_ontology.services.errors import ServiceError
from stock_ontology.services.processing import ProcessingService
from stock_ontology.web import create_app
from stock_ontology.worker import Worker

THEME = "thm_power"
WATCHED = "ent_nvda"  # stated EXPOSED_TO the theme in seed_web_db
HELD = "ent_tsmc"


def _setup(tmp_path: Path) -> tuple[Settings, FakeWebLLM]:
    db_path = tmp_path / "claims.db"
    seed_web_db(db_path)
    settings = Settings(
        db_path=db_path, embedding_dim=DIM, data_dir=tmp_path, registry_path=tmp_path / "missing.json"
    )
    return settings, FakeWebLLM()


def _apply(settings: Settings, llm: FakeWebLLM, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """Submit one claim job, run the worker once, and return its result; the job must succeed."""
    ref = ProcessingService(settings).submit_claim(kind, params)
    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    status = ProcessingService(settings).get_status(ref.job_id)
    assert status["state"] == "succeeded", status
    return status["result"] or {}


def _assert_refused(settings: Settings, llm: FakeWebLLM, kind: str, params: dict[str, Any]) -> None:
    """A refused claim write is rejected at submission or fails its job as invalid."""
    try:
        ref = ProcessingService(settings).submit_claim(kind, params)
    except ServiceError as exc:
        assert exc.code == "invalid", exc
        return
    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    status = ProcessingService(settings).get_status(ref.job_id)
    assert status["state"] == "failed" and status["error_code"] == "invalid", status


def _contexts(settings: Settings, thesis_id: str, company_id: str = WATCHED) -> dict[str, Any]:
    from stock_ontology.web.research.views import (
        build_entity_context,
        build_theme_context,
        build_thesis_context,
    )

    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        return {
            "thesis": build_thesis_context(db, thesis_id, lang="en"),
            "theme": build_theme_context(db, THEME, lang="en"),
            "entity": build_entity_context(db, company_id, lang="en"),
        }


def _membership_view(ctx: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows = []
    for row in ctx["thesis"]["memberships"]:
        cat = row.catalyst
        rows.append((
            row.company.id, row.status, row.reason,
            None if cat is None else (cat.event, cat.by_date, cat.expected_effect),
        ))
    return sorted(rows, key=lambda r: r[0])


def _ontology_rows(settings: Settings) -> dict[str, list[tuple[Any, ...]]]:
    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        return {
            table: [tuple(r) for r in db.conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
            for table in ("nodes", "edges", "pending_edges")
        }


def test_analyst_builds_a_thesis_and_teammates_reach_it_from_theme_and_company(tmp_path: Path) -> None:
    settings, llm = _setup(tmp_path)
    ontology_before = _ontology_rows(settings)

    thesis_id = _apply(settings, llm, "claim.thesis.add", {
        "theme_id": THEME, "statement": "The rollout benefits liquid cooling suppliers.",
    })["thesis_id"]
    held_id = _apply(settings, llm, "claim.membership.add", {
        "thesis_id": thesis_id, "company_id": HELD, "status": "in",
        "reason": "Already ships CoWoS capacity tied to the rollout.",
    })["membership_id"]
    watched_id = _apply(settings, llm, "claim.membership.add", {
        "thesis_id": thesis_id, "company_id": WATCHED, "status": "watching",
        "catalyst_event": "Qualification with a hyperscaler", "catalyst_by": "2027-06-30",
        "expected_effect": "Unlocks volume orders tied to the rollout.",
    })["membership_id"]
    rival_id = _apply(settings, llm, "claim.thesis.add", {
        "theme_id": THEME, "statement": "The rollout favors grid storage over on-site generation.",
    })["thesis_id"]

    ctx = _contexts(settings, thesis_id)
    assert ctx["thesis"]["thesis"].statement == "The rollout benefits liquid cooling suppliers."
    assert ctx["thesis"]["thesis"].theme_id == THEME
    rows = {row.id: row for row in ctx["thesis"]["memberships"]}
    assert set(rows) == {held_id, watched_id}
    held, watched = rows[held_id], rows[watched_id]
    assert (held.company.id, held.status, held.reason, held.catalyst) == (
        HELD, "in", "Already ships CoWoS capacity tied to the rollout.", None,
    )
    assert (watched.company.id, watched.status) == (WATCHED, "candidate")
    assert (watched.catalyst.event, watched.catalyst.by_date, watched.catalyst.expected_effect) == (
        "Qualification with a hyperscaler", "2027-06-30", "Unlocks volume orders tied to the rollout.",
    )
    assert sorted((t.id, t.statement) for t in ctx["theme"]["theses"]) == sorted([
        (thesis_id, "The rollout benefits liquid cooling suppliers."),
        (rival_id, "The rollout favors grid storage over on-site generation."),
    ]), "both competing theses show on the theme page"
    assert [(m.thesis_id, m.status) for m in ctx["entity"]["thesis_memberships"]] == [(thesis_id, "candidate")]
    exposed = {row.company.id: row for row in ctx["theme"]["exposed_companies"]}
    assert exposed[WATCHED].suggested is False, "a company in a thesis is no longer a suggested candidate"

    client = TestClient(create_app(settings, llm=llm, agent_model=llm.model))
    page = client.get(f"/thesis/{thesis_id}")
    assert page.status_code == 200, page.text
    assert "The rollout benefits liquid cooling suppliers." in page.text
    assert "Qualification with a hyperscaler" in page.text and "NVIDIA" in page.text and "TSMC" in page.text
    assert f'href="/thesis/{thesis_id}"' in client.get(f"/theme/{THEME}").text
    assert f'href="/thesis/{thesis_id}"' in client.get(f"/entity/{WATCHED}").text

    # Refusals write nothing.
    shown = _membership_view(_contexts(settings, thesis_id))
    _assert_refused(settings, llm, "claim.membership.add", {
        "thesis_id": rival_id, "company_id": HELD, "status": "in", "reason": "",
    })
    _assert_refused(settings, llm, "claim.membership.add", {
        "thesis_id": rival_id, "company_id": WATCHED, "status": "watching",
        "catalyst_event": "Qualification", "catalyst_by": "end of Q2", "expected_effect": "Volume orders.",
    })
    _assert_refused(settings, llm, "claim.membership.add", {
        "thesis_id": rival_id, "company_id": WATCHED, "status": "watching",
        "catalyst_event": "Qualification", "expected_effect": "Volume orders.",
    })
    after = _contexts(settings, rival_id)
    assert after["thesis"]["memberships"] == [], "a refused membership leaves no record"
    assert _membership_view(_contexts(settings, thesis_id)) == shown

    # Edit changes the shown values.
    _apply(settings, llm, "claim.thesis.edit", {
        "thesis_id": thesis_id, "statement": "The rollout benefits cooling and packaging suppliers.",
    })
    _apply(settings, llm, "claim.membership.edit", {
        "membership_id": watched_id, "catalyst_by": "2027-09-30",
        "expected_effect": "Unlocks a second hyperscaler program.",
    })
    ctx = _contexts(settings, thesis_id)
    assert ctx["thesis"]["thesis"].statement == "The rollout benefits cooling and packaging suppliers."
    watched = next(row for row in ctx["thesis"]["memberships"] if row.id == watched_id)
    assert (watched.catalyst.event, watched.catalyst.by_date, watched.catalyst.expected_effect) == (
        "Qualification with a hyperscaler", "2027-09-30", "Unlocks a second hyperscaler program.",
    )
    assert "The rollout benefits cooling and packaging suppliers." in client.get(f"/theme/{THEME}").text

    # Remove takes the membership and the thesis off every page.
    _apply(settings, llm, "claim.membership.remove", {"membership_id": watched_id})
    _apply(settings, llm, "claim.thesis.remove", {"thesis_id": rival_id})
    ctx = _contexts(settings, thesis_id)
    assert [row.id for row in ctx["thesis"]["memberships"]] == [held_id]
    assert ctx["entity"]["thesis_memberships"] == []
    assert [t.id for t in ctx["theme"]["theses"]] == [thesis_id]
    exposed = {row.company.id: row for row in ctx["theme"]["exposed_companies"]}
    assert exposed[WATCHED].suggested is True, "a stated-exposure company no thesis covers is a suggested candidate"
    assert client.get(f"/thesis/{rival_id}").status_code == 404
    assert f'href="/thesis/{thesis_id}"' not in client.get(f"/entity/{WATCHED}").text

    assert _ontology_rows(settings) == ontology_before, "claim jobs must not change nodes, edges, or pending_edges"


def test_merging_a_company_moves_its_thesis_membership_to_the_survivor(tmp_path: Path) -> None:
    settings, llm = _setup(tmp_path)
    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_nvda_corp", node_type="entity", name="NVIDIA Corporation", summary="s",
                 facets={"entity_type": "company"}),
            embedding=unit_vec(9),
        )
    thesis_id = _apply(settings, llm, "claim.thesis.add", {
        "theme_id": THEME, "statement": "The rollout benefits liquid cooling suppliers.",
    })["thesis_id"]
    membership_id = _apply(settings, llm, "claim.membership.add", {
        "thesis_id": thesis_id, "company_id": WATCHED, "status": "watching",
        "catalyst_event": "Qualification with a hyperscaler", "catalyst_by": "2027-06-30",
        "expected_effect": "Unlocks volume orders tied to the rollout.",
    })["membership_id"]

    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=False) as db:
        db.merge_node_into(WATCHED, "ent_nvda_corp")

    ctx = _contexts(settings, thesis_id, company_id="ent_nvda_corp")
    assert [(row.id, row.company.id) for row in ctx["thesis"]["memberships"]] == [(membership_id, "ent_nvda_corp")]
    assert [m.thesis_id for m in ctx["entity"]["thesis_memberships"]] == [thesis_id]
