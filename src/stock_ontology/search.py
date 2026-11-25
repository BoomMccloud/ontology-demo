"""Generic, entity-first ontology search shared by the web search page and the PM agent.

For a search word it resolves matching entities first (name, then alias, then keyword,
then vector search), expands one hop from those entities through their edges (edges are
never results of their own), greps the raw research notes under the data directory, and
labels every result with why it matched. It only reads: the DB through `OntologyDB`'s
read methods and the notes through a traversal-safe walk of the data directory.

Match reasons: `name`, `alias`, `relationship` (reached through an edge from a matched
entity), `note` (the word occurs in the item's extracted text or in a raw note line), and
`semantic` (vector similarity). Filter-only listings, with no search word, use `filter`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from stock_ontology.config import SUPPORTED_EXTENSIONS
from stock_ontology.db import OntologyDB
from stock_ontology.llm import LLMClient
from stock_ontology.models import Node, NodeType, resolve_item_sentiment
from stock_ontology.registry import normalize_relation_name
from stock_ontology.vocab import (
    matches_signal_filter,
    parse_category_filter,
    parse_sentiment_filter,
)
from stock_ontology.vocab import node_subtype as _stored_subtype

NODE_TYPES: tuple[str, ...] = ("entity", "event", "view", "theme")

# Base score per match reason; semantic hits scale with similarity below this ceiling.
REASON_WEIGHT: dict[str, float] = {
    "name": 1.0,
    "alias": 0.9,
    "relationship": 0.7,
    "note": 0.6,
    "semantic": 0.5,
    "filter": 0.0,
}
EXACT_NAME_BONUS = 0.2
RECENCY_WEIGHT = 0.1
RECENCY_HORIZON_DAYS = 730
PERIOD_BOOST = 0.3
MAX_EXPANSION_SEEDS = 5
MAX_NOTE_BYTES = 5_000_000
# Per-search budget for the note grep, so a large notes folder cannot stall a search.
MAX_NOTE_FILES = 2_000
MAX_GREP_BYTES = 50_000_000
MAX_PASSAGE_CHARS = 300


# --- Node field helpers -----------------------------------------------------


def node_subtype(node: Node) -> str:
    return _stored_subtype(node.node_type, node.facets or {})


def node_date(node: Node) -> str:
    facets = node.facets or {}
    raw = facets.get("event_date") or facets.get("as_of")
    if not raw and isinstance(facets.get("source"), dict):
        raw = facets["source"].get("date")
    return str(raw or "").strip()


def node_source_file(node: Node) -> str:
    src = (node.facets or {}).get("source")
    if isinstance(src, dict):
        return str(src.get("file_path") or "").strip()
    return ""


# --- Safe note paths and grep ----------------------------------------------


def resolve_safe_note_path(data_dir: Path, rel_path: str) -> Path | None:
    """Resolve `rel_path` strictly inside `data_dir`, rejecting traversal or hidden files."""
    if not rel_path or "\x00" in rel_path:
        return None
    if rel_path.startswith(("/", "\\")) or "\\" in rel_path:
        return None
    parts = rel_path.split("/")
    if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        return None
    try:
        root = data_dir.resolve()
        if not root.exists() or not root.is_dir():
            return None
        candidate = (root / rel_path).resolve()
        if not candidate.is_relative_to(root):
            return None
        rel_parts = candidate.relative_to(root).parts
        if not rel_parts or any(part.startswith(".") for part in rel_parts):
            return None
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None
    except (OSError, ValueError):
        return None
    return candidate


@dataclass(frozen=True)
class NotePassage:
    """One raw note line containing the search word: file relative to the data dir, 1-based line."""

    file: str
    line: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "text": self.text}


def _iter_note_files(data_dir: Path) -> Iterator[tuple[str, Path]]:
    """Supported, non-hidden note files under `data_dir`, never leaving it through a link.

    A generator, so a capped grep stops walking as soon as it stops reading.
    """
    try:
        root = data_dir.resolve()
        if not root.is_dir():
            return
    except OSError:
        return
    # os.walk does not descend into symlinked directories by default.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        base = Path(dirpath)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            rel = (base / name).relative_to(root).as_posix()
            path = resolve_safe_note_path(root, rel)
            if path is not None:
                yield rel, path


@dataclass(frozen=True)
class NoteScan:
    """Passages from one note grep, and whether the per-search file or byte budget cut it short."""

    passages: list[NotePassage]
    truncated: bool = False


def grep_notes(
    data_dir: Path | None,
    needles: list[str],
    *,
    per_file: int = 3,
    total: int = 30,
) -> list[NotePassage]:
    """Literal, case-insensitive line search over the research notes under `data_dir`."""
    return scan_notes(data_dir, needles, per_file=per_file, total=total).passages


def scan_notes(
    data_dir: Path | None,
    needles: list[str],
    *,
    per_file: int = 3,
    total: int = 30,
    max_files: int = MAX_NOTE_FILES,
    max_bytes: int = MAX_GREP_BYTES,
) -> NoteScan:
    """`grep_notes`, also reporting whether it stopped at `max_files` files or `max_bytes` bytes read."""
    if data_dir is None:
        return NoteScan([])
    folded = list(dict.fromkeys(n.strip().casefold() for n in needles if n and n.strip()))
    if not folded:
        return NoteScan([])
    passages: list[NotePassage] = []
    files_read = 0
    bytes_read = 0
    for rel, path in _iter_note_files(data_dir):
        try:
            size = path.stat().st_size
            if size > MAX_NOTE_BYTES:
                continue
            if files_read >= max_files or bytes_read + size > max_bytes:
                return NoteScan(passages, truncated=True)
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_read += 1
        bytes_read += size
        found = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            low = line.casefold()
            if not any(n in low for n in folded):
                continue
            passages.append(NotePassage(file=rel, line=lineno, text=line.strip()[:MAX_PASSAGE_CHARS]))
            found += 1
            if len(passages) >= total:
                return NoteScan(passages)
            if found >= per_file:
                break
    return NoteScan(passages)


# --- Time ---------------------------------------------------------------------


_MONTHS = {
    name: idx
    for idx, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"'?(\d{4}|\d{2})"


@dataclass(frozen=True)
class Period:
    """A calendar period implied by the search word. Fiscal periods map to calendar ones."""

    year: int | None
    months: frozenset[int]

    def contains(self, raw_date: str) -> bool | None:
        """True or False for a `YYYY-MM...` date, None when the date can't be read."""
        m = re.match(r"(\d{4})-(\d{2})", raw_date or "")
        if not m:
            return None
        y, mo = int(m.group(1)), int(m.group(2))
        return (self.year is None or y == self.year) and mo in self.months


