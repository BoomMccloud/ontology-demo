"""Shared fixtures for the web test modules: the seeded graph, the fake LLM, and template checks."""

from __future__ import annotations

import dataclasses
import hashlib
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.models import ConsensusSynthesis, Edge, ExtractionResult, Node
from stock_ontology.web import create_app

DIM = 16


def unit_vec(idx: int) -> list[float]:
    vec = [0.0] * DIM
    vec[idx % DIM] = 1.0
    return vec


def seed_web_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU and NVLink rack platform leader.",
            aliases=["NVDA"],
            facets={
                "entity_type": "company",
                "ticker": "NVDA",
                "sector": "Semiconductors",
                "custom_metric": "42GW",
            },
        )
        tsmc = Node(
            id="ent_tsmc",
            node_type="entity",
            name="TSMC",
            summary="Leading-edge foundry and CoWoS supplier.",
            aliases=["TSM"],
            facets={"entity_type": "company", "ticker": "TSM", "sector": "Semiconductors"},
        )
        kenji = Node(
            id="ent_kenji",
            node_type="entity",
            name="Kenji Sato",
            summary="Senior thermal engineer at Taiwan ODM.",
            facets={
                "entity_type": "person",
                "role": "supply_chain_engineer",
                "organization": "Taiwan ODM",
                "credibility": "high",
                "specialty": "Liquid Cooling CDUs",
            },
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power and rack cooling density constraints.",
            facets={"stage": "accelerating", "horizon": "12-24m"},
        )
        ev = Node(
            id="evt_q3",
            node_type="event",
            name="Blackwell Rack Ramp",
            summary="GB200 NVL72 shipping in Q4.",
            facets={
                "event_type": "fact",
                "event_date": "2026-10-15",
                "status": "occurred",
                "source": {"file_path": "NVDA/2026-10-15_q3.md"},
            },
            source_doc_id="doc_1",
        )
        vw = Node(
            id="vw_analyst",
            node_type="view",
            name="Morgan Buy View",
            summary="Buy on CUDA moat.",
            facets={
                "view_type": "analyst_report",
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-10-15",
                "source": {"file_path": "NVDA/2026-10-15_q3.md"},
            },
            source_doc_id="doc_1",
        )
        cons = Node(
            id="vw_cons_nvda",
            node_type="view",
            name="Consensus: Buy NVIDIA",
            summary="Maintain Buy driven by hyperscaler capex.",
            facets={
                "view_type": "consensus",
                "stance": "buy",
                "support_strength": "strong",
                "conviction": "high",
                "as_of": "2026-11-20",
                "pillars": ["Hyperscaler capex >20%", "Rack thermal issues stay localized"],
            },
        )

        for idx, n in enumerate([nvda, tsmc, kenji, theme, ev, vw]):
            db.upsert_node(n, embedding=unit_vec(idx))

        db.upsert_edge(
            Edge(id="ed1", from_id="evt_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed2", from_id="vw_analyst", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed3", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed4", from_id="ent_tsmc", to_id="ent_nvda", relation="SUPPLIES_TO", facets={"basis": "extracted"})
        )
        db.upsert_edge(
            Edge(id="ed5", from_id="evt_q3", to_id="ent_kenji", relation="AUTHORED_BY", source_doc_id="doc_1", facets={"basis": "extracted"})
        )
        db.upsert_consensus_view("ent_nvda", cons, unit_vec(7), ["evt_q3", "vw_analyst", "thm_power"], [])


class FakeWebLLM:
    def __init__(self) -> None:
        self.seen_system_instructions: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [unit_vec(0) for _ in texts]

    def extract_document(self, **kwargs: Any) -> ExtractionResult:
        raise NotImplementedError

    def synthesize_consensus(self, **kwargs: Any) -> ConsensusSynthesis:
        raise NotImplementedError

    @property
    def model(self) -> FunctionModel:
        """The Clippy agent's chat model, for `create_app(..., agent_model=llm.model)`."""
        return FunctionModel(self.respond, model_name="fake-web")

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.seen_system_instructions.append(info.instructions or "")
        last = next(m for m in reversed(messages) if isinstance(m, ModelRequest)).parts[-1]
        if isinstance(last, UserPromptPart):
            return ModelResponse(parts=[ToolCallPart("get_entity_overview", {"entity_name_or_id": "NVDA"})])
        if isinstance(last, ToolReturnPart):
            stance = last.content["consensus"]["facets"]["stance"]
            prior_turns = sum(
                1
                for m in messages
                if isinstance(m, ModelRequest)
                for p in m.parts
                if isinstance(p, UserPromptPart)
            )
            return ModelResponse(
                parts=[TextPart(f"NVDA consensus is {stance}. Conversation user turns={prior_turns}.")]
            )
        return ModelResponse(parts=[TextPart("Ready.")])


# ---------------------------------------------------------------------------
# Presentation-model contract for the entity page (proposal `company-view-separation`)
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "stock_ontology" / "web" / "templates"


RAW_FACET_KEYS = ("facets", "edge_facets")


# Attribute or key access to `facets` / `edge_facets`. Prepared pairs such as
# `company_facets` and translation keys such as `'facets.col_value'` don't match.
RAW_FACET_TOKEN = re.compile(r"""\.(?:edge_)?facets\b|\[\s*['"](?:edge_)?facets['"]\s*\]""")


