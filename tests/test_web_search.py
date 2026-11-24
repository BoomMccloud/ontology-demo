"""Offline tests for the Search module: filters, result sections, note links, and degraded search."""

from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from web_support import (
    DIM,
    SEARCH_EVENT_FILE,
    SEARCH_NOTE_FILE,
    FakeWebLLM,
    search_client,
    unit_vec,
)

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import SUPPORTED_LANGUAGE_CODES, translate
from stock_ontology.llm import AgentTurn
from stock_ontology.models import Edge, Node
from stock_ontology.web import create_app


def test_web_nav_and_advanced_search_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "web_adv_search.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple",
            summary="Consumer devices.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        qcom = Node(
            id="ent_qcom",
            node_type="entity",
            name="Qualcomm",
            summary="Mobile modem supplier.",
            aliases=["QCOM"],
            facets={"entity_type": "company", "ticker": "QCOM"},
        )
        evt_modem = Node(
            id="evt_modem",
            node_type="event",
            name="In-House Modem Launch",
            summary="Apple switches to internal modem.",
            facets={
                "event_type": "news",
                "event_date": "2026-11-18",
                "status": "occurred",
                "sentiment": "mixed",
                "source": {"file_path": "AAPL/2026-11-18_modem.md"},
            },
            source_doc_id="doc_1",
        )
        vw_rumor = Node(
            id="vw_rumor",
            node_type="view",
            name="Modem Loss Rumor",
            summary="Channel rumor warns on QCOM share loss.",
            facets={
                "view_type": "rumor",
                "stance": "cautious",
                "sentiment": "negative",
                "support_strength": "weak",
                "conviction": "medium",
                "as_of": "2026-11-19",
                "source": {"file_path": "QCOM/2026-11-19_rumor.md"},
            },
            source_doc_id="doc_2",
        )
        evt_legacy = Node(
            id="evt_legacy",
            node_type="event",
            name="Legacy Product Fact",
            summary="Earlier unannotated observation.",
            facets={
                "event_type": "fact",
                "event_date": "2026-09-01",
                "status": "occurred",
                "source": {"file_path": "AAPL/2026-09-01_old.md"},
            },
            source_doc_id="doc_0",
        )
        for idx, n in enumerate([aapl, qcom, evt_modem, vw_rumor, evt_legacy]):
            db.upsert_node(n, embedding=unit_vec(idx))
        db.upsert_edge(
            Edge(
                id="ed_aapl",
                from_id="evt_modem",
                to_id="ent_aapl",
                relation="ABOUT",
                facets={"sentiment": "positive", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_qcom",
                from_id="evt_modem",
                to_id="ent_qcom",
                relation="ABOUT",
                facets={"sentiment": "negative", "basis": "extracted"},
                source_doc_id="doc_1",
            )
        )
        db.upsert_edge(
            Edge(id="ed_vw", from_id="vw_rumor", to_id="ent_qcom", relation="ABOUT", source_doc_id="doc_2", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed_leg", from_id="evt_legacy", to_id="ent_aapl", relation="ABOUT", source_doc_id="doc_0", facets={"basis": "extracted"})
        )

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # Left rail navigation on 1997 portal + minimal / (no 8-field advanced-search-panel on /).
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert 'aria-current="page" data-nav="overview">&rsaquo; Overview<' in r_home.text
    assert ">Companies<" in r_home.text
    assert ">Themes<" in r_home.text
    assert ">Notes<" in r_home.text
    assert ">Ontology<" in r_home.text
    assert ">Search<" in r_home.text
    assert "advanced-search-panel" not in r_home.text
    assert 'id="rail-q"' in r_home.text

    # /search expands the integrated Advanced Search panel
    r_search_blank = client.get("/search")
    assert r_search_blank.status_code == 200
    assert ">Overview<" in r_search_blank.text
    assert '<details class="advanced-search-panel" open>' in r_search_blank.text

    # Filter-only searches (empty q)
    r_neg = client.get("/search", params={"sentiment": "negative"})
    assert r_neg.status_code == 200
    assert "Modem Loss Rumor" in r_neg.text
    assert "Legacy Product Fact" not in r_neg.text

    # The write boundary stored the `cautious` alias as its member, `bearish`.
    r_rumor = client.get("/search", params={"node_type": "view", "subtype": "rumor", "stance": "bearish"})
    assert r_rumor.status_code == 200
    assert "Modem Loss Rumor" in r_rumor.text
    assert "In-House Modem Launch" not in r_rumor.text

    # Entity-specific sentiment edge override filtering
    r_aapl_pos = client.get("/search", params={"entity_id": "ent_aapl", "sentiment": "positive"})
    assert r_aapl_pos.status_code == 200
    assert "In-House Modem Launch" in r_aapl_pos.text

    r_qcom_neg = client.get("/search", params={"entity_id": "ent_qcom", "sentiment": "negative"})
    assert r_qcom_neg.status_code == 200
    assert "In-House Modem Launch" in r_qcom_neg.text
    assert "Modem Loss Rumor" in r_qcom_neg.text

    # Date range + source file + keyword-only mode
    r_date = client.get(
        "/search",
        params={"q": "Legacy", "date_from": "2026-08-01", "date_to": "2026-09-30", "source_file": "AAPL/", "search_mode": "keyword"},
    )
    assert r_date.status_code == 200
    assert "Legacy Product Fact" in r_date.text
    assert "In-House Modem Launch" not in r_date.text
    assert "keyword" in r_date.text


_SEARCH_ATTRS = ("data-result-id", "data-note-file", "data-agent-", "data-best-match")


def _search_tags(page: str) -> list[dict[str, str]]:
    """Attributes of start tags carrying search-page data attributes, in document order."""
    tags: list[dict[str, str]] = []
    for match in re.finditer(r"<[a-zA-Z][^>]*>", page):
        raw = match.group(0)
        if not any(marker in raw for marker in _SEARCH_ATTRS):
            continue
        pairs = re.findall(r'([\w:-]+)(?:\s*=\s*"([^"]*)")?', raw[1:-1])[1:]
        tags.append({name: html.unescape(value) for name, value in pairs})
    return tags


def test_web_search_entity_first_card_sections_notes_and_agent_column(tmp_path: Path) -> None:
    client, _, _ = search_client(tmp_path, FakeWebLLM())

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    tags = _search_tags(r.text)

    # Best-match card: the entity whose name matches, labeled "name".
    best = [t for t in tags if "data-best-match" in t]
    assert len(best) == 1, "search page has no single best-match card"
    assert best[0].get("data-result-id") == "ent_nvda"
    assert best[0].get("data-match-reason") == "name"

    # The nearer vector hit is listed below the entity and says it matched semantically.
    items = [t for t in tags if "data-result-id" in t]
    order = [t["data-result-id"] for t in items]
    reason = {t["data-result-id"]: t.get("data-match-reason") for t in reversed(items)}
    assert "vw_cons_aapl" in order
    assert order.index("ent_nvda") < order.index("vw_cons_aapl")
    assert reason["vw_cons_aapl"] == "semantic"

    # Expansion from the matched entity through its edges.
    assert reason.get("thm_power") == "relationship"
    assert "evt_nvda_q3" in order

    # Grepped note passage with file and line; the event's own source line is not listed again.
    passages = [t for t in tags if "data-note-file" in t]
    note = [t for t in passages if t["data-note-file"] == SEARCH_NOTE_FILE]
    assert len(note) == 1
    assert note[0].get("data-note-line") == "3"
    assert note[0].get("data-match-reason") == "note"
    assert "NVIDIA lead times shortened." in r.text
    assert all(t["data-note-file"] != SEARCH_EVENT_FILE for t in passages)

    # Agent note for this search, carried into the shared Clippy dock (no pinned column).
    columns = [t for t in tags if "data-agent-column" in t]
    assert len(columns) == 1
    assert columns[0].get("data-agent-query") == "nvidia"
    assert not any("data-agent-detach" in t for t in tags)
    assert "/static/clippy.js" in r.text
    assert "/api/chat" in client.get("/static/clippy.js").text

    # No search word, no agent run.
    r_empty = client.get("/search")
    assert r_empty.status_code == 200
    assert all(not t.get("data-agent-query") for t in _search_tags(r_empty.text))


def test_web_search_reads_only_data_dir_notes_and_never_writes_db(tmp_path: Path) -> None:

    client, db_path, data_dir = search_client(tmp_path, FakeWebLLM())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("NVIDIA OUTSIDE-MARKER-1\n", encoding="utf-8")
    (data_dir / "linked.md").symlink_to(outside / "secret.md")
    (data_dir / ".hidden").mkdir()
    (data_dir / ".hidden" / "x.md").write_text("NVIDIA HIDDEN-DIR-MARKER-2\n", encoding="utf-8")
    (data_dir / ".dotnote.md").write_text("NVIDIA HIDDEN-FILE-MARKER-3\n", encoding="utf-8")
    (data_dir / "Notes" / "deck.pdf").write_text("NVIDIA UNSUPPORTED-MARKER-4\n", encoding="utf-8")

    def db_digest() -> tuple[str, int]:
        return hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns

    before = db_digest()

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    # Positive control: an in-scope note is grepped, so the exclusions below are meaningful.
    assert any(t.get("data-note-file") == SEARCH_NOTE_FILE for t in _search_tags(r.text))

    markers = ("OUTSIDE-MARKER-1", "HIDDEN-DIR-MARKER-2", "HIDDEN-FILE-MARKER-3", "UNSUPPORTED-MARKER-4")
    for word in ("nvidia", "../outside/secret", "NVIDIA OUTSIDE", ".hidden", "*.md", "MARKER"):
        page = client.get("/search", params={"q": word})
        assert page.status_code == 200
        for marker in markers:
            assert marker not in page.text, f"{marker} leaked for search word {word!r}"

    assert db_digest() == before


class EmbeddingAndAgentDownWebLLM(FakeWebLLM):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider unavailable")

    def generate_agent_reply(self, **kwargs: Any) -> AgentTurn:
        raise RuntimeError("agent provider unavailable")


def test_web_search_functional_results_survive_embedding_and_agent_failure(tmp_path: Path) -> None:
    client, _, _ = search_client(tmp_path, EmbeddingAndAgentDownWebLLM())

    r = client.get("/search", params={"q": "nvidia"})
    assert r.status_code == 200
    tags = _search_tags(r.text)
    assert [t.get("data-result-id") for t in tags if "data-best-match" in t] == ["ent_nvda"]
    assert any(t.get("data-note-file") == SEARCH_NOTE_FILE for t in tags)
    assert [t.get("data-agent-query") for t in tags if "data-agent-column" in t] == ["nvidia"]

    # The agent run the column starts fails as a JSON error the column can show.
    r_chat = client.post("/api/chat", json={"message": "nvidia", "page_context": "Search: nvidia"})
    assert r_chat.status_code == 500
    assert r_chat.json()["error"]
    assert r_chat.json()["session_id"]


def test_web_search_note_links_jump_to_the_matching_line(tmp_path: Path) -> None:
    client, _, _ = search_client(tmp_path, FakeWebLLM())

    page = client.get("/search", params={"q": "nvidia"}).text
    # A grepped passage, and the event folded onto its own note, both link to the raw note at that line.
    # Each link also carries the search it came from, so the reader can return to the results.
    back = "&amp;back=/search%3Fq%3Dnvidia"
    assert f"/catalog?file={SEARCH_NOTE_FILE}{back}&amp;format=raw#L3" in page
    assert f"/catalog?file={SEARCH_EVENT_FILE}{back}&amp;format=raw#L3" in page

    raw = client.get("/catalog", params={"file": SEARCH_NOTE_FILE, "format": "raw"}).text
    assert '<span id="L3" class="note-line">Channel check: NVIDIA lead times shortened.' in raw
    assert '<span id="L1" class="note-line"># Channel check' in raw

    from_search = client.get(
        "/catalog", params={"file": SEARCH_NOTE_FILE, "format": "raw", "back": "/search?q=nvidia"}
    ).text
    assert 'href="/search?q=nvidia" class="retro-link-btn">← Back to search results</a>' in from_search
    assert '<span id="L3" class="note-line">' in from_search


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGE_CODES)
def test_search_new_filter_chips_and_labels_in_every_locale(tmp_path: Path, lang: str) -> None:
    db_path = tmp_path / "chips.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_node(
            Node(id="ent_a", node_type="entity", name="Apple", summary="", facets={"entity_type": "company"}),
            embedding=unit_vec(0),
        )
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))
    r = client.get(
        "/search",
        params={
            "lang": lang,
            "status": "event:upcoming",
            "support_strength": "weak",
            "conviction": "high",
            "relation": "ABOUT",
        },
    )
    assert r.status_code == 200
    page = html.unescape(r.text)
    pills = re.findall(r'<span class="filter-pill mono">([^<]*)</span>', page)
    assert len(pills) == 4
    for key in ("filter_status", "filter_support_strength", "filter_conviction", "filter_relation"):
        label = translate(f"search.{key}", lang=lang)
        assert label != f"search.{key}"
        assert any(p.startswith(f"{label}: ") for p in pills), key
    for key in (
        "status_label",
        "any_status",
        "optgroup_event_statuses",
        "optgroup_view_statuses",
        "support_strength_label",
        "any_support_strength",
        "conviction_label",
        "any_conviction",
        "relation_label",
        "any_relation",
    ):
        label = translate(f"search.{key}", lang=lang)
        assert label != f"search.{key}"
        assert label in page, key