def _year(raw: str) -> int:
    value = int(raw)
    return value + 2000 if value < 100 else value


def _quarter(q: str) -> frozenset[int]:
    start = (int(q) - 1) * 3 + 1
    return frozenset(range(start, start + 3))


_ALL_MONTHS = frozenset(range(1, 13))
_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(rf"\bQ([1-4])\s*(?:FY)?\s*{_YEAR}\b", re.I), lambda m: Period(_year(m[2]), _quarter(m[1]))),
    (re.compile(r"\b(\d{4})\s*Q([1-4])\b", re.I), lambda m: Period(_year(m[1]), _quarter(m[2]))),
    (re.compile(rf"\b([1-4])Q\s*{_YEAR}\b", re.I), lambda m: Period(_year(m[2]), _quarter(m[1]))),
    (re.compile(rf"\bFY\s*{_YEAR}\b", re.I), lambda m: Period(_year(m[1]), _ALL_MONTHS)),
    (
        re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I),
        lambda m: Period(int(m[2]), frozenset({_MONTHS[m[1].lower()]})),
    ),
    (re.compile(r"\b(\d{4})-(0[1-9]|1[0-2])\b"), lambda m: Period(int(m[1]), frozenset({int(m[2])}))),
    (re.compile(r"\bQ([1-4])\b", re.I), lambda m: Period(None, _quarter(m[1]))),
    (re.compile(r"\b((?:19|20)\d{2})\b"), lambda m: Period(int(m[1]), _ALL_MONTHS)),
)