def template_closure(name: str) -> set[str]:
    """Return `name` plus every template it includes, followed transitively."""
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        text = (TEMPLATES_DIR / current).read_text(encoding="utf-8")
        pending.extend(re.findall(r'{%-?\s*include\s+"([^"]+)"', text))
    return seen


def raw_facet_paths(value: Any, path: str = "ctx") -> list[str]:
    """List every place in a template context where a raw facets mapping is still reachable."""
    found: list[str] = []
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            if field.name in RAW_FACET_KEYS:
                found.append(f"{path}.{field.name}")
            found.extend(raw_facet_paths(getattr(value, field.name), f"{path}.{field.name}"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in RAW_FACET_KEYS:
                found.append(f"{path}[{key!r}]")
            found.extend(raw_facet_paths(item, f"{path}[{key!r}]"))
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            found.extend(raw_facet_paths(item, f"{path}[{idx}]"))
    return found


# --- Generic ontology search (ledger: docs/proposals/ontology-search.md) ---
#
# Page contract the search page exposes, used by the witnesses below:
#   - the best-match card is one element with `data-best-match`, `data-result-id`, and
#     `data-match-reason`;
#   - every listed ontology item is an element with `data-result-id` and `data-match-reason`
#     (one of name, alias, relationship, note, semantic);
#   - every grepped note passage is an element with `data-note-file` (path relative to
#     ONTOLOGY_DATA_DIR), `data-note-line` (1-based), and `data-match-reason="note"`;
#   - the agent note is one element with `data-agent-column` and `data-agent-query`
#     (the search word, empty when there is none); clippy.js moves it into the Clippy dock.

SEARCH_NOTE_FILE = "Notes/2026-11-10_channel_check.md"


SEARCH_EVENT_FILE = "NVDA/2026-11-01_q3.md"


def seed_search_db(db_path: Path) -> None:
    with OntologyDB(db_path, embedding_dim=DIM, read_only=False) as db:
        nvda = Node(
            id="ent_nvda",
            node_type="entity",
            name="NVIDIA",
            summary="AI GPU platform leader.",
            aliases=["NVDA"],
            facets={"entity_type": "company", "ticker": "NVDA"},
        )
        aapl = Node(
            id="ent_aapl",
            node_type="entity",
            name="Apple Inc.",
            summary="Consumer devices and services.",
            aliases=["AAPL"],
            facets={"entity_type": "company", "ticker": "AAPL"},
        )
        theme = Node(
            id="thm_power",
            node_type="theme",
            name="AI Data Center Power Bottleneck",
            summary="Grid power and rack cooling density constraints.",
            facets={"stage": "accelerating"},
        )
        event = Node(
            id="evt_nvda_q3",
            node_type="event",
            name="Q3 Data Center Beat",
            summary="Data center revenue beat guidance.",
            facets={
                "event_type": "fact",
                "event_date": "2026-11-01",
                "status": "occurred",
                "source": {"file_path": SEARCH_EVENT_FILE},
            },
            source_doc_id="doc_q3",
        )
        db.upsert_node(nvda, embedding=unit_vec(1))
        db.upsert_node(aapl, embedding=unit_vec(2))
        db.upsert_node(theme, embedding=unit_vec(3))
        db.upsert_node(event, embedding=unit_vec(4))
        db.upsert_edge(Edge(id="se1", from_id="ent_nvda", to_id="thm_power", relation="EXPOSED_TO", facets={"basis": "extracted"}))
        db.upsert_edge(
            Edge(id="se2", from_id="evt_nvda_q3", to_id="ent_nvda", relation="ABOUT", source_doc_id="doc_q3", facets={"basis": "extracted"})
        )
        # FakeWebLLM embeds every query as unit_vec(0), so this consensus is the nearest vector.
        cons = Node(
            id="vw_cons_aapl",
            node_type="view",
            name="Consensus: Buy Apple Inc.",
            summary="Maintain Buy on services growth.",
            facets={"stance": "buy", "as_of": "2026-11-15", "view_type": "analyst_report"},
        )
        db.upsert_consensus_view("ent_aapl", cons, unit_vec(0), [], [])


def seed_search_notes(data_dir: Path) -> None:
    (data_dir / "Notes").mkdir(parents=True)
    (data_dir / SEARCH_NOTE_FILE).write_text(
        "# Channel check\n\nChannel check: NVIDIA lead times shortened.\n",
        encoding="utf-8",
    )
    (data_dir / "NVDA").mkdir(parents=True)
    (data_dir / SEARCH_EVENT_FILE).write_text(
        "# Q3 call\n\nNVIDIA data center revenue beat guidance.\n",
        encoding="utf-8",
    )


def search_client(tmp_path: Path, llm: Any) -> tuple[TestClient, Path, Path]:
    db_path = tmp_path / "search.db"
    seed_search_db(db_path)
    data_dir = tmp_path / "data"
    seed_search_notes(data_dir)
    settings = Settings(db_path=db_path, embedding_dim=DIM, data_dir=data_dir)
    return TestClient(create_app(settings, llm=llm, agent_model=llm.model)), db_path, data_dir


def note_tree(root: Path) -> dict[str, bytes]:
    """Every regular file under `root`, hidden ones included, without following links."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def db_digest(db_path: Path) -> tuple[str, int]:
    return hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns
