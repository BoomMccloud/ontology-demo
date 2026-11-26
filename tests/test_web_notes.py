"""Offline tests for the Notes module: catalog, note reader, pasted notes, and note corrections."""

from __future__ import annotations

import dataclasses
import hashlib
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from web_support import (
    DIM,
    RAW_FACET_TOKEN,
    TEMPLATES_DIR,
    FakeWebLLM,
    db_digest,
    note_tree,
    search_client,
    seed_web_db,
    unit_vec,
)

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import translate
from stock_ontology.models import Edge, ExtractionResult, Node
from stock_ontology.pipeline import IngestionPipeline
from stock_ontology.registry import create_minimal_registry, save_registry
from stock_ontology.web import create_app


def test_web_catalog_screen_by_company_and_person_and_safety(tmp_path: Path) -> None:
    db_path = tmp_path / "web_catalog.db"
    seed_web_db(db_path)

    # Add a corporate CEO (must be excluded from By Author) and a research analyst
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        ceo = Node(
            id="ent_jensen_ceo",
            node_type="entity",
            name="Jensen Huang",
            summary="CEO of NVIDIA.",
            facets={"entity_type": "person", "role": "CEO", "organization": "NVIDIA"},
        )
        analyst = Node(
            id="ent_stacy_analyst",
            node_type="entity",
            name="Stacy Rasgon",
            summary="Semiconductor analyst.",
            facets={"entity_type": "person", "role": "Analyst", "organization": "Bernstein"},
        )
        db.upsert_node(ceo, embedding=unit_vec(8))
        db.upsert_node(analyst, embedding=unit_vec(9))
        db.upsert_edge(
            Edge(
                id="ed_ceo_authored",
                from_id="evt_q3",
                to_id="ent_jensen_ceo",
                relation="AUTHORED_BY",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )
        db.upsert_edge(
            Edge(
                id="ed_analyst_authored",
                from_id="vw_analyst",
                to_id="ent_stacy_analyst",
                relation="AUTHORED_BY",
                source_doc_id="doc_1", facets={"basis": "extracted"},
            )
        )

    data_dir = tmp_path / "data"
    nvda_dir = data_dir / "NVDA"
    tsmc_dir = data_dir / "TSMC"
    nvda_dir.mkdir(parents=True)
    tsmc_dir.mkdir(parents=True)

    nvda_note = (
        "# NVDA Q3 Preview\n\n"
        "Blackwell rack ramp <script>alert(1)</script> update.\n\n"
        "| Metric | Value |\n"
        "| :--- | :--- |\n"
        "| Growth | Strong<br>Sequential |\n\n"
        "- Point one with **bold**\n"
    )
    (nvda_dir / "2026-10-15_q3.md").write_text(nvda_note, encoding="utf-8")
    (tsmc_dir / "2026-11-05_note.md").write_text(
        "# TSMC CoWoS Note\n\n**Author:** Internal Semi Desk\n\nField call with Kenji Sato on CoWoS packaging capacity.\n",
        encoding="utf-8",
    )
    # Files that must NEVER be served
    (data_dir / ".hidden.md").write_text("secret hidden", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside data dir", encoding="utf-8")

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # 1. Default Catalog view (Option 1 Company root: single-pane, no 2nd sidebar, no file duplication)
    r_cat = client.get("/catalog")
    assert r_cat.status_code == 200
    assert "Research Notes" in r_cat.text
    assert "NVIDIA" in r_cat.text
    assert "TSMC" in r_cat.text
    assert "By Company (2)" in r_cat.text
    assert "By Author (3)" in r_cat.text
    assert "All Notes (2)" in r_cat.text
    assert "NVDA Q3 Preview" not in r_cat.text
    assert "TSMC CoWoS Note" not in r_cat.text
    assert "portal-frame-wide" not in r_cat.text
    assert "catalog-explorer" not in r_cat.text
    assert "dir-tree" not in r_cat.text
    assert "[DIR]" not in r_cat.text
    assert "[UP]" not in r_cat.text
    assert "Index:" in r_cat.text
    assert "data/NVDA/" not in r_cat.text
    assert "INGESTED" not in r_cat.text
    assert "synced with DB" not in r_cat.text
    assert "ev /" not in r_cat.text

    # 1a. Company quick-filter Index bar
    r_co_alpha = client.get("/catalog", params={"view": "company", "alpha": "N"})
    assert r_co_alpha.status_code == 200
    assert "NVIDIA" in r_co_alpha.text
    assert "TSMC" not in r_co_alpha.text

    # 1b. Company directory drill-down (top breadcrumb, no ../ row, only that folder's notes)
    r_nvda_dir = client.get("/catalog", params={"view": "company", "dir": "NVDA"})
    assert r_nvda_dir.status_code == 200
    assert "catalog-path-bar" in r_nvda_dir.text
    assert "../" not in r_nvda_dir.text
    assert "[UP]" not in r_nvda_dir.text
    assert "NVDA Q3 Preview" in r_nvda_dir.text
    assert "TSMC CoWoS Note" not in r_nvda_dir.text

    # 2. Catalog By Author view (includes analysts & explicit note authors, excludes CEOs)
    r_author = client.get("/catalog", params={"view": "author"})
    assert r_author.status_code == 200
    assert "[DIR]" not in r_author.text
    assert "Index:" in r_author.text
    assert "Kenji Sato" in r_author.text
    assert "Stacy Rasgon" in r_author.text
    assert "Internal Semi Desk" in r_author.text
    assert "Jensen Huang" not in r_author.text

    # 2a. Author quick-filter Index bar
    r_auth_alpha = client.get("/catalog", params={"view": "author", "alpha": "S"})
    assert r_auth_alpha.status_code == 200
    assert "Stacy Rasgon" in r_auth_alpha.text
    assert "Kenji Sato" not in r_auth_alpha.text

    # Backward-compatible ?view=person alias
    r_person = client.get("/catalog", params={"view": "person"})
    assert r_person.status_code == 200
    assert "Stacy Rasgon" in r_person.text
    assert "Jensen Huang" not in r_person.text

    # Drill-down into an author shows top breadcrumb (no ../ row) and both authored and mentioned notes
    r_kenji = client.get("/catalog", params={"view": "author", "author": "Kenji Sato"})
    assert r_kenji.status_code == 200
    assert "catalog-path-bar" in r_kenji.text
    assert "../" not in r_kenji.text
    assert "[UP]" not in r_kenji.text
    assert "NVDA Q3 Preview" in r_kenji.text
    assert "TSMC CoWoS Note" in r_kenji.text
    # How a note was matched to its author is internal; the page doesn't show it.
    assert "badge-reason" not in r_kenji.text

    # 2b. All Notes flat index + quick-filter Index bar
    r_all = client.get("/catalog", params={"view": "all"})
    assert r_all.status_code == 200
    assert "Index:" in r_all.text
    assert "NVDA Q3 Preview" in r_all.text
    assert "TSMC CoWoS Note" in r_all.text

    r_all_alpha = client.get("/catalog", params={"view": "all", "alpha": "T"})
    assert r_all_alpha.status_code == 200
    assert "TSMC CoWoS Note" in r_all_alpha.text
    assert "NVDA Q3 Preview" not in r_all_alpha.text

    # 3. Safe Markdown rendered note view (XSS escaped, full-width reading pane)
    r_note = client.get("/catalog", params={"file": "NVDA/2026-10-15_q3.md"})
    assert r_note.status_code == 200
    assert "<h1>NVDA Q3 Preview</h1>" in r_note.text
    assert '<table class="catalog-table note-table">' in r_note.text
    assert "Strong<br>Sequential" in r_note.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r_note.text
    assert "<script>alert(1)</script>" not in r_note.text
    assert "Raw Source" not in r_note.text
    assert "Jensen Huang" not in r_note.text

    # 4. Raw source format toggle
    r_raw = client.get("/catalog", params={"file": "NVDA/2026-10-15_q3.md", "format": "raw"})
    assert r_raw.status_code == 200
    assert '<pre class="note-raw-pre">' in r_raw.text
    assert "# NVDA Q3 Preview" in r_raw.text

    # 5. Path traversal and hidden file blocks -> 404
    for bad_path in ("../secret.txt", "/etc/passwd", ".hidden.md", "missing.md", "NVDA\\2026-10-15_q3.md"):
        assert client.get("/catalog", params={"file": bad_path}).status_code == 404

    # 6. Graceful empty state when data_dir does not exist
    missing_settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path / "no_such_dir")
    missing_client = TestClient(create_app(missing_settings, llm=FakeWebLLM()))
    r_empty = missing_client.get("/catalog")
    assert r_empty.status_code == 200
    assert "No Research Notes Found" in r_empty.text
    assert "stock-ontology ingest" not in r_empty.text


# ---------------------------------------------------------------------------
# Presentation-model contract for the catalog note page (proposal `event-view-separation`)
# ---------------------------------------------------------------------------

NOTE_READER_TEMPLATE = "partials/note_reader.html"


NOTE_READER_NAMES = {"active_note", "t", "t_enum"}


def _non_model_paths(value: Any, path: str) -> list[str]:
    """List every place below `value` that is a raw dict, a list, or a mutable dataclass."""
    found: list[str] = []
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if not type(value).__dataclass_params__.frozen:
            found.append(f"{path} (mutable {type(value).__name__})")
        for field in dataclasses.fields(value):
            found.extend(_non_model_paths(getattr(value, field.name), f"{path}.{field.name}"))
    elif isinstance(value, dict):
        found.append(f"{path} (dict)")
    elif isinstance(value, list):
        found.append(f"{path} (list)")
    elif isinstance(value, tuple):
        for idx, item in enumerate(value):
            found.extend(_non_model_paths(item, f"{path}[{idx}]"))
    return found


def test_note_page_templates_only_see_presentation_models(tmp_path: Path) -> None:
    """The catalog note page renders from a frozen presentation model built by a mapper."""
    import jinja2
    from jinja2 import meta

    from stock_ontology.web.notes.views import build_catalog_context

    db_path = tmp_path / "web.db"
    seed_web_db(db_path)
    data_dir = tmp_path / "data"
    (data_dir / "NVDA").mkdir(parents=True)
    (data_dir / "NVDA" / "2026-10-15_q3.md").write_text(
        "# NVDA Q3 Preview\n\nBlackwell <script>alert(1)</script> ramp.\n\nThird & last.\n", encoding="utf-8"
    )
    (data_dir / "NVDA" / "2026-09-01_old.md").write_text("# NVDA Older Note\n\nOld.\n", encoding="utf-8")
    (data_dir / "NVDA" / "2026-11-01_new.md").write_text("# NVDA Newer Note\n\nNew.\n", encoding="utf-8")
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    client = TestClient(create_app(settings, llm=FakeWebLLM()))
    note_file = "NVDA/2026-10-15_q3.md"

    def reader(params: dict[str, str]) -> str:
        """The note reader section, with whitespace runs squashed so markup layout does not matter."""
        page = client.get("/catalog", params=params)
        assert page.status_code == 200
        assert 'class="portal-jumpbar"' not in page.text
        assert translate("catalog.page_desc", lang="en") not in page.text
        section = page.text.split('<section aria-label="Raw Note Reader">', 1)[1].split("</section>", 1)[0]
        return re.sub(r"\s+>", ">", re.sub(r"[ \t\n]+", " ", section))

    # 1. The rendered note page still shows the note, its chips and its navigation.
    rendered = reader({"file": note_file})
    assert '<h1 class="u-m-0 u-fs-1p55rem"> NVDA Q3 Preview </h1>' in rendered
    assert 'Company: <a href="/entity/ent_nvda"> NVIDIA (NVDA) </a>' in rendered
    assert 'Author: <a href="/entity/ent_kenji">Kenji Sato</a> </span>' in rendered
    # The breadcrumb is the one link to the catalog parent, so the reader adds no Back button.
    assert "note-toolbar" not in rendered
    assert '<div class="note-rendered"><h1>NVDA Q3 Preview</h1>' in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered and "<script>" not in rendered
    assert '&laquo; <a href="/catalog?view=company&amp;dir=NVDA&amp;file=NVDA/2026-11-01_new.md"> NVDA Newer Note </a>' in rendered
    assert '<a href="/catalog?view=company&amp;dir=NVDA&amp;file=NVDA/2026-09-01_old.md"> NVDA Older Note </a> &raquo;' in rendered

    raw = reader({"view": "author", "author": "Kenji Sato", "file": note_file, "format": "raw"})
    assert "note-toolbar" not in raw
    assert '<span id="L3" class="note-line">Blackwell &lt;script&gt;alert(1)&lt;/script&gt; ramp. </span>' in raw
    assert '<span id="L5" class="note-line">Third &amp; last. </span></pre>' in raw
    assert "note-rendered" not in raw
    assert '<span class="source-cite">Start of list</span>' in raw and '<span class="source-cite">End of list</span>' in raw

    all_view = reader({"view": "all", "file": note_file})
    assert "note-toolbar" not in all_view
    assert '<a href="/catalog?view=all&amp;file=NVDA/2026-11-01_new.md">' in all_view

    # 2. The view model hands the note reader one frozen presentation model, with no raw dicts or lists.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        for view, author in (("company", ""), ("author", "Kenji Sato"), ("all", "")):
            ctx = build_catalog_context(db, data_dir, view=view, selected_author=author, selected_file=note_file)
            note = ctx["active_note"]
            assert dataclasses.is_dataclass(note), view
            assert _non_model_paths(note, "active_note") == [], view

    # 3. The note reader is a partial that reads only that model, and catalog.html only includes it.
    catalog_src = (TEMPLATES_DIR / "catalog.html").read_text(encoding="utf-8")
    assert '{% include "' + NOTE_READER_TEMPLATE + '" %}' in catalog_src
    assert re.search(r"active_note\s*[.\[]", catalog_src) is None
    reader_src = (TEMPLATES_DIR / NOTE_READER_TEMPLATE).read_text(encoding="utf-8")
    names = meta.find_undeclared_variables(jinja2.Environment().parse(reader_src))
    assert names <= NOTE_READER_NAMES, sorted(names - NOTE_READER_NAMES)
    assert RAW_FACET_TOKEN.search(reader_src) is None


# --- Paste a note: POST /api/notes {title, content} -> 201 {"file": "_general/<name>.md"} ---

_PASTE_TITLE = "NVDA channel check"


_PASTE_BODY = "# Pasted channel check\n\nPASTE-MARKER-7: CoWoS lead times shortened.\n"


class _PasteIngestLLM(FakeWebLLM):
    """Offline extractor that records what ingestion read for each note."""

    def __init__(self) -> None:
        super().__init__()
        self.extracted: dict[str, str] = {}

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        self.extracted[kwargs["source_meta"]["file_path"]] = kwargs["text"]
        return ExtractionResult()


class _NoteReaderLLM(FakeWebLLM):
    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        source = kwargs["text"]
        if "Extraction fails here" in source:
            raise RuntimeError("Extraction fails here")
        replacement = "Latest source marker" in source
        names = ["Northstar Cloud", "Latest Supplier" if replacement else "Arbor Energy"]
        if kwargs["source_meta"]["file_path"] == "focus.md" and not replacement:
            names.append("Isolated Observer")
        return ExtractionResult.model_validate({
            "entities": [
                {
                    "temp_id": f"e{index}",
                    "name": name,
                    "summary": "",
                    "entity_type": "company",
                    "facets": [{"key": "sector", "value": "Industrial"}],
                }
                for index, name in enumerate(names)
            ],
            "edges": [{"from_ref": "e0", "to_ref": "e1", "relation": "BUY"}],
        })


@dataclasses.dataclass(frozen=True)
class _Outcome:
    status_code: int
    text: str


def _note_action(client: TestClient, settings: Settings, llm: Any, url: str, payload: dict[str, Any]) -> _Outcome:
    """POST a note action. A job reference is applied by one worker run; its outcome maps to a status."""
    response = client.post(url, json=payload)
    assert response.status_code == 202 or response.status_code >= 400, "a note action must return a job reference"
    if response.status_code != 202:
        return _Outcome(response.status_code, response.text)
    job_id = response.json()["job_id"]
    assert job_id, response.text
    from stock_ontology.worker import Worker

    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200, status.text
    job = status.json()
    if job["state"] == "succeeded":
        return _Outcome(200, status.text)
    codes = {"invalid": 422, "conflict": 409, "not_found": 404}
    return _Outcome(codes.get(job.get("error_code") or "", 500), status.text)


def test_note_reader_extraction_workflow(tmp_path: Path) -> None:
    from stock_ontology import cli

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    focus = data_dir / "focus.md"
    focus.write_text("# Source reference\n\nFirst source marker.\n", encoding="utf-8")
    (data_dir / "peer.txt").write_text("Peer source marker.\n", encoding="utf-8")
    db_path = tmp_path / "reader.db"
    registry = create_minimal_registry()
    registry_path = tmp_path / "registry.json"
    save_registry(registry, registry_path)
    buyer_id, wrong_id, existing_id = "ent_northstar", "ent_arbor_energy", "ent_arbor_cooling"
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for entity_id, name in (
            (buyer_id, "Northstar Cloud"),
            (wrong_id, "Arbor Energy"),
            (existing_id, "Arbor Cooling"),
        ):
            db.upsert_node(Node(
                id=entity_id,
                name=name,
                summary="",
                node_type="entity",
                facets={"entity_type": "company", "sector": "Industrial"},
            ))
    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=registry_path, embedding_dim=DIM)
    llm = _NoteReaderLLM()
    client = TestClient(cli._create_library_app(settings, llm=llm))

    def act(url: str, payload: dict[str, Any]) -> _Outcome:
        return _note_action(client, settings, llm, url, payload)

    def read_note(file: str = "focus.md") -> str:
        response = client.get("/catalog", params={"file": file, "format": "raw", "lang": "en"})
        assert response.status_code == 200, response.text
        return response.text

    def process(file: str = "focus.md") -> Any:
        return act("/api/notes/process", {"file": file})

    def relationships(file: str = "focus.md") -> list[dict[str, Any]]:
        with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
            entry = db.get_ingestion_log().get(file)
            if entry is None:
                return []
            return [edge for edge in db.list_edges_with_endpoints() if edge["source_doc_id"] == entry["doc_id"]]

    def entity_id(name: str) -> str:
        with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
            node = db.find_by_name_or_alias(name, node_type="entity")
            assert node is not None, name
            return node.id

    def shows_entity(page: str, node_id: str, name: str) -> bool:
        pattern = rf'<a\b[^>]*href="/entity/{re.escape(node_id)}"[^>]*>\s*(?:<strong>\s*)?{re.escape(name)}'
        return re.search(pattern, page) is not None

    original_sources = note_tree(data_dir)
    reader = read_note()
    assert 'data-note-status="not-processed"' in reader
    assert re.search(r">\s*Process\s*</button>", reader)
    assert reader.index('data-note-status="not-processed"') < reader.index('id="L1"')
    assert "First source marker." in reader
    response = process()
    assert response.status_code == 200, response.text
    assert relationships("peer.txt") == []
    assert 'data-note-status="not-processed"' in read_note("peer.txt")

    reader = read_note()
    assert 'data-note-status="extracted"' in reader
    assert reader.index('data-note-status="extracted"') < reader.index('id="L1"')
    assert shows_entity(reader, entity_id("Isolated Observer"), "Isolated Observer")
    initial, = relationships()
    assert (initial["from_id"], initial["relation"], initial["to_id"]) == (buyer_id, "BUY", wrong_id)

    response = process("peer.txt")
    assert response.status_code == 200, response.text
    peer_edges = relationships("peer.txt")
    assert len(peer_edges) == 1

    response = act("/api/notes/relink", {
        "file": "focus.md", "entity_id": wrong_id, "replacement_id": existing_id,
    })
    assert response.status_code == 200, response.text
    assert shows_entity(read_note(), existing_id, "Arbor Cooling")
    assert not shows_entity(read_note(), wrong_id, "Arbor Energy")
    assert shows_entity(client.get(f"/entity/{buyer_id}").text, existing_id, "Arbor Cooling")
    after_match, = relationships()
    assert (after_match["from_id"], after_match["relation"], after_match["to_id"]) == (buyer_id, "BUY", existing_id)
    assert relationships("peer.txt") == peer_edges

    response = act("/api/notes/relink", {
        "file": "focus.md",
        "entity_id": existing_id,
        "new_entity": {"name": "Arbor Systems", "facets": {"entity_type": "company", "sector": "Industrial"}},
    })
    assert response.status_code == 200, response.text
    new_id = entity_id("Arbor Systems")
    assert shows_entity(read_note(), new_id, "Arbor Systems")
    assert shows_entity(client.get(f"/entity/{buyer_id}").text, new_id, "Arbor Systems")
    after_create, = relationships()
    assert after_create["to_id"] == new_id

    response = act("/api/notes/relationship", {
        "file": "focus.md", "edge_id": after_create["edge_id"], "relation": "OWNS", "reverse": True,
    })
    assert response.status_code == 200, response.text
    corrected, = relationships()
    assert (corrected["from_id"], corrected["relation"], corrected["to_id"]) == (new_id, "OWNS", buyer_id)
    assert relationships("peer.txt") == peer_edges
    assert note_tree(data_dir) == original_sources

    for edge_id, relation in ((corrected["edge_id"], "NONEXISTENT_RELATION"), (peer_edges[0]["edge_id"], "COMPETE")):
        invalid = act("/api/notes/relationship", {
            "file": "focus.md", "edge_id": edge_id, "relation": relation,
        })
        assert 400 <= invalid.status_code < 500, invalid.text
    assert relationships() == [corrected]
    assert relationships("peer.txt") == peer_edges
    # An invalid correction is rejected at submit by the shared review, so no job is queued or failed.
    assert 'data-job-state="failed"' not in read_note()

    focus.write_text("Extraction fails here.\n", encoding="utf-8")
    reader = read_note()
    assert 'data-note-status="not-processed"' in reader
    assert re.search(r">\s*Process\s*</button>", reader)
    assert "Extraction fails here." in reader
    assert not shows_entity(reader, new_id, "Arbor Systems")
    stale = act("/api/notes/relationship", {
        "file": "focus.md", "edge_id": corrected["edge_id"], "relation": "BUY",
    })
    assert 400 <= stale.status_code < 500, stale.text
    assert process().status_code >= 400
    assert 'data-note-status="not-processed"' in read_note()
    assert relationships() == [corrected]

    focus.write_text("Latest source marker.\n", encoding="utf-8")
    latest_sources = note_tree(data_dir)
    response = process()
    assert response.status_code == 200, response.text
    latest, = relationships()
    supplier_id = entity_id("Latest Supplier")
    assert (latest["from_id"], latest["relation"], latest["to_id"]) == (buyer_id, "BUY", supplier_id)
    assert latest["edge_id"] != corrected["edge_id"]
    reader = read_note()
    assert 'data-note-status="extracted"' in reader and "Latest source marker." in reader
    assert shows_entity(reader, supplier_id, "Latest Supplier")
    assert not shows_entity(reader, new_id, "Arbor Systems")
    assert relationships("peer.txt") == peer_edges
    assert note_tree(data_dir) == latest_sources