def parse_period(text: str) -> tuple[Period | None, str]:
    """Find one explicit period (quarter, fiscal year, month, year) and return the rest of the text."""
    for pattern, build in _PERIOD_PATTERNS:
        m = pattern.search(text)
        if m:
            rest = " ".join((text[: m.start()] + " " + text[m.end() :]).split())
            return build(m), rest
    return None, " ".join(text.split())


def _recency_bonus(raw_date: str, today: date) -> float:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw_date or "")
    if not m:
        return 0.0
    try:
        age = (today - date(int(m[1]), int(m[2]), int(m[3]))).days
    except ValueError:
        return 0.0
    return RECENCY_WEIGHT * max(0.0, 1.0 - max(age, 0) / RECENCY_HORIZON_DAYS)


# --- Filters ------------------------------------------------------------------


def split_qualified_value(raw: str | None) -> tuple[str | None, str | None]:
    """Split a `<node_type>:<value>` filter value into its node type and bare value.

    A bare value, or one whose prefix is not a node type, comes back whole with no node type.
    """
    cleaned = raw.strip() if raw else ""
    if not cleaned:
        return None, None
    prefix, sep, rest = cleaned.partition(":")
    if sep and prefix.strip().lower() in NODE_TYPES and rest.strip():
        return prefix.strip().lower(), rest.strip()
    return None, cleaned


