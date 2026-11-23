"""Offline witnesses: advanced-search options and filters follow the ontology."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.models import Edge, Node
from stock_ontology.registry import create_minimal_registry, load_registry
from stock_ontology.search import NODE_TYPES, SearchFilters, search_ontology
from stock_ontology.vocab import (
    CONVICTION,
    NODE_FACET_VOCABS,
    SENTIMENT_FILTER_VALUES,
    STANCE,
    SUBTYPE_FACET,
    SUPPORT_STRENGTH,
)
from stock_ontology.web import create_app

from test_db import insert_legacy_edge
from test_web import DIM, FakeWebLLM, _unit_vec

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "ontology_registry.json"


def _seed(db_path: Path) -> None:
    nodes = [
        Node(id="ent_aapl", node_type="entity", name="Apple", summary="", facets={"entity_type": "company", "ticker": "AAPL"}),
        Node(id="ent_qcom", node_type="entity", name="Qualcomm", summary="", facets={"entity_type": "company", "ticker": "QCOM"}),
        Node(
            id="evt_up",
            node_type="event",
            name="Upcoming Launch Event", summary="",
            facets={"event_type": "catalyst", "status": "upcoming", "event_date": "2026-12-01"},
        ),
        Node(
            id="evt_occ",
            node_type="event",
            name="Occurred News Event", summary="",
            facets={
                "event_type": "news",
                "status": "occurred",
                "sentiment": "negative",
                "event_date": "2026-10-01",
                "source": {"file_path": "QCOM/2026-10-01_news.md"},
            },
        ),
        Node(
            id="evt_rum",
            node_type="event",
            name="Rumored Deal Event", summary="",
            facets={"event_type": "news", "status": "rumored", "event_date": "2026-09-01"},
        ),
        Node(
            id="evt_off",
            node_type="event",
            name="Webinar Event", summary="",
            facets={"event_type": "webinar", "status": "occurred", "event_date": "2026-08-01"},
        ),
        Node(
            id="vw_weak",
            node_type="view",
            name="Weak Rumor View", summary="",
            facets={
                "view_type": "rumor",
                "stance": "cautious",
                "support_strength": "weak",
                "conviction": "low",
                "as_of": "2026-11-01",
            },
        ),
        Node(
            id="vw_strong",
            node_type="view",
            name="Strong Analyst View", summary="",
            facets={
                "view_type": "analyst_report",
                "stance": "outperform",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-11-02",
            },
        ),
        Node(
            id="vw_cons",
            node_type="view",
            name="House Consensus View", summary="",
            facets={
                "view_type": "consensus",
                "status": "active",
                "stance": "buy",
                "support_strength": "moderate",
                "conviction": "medium",
                "as_of": "2026-11-03",
            },
        ),
        Node(id="thm_cons", node_type="theme", name="Consensus Stage Theme", summary="", facets={"stage": "consensus"}),
        Node(id="thm_acc", node_type="theme", name="Accelerating Stage Theme", summary="", facets={"stage": "accelerating"}),
    ]
    edges = [
        Edge(id="e_up", from_id="evt_up", to_id="ent_aapl", relation="ABOUT", facets={"basis": "extracted"}),
        Edge(id="e_weak", from_id="vw_weak", to_id="ent_aapl", relation="ABOUT", facets={"basis": "extracted"}),
        Edge(id="e_occ_q", from_id="evt_occ", to_id="ent_qcom", relation="ABOUT", facets={"basis": "extracted"}),
        Edge(id="e_occ_a", from_id="evt_occ", to_id="ent_aapl", relation="RELATES_TO", facets={"basis": "extracted"}),
        Edge(id="e_strong", from_id="vw_strong", to_id="ent_aapl", relation="SUPPORTS", facets={"basis": "extracted"}),
        Edge(id="e_thm", from_id="ent_aapl", to_id="thm_acc", relation="EXPOSED_TO", facets={"basis": "extracted"}),
    ]
    # `evt_off` is a legacy row whose `event_type` is outside the vocabulary, so it is written
    # under a registry that declares no facet schema, as rows were before it existed.
    legacy = create_minimal_registry().model_copy(update={"facet_schema": {}})
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False, registry=legacy) as db:
        for idx, node in enumerate(nodes):
            db.upsert_node(node, embedding=_unit_vec(idx))
        for edge in edges:
            db.upsert_edge(edge)
        insert_legacy_edge(
            db, Edge(id="e_off", from_id="vw_cons", to_id="ent_qcom", relation="FROBNICATES", facets={"basis": "extracted"})
        )


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    db_path = tmp_path / "opts.db"
    _seed(db_path)
    return db_path


def _client(db_path: Path, tmp_path: Path, registry_path: Path = REGISTRY_PATH) -> TestClient:
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path, registry_path=registry_path)
    return TestClient(create_app(settings, llm=FakeWebLLM()))


def _select_values(page: str, name: str) -> set[str] | None:
    m = re.search(rf'<select[^>]*\bname="{name}"[^>]*>(.*?)</select>', page, re.DOTALL)
    if m is None:
        return None
    return {v for v in re.findall(r'<option value="([^"]*)"', m.group(1)) if v}


def _result_ids(client: TestClient, **params: str) -> set[str]:
    r = client.get("/search", params=params)
    assert r.status_code == 200
    return set(re.findall(r'data-result-id="([^"]+)"', r.text))


def _expected_options() -> dict[str, set[str]]:
    return {
        "node_type": set(NODE_TYPES),
        "subtype": {
            f"{nt}:{m}" for nt, facet in SUBTYPE_FACET.items() for m in NODE_FACET_VOCABS[nt][facet].members
        },
        "status": {f"{nt}:{m}" for nt in ("event", "view") for m in NODE_FACET_VOCABS[nt]["status"].members},
        "sentiment": set(SENTIMENT_FILTER_VALUES),
        "stance": set(STANCE.members),
        "support_strength": set(SUPPORT_STRENGTH.members),
        "conviction": set(CONVICTION.members),
        "relation": {spec.name for spec in load_registry(REGISTRY_PATH).relations},
    }


@pytest.mark.parametrize(
    "select_name",
    ["node_type", "subtype", "status", "sentiment", "stance", "support_strength", "conviction", "relation"],
)
def test_search_select_lists_exactly_the_ontology_values(seeded: Path, tmp_path: Path, select_name: str) -> None:
    page = _client(seeded, tmp_path).get("/search").text
    assert _select_values(page, select_name) == _expected_options()[select_name]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "event:upcoming"}, {"evt_up"}),
        ({"status": "view:active"}, {"vw_cons"}),
        ({"support_strength": "weak"}, {"vw_weak"}),
        ({"conviction": "high"}, {"vw_strong"}),
        ({"node_type": "event", "relation": "ABOUT"}, {"evt_up", "evt_occ"}),
        ({"entity_id": "ent_aapl", "relation": "ABOUT"}, {"evt_up", "vw_weak"}),
    ],
    ids=["status-event", "status-view", "support_strength", "conviction", "relation-any", "relation-entity"],
)
def test_new_ontology_filters_return_exactly_the_matching_items(
    seeded: Path, tmp_path: Path, params: dict[str, str], expected: set[str]
) -> None:
    assert _result_ids(_client(seeded, tmp_path), **params) == expected


def test_group_qualified_subtype_separates_theme_stage_from_view_type(seeded: Path, tmp_path: Path) -> None:
    client = _client(seeded, tmp_path)
    assert _result_ids(client, subtype="theme:consensus") == {"thm_cons"}
    assert _result_ids(client, subtype="view:consensus") == {"vw_cons"}


def test_search_ontology_parses_group_qualified_subtype(seeded: Path) -> None:
    with OntologyDB(seeded, embedding_dim=DIM, read_only=True) as db:

        def ids(**raw: str) -> set[str]:
            res = search_ontology(db, None, "", filters=SearchFilters.from_raw(**raw))
            return {h.node.id for h in res.ranked()}

        assert ids(subtype="theme:consensus") == {"thm_cons"}
        assert ids(subtype="view:rumor") == {"vw_weak"}
        assert ids(subtype="event:news") == {"evt_occ", "evt_rum"}


def test_bare_subtype_and_existing_filters_keep_todays_results(seeded: Path, tmp_path: Path) -> None:
    with OntologyDB(seeded, embedding_dim=DIM, read_only=True) as db:

        def ids(**raw: str) -> set[str]:
            res = search_ontology(db, None, "", filters=SearchFilters.from_raw(**raw))
            return {h.node.id for h in res.ranked()}

        assert ids(subtype="rumor") == {"vw_weak", "evt_rum"}
        assert ids(subtype="rumors") == {"vw_weak", "evt_rum"}
        assert ids(subtype="consensus") == {"vw_cons", "thm_cons"}

    client = _client(seeded, tmp_path)
    assert _result_ids(client, subtype="rumor") == {"vw_weak", "evt_rum"}
    assert _result_ids(client, stance="cautious") == {"vw_weak"}
    assert _result_ids(client, sentiment="negative") == {"evt_occ", "vw_weak"}
    assert _result_ids(client, node_type="event", date_from="2026-09-15", date_to="2026-10-15") == {"evt_occ"}
    assert _result_ids(client, source_file="QCOM/") == {"evt_occ"}
    assert _result_ids(client, q="Rumored", search_mode="keyword") == {"evt_rum"}


def test_search_without_registry_hides_only_the_relation_filter(seeded: Path, tmp_path: Path) -> None:
    client = _client(seeded, tmp_path, registry_path=tmp_path / "missing_registry.json")
    r = client.get("/search")
    assert r.status_code == 200
    assert _select_values(r.text, "relation") is None
    expected = _expected_options()
    for name in ("node_type", "subtype", "status", "sentiment", "stance", "support_strength", "conviction"):
        assert _select_values(r.text, name) == expected[name], name
    assert _result_ids(client, support_strength="weak") == {"vw_weak"}