def test_paste_note_saves_md_lists_in_catalog_and_next_ingest_reads_it(tmp_path: Path) -> None:
    client, db_path, data_dir = search_client(tmp_path, FakeWebLLM())
    before_db = db_digest(db_path)
    before_tree = note_tree(data_dir)

    assert 'href="/notes/new"' in client.get("/catalog").text
    form = client.get("/notes/new")
    assert form.status_code == 200
    assert "<textarea" in form.text and "/api/notes" in form.text
    controls = re.findall(r"<(?:input|select|datalist)\b[^>]*>", form.text, flags=re.IGNORECASE)
    assert not [c for c in controls if "folder" in c.lower()], "the form must offer no folder choice"

    # No cookie, token, or credential: the demo's root user has no permission check.
    saved = client.post("/api/notes", json={"title": _PASTE_TITLE, "content": _PASTE_BODY})
    assert saved.status_code == 201, saved.text
    rel = saved.json()["file"]
    assert re.fullmatch(r"_general/\d{4}-\d{2}-\d{2}[^/]*nvda[^/]*channel[^/]*check[^/]*\.md", rel)

    after_tree = note_tree(data_dir)
    assert set(after_tree) - set(before_tree) == {rel}, "exactly one new file, no temp left behind"
    assert after_tree[rel].decode("utf-8") == _PASTE_BODY
    assert {k: after_tree[k] for k in before_tree} == before_tree

    assert "Pasted channel check" in client.get("/catalog", params={"view": "all"}).text
    assert "PASTE-MARKER-7" in client.get("/catalog", params={"file": rel}).text
    assert db_digest(db_path) == before_db, "saving must not write ontology.db"

    llm = _PasteIngestLLM()
    with OntologyDB(tmp_path / "ingest.db", embedding_dim=DIM, read_only=False) as db:
        IngestionPipeline(db, llm, data_dir).run()
    assert "PASTE-MARKER-7" in llm.extracted[rel]


