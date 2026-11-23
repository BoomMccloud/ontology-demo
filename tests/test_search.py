"""Offline unit tests for the shared ontology search (`stock_ontology.search`)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.llm import AgentTurn, ToolCall
from stock_ontology.models import ConsensusSynthesis, Edge, ExtractionResult, Node
from stock_ontology.search import (
    SearchFilters,
    grep_notes,
    parse_period,
    scan_notes,
    search_ontology,
    split_qualified_value,
)
from stock_ontology.web import create_app

DIM = 16


def _unit_vec(idx: int) -> list[float]:
    vec = [0.0] * DIM
    vec[idx % DIM] = 1.0
    return vec


class NearestLLM:
    """Embeds every query at one fixed vector, so the test picks the nearest node."""

    def __init__(self, idx: int = 0, *, fail: bool = False) -> None:
        self.idx = idx
        self.fail = fail
        self.agent_turns: list[AgentTurn] = []
        self.tool_responses: list[dict[str, Any]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding provider unavailable")
        return [_unit_vec(self.idx) for _ in texts]

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    def generate_agent_reply(self, *, messages: list[dict[str, Any]], **kwargs: Any) -> AgentTurn:
        last = messages[-1]
        if last["role"] == "tool":
            self.tool_responses.append(last["responses"][0]["response"])
        return self.agent_turns.pop(0)


def _seed(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU platform leader.",
            aliases=["NVDA", "Green Team"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        tsmc = Node(
            id="ent_tsmc",
            node_type="entity",
            name="TSMC",
            summary="Foundry.",
            facets={"entity_type": "company", "ticker": "TSM"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power constraints.",
            facets={"stage": "accelerating"},
        )
        q3 = Node(
            id="evt_q3",
            node_type="event",
            name="Q3 Data Center Beat",
            summary="Revenue beat guidance.",
            facets={
                "event_type": "earnings",
                "event_date": "2026-08-20",
                "source": {"file_path": "NVDA/2026-08-20_q3.md"},
            },
            source_doc_id="doc_q3",
        )
        q1 = Node(
            id="evt_q1",
            node_type="event",
            name="Q1 Supply Update",
            summary="Supply improved.",
            facets={"event_type": "news", "event_date": "2026-02-10"},
            source_doc_id="doc_q1",
        )
        far = Node(
            id="vw_far",
            node_type="view",
            name="Unrelated Retail View",
            summary="Retail margins.",
            facets={"view_type": "analyst_report", "as_of": "2026-01-01"},
        )
        db.upsert_node(nvda, embedding=_unit_vec(1))
        db.upsert_node(tsmc, embedding=_unit_vec(2))
        db.upsert_node(theme, embedding=_unit_vec(3))
        db.upsert_node(q3, embedding=_unit_vec(4))
        db.upsert_node(q1, embedding=_unit_vec(5))
        db.upsert_node(far, embedding=_unit_vec(0))
        db.upsert_edge(Edge(id="e1", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"}))
        # Raw alias of a registry relation, stored the way older ingests left it.
        db.upsert_edge(Edge(id="e2", from_id="ent_tsmc", to_id="ent_nvda", relation="supplies to", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e3", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e4", from_id="evt_q1", to_id="ent_nvda", relation="ABOUT", facets={"basis": "extracted"}))


def _run(tmp_path: Path, query: str, **kwargs: Any) -> Any:
    db_path = tmp_path / "s.db"
    if not db_path.exists():
        _seed(db_path)
    llm = kwargs.pop("llm", NearestLLM(0))
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        return search_ontology(db, llm, query, today=date(2026, 11, 22), **kwargs)


def test_name_match_beats_nearer_vector_hit_and_alias_is_labeled(tmp_path: Path) -> None:
    res = _run(tmp_path, "nvidia")
    assert res.best_match is not None
    assert (res.best_match.node.id, res.best_match.match_reason) == ("ent_nvda", "name")
    ranked = [h.node.id for h in res.ranked()]
    assert ranked[0] == "ent_nvda"
    far = next(h for h in res.ranked() if h.node.id == "vw_far")
    assert far.match_reason == "semantic"
    assert ranked.index("ent_nvda") < ranked.index("vw_far")

    alias = _run(tmp_path, "green team")
    assert alias.best_match is not None
    assert (alias.best_match.node.id, alias.best_match.match_reason) == ("ent_nvda", "alias")


def test_expansion_uses_canonical_relations_and_returns_no_edges(tmp_path: Path) -> None:
    res = _run(tmp_path, "nvidia")
    related = {h.node.id: h for h in res.related}
    assert set(related) == {"thm_power", "ent_tsmc"}
    assert all(h.match_reason == "relationship" for h in related.values())
    # "supplies to" is a registry inverse alias of BUY, so NVIDIA buys from TSMC.
    assert related["ent_tsmc"].via_relation == "BUY"
    assert related["ent_tsmc"].via_node_id == "ent_nvda"
    signals = {h.node.id: h.match_reason for h in res.signals}
    assert signals["evt_q3"] == "relationship"
    assert signals["evt_q1"] == "relationship"
    assert not {"e1", "e2", "e3", "e4"} & {h.node.id for h in res.ranked()}


def test_semantic_failure_and_keyword_mode_keep_name_results(tmp_path: Path) -> None:
    down = _run(tmp_path, "nvidia", llm=NearestLLM(fail=True))
    assert down.best_match is not None and down.best_match.node.id == "ent_nvda"
    assert all(h.match_reason != "semantic" for h in down.ranked())

    kw = _run(tmp_path, "nvidia", filters=SearchFilters.from_raw(search_mode="keyword"))
    assert all(h.match_reason != "semantic" for h in kw.ranked())


def test_filters_narrow_results_but_expansion_still_seeds_from_entity(tmp_path: Path) -> None:
    res = _run(tmp_path, "nvidia", filters=SearchFilters.from_raw(node_type="event"))
    assert res.best_match is None
    assert {h.node.id for h in res.ranked()} == {"evt_q3", "evt_q1"}

    dated = _run(tmp_path, "nvidia", filters=SearchFilters.from_raw(date_from="2026-06-01"))
    assert "evt_q1" not in {h.node.id for h in dated.ranked()}


def test_period_in_word_narrows_dated_items_and_recency_is_bounded(tmp_path: Path) -> None:
    period, rest = parse_period("nvidia Q3 2026")
    assert period is not None and rest == "nvidia"
    assert period.contains("2026-08-20") is True
    assert period.contains("2026-02-10") is False
    assert period.contains("") is None
    assert parse_period("FY2025 capex")[0].contains("2025-06-01") is True  # type: ignore[union-attr]
    assert parse_period("march 2026")[0].contains("2026-03-31") is True  # type: ignore[union-attr]
    assert parse_period("nvidia") == (None, "nvidia")

    res = _run(tmp_path, "nvidia q3 2026")
    assert res.best_match is not None and res.best_match.node.id == "ent_nvda"
    ids = {h.node.id for h in res.ranked()}
    assert "evt_q3" in ids and "evt_q1" not in ids

    plain = _run(tmp_path, "nvidia")
    by_id = {h.node.id: h for h in plain.ranked()}
    # Recency nudges the newer event ahead, but never past a stronger match reason.
    assert by_id["evt_q3"].score > by_id["evt_q1"].score
    assert by_id["evt_q3"].score - by_id["evt_q1"].score <= 0.1
    assert by_id["ent_tsmc"].score > by_id["vw_far"].score


def _notes(root: Path) -> Path:
    data = root / "data"
    (data / "NVDA").mkdir(parents=True)
    (data / "NVDA" / "2026-08-20_q3.md").write_text("# Q3\n\nNVIDIA beat.\n", encoding="utf-8")
    (data / "Notes").mkdir()
    (data / "Notes" / "regex.txt").write_text("plain a line\nliteral a.* here\n", encoding="utf-8")
    (data / "Notes" / "many.md").write_text("nvidia\n" * 20, encoding="utf-8")
    (data / "Notes" / "other.md").write_text("Nvidia channel check.\n", encoding="utf-8")
    (data / ".hidden").mkdir()
    (data / ".hidden" / "x.md").write_text("nvidia hidden\n", encoding="utf-8")
    (data / ".dot.md").write_text("nvidia dot\n", encoding="utf-8")
    (data / "Notes" / "deck.pdf").write_text("nvidia pdf\n", encoding="utf-8")
    outside = root / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("nvidia outside\n", encoding="utf-8")
    (data / "link.md").symlink_to(outside / "secret.md")
    (data / "linkdir").symlink_to(outside, target_is_directory=True)
    return data


def test_grep_is_literal_case_insensitive_capped_and_stays_in_data_dir(tmp_path: Path) -> None:
    data = _notes(tmp_path)

    literal = grep_notes(data, ["A.*"])
    assert [(p.file, p.line) for p in literal] == [("Notes/regex.txt", 2)]

    hits = grep_notes(data, ["nvidia"], per_file=3, total=50)
    files = [p.file for p in hits]
    assert files.count("Notes/many.md") == 3
    assert "Notes/other.md" in files and "NVDA/2026-08-20_q3.md" in files
    assert all(not f.startswith((".", "link")) and f.endswith((".md", ".txt")) for f in files)
    assert not any("outside" in p.text or "hidden" in p.text or "pdf" in p.text for p in hits)

    assert len(grep_notes(data, ["nvidia"], per_file=3, total=4)) == 4
    assert grep_notes(data, ["../outside/secret"]) == []
    assert grep_notes(tmp_path / "missing", ["nvidia"]) == []


def test_note_scan_stops_at_its_file_and_byte_budget(tmp_path: Path) -> None:
    data = _notes(tmp_path)

    full = scan_notes(data, ["nvidia"], total=50)
    assert not full.truncated
    assert len({p.file for p in full.passages}) == 3

    by_files = scan_notes(data, ["nvidia"], total=50, max_files=1)
    assert by_files.truncated
    assert len({p.file for p in by_files.passages}) <= 1

    by_bytes = scan_notes(data, ["nvidia"], total=50, max_bytes=10)
    assert by_bytes.truncated
    assert by_bytes.passages == []


def test_item_and_passage_from_one_file_appear_once_with_line(tmp_path: Path) -> None:
    data = _notes(tmp_path)
    res = _run(tmp_path, "nvidia", data_dir=data)
    q3 = next(h for h in res.signals if h.node.id == "evt_q3")
    assert q3.note_line == 3
    assert all(p.file != "NVDA/2026-08-20_q3.md" for p in res.passages)
    assert any(p.file == "Notes/other.md" for p in res.passages)

    # Structured node filters leave note text out; a source filter narrows note files.
    typed = _run(tmp_path, "nvidia", data_dir=data, filters=SearchFilters.from_raw(node_type="event"))
    assert typed.passages == []
    by_src = _run(tmp_path, "nvidia", data_dir=data, filters=SearchFilters.from_raw(source_file="other"))
    assert {p.file for p in by_src.passages} == {"Notes/other.md"}


def test_chat_endpoint_gives_the_agent_note_search(tmp_path: Path) -> None:
    db_path = tmp_path / "s.db"
    _seed(db_path)
    data = _notes(tmp_path)
    llm = NearestLLM(0)
    llm.agent_turns = [
        AgentTurn(tool_calls=[ToolCall(name="search_notes", args={"query": "channel check"})]),
        AgentTurn(text="done"),
    ]
    client = TestClient(create_app(Settings(db_path=db_path, embedding_dim=DIM, data_dir=data), llm=llm))

    r = client.post("/api/chat", json={"message": "channel check", "page_context": "Search: channel check"})
    assert r.status_code == 200
    assert r.json()["tools_used"] == ["search_notes"]
    passages = llm.tool_responses[0]["passages"]
    assert [(p["file"], p["line"]) for p in passages] == [("Notes/other.md", 1)]


def test_from_raw_parses_group_qualified_subtype_and_status_values() -> None:
    assert split_qualified_value("theme:consensus") == ("theme", "consensus")
    assert split_qualified_value(" View : rumor ") == ("view", "rumor")
    assert split_qualified_value("rumors") == (None, "rumors")
    assert split_qualified_value("foo:bar") == (None, "foo:bar")
    assert split_qualified_value("event:") == (None, "event:")
    assert split_qualified_value("") == (None, None)

    qualified = SearchFilters.from_raw(subtype="view:Rumors", status="event:UPCOMING")
    assert (qualified.subtype_node_type, qualified.subtype) == ("view", "rumor")
    assert (qualified.status_node_type, qualified.status) == ("event", "upcoming")
    assert qualified.node_type is None

    bare = SearchFilters.from_raw(subtype="rumors", status="active")
    assert (bare.subtype_node_type, bare.subtype) == (None, "rumor")
    assert (bare.status_node_type, bare.status) == (None, "active")

    unknown = SearchFilters.from_raw(subtype="foo:bar")
    assert (unknown.subtype_node_type, unknown.subtype) == (None, "foo:bar")

    new = SearchFilters.from_raw(support_strength=" Weak ", conviction="HIGH", relation="about")
    assert (new.support_strength, new.conviction, new.relation) == ("weak", "high", "ABOUT")
    assert new.narrows_nodes

    # The agent's search_nodes builds filters with node_type only; the new fields stay unset.
    agent = SearchFilters.from_raw(node_type="event")
    assert agent == SearchFilters(node_type="event")


def test_get_relation_node_ids_keeps_every_relation_per_neighbor(tmp_path: Path) -> None:
    db_path = tmp_path / "rel.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        for idx, (nid, nt) in enumerate(
            [("ent_a", "entity"), ("ent_b", "entity"), ("evt_1", "event"), ("evt_2", "event")]
        ):
            subtype = {"entity_type": "company"} if nt == "entity" else {"event_type": "news"}
            db.upsert_node(Node(id=nid, node_type=nt, name=nid, summary="", facets=subtype), embedding=_unit_vec(idx))
        # evt_1 has two edges to ent_a; the best-edge collapse in get_entity_connected_nodes keeps one.
        db.upsert_edge(Edge(id="e1", from_id="evt_1", to_id="ent_a", relation="ABOUT", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e2", from_id="evt_1", to_id="ent_a", relation="RELATES_TO", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e3", from_id="evt_2", to_id="ent_b", relation="ABOUT", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="e4", from_id="ent_a", to_id="evt_2", relation="RELATES_TO", facets={"basis": "extracted"}))

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.get_relation_node_ids("ABOUT") == {"evt_1", "evt_2", "ent_a", "ent_b"}
        assert db.get_relation_node_ids("ABOUT", entity_id="ent_a") == {"evt_1"}
        assert db.get_relation_node_ids("RELATES_TO", entity_id="ent_a") == {"evt_1", "evt_2"}
        assert db.get_relation_node_ids("ABOUT", entity_id="ent_b") == {"evt_2"}
        assert db.get_relation_node_ids("MISSING") == set()