@dataclass(frozen=True)
class SearchFilters:
    """The advanced-search filters, normalized. Build with `SearchFilters.from_raw`."""

    node_type: NodeType | None = None
    subtype: str | None = None
    subtype_node_type: NodeType | None = None
    status: str | None = None
    status_node_type: NodeType | None = None
    sentiment: str | None = None
    stance: str | None = None
    support_strength: str | None = None
    conviction: str | None = None
    relation: str | None = None
    entity_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    source_file: str | None = None
    keyword_only: bool = False

    @classmethod
    def from_raw(
        cls,
        *,
        node_type: str | None = None,
        subtype: str | None = None,
        status: str | None = None,
        sentiment: str | None = None,
        stance: str | None = None,
        support_strength: str | None = None,
        conviction: str | None = None,
        relation: str | None = None,
        entity_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_file: str | None = None,
        search_mode: str = "hybrid",
    ) -> SearchFilters:
        def clean(value: str | None) -> str | None:
            return value.strip() if value and value.strip() else None

        def lower(value: str | None) -> str | None:
            cleaned = clean(value)
            return cleaned.lower() if cleaned else None

        subtype_nt, bare_subtype = split_qualified_value(subtype)
        status_nt, bare_status = split_qualified_value(status)
        relation_name = normalize_relation_name(relation) if clean(relation) else ""
        return cls(
            node_type=node_type if node_type in NODE_TYPES else None,  # type: ignore[arg-type]
            subtype=parse_category_filter(bare_subtype),
            subtype_node_type=subtype_nt,  # type: ignore[arg-type]
            status=lower(bare_status),
            status_node_type=status_nt,  # type: ignore[arg-type]
            sentiment=parse_sentiment_filter(sentiment),
            stance=lower(stance),
            support_strength=lower(support_strength),
            conviction=lower(conviction),
            relation=relation_name or None,
            entity_id=clean(entity_id),
            date_from=clean(date_from),
            date_to=clean(date_to),
            source_file=clean(source_file) and source_file.strip().casefold(),  # type: ignore[union-attr]
            keyword_only=search_mode.strip().lower() == "keyword",
        )

    @property
    def narrows_nodes(self) -> bool:
        """True when a filter beyond the source note narrows which ontology items show."""
        return any(
            [
                self.node_type,
                self.subtype,
                self.status,
                self.sentiment,
                self.stance,
                self.support_strength,
                self.conviction,
                self.relation,
                self.entity_id,
                self.date_from,
                self.date_to,
            ]
        )

    @property
    def active(self) -> bool:
        return self.narrows_nodes or bool(self.source_file)

    def matches(
        self,
        node: Node,
        connected: dict[str, dict[str, Any] | None],
        relation_ids: set[str] | None = None,
    ) -> bool:
        """Whether `node` passes every filter.

        `relation_ids` holds the items with an edge of the `relation` filter (to the selected
        entity when one is set). With a relation filter and no `relation_ids`, nothing matches.
        """
        if self.node_type is not None and node.node_type != self.node_type:
            return False
        if self.subtype_node_type is not None and node.node_type != self.subtype_node_type:
            return False
        if self.status_node_type is not None and node.node_type != self.status_node_type:
            return False
        if self.entity_id is not None and node.id not in connected:
            return False
        if self.relation is not None and (relation_ids is None or node.id not in relation_ids):
            return False
        eff: str | None = None
        if self.sentiment is not None:
            edge_facets = connected.get(node.id) if self.entity_id else None
            eff, _ = resolve_item_sentiment(node.facets, edge_facets)
        if not matches_signal_filter(
            node.node_type,
            node.facets,
            eff,
            categories={self.subtype} if self.subtype is not None else None,
            sentiments={self.sentiment} if self.sentiment is not None else None,
        ):
            return False
        for key, wanted in (
            ("status", self.status),
            ("stance", self.stance),
            ("support_strength", self.support_strength),
            ("conviction", self.conviction),
        ):
            if wanted is not None and node.facets.get(key) != wanted:
                return False
        if self.date_from is not None or self.date_to is not None:
            d = node_date(node)
            if not d:
                return False
            if self.date_from is not None and d < self.date_from:
                return False
            if self.date_to is not None and d > self.date_to:
                return False
        if self.source_file is not None and self.source_file not in node_source_file(node).casefold():
            return False
        return True


# --- Results ------------------------------------------------------------------


@dataclass
class SearchHit:
    """One ontology item in the results, with why it matched."""

    node: Node
    match_reason: str
    score: float
    distance: float | None = None
    via_relation: str | None = None
    via_node_id: str | None = None
    via_node_name: str | None = None
    edge_facets: dict[str, Any] | None = None
    note_line: int | None = None


@dataclass
class SearchResults:
    """Entity-first search results. `ranked()` flattens them best first."""

    query: str
    period: Period | None = None
    best_match: SearchHit | None = None
    entities: list[SearchHit] = field(default_factory=list)
    related: list[SearchHit] = field(default_factory=list)
    signals: list[SearchHit] = field(default_factory=list)
    passages: list[NotePassage] = field(default_factory=list)
    notes_truncated: bool = False

    def ranked(self) -> list[SearchHit]:
        rest = sorted([*self.entities, *self.related, *self.signals], key=_sort_key)
        return [self.best_match, *rest] if self.best_match else rest

    @property
    def count(self) -> int:
        return len(self.ranked()) + len(self.passages)


def _sort_key(hit: SearchHit) -> tuple[float, str]:
    return (-hit.score, hit.node.name.casefold())


def _text_reason(node: Node, needle: str) -> str:
    if needle in node.name.casefold():
        return "name"
    if any(needle in alias.casefold() for alias in node.aliases):
        return "alias"
    return "note"