def test_paste_note_never_overwrites_including_concurrent_same_title(tmp_path: Path) -> None:
    client, _, data_dir = search_client(tmp_path, FakeWebLLM())
    first = client.post("/api/notes", json={"title": _PASTE_TITLE, "content": "first\n"})
    assert first.status_code == 201, first.text
    first_file = first.json()["file"]

    count = 24
    barrier = threading.Barrier(count)

    def save(index: int) -> tuple[int, str]:
        barrier.wait(timeout=10)
        resp = client.post(
            "/api/notes", json={"title": _PASTE_TITLE, "content": f"concurrent {index}\n"}
        )
        assert resp.status_code == 201, resp.text
        return index, resp.json()["file"]

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(save, range(count)))

    files = [file for _, file in results]
    assert len(set(files)) == count and first_file not in files
    assert all(Path(file).parent.as_posix() == "_general" for file in [first_file, *files])
    assert (data_dir / first_file).read_text(encoding="utf-8") == "first\n"
    for index, file in results:
        assert (data_dir / file).read_text(encoding="utf-8") == f"concurrent {index}\n"


@pytest.mark.parametrize(
    "folder",
    [
        "Notes",
        "_general/../Notes",
        "../outside",
        "Notes/../../outside",
        "/etc",
        "..\\outside",
        ".hidden",
        "Notes/.hidden",
        "escape",
        "escape/nested",
        "bad\x00folder",
    ],
)
def test_paste_note_extra_folder_field_cannot_move_the_note_out_of_general(
    tmp_path: Path, folder: str
) -> None:
    client, _, data_dir = search_client(tmp_path, FakeWebLLM())
    outside = tmp_path / "outside"
    (outside / "nested").mkdir(parents=True)
    (data_dir / ".hidden").mkdir()
    (data_dir / "Notes" / ".hidden").mkdir(parents=True)
    (data_dir / "escape").symlink_to(outside, target_is_directory=True)

    # Positive control: the route exists, so a rejection below is not just a missing route.
    control = client.post("/api/notes", json={"title": "control", "content": "ok\n"})
    assert control.status_code == 201, control.text

    before_data, before_outside = note_tree(data_dir), note_tree(outside)
    resp = client.post(
        "/api/notes", json={"title": _PASTE_TITLE, "content": _PASTE_BODY, "folder": folder}
    )
    after_data = note_tree(data_dir)
    assert note_tree(outside) == before_outside
    assert {k: after_data.get(k) for k in before_data} == before_data
    # The field may be ignored or rejected. It may never choose where the note lands.
    if resp.status_code == 201:
        rel = resp.json()["file"]
        assert Path(rel).parent.as_posix() == "_general"
        assert set(after_data) - set(before_data) == {rel}
    else:
        assert resp.status_code in (400, 422), resp.text
        assert after_data == before_data


