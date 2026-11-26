"""Offline tests for the Ontology module: model tabs, registry and audit views, and registry editing."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlparse

import pytest
from fastapi.testclient import TestClient
from test_db import insert_legacy_edge, seed_edge
from web_support import (
    DIM,
    FakeWebLLM,
    db_digest,
    seed_web_db,
    unit_vec,
)

import stock_ontology.web
from stock_ontology.audit import run_ontology_audit
from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.i18n import translate, translate_enum, translate_facet_label
from stock_ontology.models import Edge, Node
from stock_ontology.registry import create_minimal_registry, load_registry, save_registry
from stock_ontology.web import create_app


def test_web_ontology_view_screen_4_structures_and_tabs(tmp_path: Path) -> None:
    db_path = tmp_path / "web_ontology.db"
    seed_web_db(db_path)

    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=tmp_path)
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        before_stats = ro.get_stats()

    # Explicit Entity explorer (4 structure cards and SVG blueprint)
    r_ont = client.get("/ontology", params={"tab": "entity"})
    assert r_ont.status_code == 200
    assert "4-Node Stock Ontology &amp; Unified Edges" in r_ont.text
    assert "<svg" in r_ont.text
    assert "1. Entity" in r_ont.text
    assert "2. Event" in r_ont.text
    assert "3. View" in r_ont.text
    assert "4. Theme" in r_ont.text
    assert "NVIDIA" in r_ont.text
    assert "custom_metric" in r_ont.text

    # Subtype filter on entity tab
    r_ont_person = client.get("/ontology", params={"tab": "entity", "subtype": "person"})
    assert r_ont_person.status_code == 200
    assert "Kenji Sato" in r_ont_person.text
    assert "ent_nvda" not in r_ont_person.text

    # Other structure tabs + Unified Edges tab
    r_event = client.get("/ontology", params={"tab": "event"})
    assert r_event.status_code == 200
    assert "Blackwell Rack Ramp" in r_event.text

    r_view = client.get("/ontology", params={"tab": "view"})
    assert r_view.status_code == 200
    assert "Morgan Buy View" in r_view.text
    assert "Consensus: Buy NVIDIA" in r_view.text

    r_theme = client.get("/ontology", params={"tab": "theme"})
    assert r_theme.status_code == 200
    assert "AI Data Center Power Bottleneck" in r_theme.text

    r_edges = client.get("/ontology", params={"tab": "edges"})
    assert r_edges.status_code == 200
    assert "Edge Schema Triples" in r_edges.text
    assert "SUPPLIES_TO" in r_edges.text
    assert "AUTHORED_BY" in r_edges.text

    # Strictly read-only verification
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        assert ro.get_stats() == before_stats


def test_ontology_registry_schema_browse_records_and_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "ontology.db"
    registry_path = tmp_path / "registry.json"
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / "supplier.md"
    note.write_text("# Supplier note\n\nSourced purchasing evidence.\n", encoding="utf-8")
    spaced_note = notes / " shifted.md"
    spaced_note.write_text("# Logged source\n\nEvidence from the space-prefixed note.\n", encoding="utf-8")
    competing_note = notes / "shifted.md"
    competing_note.write_text("# Unrelated note\n\nDifferent evidence.\n", encoding="utf-8")
    fixture_notes = (note, spaced_note, competing_note)
    registry = create_minimal_registry()
    registry.facet_schema["node"]["entity:person"] = {
        "organization": {"kind": "text", "required": True},
    }
    save_registry(registry, registry_path)
    seed_web_db(db_path)
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        db.upsert_ingestion_log(note.name, "doc_1", hashlib.sha256(note.read_bytes()).hexdigest())
        db.upsert_ingestion_log("missing.md", "doc_missing", "old")
        db.upsert_ingestion_log(spaced_note.name, "doc_spaced", hashlib.sha256(spaced_note.read_bytes()).hexdigest())
        db.upsert_node(
            Node(id="ent_nvda_legacy", node_type="entity", name="Nvidia Corporation", summary="",
                 facets={"entity_type": "company", "ticker": "NVDA", "sector": "Semiconductors"}),
            embedding=unit_vec(8),
        )
        db.upsert_edge(Edge(
            id="alternate-purchasing-edge", from_id="ent_nvda_legacy", to_id="ent_tsmc",
            relation="BUY", source_doc_id="doc_missing", facets={"basis": "extracted"},
        ))
        db.upsert_edge(Edge(
            id="competitor-edge", from_id="ent_nvda_legacy", to_id="ent_tsmc",
            relation="COMPETE", source_doc_id="doc_spaced", facets={"basis": "extracted"},
        ))
        db.record_registry_adoption(registry, from_revision=None, plan="test")
    registry.version = 2
    save_registry(registry, registry_path)

    client = TestClient(create_app(
        Settings(db_path=db_path, registry_path=registry_path, data_dir=notes, embedding_dim=DIM),
        llm=FakeWebLLM(),
    ))
    before = (db_digest(db_path), registry_path.read_bytes(), *(path.read_bytes() for path in fixture_notes))

    def link(page: str, label: str) -> str:
        anchor = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>\s*' + re.escape(html.escape(label)) + r'\s*</a>', page)
        assert anchor is not None, f"Missing visible link: {label}"
        return html.unescape(anchor[1])

    def search(url: str, query: str) -> str:
        params = dict(parse_qsl(urlparse(url).query))
        return client.get(url, params={**params, "q": query}).text

    landing = client.get("/ontology")
    assert landing.status_code == 200
    registry_browser = landing.text.split('id="structure-explorer"', 1)[-1]
    companies_url = link(registry_browser, "Companies")
    themes_url = link(registry_browser, "Themes")
    people_url = link(registry_browser, "People")
    company_results = search(companies_url, "NVDA")
    assert "Microsoft" not in company_results
    company_url = link(company_results, "NVIDIA")
    company = client.get(company_url)
    assert company.status_code == 200
    assert "<h1>NVIDIA</h1>" in company.text
    assert "Semiconductors" in company.text and "Nvidia Corporation" in company.text
    note_url = link(company.text, "supplier.md")
    cited = client.get(note_url)
    assert cited.status_code == 200 and "Sourced purchasing evidence." in cited.text
    record_return_url = link(cited.text, translate("catalog.back_to_previous"))
    assert record_return_url == company_url
    returned_record = client.get(record_return_url)
    assert returned_record.status_code == 200 and "<h1>NVIDIA</h1>" in returned_record.text
    assert link(returned_record.text, "supplier.md") == note_url
    breadcrumb = re.search(r'<nav id="breadcrumb".*?</nav>', returned_record.text, re.S)
    assert breadcrumb is not None
    registry_return_url = link(breadcrumb[0], "Registry")
    assert parse_qs(urlparse(registry_return_url).query) == {
        "tab": ["registry"], "kind": ["companies"], "q": ["NVDA"],
    }
    returned_search = client.get(registry_return_url)
    assert returned_search.status_code == 200
    assert "Microsoft" not in returned_search.text
    assert link(returned_search.text, "NVIDIA") == company_url
    assert "BUY" in company.text
    competitor_row = next(row for row in re.findall(r"<tr>(.*?)</tr>", company.text, re.S)
                          if "<strong>COMPETE</strong>" in row)
    assert "Nvidia Corporation" in competitor_row and "TSMC" in competitor_row
    assert "/catalog?" not in competitor_row
    assert "missing.md" not in company.text and "shifted.md" not in company.text

    theme = client.get(link(search(themes_url, "AI Data Center Power Bottleneck"), "AI Data Center Power & Cooling"))
    assert theme.status_code == 200
    assert "AI Data Center Power Bottleneck" in theme.text
    person = client.get(link(search(people_url, "Kenji"), "Kenji Sato"))
    assert person.status_code == 200
    assert "Taiwan ODM" in person.text
    assert "supply_chain_engineer" in person.text
    orphan = client.get(link(client.get(companies_url).text, "Microsoft"))
    assert orphan.status_code == 200
    assert "Technology" in orphan.text
    assert "/catalog?file=" not in orphan.text

    schema = client.get(link(landing.text, "Schema"))
    assert schema.status_code == 200
    assert "Published registry v2. The database still uses v1." in schema.text
    person_schema = client.get(link(schema.text, "Person"))
    field_rows = re.findall(r"<tr>(.*?)</tr>", person_schema.text, re.S)
    for field in ("entity_type", "organization"):
        field_row = next(row for row in field_rows if f"<code>{field}</code>" in row)
        cells = re.findall(r"<td>(.*?)</td>", field_row, re.S)
        assert cells[2].strip() == "Required", f"{field} must be Required in its own row"
    relation = client.get(link(schema.text, "WORKS_AT"))
    paragraph_text = [" ".join(html.unescape(text).split()) for text in re.findall(r"<p>([^<]+)</p>", relation.text)]
    assert "Person → Company, Institution" in paragraph_text
    assert "Directed" in paragraph_text
    assert "Personas" in client.get("/ontology", params={"kind": "people", "lang": "es"}).text
    assert (db_digest(db_path), registry_path.read_bytes(), *(path.read_bytes() for path in fixture_notes)) == before


def _norm_vec(values: list[float]) -> list[float]:
    padded = list(values) + [0.0] * (DIM - len(values))
    norm = math.sqrt(sum(x * x for x in padded)) or 1.0
    return [x / norm for x in padded]


def test_web_ontology_view_connected_to_registry_and_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "web_reg_ontology.db"
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA", "sector": "Semiconductors"},
        )
        vrt = Node(
            id="ent_vrt",
            node_type="entity",
            name="Vertiv",
            summary="Liquid cooling provider.",
            aliases=["VRT"],
            facets={"entity_type": "company", "ticker": "NYSE: VRT"},
        )
        amd = Node(
            id="ent_amd",
            node_type="entity",
            name="AMD",
            summary="Data center GPU challenger.",
            facets={"entity_type": "company", "ticker": "AMD"},
        )
        dell = Node(
            id="ent_dell",
            node_type="entity",
            name="Dell",
            summary="Server OEM.",
            aliases=["HPE"],
            facets={"entity_type": "company"},
        )
        kenji = Node(
            id="ent_kenji",
            node_type="entity",
            name="Kenji Sato",
            summary="Thermal engineer.",
            facets={"entity_type": "person", "role": "engineer"},
        )
        blackwell = Node(
            id="ent_blackwell",
            node_type="entity",
            name="Blackwell GPU",
            summary="Data center GPU.",
            facets={"entity_type": "institution"},
        )
        thm_official_alias = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Rack power and cooling constraints.",
            facets={"stage": "accelerating"},
        )
        thm_unmapped_close = Node(
            id="thm_grid",
            node_type="theme",
            name="Grid-to-Chip Power & Thermal Enablement",
            summary="Utility power and thermal integration.",
            facets={"stage": "accelerating"},
        )
        ev_q3 = Node(
            id="evt_q3",
            node_type="event",
            name="Q3 Earnings",
            summary="Strong data center growth.",
            facets={"event_type": "earnings", "status": "occurred"},
            source_doc_id="doc_1",
        )
        vw_note = Node(
            id="vw_note",
            node_type="view",
            name="Desk Buy Note",
            summary="Bullish GPU demand.",
            facets={
                "view_type": "analyst_report",
                "stance": "buy",
                "catalyst_to_watch": "Rubin ramp",
            },
            source_doc_id="doc_1",
        )

        nodes_vecs = [
            (nvda, unit_vec(0)),
            (vrt, unit_vec(1)),
            (amd, unit_vec(2)),
            (dell, unit_vec(3)),
            (kenji, unit_vec(4)),
            (blackwell, unit_vec(5)),
            (thm_official_alias, _norm_vec([1.0, 0.0, 0.0])),
            (thm_unmapped_close, _norm_vec([0.96, 0.28, 0.0])),
            (ev_q3, unit_vec(8)),
            (vw_note, unit_vec(9)),
        ]
        for node, vec in nodes_vecs:
            db.upsert_node(node, embedding=vec)

        for edge in (
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="ed2", from_id="vw_note", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"}),
            Edge(id="ed3", from_id="ent_vrt", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"}),
            Edge(id="ed4", from_id="ent_vrt", to_id="ent_nvda", relation="COMPETES_WITH", facets={"basis": "extracted"}),
            Edge(id="ed5", from_id="ent_nvda", to_id="ent_kenji", relation="HAS_EMPLOYEE", facets={"basis": "extracted"}),
            Edge(id="ed6", from_id="ent_nvda", to_id="ent_kenji", relation="WORKS_AT", facets={"basis": "extracted"}),
            Edge(id="ed7", from_id="thm_power", to_id="ent_vrt", relation="BENEFITS_FROM", facets={"basis": "extracted"}),
        ):
            seed_edge(db, edge)
        insert_legacy_edge(
            db, Edge(id="ed8", from_id="ent_nvda", to_id="ent_blackwell", relation="PRODUCES", facets={"basis": "extracted"})
        )

    reg_path = tmp_path / "ontology_registry.json"
    reg = create_minimal_registry()
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        audit_rep = run_ontology_audit(ro, reg)
        before_stats = ro.get_stats()
    reg.sync_suggestions(
        audit_rep.unmapped_relations,
        audit_rep.unmapped_companies,
        audit_rep.unmapped_themes,
    )
    save_registry(reg, reg_path)
    reg_before_bytes = reg_path.read_bytes()

    settings = Settings(
        db_path=db_path,
        embedding_dim=DIM,
        data_dir=tmp_path,
        registry_path=reg_path,
    )
    app = create_app(settings, llm=FakeWebLLM())
    client = TestClient(app)

    # 1. /api/health reports loaded registry metadata & pending suggestion counts.
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    health_reg = r_health.json()["registry"]
    assert health_reg["loaded"] is True
    assert health_reg["official_relations"] == 11
    assert health_reg["pending_suggestions"] == {"relations": 1, "companies": 2, "themes": 1}

    # 2. The explicit Entity explorer retains its registry KPIs and SVG relationship counts.
    r_ont = client.get("/ontology", params={"tab": "entity"})
    assert r_ont.status_code == 200
    assert "REGISTRY v1" in r_ont.text
    assert "Official Ontology Registry &amp; Live Audit" in r_ont.text
    assert "OFFICIAL" in r_ont.text
    assert "UNMAPPED" in r_ont.text
    assert "BENEFITS_FROM ↔ (1)" in html.unescape(r_ont.text)

    # 3. Registry status filter on entity tab (official vs unmapped).
    r_ent_off = client.get("/ontology", params={"tab": "entity", "reg_status": "official"})
    assert r_ent_off.status_code == 200
    assert "ent_nvda" in r_ent_off.text
    assert "ent_amd" not in r_ent_off.text

    r_ent_unm = client.get("/ontology", params={"tab": "entity", "reg_status": "unmapped"})
    assert r_ent_unm.status_code == 200
    assert "ent_amd" in r_ent_unm.text
    assert "ent_nvda" not in r_ent_unm.text

    # 4. Theme tab shows aliased official mapping and unmapped nearest-official cosine distance.
    r_thm = client.get("/ontology", params={"tab": "theme"})
    assert r_thm.status_code == 200
    assert "AI Data Center Power &amp; Cooling" in r_thm.text
    assert "Grid-to-Chip Power &amp; Thermal Enablement" in r_thm.text
    assert "d=" in r_thm.text

    # 5. Edges tab shows OFFICIAL, ALIAS, INVERSE (HAS_EMPLOYEE), REVERSED (WORKS_AT), UNMAPPED (PRODUCES).
    r_edges = client.get("/ontology", params={"tab": "edges"})
    assert r_edges.status_code == 200
    for badge_text in ("OFFICIAL", "ALIAS", "INVERSE", "REVERSED", "UNMAPPED"):
        assert badge_text in r_edges.text
    assert "COMPETES_WITH" in r_edges.text
    assert "HAS_EMPLOYEE" in r_edges.text
    assert "PRODUCES" in r_edges.text

    # 6. Registry opens each record, and Schema owns the shared definitions.
    r_reg = client.get("/ontology", params={"tab": "registry"})
    assert r_reg.status_code == 200
    assert "NVIDIA" in r_reg.text and "Vertiv" in r_reg.text
    assert "Official Edge Relations (11)" not in r_reg.text
    for kind, name, target in (
        ("companies", "NVIDIA", "/entity/ent_nvda"),
        ("companies", "Vertiv", "/entity/ent_vrt"),
        ("themes", "AI Data Center Power & Cooling", "/theme/thm_power"),
    ):
        record = client.get("/ontology", params={"tab": "registry", "kind": kind, "record": name})
        assert record.status_code == 200 and target in record.text
        assert client.get(target).status_code == 200
    schema = client.get("/ontology", params={"tab": "schema"})
    assert schema.status_code == 200
    assert all(definition in schema.text for definition in ("BUY", "WORKS_AT", "catalyst_to_watch"))

    # 7. Audit & Suggestions tab lists unmapped items, reversed edges, suspicious aliases, ticker & facet drift.
    r_audit = client.get("/ontology", params={"tab": "audit"})
    assert r_audit.status_code == 200
    assert "PRODUCES" in r_audit.text
    assert "AMD" in r_audit.text
    assert "Grid-to-Chip Power &amp; Thermal Enablement" in r_audit.text
    assert "reversed_direction" in r_audit.text
    assert "HPE" in r_audit.text
    assert "NYSE: VRT" in r_audit.text
    assert "catalyst_to_watch" in r_audit.text

    # 8. Missing registry graceful fallback.
    missing_settings = Settings(
        db_path=db_path,
        embedding_dim=DIM,
        data_dir=tmp_path,
        registry_path=tmp_path / "missing_registry.json",
    )
    missing_client = TestClient(create_app(missing_settings, llm=FakeWebLLM()))
    assert missing_client.get("/ontology").status_code == 200
    assert "NO REGISTRY" in missing_client.get("/ontology").text
    assert missing_client.get("/ontology", params={"tab": "registry"}).status_code == 200
    assert missing_client.get("/ontology", params={"tab": "audit"}).status_code == 200
    r_missing_health = missing_client.get("/api/health")
    assert r_missing_health.status_code == 200
    assert r_missing_health.json()["registry"]["loaded"] is False

    # 9. DB stats and ontology_registry.json remain completely untouched.
    with OntologyDB(db_path, embedding_dim=DIM, read_only=True) as ro:
        assert ro.get_stats() == before_stats
    assert reg_path.read_bytes() == reg_before_bytes


def _finish_registry_edit_job(
    client: TestClient, settings: Settings, response: Any, *, state: str = "succeeded",
) -> dict[str, Any]:
    from stock_ontology.worker import Worker

    assert response.status_code == 202, response.text
    job_url = f"/api/jobs/{response.json()['job_id']}"
    assert client.get(job_url).json()["state"] == "queued"
    Worker(settings, llm_factory=lambda _settings: FakeWebLLM()).run_once(scan=False)
    job = client.get(job_url).json()
    assert job["state"] == state, job
    return job


@pytest.mark.parametrize(
    ("kind", "record", "node_id", "field", "old", "new"),
    [
        pytest.param("companies", "NVIDIA", "company", "sector", "Semiconductors", "Compute Systems", id="company"),
        pytest.param("themes", "AI Infrastructure & Capex", "theme", "stage", "accelerating", "emerging", id="theme"),
    ],
)
def test_ontology_registry_editing_operator_two_decisions(
    tmp_path: Path, kind: str, record: str, node_id: str, field: str, old: str, new: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import secrets
    from inspect import signature

    from stock_ontology.registry import load_registry
    from stock_ontology.worker import Worker

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    facets = {"entity_type": "company", "ticker": "NVDA"} if kind == "companies" else {}
    node = Node(id=node_id, name=record, summary="Research summary", aliases=["Research alias"],
                node_type="entity" if kind == "companies" else "theme", facets={**facets, field: old})
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(node)
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    origin = "http://127.0.0.1:8000"
    # The accepted browsing baseline has no operator switch. Exercise HTTP on both revisions.
    opt_in = {"registry_origin": origin} if "registry_origin" in signature(create_app).parameters else {}
    llm = FakeWebLLM()
    enabled_app = create_app(settings, llm=llm, note_actions=True, **opt_in)
    disabled_app = create_app(settings, llm=llm, note_actions=True)
    client = TestClient(enabled_app, base_url=origin, client=("127.0.0.1", 50000))
    disabled = TestClient(disabled_app, base_url=origin, client=("127.0.0.1", 50000))
    remote = TestClient(enabled_app, base_url=origin, client=("192.0.2.10", 50000))
    headers = {"Origin": origin}
    record_params = {"tab": "registry", "kind": kind, "record": record, "lang": "en"}
    prefix = "/api/ontology/registry"
    publish_preview = f"{prefix}/publish/preview"
    publish_confirm = f"{prefix}/publish/confirm"
    apply_preview = f"{prefix}/apply/preview"
    apply_confirm = f"{prefix}/apply/confirm"
    edit = {"kind": kind, "record": record, "changes": {field: new}}

    def public_state(applied: str, displayed: str) -> None:
        with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
            assert db.applied_registry().revision() == applied
            stored = db.get_node(node_id)
            assert stored.facets[field] == displayed
            assert (stored.summary, stored.aliases) == (node.summary, node.aliases)
        page = client.get("/ontology", params=record_params)
        assert page.status_code == 200
        shown_values = [html.unescape(re.sub(r"<[^>]+>", "", value)).strip().casefold()
                        for value in re.findall(r"<dd\b[^>]*>(.*?)</dd>", page.text, re.S)]
        assert displayed.casefold() in shown_values
        assert (new if displayed == old else old).casefold() not in shown_values

    public_state(registry.revision(), old)
    abandoned = client.post(publish_preview, json=edit, headers=headers)
    assert abandoned.status_code == 200 and abandoned.json()["confirmation"]
    client.get("/ontology", params=record_params)
    assert Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False) == 0
    assert load_registry(settings.registry_path).revision() == registry.revision()
    public_state(registry.revision(), old)
    preview = client.post(publish_preview, json=edit, headers=headers)
    assert preview.status_code == 200, preview.text
    publication = preview.json()
    assert all(value.casefold() in str(publication["diff"]).casefold() for value in (field, old, new))
    assert publication["confirmation"]
    assert "Edit details" in client.get("/ontology", params=record_params).text
    assert "Edit details" not in disabled.get("/ontology", params=record_params).text
    assert "Edit details" not in remote.get("/ontology", params=record_params).text

    def denied(response: Any) -> None:
        assert 400 <= response.status_code < 500, response.text

    for request_client, request_headers in (
        (disabled, headers), (remote, {**headers, "X-Forwarded-For": "127.0.0.1"}),
        (remote, headers),
        (client, {}), (client, {"Origin": "http://localhost:8000"}),
        (client, {**headers, "Host": "localhost:8000"}),
        (client, {**headers, "Forwarded": "for=127.0.0.1"}),
    ):
        denied(request_client.post(publish_preview, headers=request_headers, json=edit))
        denied(request_client.post(publish_confirm, headers=request_headers,
                                   json={"confirmation": publication["confirmation"]}))
        denied(request_client.post(apply_preview, headers=request_headers, json={}))
        denied(request_client.post(apply_confirm, headers=request_headers,
                                   json={"confirmation": publication["confirmation"]}))
    denied(client.post(publish_confirm, headers=headers, json={"confirmation": "unreviewed"}))
    denied(client.post(publish_preview, headers=headers, json={**edit, "proposal_path": "anything.json"}))
    assert Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False) == 0
    assert load_registry(settings.registry_path).revision() == registry.revision()
    public_state(registry.revision(), old)

    _finish_registry_edit_job(client, settings, client.post(
        publish_confirm, headers=headers, json={"confirmation": publication["confirmation"]},
    ))
    published = load_registry(settings.registry_path)
    selected = next(item for item in getattr(published, kind) if item.name == record)
    assert published.version == registry.version + 1 and getattr(selected, field) == new
    public_state(registry.revision(), old)
    denied(client.post(publish_confirm, headers=headers, json={"confirmation": publication["confirmation"]}))
    denied(client.post(apply_confirm, headers=headers, json={"confirmation": publication["confirmation"]}))

    abandoned_apply = client.post(apply_preview, headers=headers, json={})
    assert _finish_registry_edit_job(client, settings, abandoned_apply)["result"]["confirmation"]
    client.get("/ontology", params=record_params)
    assert Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False) == 0
    assert load_registry(settings.registry_path).revision() == published.revision()
    public_state(registry.revision(), old)

    # Know the genuine opaque reference before the server reveals it in the completed result.
    early_reference = "worker-preview-reference-before-completion"
    with monkeypatch.context() as entropy:
        entropy.setattr(secrets, "token_urlsafe", lambda _size: early_reference)
        queued_preview = client.post(apply_preview, headers=headers, json={})
    assert queued_preview.status_code == 202, queued_preview.text
    pending = client.get(f"/api/jobs/{queued_preview.json()['job_id']}").json()
    assert pending["state"] == "queued" and not pending["result"]
    assert early_reference not in str(pending)
    denied(client.post(apply_confirm, headers=headers, json={"confirmation": early_reference}))
    denied(client.post(apply_confirm, headers=headers, json={"confirmation": queued_preview.json()["job_id"]}))
    reviewed = _finish_registry_edit_job(client, settings, queued_preview)["result"]
    assert reviewed["confirmation"] == early_reference
    diff = str(reviewed["diff"]).casefold()
    assert all(value.casefold() in diff for value in (field, old, new))
    assert node_id in diff or record.casefold() in diff
    public_state(registry.revision(), old)

    # A graph edit after review makes the exact old plan stale.
    with OntologyDB(settings.db_path, embedding_dim=DIM) as db:
        db.upsert_node(node.model_copy(update={"summary": "New research summary"}))
    rejected = client.post(apply_confirm, headers=headers, json={"confirmation": reviewed["confirmation"]})
    if rejected.status_code == 202:
        _finish_registry_edit_job(client, settings, rejected, state="failed")
    else:
        denied(rejected)
    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.applied_registry().revision() == registry.revision()
        assert db.get_node(node_id).facets[field] == old
    node = node.model_copy(update={"summary": "New research summary"})

    fresh = _finish_registry_edit_job(client, settings, client.post(apply_preview, headers=headers, json={}))
    confirmation = {"confirmation": fresh["result"]["confirmation"]}
    _finish_registry_edit_job(client, settings, client.post(apply_confirm, headers=headers, json=confirmation))
    denied(client.post(apply_confirm, headers=headers, json=confirmation))
    assert Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False) == 0
    public_state(published.revision(), new)
    assert load_registry(settings.registry_path).revision() == published.revision()


@pytest.mark.parametrize("case", ["person", "relationship", "wrong-owner", "stale-note"])
def test_ontology_registry_editing_note_correction(tmp_path: Path, case: str) -> None:
    from stock_ontology.worker import Worker

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    registry.facet_schema.setdefault("relation", {})["WORKS_AT"] = {"role": {"kind": "text", "required": False}}
    save_registry(registry, settings.registry_path)
    old, new = "Process Engineer", "Fabrication Director"
    note_sources = {"selected.md": "Selected employment source.\n", "other.md": "Independent employment source.\n"}
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(Node(id="person", name="Robin Lee", summary="", node_type="entity",
                            facets={"entity_type": "person", "role": old, "organization": "NVIDIA"}))
        db.upsert_node(Node(id="company", name="NVIDIA", summary="", node_type="entity",
                            facets={"entity_type": "company", "ticker": "NVDA"}))
        for index, (file, content) in enumerate(note_sources.items()):
            (tmp_path / file).write_text(content, encoding="utf-8")
            db.upsert_ingestion_log(file, f"doc-{index}", hashlib.sha256(content.encode()).hexdigest(),
                                    entity_ids=("person", "company"))
            db.upsert_edge(Edge(id=f"employment-{index}", from_id="person", to_id="company",
                                relation="WORKS_AT", source_doc_id=f"doc-{index}",
                                facets={"basis": "extracted", "role": old}))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True))
    preview_url = "/api/ontology/corrections/preview"
    confirm_url = "/api/ontology/corrections/confirm"
    record_params = {"tab": "registry", "kind": "people", "record": "person", "lang": "en"}
    page = client.get("/ontology", params=record_params)
    assert page.status_code == 200 and old in page.text and "selected.md" in page.text
    if case in {"person", "stale-note"}:
        edit = {"kind": "person", "file": "selected.md", "record": "person", "changes": {"role": new}}
    else:
        edit = {"kind": "relationship", "file": "selected.md", "edge_id": "employment-0",
                "changes": {"facets": {"role": new}}}
    review = client.post(preview_url, json=edit)
    assert review.status_code == 200, review.text
    assert all(value in str(review.json()["diff"]) for value in (old, new))
    if case == "wrong-owner":
        unrelated = client.post(preview_url, json={**edit, "file": "other.md"})
        assert 400 <= unrelated.status_code < 500, unrelated.text
        assert Worker(settings, llm_factory=lambda _settings: FakeWebLLM()).run_once(scan=False) == 0
    else:
        if case == "stale-note":
            note_sources["selected.md"] += "Changed after review.\n"
        response = client.post(confirm_url, json={"confirmation": review.json()["confirmation"]})
        if case == "stale-note":
            # Race the queued correction: the worker must recheck the supporting file at commit.
            assert response.status_code == 202, response.text
            (tmp_path / "selected.md").write_text(note_sources["selected.md"], encoding="utf-8")
        _finish_registry_edit_job(client, settings, response, state="failed" if case == "stale-note" else "succeeded")

    expected_role = new if case == "person" else old
    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        assert db.get_node("person").facets["role"] == expected_role
        assert [person.id for person in db.list_nodes(node_type="entity")
                if person.facets.get("entity_type") == "person"] == ["person"]
        for index, role in enumerate((new if case in {"person", "relationship"} else old, old)):
            retained, = db.list_note_edges(f"doc-{index}")
            assert (retained["edge_id"], retained["from_id"], retained["to_id"], retained["relation"]) == (
                f"employment-{index}", "person", "company", "WORKS_AT",
            )
            assert retained["facets"] == {"basis": "extracted", "role": role}
            assert {entity.id for entity in db.list_note_entities(f"doc-{index}")} == {"person", "company"}
    for file, content in note_sources.items():
        assert (tmp_path / file).read_bytes() == content.encode()
    record = client.get("/ontology", params=record_params).text
    assert expected_role in record
    if case == "relationship":
        assert new in record


@pytest.mark.parametrize("case", ["source-options", "unrelated-http", "authorized", "ownership-race"])
def test_ontology_registry_editing_relationship_add_source(tmp_path: Path, case: str) -> None:
    from stock_ontology.worker import Worker

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    note_sources = {
        "related.md": ("Anchor employment source.\n", "person"),
        "unrelated.md": ("Research about another company.\n", "other"),
    }
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name, entity_type in (
            ("person", "Robin Lee", "person"), ("company", "NVIDIA", "company"), ("other", "TSMC", "company"),
        ):
            db.upsert_node(Node(id=node_id, name=name, summary="", node_type="entity", facets={"entity_type": entity_type}))
        for file, (content, member) in note_sources.items():
            (tmp_path / file).write_text(content, encoding="utf-8")
            db.upsert_ingestion_log(file, file, hashlib.sha256(content.encode()).hexdigest(), entity_ids=(member,))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    llm = FakeWebLLM()
    client = TestClient(create_app(settings, llm=llm, note_actions=True))
    preview_url = "/api/ontology/corrections/preview"
    confirm_url = "/api/ontology/corrections/confirm"
    record_params = {"tab": "registry", "kind": "people", "record": "person", "lang": "en"}
    edit = {"kind": "relationship_add", "record": "person", "file": "related.md",
            "changes": {"from_id": "person", "to_id": "company", "relation": "WORKS_AT"}}
    review = client.post(preview_url, json=edit)
    assert review.status_code == 200, review.text
    assert "WORKS_AT" in str(review.json()["diff"])

    if case == "source-options":
        page = client.get("/ontology", params=record_params)
        assert page.status_code == 200
        form = re.search(r'<form\b[^>]*\bdata-kind="relationship_add"[^>]*>(.*?)</form>', page.text, re.S)
        assert form is not None
        offered = re.findall(r'<option\b[^>]*\bvalue="([^"]+)"', form[1])
        assert offered == ["related.md"]
    elif case == "unrelated-http":
        denied = client.post(preview_url, json={**edit, "file": "unrelated.md"})
        assert 400 <= denied.status_code < 500, denied.text
        assert Worker(settings, llm_factory=lambda _settings: llm).run_once(scan=False) == 0
    else:
        confirmed = client.post(confirm_url, json={"confirmation": review.json()["confirmation"]})
        if case == "ownership-race":
            assert confirmed.status_code == 202, confirmed.text
            with OntologyDB(settings.db_path, embedding_dim=DIM) as db:
                assert db.remove_note_entity("related.md", "person")
        _finish_registry_edit_job(client, settings, confirmed, state="failed" if case == "ownership-race" else "succeeded")

    with OntologyDB(settings.db_path, embedding_dim=DIM, read_only=True) as db:
        assert {node.id for node in db.list_note_entities("unrelated.md")} == {"other"}
        assert db.list_note_edges("unrelated.md") == []
        expected_members = {"person", "company"} if case == "authorized" else {"person"}
        if case == "ownership-race":
            expected_members = set()
        assert {node.id for node in db.list_note_entities("related.md")} == expected_members
        edges = db.list_note_edges("related.md")
        if case == "authorized":
            edge, = edges
            assert (edge["from_id"], edge["relation"], edge["to_id"]) == ("person", "WORKS_AT", "company")
        else:
            assert edges == []
    for file, (content, _) in note_sources.items():
        assert (tmp_path / file).read_text(encoding="utf-8") == content
    if case == "authorized":
        page = client.get("/ontology", params=record_params)
        assert "NVIDIA" in page.text and "related.md" in page.text


@pytest.mark.parametrize(
    ("kind", "record", "changed", "replacement", "blank"),
    [
        pytest.param("companies", "Independent Foundry", "ticker", "INDP", "sector", id="company"),
        pytest.param("people", "person", "role", "Thermal Architect", "organization", id="person"),
    ],
)
def test_ontology_registry_editing_optional_details(
    tmp_path: Path, kind: str, record: str, changed: str, replacement: str, blank: str,
) -> None:
    from inspect import signature

    from stock_ontology.registry import CompanySpec

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    registry.companies.append(CompanySpec(name="Independent Foundry", ticker="IFND"))
    save_registry(registry, settings.registry_path)
    source = tmp_path / "profile.md"
    source.write_text("Role research.\n", encoding="utf-8")
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(Node(id="person", name="Robin Lee", summary="", node_type="entity",
                            facets={"entity_type": "person", "role": "Engineer"}))
        db.upsert_ingestion_log(source.name, "profile", hashlib.sha256(source.read_bytes()).hexdigest(),
                                entity_ids=("person",))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    origin = "http://127.0.0.1:8000"
    opt_in = {"registry_origin": origin} if "registry_origin" in signature(create_app).parameters else {}
    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True, **opt_in),
                        base_url=origin, client=("127.0.0.1", 50000))
    page = client.get("/ontology", params={"tab": "registry", "kind": kind, "record": record, "lang": "en"})
    assert page.status_code == 200
    edit = {"record": record, "changes": {changed: replacement}}
    if kind == "people":
        preview = client.post("/api/ontology/corrections/preview", json={**edit, "kind": "person", "file": source.name})
    else:
        preview = client.post("/api/ontology/registry/publish/preview", json={**edit, "kind": kind}, headers={"Origin": origin})
    assert preview.status_code == 200, preview.text
    assert replacement in str(preview.json()["diff"])
    assert blank not in str(preview.json()["diff"])

    details = re.search(r'<summary>\s*Edit details\s*</summary>\s*(<form\b.*?</form>)', page.text, re.S)
    assert details is not None
    assert re.search(rf'<input\b[^>]*\bdata-edit-field="{changed}"', details[1])
    optional = re.search(rf'<input\b[^>]*\bdata-edit-field="{blank}"[^>]*>', details[1])
    assert optional is not None and 'value=""' in optional[0]
    assert not re.search(r'\srequired(?:\s|=|>)', optional[0], re.I), optional[0]
    assert re.search(r'<button\b[^>]*\btype="submit"', details[1])


@pytest.mark.parametrize("lang", ["en", "zh", "fr"])
def test_service_errors_reach_the_browser_in_the_viewer_language(tmp_path: Path, lang: str) -> None:
    from inspect import signature

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    save_registry(create_minimal_registry(), settings.registry_path)
    origin = "http://127.0.0.1:8000"
    opt_in = {"registry_origin": origin} if "registry_origin" in signature(create_app).parameters else {}
    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True, **opt_in),
                        base_url=origin, client=("127.0.0.1", 50000))

    response = client.post("/api/ontology/registry/publish/confirm", params={"lang": lang},
                           json={"confirmation": "expired"}, headers={"Origin": origin})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == translate("service_error.review_expired", lang=lang)
    if lang != "en":
        assert response.json()["detail"] != translate("service_error.review_expired", lang="en")


def test_service_error_enum_params_are_translated() -> None:
    from stock_ontology.i18n import translate_enum
    from stock_ontology.services import ServiceError
    from stock_ontology.web.shell import http_error

    exc = ServiceError("conflict", "Only a failed job can be retried; this one is running.",
                       key="service_error.retry_not_failed", params={"state": "running"}, enums={"state": "job_state"})

    detail = http_error(exc, "en").detail
    assert detail == translate("service_error.retry_not_failed", lang="en", state=translate_enum("job_state", "running"))
    assert "running" in detail


def test_person_details_form_edits_accuracy(tmp_path: Path) -> None:
    from inspect import signature

    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = load_registry(Path(__file__).resolve().parents[1] / "ontology_registry.json")
    save_registry(registry, settings.registry_path)
    source = tmp_path / "profile.md"
    source.write_text("Rumor source.\n", encoding="utf-8")
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        db.upsert_node(Node(id="person", name="Robin Lee", summary="", node_type="entity",
                            facets={"entity_type": "person", "role": "Trader", "organization": "Desk",
                                    "accuracy": "medium"}))
        db.upsert_ingestion_log(source.name, "profile", hashlib.sha256(source.read_bytes()).hexdigest(),
                                entity_ids=("person",))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")

    origin = "http://127.0.0.1:8000"
    opt_in = {"registry_origin": origin} if "registry_origin" in signature(create_app).parameters else {}
    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True, **opt_in),
                        base_url=origin, client=("127.0.0.1", 50000))
    page = client.get("/ontology", params={"tab": "registry", "kind": "people", "record": "person", "lang": "en"})
    assert page.status_code == 200
    details = re.search(r'<summary>\s*Edit details\s*</summary>\s*(<form\b.*?</form>)', page.text, re.S)
    assert details is not None
    select = re.search(r'<select\b[^>]*\bdata-edit-field="accuracy".*?</select>', details[1], re.S)
    assert select is not None
    assert re.search(r'<option value="medium" selected>', select[0])
    assert re.search(r'<option value="">Unrated</option>', select[0])

    edit = {"record": "person", "kind": "person", "file": source.name}
    preview = client.post("/api/ontology/corrections/preview", json={**edit, "changes": {"accuracy": "low"}})
    assert preview.status_code == 200, preview.text
    assert {"field": "accuracy", "before": "medium", "after": "low"}.items() <= preview.json()["diff"][0].items()
    unrated = client.post("/api/ontology/corrections/preview", json={**edit, "changes": {"accuracy": ""}})
    assert unrated.status_code == 200, unrated.text
    assert unrated.json()["diff"][0]["after"] is None
    bad = client.post("/api/ontology/corrections/preview", json={**edit, "changes": {"accuracy": "excellent"}})
    assert bad.status_code in {400, 422}, bad.text


def test_note_reader_and_ontology_record_share_one_relationship_editor(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    content = "Anchor employment source.\n"
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name, entity_type in (("person", "Robin Lee", "person"), ("company", "NVIDIA", "company")):
            db.upsert_node(Node(id=node_id, name=name, summary="", node_type="entity", facets={"entity_type": entity_type}))
        (tmp_path / "related.md").write_text(content, encoding="utf-8")
        db.upsert_ingestion_log("related.md", "related.md", hashlib.sha256(content.encode()).hexdigest(),
                                entity_ids=("person",))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True))

    pages = {
        "note_reader.js": client.get("/catalog", params={"file": "related.md", "lang": "fr"}),
        "ontology_edit.js": client.get(
            "/ontology", params={"tab": "registry", "kind": "people", "record": "person", "lang": "fr"}),
    }
    models = []
    for page_script, page in pages.items():
        assert page.status_code == 200, page.text
        embedded = re.search(r'<script type="application/json" id="relationship-editor-model">(.*?)</script>',
                             page.text, re.S)
        assert embedded is not None, page_script
        models.append(json.loads(embedded[1]))
        scripts = re.findall(r'<script\b[^>]*\bsrc="[^"]*/static/([\w.]+)"', page.text)
        assert "editor.js" in scripts and scripts.index("editor.js") < scripts.index(page_script)

    assert models[0] == models[1]
    model = models[0]
    # Only the node both pages show (the note's entity, the record's anchor); the editors search for the rest.
    assert {node["id"]: node["type"] for node in model["nodes"]} == {"person": "entity:person"}
    works_at = next(item for item in model["relations"] if item["name"] == "WORKS_AT")
    assert works_at["label"] == translate_enum("relation", "WORKS_AT", lang="fr")
    assert [field["name"] for field in works_at["fields"]] == ["sentiment"]
    sentiment = works_at["fields"][0]
    assert sentiment["label"] == translate_facet_label("sentiment", lang="fr")
    assert sentiment["options"] == [
        [value, translate_enum("sentiment", value, lang="fr")]
        for value in next(field.options for field in registry.field_specs(None) if field.name == "sentiment")
    ]


def test_page_scripts_post_and_poll_jobs_through_the_shared_editor_script() -> None:
    static = Path(stock_ontology.web.__file__).parent / "static"
    for name in ("note_reader.js", "ontology_edit.js"):
        script = (static / name).read_text(encoding="utf-8")
        assert "window.StockEditor" in script, name
        assert "/api/jobs/" not in script and '"POST"' not in script, name


def test_editors_find_nodes_by_search_instead_of_loading_the_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "graph.db", registry_path=tmp_path / "registry.json",
                        data_dir=tmp_path, embedding_dim=DIM)
    registry = create_minimal_registry()
    save_registry(registry, settings.registry_path)
    content = "Robin Lee works at NVIDIA.\n"
    with OntologyDB(settings.db_path, embedding_dim=DIM, registry=registry) as db:
        for node_id, name, entity_type, aliases in (
            ("person", "Robin Lee", "person", []), ("company", "NVIDIA", "company", []),
            ("tsmc", "Taiwan Semiconductor", "company", ["TSMC"]), ("alex", "Alex Taiwo", "person", []),
        ):
            db.upsert_node(Node(id=node_id, name=name, summary="", aliases=aliases, node_type="entity",
                                facets={"entity_type": entity_type}))
        db.upsert_node(Node(id="theme", name="Taiwan supply chain", summary="", node_type="theme",
                            facets={"stage": "emerging"}))
        db.upsert_edge(Edge(id="employment-0", from_id="person", to_id="company", relation="WORKS_AT",
                            source_doc_id="related.md", facets={"basis": "extracted"}))
        (tmp_path / "related.md").write_text(content, encoding="utf-8")
        db.upsert_ingestion_log("related.md", "related.md", hashlib.sha256(content.encode()).hexdigest(),
                                entity_ids=("person", "company"))
        db.record_registry_adoption(registry, from_revision=None, plan="fixture")
    client = TestClient(create_app(settings, llm=FakeWebLLM(), note_actions=True))

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("an editor page loaded the whole graph")

    original_list_nodes = OntologyDB.list_nodes
    monkeypatch.setattr(OntologyDB, "list_all_nodes", refuse)
    monkeypatch.setattr(OntologyDB, "list_nodes", lambda self, node_type=None, limit=100: (
        refuse() if limit < 0 else original_list_nodes(self, node_type, limit)))
    pages = (
        client.get("/catalog", params={"file": "related.md", "lang": "en"}),
        client.get("/ontology", params={"tab": "registry", "kind": "companies", "record": "NVIDIA", "lang": "en"}),
    )
    for page in pages:
        assert page.status_code == 200, page.text
        embedded = re.search(r'<script type="application/json" id="relationship-editor-model">(.*?)</script>',
                             page.text, re.S)
        assert embedded is not None
        assert {node["id"] for node in json.loads(embedded[1])["nodes"]} == {"person", "company"}
        assert "Taiwan Semiconductor" not in page.text
    reader = pages[0].text
    assert "data-note-entity-add" in reader and "data-note-add" in reader  # Graph has nodes the note lacks.

    def found(query: str, *types: str) -> list[str]:
        response = client.get("/api/nodes/search", params=[("q", query), *(("type", item) for item in types)])
        assert response.status_code == 200, response.text
        return [node["id"] for node in response.json()["nodes"]]

    assert found("taiw") == ["tsmc", "theme", "alex"]  # names starting with the query first
    assert found("tsmc", "entity:company") == ["tsmc"]
    assert found("taiw", "entity:company") == ["tsmc"]
    assert found("taiw", "entity") == ["tsmc", "alex"]
    assert found("taiw", "theme", "entity:person") == ["theme", "alex"]
    assert client.get("/api/nodes/search", params={"q": "taiwan s", "type": "theme", "lang": "en"}).json()["nodes"][0] == {
        "id": "theme", "label": "Taiwan supply chain (theme)", "type": "theme"}
    assert found("") == []