def _canonical_relation(db: OntologyDB, seed: Node, item: dict[str, Any]) -> str:
    nb = item["neighbor"]
    seed_et = seed.facets.get("entity_type")
    nb_et = (nb.get("facets") or {}).get("entity_type")
    seed_meta = (seed.id, seed.node_type, str(seed_et) if seed_et else None)
    nb_meta = (str(nb["id"]), str(nb["node_type"]), str(nb_et) if nb_et else None)
    src, dst = (seed_meta, nb_meta) if item["direction"] == "outgoing" else (nb_meta, seed_meta)
    res = db.registry.canonicalize_edge(
        item["relation"],
        from_id=src[0],
        from_type=src[1],
        from_entity_type=src[2],
        to_id=dst[0],
        to_type=dst[1],
        to_entity_type=dst[2],
        facets=item["facets"],
    )
    return res.relation


def _filter_only(
    db: OntologyDB,
    filters: SearchFilters,
    connected: dict[str, Any],
    relation_ids: set[str] | None,
    limit: int,
) -> SearchResults:
    nodes = [
        n
        for n in db.list_nodes(node_type=filters.node_type, limit=5000)
        if filters.matches(n, connected, relation_ids)
    ]
    nodes.sort(key=lambda n: n.name.casefold())
    nodes.sort(key=lambda n: (node_date(n) or "", n.updated_at.isoformat()), reverse=True)
    results = SearchResults(query="")
    for node in nodes[:limit]:
        hit = SearchHit(
            node=node,
            match_reason="filter",
            score=0.0,
            edge_facets=connected.get(node.id) if filters.entity_id else None,
        )
        (results.signals if node.node_type in ("event", "view") else results.entities).append(hit)
    return results