@pytest.mark.parametrize("target", ["external", "external_missing", "inside_data"])
def test_paste_note_refuses_general_symlink_that_leaves_the_folder(
    tmp_path: Path, target: str
) -> None:
    client, _, data_dir = search_client(tmp_path, FakeWebLLM())
    (data_dir / "Notes").mkdir(exist_ok=True)

    # Positive control: the route saves normally before `_general` is swapped for a link.
    control = client.post("/api/notes", json={"title": "control", "content": "ok\n"})
    assert control.status_code == 201, control.text
    (data_dir / "_general").rename(tmp_path / "moved_general")

    outside = tmp_path / "outside"
    if target == "external":
        outside.mkdir()
    destination = data_dir / "Notes" if target == "inside_data" else outside
    (data_dir / "_general").symlink_to(destination, target_is_directory=True)

    before_data = note_tree(data_dir)
    resp = client.post("/api/notes", json={"title": _PASTE_TITLE, "content": _PASTE_BODY})

    assert 400 <= resp.status_code < 500, resp.text
    assert note_tree(data_dir) == before_data
    if target == "external":
        assert note_tree(outside) == {}
    if target == "external_missing":
        assert not outside.exists()


@pytest.mark.parametrize("title", ["../../evil", "/etc/evil", ".hidden", "a/b\\c", "..", "evil\x00name"])
def test_paste_note_hostile_title_stays_a_visible_file_in_general(
    tmp_path: Path, title: str
) -> None:
    client, db_path, data_dir = search_client(tmp_path, FakeWebLLM())
    # Saving queues a processing job: the command spool beside the database may change too.
    spool = Path(f"{db_path}.commands")

    def outside_notes() -> set[Path]:
        return {
            p for p in tmp_path.rglob("*")
            if data_dir not in p.parents and p != data_dir and p != spool and spool not in p.parents
        }

    before_outside = outside_notes()

    resp = client.post("/api/notes", json={"title": title, "content": _PASTE_BODY})
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_id"], "saving must queue a processing job"
    rel = Path(resp.json()["file"])
    assert rel.parent.as_posix() == "_general"
    assert rel.suffix == ".md" and not rel.name.startswith(".")
    target = (data_dir / rel).resolve()
    assert target.parent == (data_dir / "_general").resolve()
    assert target.read_text(encoding="utf-8") == _PASTE_BODY
    assert outside_notes() == before_outside


def test_paste_note_is_never_visible_to_ingestion_partially_written(tmp_path: Path) -> None:
    client, _, data_dir = search_client(tmp_path, FakeWebLLM())
    before = set(note_tree(data_dir))
    body = "# Large paste\n\n" + ("PASTE-LINE complete content.\n" * 2200) + "PASTE-END\n"
    stop = threading.Event()
    partial: list[str] = []
    observed: set[str] = set()

    def watch() -> None:
        # The same visibility rule the ingestion scan applies: non-hidden `.md` files.
        while not stop.is_set():
            for path in data_dir.rglob("*.md"):
                rel = path.relative_to(data_dir)
                if rel.as_posix() in before or any(p.startswith(".") for p in rel.parts):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (FileNotFoundError, UnicodeDecodeError):
                    partial.append(rel.as_posix())
                    continue
                observed.add(rel.as_posix())
                if text != body:
                    partial.append(rel.as_posix())

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        saved = [
            client.post("/api/notes", json={"title": f"large {i}", "content": body})
            for i in range(30)
        ]
    finally:
        stop.set()
        watcher.join(timeout=10)

    assert all(r.status_code == 201 for r in saved), [r.text for r in saved if r.status_code != 201]
    assert observed, "the watcher must see at least one published note"
    assert not partial, f"ingestion-visible partial notes: {sorted(set(partial))[:3]}"
    files = {r.json()["file"] for r in saved}
    assert all(Path(file).parent.as_posix() == "_general" for file in files)
    assert set(note_tree(data_dir)) - before == files, "no temp files left"


def test_note_reader_can_correct_both_relationship_endpoints(tmp_path: Path) -> None:
    from stock_ontology.cli import _create_library_app

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    source = data_dir / "note.md"
    source.write_text("Source reference.", encoding="utf-8")
    db_path = tmp_path / "reader.db"
    registry = create_minimal_registry()
    registry_path = tmp_path / "registry.json"
    save_registry(registry, registry_path)
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name in (("a", "Alpha"), ("b", "Beta"), ("c", "Cedar"), ("d", "Delta")):
            db.upsert_node(Node(
                id=node_id, name=name, summary="", node_type="entity",
                facets={"entity_type": "company", "sector": "Industrial"},
            ))
        db.upsert_node(Node(
            id="fact", name="An announcement", summary="", node_type="event",
            facets={"event_type": "fact"},
        ))
        db.upsert_ingestion_log("note.md", "note", hashlib.sha256(source.read_bytes()).hexdigest(),
                                entity_ids=("a", "b"))
        for edge_id, doc_id in (("original", "note"), ("peer", "different-note")):
            db.upsert_edge(Edge(
                id=edge_id, from_id="a", to_id="b", relation="BUY",
                source_doc_id=doc_id, facets={"basis": "extracted"},
            ))

    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=registry_path, embedding_dim=DIM)
    llm = FakeWebLLM()
    client = TestClient(_create_library_app(settings, llm=llm))
    payload = {"file": "note.md", "edge_id": "original", "relation": "BUY"}
    for endpoints in ({"from_id": "missing"}, {"from_id": "fact"}, {"from_id": "b"}):
        response = _note_action(client, settings, llm, "/api/notes/relationship", {**payload, **endpoints})
        assert response.status_code == 422, response.text

    response = _note_action(client, settings, llm, "/api/notes/relationship", {**payload, "from_id": "c", "to_id": "d"})
    assert response.status_code == 200, response.text

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        edited, = db.list_note_edges("note")
        assert (edited["from_id"], edited["relation"], edited["to_id"]) == ("c", "BUY", "d")
        assert {node.id for node in db.list_note_entities("note")} == {"a", "b", "c", "d"}
        peer, = db.list_note_edges("different-note")
        assert (peer["edge_id"], peer["from_id"], peer["to_id"]) == ("peer", "a", "b")
    assert source.read_text(encoding="utf-8") == "Source reference."
    assert 'href="/entity/d"' in client.get("/entity/c").text


def test_note_reader_adds_and_deletes_relationships(tmp_path: Path) -> None:
    from stock_ontology.cli import _create_library_app

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    source = data_dir / "note.md"
    source.write_text("Source reference.", encoding="utf-8")
    (data_dir / "unprocessed.md").write_text("Unprocessed source.", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    db_path = tmp_path / "reader.db"
    registry = create_minimal_registry()
    registry_path = tmp_path / "registry.json"
    save_registry(registry, registry_path)
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name in (("alpha", "Alpha"), ("beta", "Beta"), ("cedar", "Cedar")):
            db.upsert_node(Node(
                id=node_id, name=name, summary="", node_type="entity",
                facets={"entity_type": "company", "sector": "Industrial"},
            ))
        db.upsert_ingestion_log("note.md", "note", source_hash, entity_ids=())
        db.upsert_edge(Edge(
            id="peer-edge", from_id="cedar", to_id="alpha", relation="BUY",
            source_doc_id="peer", facets={"basis": "extracted"},
        ))

    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=registry_path, embedding_dim=DIM)
    llm = FakeWebLLM()
    client = TestClient(_create_library_app(settings, llm=llm))

    def reader_table() -> str:
        response = client.get("/catalog", params={"file": "note.md", "lang": "en"})
        assert response.status_code == 200
        assert 'data-note-status="extracted"' in response.text
        assert "Source reference." in response.text
        table = re.search(r'<table\b[^>]*class="catalog-table note-relationships"[^>]*>(.*?)</table>', response.text, re.S)
        assert table is not None, "Processed notes need a relationship table even while empty."
        return table.group(1)

    def note_edges() -> list[dict[str, Any]]:
        with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
            return db.list_note_edges("note")

    assert "Add relationship" in reader_table()
    assert 'href="/entity/beta"' not in client.get("/entity/alpha").text

    add_url = "/api/notes/relationship/add"
    delete_url = "/api/notes/relationship/delete"
    add = {"file": "note.md", "from_id": "alpha", "relation": "BUY", "to_id": "beta"}
    for invalid in ({"to_id": "missing"}, {"to_id": "alpha"}, {"file": "unprocessed.md"},
                    {"expected_hash": "stale"}):
        response = _note_action(client, settings, llm, add_url, {**add, **invalid})
        assert 400 <= response.status_code < 500, response.text
    assert note_edges() == []

    response = _note_action(client, settings, llm, add_url, {**add, "expected_hash": source_hash})
    assert response.status_code == 200, response.text
    # The same relationship again is a duplicate, refused as on the Ontology page.
    response = _note_action(client, settings, llm, add_url, {**add, "expected_hash": source_hash})
    assert response.status_code == 409, response.text
    edge, = note_edges()
    assert (edge["from_id"], edge["relation"], edge["to_id"]) == ("alpha", "BUY", "beta")
    assert re.search(r"<tr\b[^>]*>\s*<td>Alpha</td>\s*<td>BUY\s*</td>\s*<td>Beta</td>",
                     reader_table())
    assert "Delete" in reader_table()
    assert 'href="/entity/beta"' in client.get("/entity/alpha").text

    delete = {"file": "note.md", "edge_id": edge["edge_id"]}
    for invalid in ({"edge_id": "peer-edge"}, {"expected_hash": "stale"}):
        response = _note_action(client, settings, llm, delete_url, {**delete, **invalid})
        assert 400 <= response.status_code < 500, response.text
    assert note_edges() == [edge]

    response = _note_action(client, settings, llm, delete_url, {**delete, "expected_hash": source_hash})
    assert response.status_code == 200, response.text
    assert note_edges() == []
    assert "Add relationship" in reader_table()
    assert 'href="/entity/beta"' not in client.get("/entity/alpha").text
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        peer, = db.list_note_edges("peer")
        assert (peer["edge_id"], peer["from_id"], peer["to_id"]) == ("peer-edge", "cedar", "alpha")
    assert source.read_text(encoding="utf-8") == "Source reference."