def search_ontology(
    db: OntologyDB,
    llm: LLMClient | None,
    query: str,
    *,
    filters: SearchFilters | None = None,
    data_dir: Path | None = None,
    limit: int = 50,
    today: date | None = None,
) -> SearchResults:
    """Entity-first search across entities, their relationships, events, views, and raw notes."""
    filters = filters or SearchFilters()
    today = today or date.today()
    cleaned = " ".join(query.split())

    connected: dict[str, dict[str, Any] | None] = {}
    if filters.entity_id is not None:
        if db.get_node(filters.entity_id) is None:
            return SearchResults(query=cleaned)
        connected = db.get_entity_connected_nodes(filters.entity_id)
    relation_ids: set[str] | None = None
    if filters.relation is not None:
        relation_ids = db.get_relation_node_ids(filters.relation, entity_id=filters.entity_id)

    if not cleaned:
        if not filters.active:
            return SearchResults(query="")
        return _filter_only(db, filters, connected, relation_ids, limit)

    period, rest = parse_period(cleaned)
    word = rest or cleaned
    needle = word.casefold()
    hits: dict[str, SearchHit] = {}

    def score_for(node: Node, reason: str, distance: float | None = None) -> float | None:
        """Score with time terms, or None when the item is dated outside the implied period."""
        base = REASON_WEIGHT[reason]
        if reason == "semantic" and distance is not None:
            base *= max(0.0, 1.0 - distance)
        if reason in ("name", "alias") and needle in (
            node.name.casefold(),
            *(a.casefold() for a in node.aliases),
        ):
            base += EXACT_NAME_BONUS
        raw_date = node_date(node)
        if period is not None:
            inside = period.contains(raw_date)
            if inside is False:
                return None
            if inside:
                base += PERIOD_BOOST
        return base + _recency_bonus(raw_date, today)

    def offer(node: Node, reason: str, **extra: Any) -> None:
        score = score_for(node, reason, extra.get("distance"))
        if score is None:
            return
        current = hits.get(node.id)
        if current is None or score > current.score:
            hits[node.id] = SearchHit(node=node, match_reason=reason, score=score, **extra)

    # 1. Entities first: exact name or alias, then keyword matches.
    best_node = db.find_by_name_or_alias(word, node_type="entity") or db.find_by_name_or_alias(
        word, node_type="theme"
    )
    if best_node is not None:
        offer(best_node, _text_reason(best_node, needle))

    widened = filters.active
    kw_limit = max(limit * 10, 500) if widened else limit
    keyword_nodes = db.keyword_search(word, node_type=filters.node_type, limit=kw_limit)
    for node in keyword_nodes:
        offer(node, _text_reason(node, needle))
    if best_node is None:
        # No exact name: the first entity whose name or alias contains the word.
        best_node = next(
            (
                n
                for n in keyword_nodes
                if n.node_type == "entity" and n.id in hits and hits[n.id].match_reason in ("name", "alias")
            ),
            None,
        )

    # 2. Expand one hop from the matched entities and themes. Edges are not results.
    seeds = [best_node] if best_node is not None else []
    seeds += [
        h.node
        for h in sorted(hits.values(), key=_sort_key)
        if h.node.node_type in ("entity", "theme")
        and h.match_reason in ("name", "alias")
        and (best_node is None or h.node.id != best_node.id)
    ]
    for seed in seeds[:MAX_EXPANSION_SEEDS]:
        incident = db.get_incident_edges(seed.id)
        neighbors = {n.id: n for n in db.get_nodes([str(item["neighbor"]["id"]) for item in incident])}
        for item in incident:
            nb = neighbors.get(str(item["neighbor"]["id"]))
            if nb is None or nb.id == seed.id:
                continue
            offer(
                nb,
                "relationship",
                via_relation=_canonical_relation(db, seed, item),
                via_node_id=seed.id,
                via_node_name=seed.name,
            )

    # 3. Semantic neighbors, when embeddings are available.
    if not filters.keyword_only and llm is not None:
        try:
            vec = llm.embed_texts([cleaned])[0]
            vec_limit = max(limit * 5, 100) if widened else min(limit, 10)
            for node, dist in db.vector_search(vec, node_type=filters.node_type, limit=vec_limit):
                if dist < 1.0:  # non-positive cosine similarity is never a match
                    offer(node, "semantic", distance=round(dist, 4))
        except Exception:  # noqa: BLE001
            # An offline or failing embedding provider leaves the name and keyword results.
            pass

    # Apply the advanced-search filters to what is shown.
    shown = [h for h in hits.values() if filters.matches(h.node, connected, relation_ids)]
    if filters.entity_id:
        for h in shown:
            h.edge_facets = connected.get(h.node.id)

    results = SearchResults(query=cleaned, period=period)
    best_id = best_node.id if best_node is not None else None
    for hit in sorted(shown, key=_sort_key):
        if hit.node.id == best_id:
            results.best_match = hit
        elif hit.node.node_type in ("event", "view"):
            results.signals.append(hit)
        elif hit.match_reason == "relationship":
            results.related.append(hit)
        else:
            results.entities.append(hit)
    results.entities = results.entities[:limit]
    results.related = results.related[:limit]
    results.signals = results.signals[:limit]

    # 4. Raw notes, grepped for the word and the best match's name and aliases.
    if data_dir is not None and not filters.narrows_nodes:
        needles = [word]
        if best_node is not None:
            needles += [best_node.name, *(a for a in best_node.aliases if len(a.strip()) >= 3)]
        scan = scan_notes(data_dir, needles)
        results.notes_truncated = scan.truncated
        passages = scan.passages
        if filters.source_file is not None:
            passages = [p for p in passages if filters.source_file in p.file.casefold()]
        results.passages = _fold_passages(results.signals, passages)
    return results


def _fold_passages(signals: list[SearchHit], passages: list[NotePassage]) -> list[NotePassage]:
    """Attach a note line to the event or view extracted from that note instead of listing it again."""
    first_line: dict[str, int] = {}
    for p in passages:
        first_line.setdefault(p.file, p.line)
    folded: set[str] = set()
    for hit in signals:
        src = node_source_file(hit.node)
        if src in first_line:
            hit.note_line = first_line[src]
            folded.add(src)
    return [p for p in passages if p.file not in folded]