def test_note_reader_adds_and_deletes_entities(tmp_path: Path) -> None:
    from stock_ontology.cli import _create_library_app

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    source = data_dir / "note.md"
    source.write_text("Source reference.", encoding="utf-8")
    (data_dir / "unprocessed.md").write_text("Unprocessed source.", encoding="utf-8")
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    db_path = tmp_path / "reader.db"
    registry = create_minimal_registry()
    registry_path = tmp_path / "registry.json"
    save_registry(registry, registry_path)
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name in (("alpha", "Alpha"), ("beta", "Beta"), ("cedar", "Cedar")):
            db.upsert_node(Node(
                id=node_id, name=name, summary="", node_type="entity",
                facets={"entity_type": "company", "sector": "Industrial"},
            ))
        db.upsert_node(Node(
            id="announcement", name="Announcement", summary="", node_type="event",
            facets={"event_type": "fact"},
        ))
        db.upsert_ingestion_log("note.md", "note", content_hash, entity_ids=())
        db.upsert_ingestion_log("peer.md", "peer", "peer-hash", entity_ids=("alpha", "beta"))
        db.upsert_edge(Edge(
            id="peer-edge", from_id="alpha", to_id="beta", relation="BUY",
            source_doc_id="peer", facets={"basis": "extracted"},
        ))

    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=registry_path, embedding_dim=DIM)
    llm = FakeWebLLM()
    client = TestClient(_create_library_app(settings, llm=llm))

    def read_note() -> str:
        response = client.get("/catalog", params={"file": "note.md", "lang": "en"})
        assert response.status_code == 200
        assert 'data-note-status="extracted"' in response.text
        assert "Source reference." in response.text
        return response.text

    def entity_list() -> str:
        result = re.search(r'<ul class="note-extraction-entities">(.*?)</ul>', read_note(), re.S)
        assert result is not None
        return result.group(1)

    add_url = "/api/notes/entity/add"
    delete_url = "/api/notes/entity/delete"
    alpha = {"file": "note.md", "entity_id": "alpha"}
    assert "Add entity" in read_note(), "A processed note with no entities must offer Add entity."
    for invalid in ({"entity_id": "missing"}, {"entity_id": "announcement"},
                    {"file": "unprocessed.md"}, {"expected_hash": "stale"}):
        response = _note_action(client, settings, llm, add_url, {**alpha, **invalid})
        assert 400 <= response.status_code < 500, response.text
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.list_note_entities("note") == []

    for _ in range(2):
        response = _note_action(client, settings, llm, add_url, {**alpha, "expected_hash": content_hash})
        assert response.status_code == 200, response.text
    entities = entity_list()
    assert entities.count('href="/entity/alpha"') == 1
    assert "Edit" in entities and "Delete" in entities

    for invalid in ({"entity_id": "beta"}, {"expected_hash": "stale"}):
        response = _note_action(client, settings, llm, delete_url, {**alpha, **invalid})
        assert 400 <= response.status_code < 500, response.text
    assert 'href="/entity/alpha"' in entity_list()

    for from_id, to_id in (("alpha", "beta"), ("beta", "cedar")):
        response = _note_action(client, settings, llm, "/api/notes/relationship/add", {
            "file": "note.md", "from_id": from_id, "to_id": to_id, "relation": "BUY",
        })
        assert response.status_code == 200, response.text
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for edge_id, doc_id in (("pending-note", "note"), ("pending-peer", "peer")):
            db.insert_pending_edge(Edge(
                id=edge_id, from_id="beta", to_id="alpha", relation="UNREVIEWED",
                source_doc_id=doc_id, facets={"basis": "extracted"},
            ))

    response = _note_action(client, settings, llm, delete_url, {**alpha, "expected_hash": content_hash})
    assert response.status_code == 200, response.text
    entities = entity_list()
    assert 'href="/entity/alpha"' not in entities
    assert 'href="/entity/beta"' in entities
    assert client.get("/entity/alpha").status_code == 200
    assert source.read_text(encoding="utf-8") == "Source reference."

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as db:
        assert {node.id for node in db.list_note_entities("note")} == {"beta", "cedar"}
        assert {node.id for node in db.list_note_entities("peer")} == {"alpha", "beta"}
        remaining, = db.list_note_edges("note")
        assert (remaining["from_id"], remaining["to_id"]) == ("beta", "cedar")
        assert db.list_note_edges("note", pending=True) == []
        assert [edge["edge_id"] for edge in db.list_note_edges("peer")] == ["peer-edge"]
        assert [edge["edge_id"] for edge in db.list_note_edges("peer", pending=True)] == ["pending-peer"]


def test_web_note_actions_return_job_references_and_open_the_db_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stock_ontology import cli
    from stock_ontology.worker import Worker

    data_dir = tmp_path / "notes"
    data_dir.mkdir()
    (data_dir / "focus.md").write_text("First source marker.\n", encoding="utf-8")
    db_path = tmp_path / "reader.db"
    registry = create_minimal_registry()
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry):
        pass
    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=tmp_path / "missing.json", embedding_dim=DIM)
    llm = _NoteReaderLLM()
    opens: list[bool] = []
    original = OntologyDB.__init__

    def record(self: OntologyDB, *args: Any, **kwargs: Any) -> None:
        opens.append(bool(kwargs.get("read_only", False)))
        original(self, *args, **kwargs)

    monkeypatch.setattr(OntologyDB, "__init__", record)
    client = TestClient(cli._create_library_app(settings, llm=llm))
    response = client.post("/api/notes/process", json={"file": "focus.md"})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert client.post("/api/notes/process", json={"file": "focus.md"}).json()["job_id"] == job_id
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "queued"
    reader = client.get("/catalog", params={"file": "focus.md", "lang": "en"}).text
    assert 'data-job-state="queued"' in reader and 'data-note-status="not-processed"' in reader
    assert client.get("/api/jobs/job_missing").status_code == 404
    assert opens and all(opens), "the web app opened ontology.db for writing"
    monkeypatch.undo()

    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "succeeded"
    reader = client.get("/catalog", params={"file": "focus.md", "lang": "en"}).text
    assert 'data-job-state="succeeded"' in reader and 'data-note-status="extracted"' in reader


# One review path for note corrections: the note reader and the Ontology page judge the same edit alike.

_FIXTURE_SOURCE = "Correction source reference.\n"


def _correction_workspace(root: Path) -> tuple[Settings, TestClient, Any]:
    """A processed note with one main edge, one pending edge, and a peer note's edge."""
    root.mkdir()
    data_dir = root / "notes"
    data_dir.mkdir()
    (data_dir / "note.md").write_text(_FIXTURE_SOURCE, encoding="utf-8")
    registry = create_minimal_registry()
    registry.facet_schema.setdefault("relation", {})["OWNS"] = {"stake": {"kind": "text", "required": True}}
    registry_path = root / "registry.json"
    save_registry(registry, registry_path)
    db_path = root / "reader.db"
    with OntologyDB(db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name in (("a", "Alpha"), ("b", "Beta"), ("c", "Cedar"), ("d", "Delta")):
            db.upsert_node(Node(id=node_id, name=name, summary="", node_type="entity",
                                facets={"entity_type": "company", "sector": "Industrial"}))
        db.upsert_node(Node(id="fact", name="An announcement", summary="", node_type="event",
                            facets={"event_type": "fact"}))
        db.upsert_ingestion_log("note.md", "note", hashlib.sha256(_FIXTURE_SOURCE.encode()).hexdigest(),
                                entity_ids=("a", "b"))
        db.upsert_edge(Edge(id="original", from_id="a", to_id="b", relation="BUY",
                            source_doc_id="note", facets={"basis": "extracted"}))
        db.upsert_edge(Edge(id="peer", from_id="a", to_id="b", relation="BUY",
                            source_doc_id="peer-note", facets={"basis": "extracted"}))
        db.insert_pending_edge(Edge(id="pending", from_id="a", to_id="b", relation="UNREVIEWED_RELATION",
                                    source_doc_id="note", facets={"basis": "extracted"}))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
    settings = Settings(db_path=db_path, data_dir=data_dir, registry_path=registry_path, embedding_dim=DIM)
    llm = FakeWebLLM()
    return settings, TestClient(create_app(settings, llm=llm, note_actions=True)), llm


def _note_graph(settings: Settings) -> dict[str, list[tuple[Any, ...]]]:
    """The note's and the peer note's edges, without generated edge IDs."""
    def rows(doc_id: str, pending: bool = False) -> list[tuple[Any, ...]]:
        return sorted(
            (row["from_id"], row["relation"], row["to_id"], tuple(sorted(row["facets"].items())))
            for row in db.list_note_edges(doc_id, pending=pending)
        )

    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        return {"edges": rows("note"), "pending": rows("note", True), "peer": rows("peer-note")}


@dataclasses.dataclass(frozen=True)
class _Judgement:
    """Where a correction was decided (at submit or by the worker), its HTTP status and message, and the graph after."""

    phase: str
    status: int
    detail: str
    graph: dict[str, list[tuple[Any, ...]]]


def _run_job(client: TestClient, settings: Settings, llm: Any, job_id: str) -> tuple[int, str]:
    from stock_ontology.worker import Worker

    Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False)
    job = client.get(f"/api/jobs/{job_id}").json()
    if job["state"] == "succeeded":
        return 200, ""
    codes = {"invalid": 422, "conflict": 409, "not_found": 404}
    return codes.get(job.get("error_code") or "", 500), str(job.get("error") or "")


def _judged(client: TestClient, settings: Settings, llm: Any, response: Any) -> _Judgement:
    if response.status_code != 202:
        return _Judgement("submit", response.status_code, response.json()["detail"], _note_graph(settings))
    status, detail = _run_job(client, settings, llm, response.json()["job_id"])
    return _Judgement("worker", status, detail, _note_graph(settings))


def _reader_judgement(root: Path, url: str, payload: dict[str, Any], *, stale: bool) -> _Judgement:
    settings, client, llm = _correction_workspace(root)
    if stale:
        (settings.data_dir / "note.md").write_text(_FIXTURE_SOURCE + "Changed after processing.\n", encoding="utf-8")
    return _judged(client, settings, llm, client.post(url, json={"file": "note.md", **payload}))


def _ontology_judgement(root: Path, edit: dict[str, Any], *, stale: bool) -> _Judgement:
    from stock_ontology.services import ProcessingService, ServiceError
    from stock_ontology.services.corrections import review_note_correction
    from stock_ontology.web.shell import http_error

    settings, client, llm = _correction_workspace(root)
    if stale:
        (settings.data_dir / "note.md").write_text(_FIXTURE_SOURCE + "Changed after processing.\n", encoding="utf-8")
    edit = {"file": "note.md", **edit}
    if edit["kind"] != "relationship_delete":
        preview = client.post("/api/ontology/corrections/preview", json=edit)
        if preview.status_code != 200:
            return _Judgement("submit", preview.status_code, preview.json()["detail"], _note_graph(settings))
        confirmed = client.post("/api/ontology/corrections/confirm", json={"confirmation": preview.json()["confirmation"]})
        assert confirmed.status_code == 202, confirmed.text
        return _judged(client, settings, llm, confirmed)
    # The Ontology page has no delete form yet; its review and its worker job are the same ones confirm uses.
    path = (settings.data_dir / "note.md").resolve()
    try:
        with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
            review = review_note_correction(db, path, settings.data_dir, **{k: v for k, v in edit.items() if k != "file"})
    except ServiceError as exc:
        error = http_error(exc, "en")
        return _Judgement("submit", error.status_code, str(error.detail), _note_graph(settings))
    job = ProcessingService(settings).submit_correction("note.ontology.correction", "note.md", review)
    status, detail = _run_job(client, settings, llm, job.job_id)
    return _Judgement("worker", status, detail, _note_graph(settings))


_EXTRACTED = (("basis", "extracted"),)
_PEER = [("a", "BUY", "b", _EXTRACTED)]
_PENDING = [("a", "UNREVIEWED_RELATION", "b", _EXTRACTED)]
_EDIT_URL, _ADD_URL, _DELETE_URL = (
    "/api/notes/relationship", "/api/notes/relationship/add", "/api/notes/relationship/delete",
)


def _edit(edge_id: str, relation: str, from_id: str, to_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """The note reader always sends relation and both endpoints; the Ontology page sends the same fields."""
    fields = {"relation": relation, "from_id": from_id, "to_id": to_id}
    return _EDIT_URL, {"edge_id": edge_id, **fields}, {"kind": "relationship", "edge_id": edge_id, "changes": fields}


def _add(from_id: str, relation: str, to_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    fields = {"from_id": from_id, "relation": relation, "to_id": to_id}
    return _ADD_URL, fields, {"kind": "relationship_add", "record": from_id, "changes": fields}


def _delete(edge_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    return _DELETE_URL, {"edge_id": edge_id}, {"kind": "relationship_delete", "edge_id": edge_id, "changes": {}}


@pytest.mark.parametrize(
    ("correction", "stale", "expected"),
    [
        pytest.param(_edit("original", "NONEXISTENT_RELATION", "a", "b"), False,
                     (422, "service_error.choose_relationship_type"), id="unregistered-relation"),
        pytest.param(_edit("original", "BUY", "fact", "b"), False,
                     (422, "service_error.relationship_not_allowed"), id="forbidden-endpoints"),
        pytest.param(_edit("original", "BUY", "b", "b"), False,
                     (422, "service_error.choose_two_endpoints"), id="same-node"),
        pytest.param(_edit("original", "OWNS", "a", "b"), False, (422, None), id="missing-required-facet"),
        pytest.param(_add("a", "BUY", "b"), False,
                     (409, "service_error.relationship_exists"), id="duplicate-add"),
        pytest.param(_delete("peer"), False,
                     (404, "service_error.relationship_missing"), id="delete-other-notes-edge"),
        pytest.param(_edit("original", "BUY", "c", "d"), True,
                     (409, "service_error.stale_source_note"), id="note-changed"),
        pytest.param(_edit("original", "BUY", "c", "d"), False,
                     {"edges": [("c", "BUY", "d", _EXTRACTED)], "pending": _PENDING, "peer": _PEER},
                     id="valid-edit"),
        pytest.param(_edit("pending", "BUY", "a", "c"), False,
                     {"edges": sorted([("a", "BUY", "b", _EXTRACTED), ("a", "BUY", "c", _EXTRACTED)]),
                      "pending": [], "peer": _PEER},
                     id="valid-pending-edit"),
        pytest.param(_add("a", "BUY", "c"), False,
                     {"edges": sorted([("a", "BUY", "b", _EXTRACTED), ("a", "BUY", "c", _EXTRACTED)]),
                      "pending": _PENDING, "peer": _PEER},
                     id="valid-add"),
        pytest.param(_delete("original"), False,
                     {"edges": [], "pending": _PENDING, "peer": _PEER}, id="valid-delete"),
    ],
)
def test_note_reader_and_ontology_page_judge_a_relationship_correction_alike(
    tmp_path: Path, correction: tuple[str, dict[str, Any], dict[str, Any]], stale: bool, expected: Any,
) -> None:
    url, reader_payload, ontology_edit = correction
    reader = _reader_judgement(tmp_path / "reader", url, reader_payload, stale=stale)
    ontology = _ontology_judgement(tmp_path / "ontology", ontology_edit, stale=stale)
    untouched = {"edges": [("a", "BUY", "b", _EXTRACTED)], "pending": _PENDING, "peer": _PEER}

    if isinstance(expected, dict):
        assert (ontology.status, ontology.graph) == (200, expected), ontology
        assert (reader.status, reader.graph) == (200, expected), reader
        return
    status, key = expected
    assert (ontology.phase, ontology.status, ontology.graph) == ("submit", status, untouched), ontology
    if key is not None:
        assert ontology.detail == translate(key, lang="en"), ontology
    # The reader rejects at submit, with the same status and message, and queues nothing.
    assert reader == ontology


def test_queued_legacy_relationship_jobs_are_judged_by_the_same_review(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from stock_ontology.services import ProcessingService, ServiceError
    from stock_ontology.services.processing import job_priority

    settings, client, llm = _correction_workspace(tmp_path / "graph")
    source_hash = hashlib.sha256(_FIXTURE_SOURCE.encode()).hexdigest()

    def queue_legacy(job_id: str, kind: str, params: dict[str, Any]) -> str:
        """A job of a retired kind that was queued before deploy."""
        now = datetime.now(UTC)
        with OntologyDB(settings.db_path, embedding_dim=DIM) as db:
            assert db.jobs.insert(
                job_id=job_id, kind=kind, target="note.md", revision=source_hash, priority=job_priority(kind),
                payload={"file": "note.md", "expected_hash": source_hash, **params},
                created_at=now.isoformat(), now=now,
            )
        return job_id

    duplicate = queue_legacy("job_legacy_duplicate", "note.relationship.add",
                             {"from_id": "a", "relation": "BUY", "to_id": "b"})
    # Before this change the legacy executor upserted the duplicate silently; the review rejects it.
    assert _run_job(client, settings, llm, duplicate)[0] == 409
    assert _note_graph(settings)["edges"] == [("a", "BUY", "b", _EXTRACTED)]

    pending = queue_legacy("job_legacy_pending", "note.relationship",
                           {"edge_id": "pending", "relation": "BUY", "from_id": "a", "to_id": "c"})
    assert _run_job(client, settings, llm, pending) == (200, "")
    deleted = queue_legacy("job_legacy_delete", "note.relationship.delete", {"edge_id": "original"})
    assert _run_job(client, settings, llm, deleted) == (200, "")
    assert _note_graph(settings) == {"edges": [("a", "BUY", "c", _EXTRACTED)], "pending": [], "peer": _PEER}

    # New jobs of the retired kinds can no longer be submitted.
    for kind, params in (
        ("note.relationship", {"edge_id": "original", "relation": "BUY", "from_id": "c", "to_id": "d"}),
        ("note.relationship.add", {"from_id": "a", "relation": "BUY", "to_id": "c"}),
        ("note.relationship.delete", {"edge_id": "original"}),
    ):
        with pytest.raises(ServiceError) as refused:
            ProcessingService(settings).submit_correction(kind, "note.md", {**params, "expected_hash": source_hash})
        assert refused.value.code == "invalid", kind


def test_note_reader_form_opened_before_an_ontology_correction_cannot_reapply(tmp_path: Path) -> None:
    settings, client, llm = _correction_workspace(tmp_path / "graph")
    preview = client.post("/api/ontology/corrections/preview", json={
        "kind": "relationship", "file": "note.md", "edge_id": "original", "changes": {"to_id": "c"},
    })
    assert preview.status_code == 200, preview.text
    confirmed = client.post("/api/ontology/corrections/confirm", json={"confirmation": preview.json()["confirmation"]})
    assert _judged(client, settings, llm, confirmed).status == 200
    corrected = _note_graph(settings)
    assert corrected["edges"] == [("a", "BUY", "c", _EXTRACTED)]

    # A reader form still holds the edge ID it rendered before the Ontology page corrected that edge.
    stale_form = client.post(_EDIT_URL, json={
        "file": "note.md", "edge_id": "original", "relation": "BUY", "from_id": "a", "to_id": "d",
    })
    judged = _judged(client, settings, llm, stale_form)
    assert (judged.phase, judged.status) == ("submit", 404), judged
    assert judged.detail == translate("service_error.relationship_missing", lang="en")
    assert _note_graph(settings) == corrected


def test_note_reader_reverse_reviews_like_the_swapped_endpoints(tmp_path: Path) -> None:
    from stock_ontology.services.corrections import review_reader_correction

    settings, _, _ = _correction_workspace(tmp_path / "graph")
    path = (settings.data_dir / "note.md").resolve()
    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        def review(params: dict[str, Any]) -> dict[str, Any]:
            return review_reader_correction(db, path, settings.data_dir, "note.relationship",
                                             {"edge_id": "original", "relation": "COMPETE", **params})

        reversed_ = review({"reverse": True})
        swapped = review({"from_id": "b", "to_id": "a"})
    assert reversed_["edges"] == swapped["edges"]
    assert reversed_["request"]["changes"] == swapped["request"]["changes"]


def test_ontology_preview_judges_an_unregistered_relation_before_its_fields(tmp_path: Path) -> None:
    settings, client, _ = _correction_workspace(tmp_path / "graph")
    for facets in ("not-a-dict", {"stake": "10%"}):
        preview = client.post("/api/ontology/corrections/preview", json={
            "kind": "relationship", "file": "note.md", "edge_id": "original",
            "changes": {"relation": "NONEXISTENT_RELATION", "facets": facets},
        })
        assert preview.status_code == 422, preview.text
        assert preview.json()["detail"] == translate("service_error.choose_relationship_type", lang="en")
    assert _note_graph(settings)["edges"] == [("a", "BUY", "b", _EXTRACTED)]
