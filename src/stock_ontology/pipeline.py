"""One-directional ingestion pipeline: data/ notes -> extraction -> SQLite + consensus."""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_ontology.db import OntologyDB
from stock_ontology.llm import LLMClient
from stock_ontology.registry import OntologyRegistry, create_minimal_registry
from stock_ontology.models import (
    Edge,
    Node,
    NodeType,
    derive_sentiment_from_stance,
    facets_list_to_dict,
    normalize_sentiment,
)

SUPPORTED_EXTENSIONS = {".md", ".txt"}
CANONICAL_DISTANCE_THRESHOLD = 0.15

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """Summary of one ingestion pipeline run."""

    files_scanned: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    nodes_created_or_updated: int = 0
    edges_created_or_updated: int = 0
    consensus_updated_for: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ReembedReport:
    """Summary of one full vector re-embedding run."""

    total_nodes: int = 0
    reembedded: int = 0
    provider: str | None = None
    model: str | None = None
    embedding_dim: int = 0


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:24] or "node"


def _make_node_id(prefix: str, label: str) -> str:
    return f"{prefix}_{_slugify(label)}_{uuid.uuid4().hex[:6]}"


def node_embedding_text(node: Node) -> str:
    """Build canonical text representation used to compute a node's vector embedding."""
    alias_str = f" (aliases: {', '.join(node.aliases)})" if node.aliases else ""
    return f"{node.node_type}: {node.name}{alias_str}\n{node.summary}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _merge_unique_str(existing: list[str], incoming: list[str]) -> list[str]:
    seen = {item.casefold(): item for item in existing if item.strip()}
    out = list(seen.values())
    for item in incoming:
        cleaned = item.strip()
        if cleaned and cleaned.casefold() not in seen:
            seen[cleaned.casefold()] = cleaned
            out.append(cleaned)
    return out


class IngestionPipeline:
    """Scans research notes under `data_dir`, extracts 4-node ontology graphs, and synthesizes consensus."""

    def __init__(
        self,
        db: OntologyDB,
        llm: LLMClient,
        data_dir: Path | str,
        registry: OntologyRegistry | None = None,
    ) -> None:
        if db.read_only:
            raise ValueError("IngestionPipeline requires a writable OntologyDB.")  # noqa: TRY003
        self.db = db
        self.llm = llm
        self.data_dir = Path(data_dir)
        self.registry = registry if registry is not None else create_minimal_registry()

    def _scan_files(self) -> tuple[dict[str, tuple[Path, str, str]], dict[str, str]]:
        """Return `({rel_posix_path: (abs_path, text, sha256)}, {rel_posix_path: read_error})`."""
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")  # noqa: TRY003

        discovered: dict[str, tuple[Path, str, str]] = {}
        unreadable: dict[str, str] = {}
        for path in sorted(self.data_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.data_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                unreadable[rel.as_posix()] = f"Could not read note: {exc}"
                continue
            discovered[rel.as_posix()] = (path, text, _sha256_text(text))
        return discovered, unreadable

    def _build_existing_catalog(self) -> str:
        entities = self.db.list_nodes(node_type="entity", limit=500)
        themes = self.db.list_nodes(node_type="theme", limit=500)
        lines: list[str] = []
        for node in entities + themes:
            subtype = (
                node.facets.get("entity_type", "entity")
                if node.node_type == "entity"
                else f"theme/{node.facets.get('stage', 'active')}"
            )
            aliases = f" aliases={node.aliases}" if node.aliases else ""
            lines.append(f"- [{node.id}] ({node.node_type}:{subtype}) {node.name}{aliases}")
        if self.registry.relations:
            lines.append("")
            lines.append("Canonical edge relations (use exact name and direction):")
            for spec in self.registry.relations:
                from_sig = "|".join(spec.from_types) or "*"
                to_sig = "|".join(spec.to_types) or "*"
                arrow = "<->" if spec.symmetric else "->"
                lines.append(f"- {spec.name} ({from_sig} {arrow} {to_sig})")
        return "\n".join(lines)

    def _resolve_canonical_node(
        self,
        *,
        node_type: NodeType,
        temp_id: str,
        name: str,
        summary: str,
        aliases: list[str],
        facets: dict[str, Any],
        prefix: str,
    ) -> tuple[Node, bool]:
        """Resolve an entity/theme by exact name/alias or vector distance; upsert if new/merged."""
        # If LLM returned an already-existing DB ID in `temp_id`, reuse it.
        existing = self.db.get_node(temp_id)
        if existing is None or existing.node_type != node_type:
            existing = self.db.find_by_name_or_alias(name, node_type=node_type)
        if existing is None:
            for alias in aliases:
                existing = self.db.find_by_name_or_alias(alias, node_type=node_type)
                if existing is not None:
                    break

        candidate_vec: list[float] | None = None
        if existing is None:
            probe_text = f"{node_type}: {name}\n{summary}"
            candidate_vec = self.llm.embed_texts([probe_text])[0]
            matches = self.db.vector_search(candidate_vec, node_type=node_type, limit=1)
            if matches and matches[0][1] < CANONICAL_DISTANCE_THRESHOLD:
                existing = matches[0][0]

        now = datetime.now(UTC)
        if existing is not None:
            merged_aliases = _merge_unique_str(existing.aliases, [name] + aliases)
            # Do not keep canonical name duplicated inside aliases.
            merged_aliases = [
                a for a in merged_aliases if a.casefold() != existing.name.strip().casefold()
            ]
            merged_facets = dict(existing.facets)
            for k, v in facets.items():
                if k not in merged_facets or merged_facets[k] in (None, "", []):
                    merged_facets[k] = v

            changed = (
                merged_aliases != existing.aliases
                or merged_facets != existing.facets
                or (not existing.summary and bool(summary))
            )
            if changed:
                existing.aliases = merged_aliases
                existing.facets = merged_facets
                if not existing.summary and summary:
                    existing.summary = summary
                existing.updated_at = now
                vec = self.llm.embed_texts([node_embedding_text(existing)])[0]
                self.db.upsert_node(existing, embedding=vec)
            return existing, changed

        cleaned_aliases = [
            a.strip()
            for a in aliases
            if a.strip() and a.strip().casefold() != name.strip().casefold()
        ]
        node = Node(
            id=_make_node_id(prefix, name),
            node_type=node_type,
            name=name.strip(),
            summary=summary.strip(),
            aliases=cleaned_aliases,
            facets=facets,
            source_doc_id=None,
            created_at=now,
            updated_at=now,
        )
        vec = candidate_vec if candidate_vec is not None else self.llm.embed_texts([node_embedding_text(node)])[0]
        self.db.upsert_node(node, embedding=vec)
        return node, True

    def _resolve_node_ref(self, ref: str, ref_map: dict[str, str]) -> str | None:
        if ref in ref_map:
            return ref_map[ref]
        if self.db.get_node(ref) is not None:
            return ref
        for node_type in ("entity", "theme"):
            found = self.db.find_by_name_or_alias(ref, node_type=node_type)
            if found is not None:
                return found.id
        return None

    def _node_endpoint_meta(
        self, node_id: str, local_nodes: dict[str, Node]
    ) -> tuple[str, str | None]:
        node = local_nodes.get(node_id) or self.db.get_node(node_id)
        if node is None:
            return "entity", None
        et = node.facets.get("entity_type")
        return node.node_type, str(et).strip().lower() if et else None

    def _process_document(
        self,
        *,
        rel_path: str,
        doc_id: str,
        text: str,
        content_hash: str,
        replace_old_doc_id: str | None,
        affected_company_ids: set[str],
        report: IngestReport,
    ) -> None:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        parent = Path(rel_path).parent.as_posix()
        source_meta: dict[str, Any] = {
            "doc_id": doc_id,
            "file_path": rel_path,
            "ingested_at": now_iso,
        }
        if parent != ".":
            source_meta["folder"] = parent

        if not text.strip():
            with self.db.transaction():
                self._clear_prior_artifacts(doc_id, replace_old_doc_id, affected_company_ids)
                self.db.upsert_ingestion_log(rel_path, doc_id, content_hash, now_iso)
            report.files_processed += 1
            return

        extraction = self.llm.extract_document(
            text=text,
            source_meta=source_meta,
            existing_catalog=self._build_existing_catalog(),
            known_facets=self.db.get_known_facet_keys(),
        )

        # All writes for this note commit together or not at all, so a failure partway
        # leaves no partial rows behind and no ingestion log entry.
        with self.db.transaction():
            # Always clear this note's prior artifacts (including leftovers from a failed run).
            self._clear_prior_artifacts(doc_id, replace_old_doc_id, affected_company_ids)
            nodes_written, edges_written = self._write_extraction(
                extraction=extraction,
                doc_id=doc_id,
                source_meta=source_meta,
                now=now,
                affected_company_ids=affected_company_ids,
            )
            affected_company_ids.update(self.db.get_doc_affected_company_ids(doc_id))
            self.db.upsert_ingestion_log(rel_path, doc_id, content_hash, now_iso)
        report.nodes_created_or_updated += nodes_written
        report.edges_created_or_updated += edges_written
        report.files_processed += 1

    def _clear_prior_artifacts(
        self, doc_id: str, replace_old_doc_id: str | None, affected_company_ids: set[str]
    ) -> None:
        for old_id in {doc_id, replace_old_doc_id} - {None}:
            assert old_id is not None
            affected_company_ids.update(self.db.get_doc_affected_company_ids(old_id))
            self.db.delete_document_artifacts(old_id)

    def _write_extraction(
        self,
        *,
        extraction: Any,
        doc_id: str,
        source_meta: dict[str, Any],
        now: datetime,
        affected_company_ids: set[str],
    ) -> tuple[int, int]:
        """Write resolved entities/themes, doc-scoped events/views, and edges; return counts."""
        nodes_written = 0
        edges_written = 0
        ref_map: dict[str, str] = {}
        local_nodes: dict[str, Node] = {}

        # 1. Resolve canonical entities & themes.
        for ent in extraction.entities:
            ent_facets = facets_list_to_dict(ent.facets)
            ent_facets.setdefault("entity_type", ent.entity_type or "company")
            node, updated = self._resolve_canonical_node(
                node_type="entity",
                temp_id=ent.temp_id,
                name=ent.name,
                summary=ent.summary,
                aliases=ent.aliases,
                facets=ent_facets,
                prefix="ent",
            )
            ref_map[ent.temp_id] = node.id
            local_nodes[node.id] = node
            if updated:
                nodes_written += 1
            if str(node.facets.get("entity_type", "")).lower() == "company":
                affected_company_ids.add(node.id)

        for thm in extraction.themes:
            thm_facets = facets_list_to_dict(thm.facets)
            thm_facets.setdefault("stage", thm.stage or "accelerating")
            node, updated = self._resolve_canonical_node(
                node_type="theme",
                temp_id=thm.temp_id,
                name=thm.name,
                summary=thm.summary,
                aliases=thm.aliases,
                facets=thm_facets,
                prefix="thm",
            )
            ref_map[thm.temp_id] = node.id
            local_nodes[node.id] = node
            if updated:
                nodes_written += 1

        # 2. Build doc-scoped events and views.
        doc_nodes: list[Node] = []
        for ev in extraction.events:
            ev_facets = facets_list_to_dict(ev.facets)
            ev_facets["event_type"] = ev.event_type or "fact"
            if ev.event_date:
                ev_facets["event_date"] = ev.event_date
            ev_facets["status"] = ev.status or "occurred"
            explicit_ev_sentiment = (
                normalize_sentiment(ev.sentiment)
                if "sentiment" in ev.model_fields_set
                else None
            )
            ev_facets["sentiment"] = (
                explicit_ev_sentiment
                or normalize_sentiment(ev_facets.get("sentiment"))
                or normalize_sentiment(ev.sentiment)
                or "neutral"
            )
            ev_facets["source"] = _build_node_source(source_meta, ev_facets)
            node = Node(
                id=_make_node_id("evt", ev.name),
                node_type="event",
                name=ev.name.strip(),
                summary=ev.summary.strip(),
                aliases=[],
                facets=ev_facets,
                source_doc_id=doc_id,
                created_at=now,
                updated_at=now,
            )
            ref_map[ev.temp_id] = node.id
            local_nodes[node.id] = node
            doc_nodes.append(node)

        for vw in extraction.views:
            vw_facets = facets_list_to_dict(vw.facets)
            vtype = (vw.view_type or "analyst_report").strip().lower()
            if vtype in ("consensus", "house_consensus"):
                vtype = "pm_view"
            vw_facets["view_type"] = vtype
            vw_facets["stance"] = vw.stance or "neutral"
            vw_facets["sentiment"] = (
                normalize_sentiment(vw.sentiment)
                or normalize_sentiment(vw_facets.get("sentiment"))
                or derive_sentiment_from_stance(vw_facets["stance"])
                or "neutral"
            )
            vw_facets["support_strength"] = vw.support_strength or "moderate"
            vw_facets["conviction"] = vw.conviction or "medium"
            if vw.as_of:
                vw_facets["as_of"] = vw.as_of
            vw_facets["source"] = _build_node_source(source_meta, vw_facets)
            node = Node(
                id=_make_node_id("vw", vw.name),
                node_type="view",
                name=vw.name.strip(),
                summary=vw.summary.strip(),
                aliases=[],
                facets=vw_facets,
                source_doc_id=doc_id,
                created_at=now,
                updated_at=now,
            )
            ref_map[vw.temp_id] = node.id
            local_nodes[node.id] = node
            doc_nodes.append(node)

        if doc_nodes:
            embeddings = self.llm.embed_texts([node_embedding_text(n) for n in doc_nodes])
            for node, vec in zip(doc_nodes, embeddings, strict=True):
                self.db.upsert_node(node, embedding=vec)
                nodes_written += 1

        # 3. Resolve & store edges.
        for ex_edge in extraction.edges:
            from_id = self._resolve_node_ref(ex_edge.from_ref, ref_map)
            to_id = self._resolve_node_ref(ex_edge.to_ref, ref_map)
            if from_id is None or to_id is None or from_id == to_id:
                continue
            edge_facets = facets_list_to_dict(ex_edge.facets)
            from_type, from_et = self._node_endpoint_meta(from_id, local_nodes)
            to_type, to_et = self._node_endpoint_meta(to_id, local_nodes)
            canon = self.registry.canonicalize_edge(
                ex_edge.relation,
                from_id=from_id,
                from_type=from_type,
                from_entity_type=from_et,
                to_id=to_id,
                to_type=to_type,
                to_entity_type=to_et,
                facets=edge_facets,
            )
            canon_facets = dict(canon.facets)
            if "sentiment" in canon_facets:
                norm_edge_sent = normalize_sentiment(canon_facets["sentiment"])
                if norm_edge_sent is not None:
                    canon_facets["sentiment"] = norm_edge_sent
                else:
                    canon_facets.pop("sentiment", None)
            self.db.upsert_edge(
                Edge(
                    id=f"edge_{uuid.uuid4().hex[:12]}",
                    from_id=canon.from_id,
                    to_id=canon.to_id,
                    relation=canon.relation,
                    facets=canon_facets,
                    source_doc_id=doc_id,
                    created_at=now,
                )
            )
            edges_written += 1

        return nodes_written, edges_written

    def _rebuild_company_consensus(self, company_id: str) -> bool:
        company = self.db.get_node(company_id)
        if company is None:
            return False

        overview = self.db.get_entity_overview(company_id)
        event_nodes = [
            n for item in overview["events"] if (n := self.db.get_node(item["id"])) is not None
        ]
        view_nodes = [
            n for item in overview["views"] if (n := self.db.get_node(item["id"])) is not None
        ]
        theme_nodes = [
            n for item in overview["themes"] if (n := self.db.get_node(item["id"])) is not None
        ]
        prior = self.db.get_entity_consensus(company_id)

        if not event_nodes and not view_nodes:
            if prior is not None:
                prior.facets["status"] = "stale"
                prior.updated_at = datetime.now(UTC)
                self.db.upsert_node(prior)
                return True
            return False

        syn = self.llm.synthesize_consensus(
            company=company,
            events=event_nodes,
            views=view_nodes,
            themes=theme_nodes,
            prior_consensus=prior,
        )
        now = datetime.now(UTC)
        facets = facets_list_to_dict(syn.facets)
        facets.update(
            {
                "view_type": "consensus",
                "stance": syn.stance,
                "sentiment": derive_sentiment_from_stance(syn.stance) or "neutral",
                "support_strength": syn.support_strength,
                "conviction": syn.conviction,
                "status": "active",
                "as_of": now.date().isoformat(),
                "pillars": syn.pillars,
            }
        )
        cons_node = Node(
            id=_make_node_id("vw_cons", company.name),
            node_type="view",
            name=f"Consensus: {syn.stance.title()} {company.name}",
            summary=syn.summary.strip(),
            aliases=[],
            facets=facets,
            source_doc_id=None,
            created_at=now,
            updated_at=now,
        )
        vec = self.llm.embed_texts([node_embedding_text(cons_node)])[0]
        self.db.upsert_consensus_view(
            company_id=company_id,
            view_node=cons_node,
            embedding=vec,
            supporting_ids=syn.supporting_node_ids,
            contradicting_ids=syn.contradicting_node_ids,
        )
        return True

    def run(self, force: bool = False, rebuild_consensus: bool = False) -> IngestReport:
        """Scan `data_dir`, incrementally extract changed files, and update consensus."""
        report = IngestReport()
        discovered, unreadable = self._scan_files()
        report.files_scanned = len(discovered) + len(unreadable)
        report.errors.extend(sorted(unreadable.items()))

        log = self.db.get_ingestion_log()
        affected_company_ids: set[str] = set()

        # 1. Clean up files removed from disk (an unreadable file still exists, so keep it).
        for deleted_rel in sorted(set(log.keys()) - set(discovered.keys()) - set(unreadable.keys())):
            doc_id = log[deleted_rel]["doc_id"]
            affected_company_ids.update(self.db.get_doc_affected_company_ids(doc_id))
            with self.db.transaction():
                self.db.delete_document_artifacts(doc_id)
                self.db.delete_ingestion_log(deleted_rel)
            report.files_deleted += 1

        # 2. Process new or modified files.
        for rel_path, (_, text, content_hash) in discovered.items():
            doc_id = f"doc_{hashlib.sha256(rel_path.encode('utf-8')).hexdigest()[:12]}"
            existing_entry = log.get(rel_path)
            if not force and existing_entry and existing_entry["content_hash"] == content_hash:
                report.files_skipped += 1
                continue

            old_doc_id = existing_entry["doc_id"] if existing_entry is not None else None
            try:
                self._process_document(
                    rel_path=rel_path,
                    doc_id=doc_id,
                    text=text,
                    content_hash=content_hash,
                    replace_old_doc_id=old_doc_id,
                    affected_company_ids=affected_company_ids,
                    report=report,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append((rel_path, str(exc)))

        # 3. Synthesize consensus views in the DB for affected companies.
        if rebuild_consensus:
            target_company_ids = sorted(
                n.id
                for n in self.db.list_nodes(node_type="entity", limit=5000)
                if str(n.facets.get("entity_type", "")).lower() == "company"
            )
        else:
            target_company_ids = sorted(affected_company_ids)

        for company_id in target_company_ids:
            company = self.db.get_node(company_id)
            label = company.name if company else company_id
            try:
                with self.db.transaction():
                    updated = self._rebuild_company_consensus(company_id)
                if updated:
                    report.consensus_updated_for.append(label)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((f"consensus:{label}", str(exc)))

        return report

    def watch(self, interval_seconds: int = 60, on_tick: Any = None) -> None:
        """Periodically run incremental ingestion until interrupted."""
        while True:
            try:
                report = self.run()
            except Exception:  # noqa: BLE001 - one failing tick must not stop the watcher
                logger.exception("Ingestion tick failed; retrying after %s seconds", interval_seconds)
            else:
                if on_tick is not None:
                    on_tick(report)
            time.sleep(interval_seconds)


def _resolve_embedding_provenance(llm: Any) -> tuple[str | None, str | None]:
    """Extract the active embedding provider and model name from `llm`."""
    last_prov = getattr(llm, "last_embedding_provider", None)
    providers = getattr(llm, "embedding_providers", None)
    if providers:
        selected = None
        if last_prov:
            for prov in providers:
                if getattr(prov, "name", None) == last_prov:
                    selected = prov
                    break
        if selected is None:
            selected = providers[0]
        return getattr(selected, "name", last_prov), getattr(selected, "embedding_model", None)
    return (
        last_prov or getattr(llm, "name", None),
        getattr(llm, "embedding_model", None),
    )


def reembed_all_nodes(db: OntologyDB, llm: LLMClient) -> ReembedReport:
    """Recompute and atomically replace vector embeddings for all nodes in `db`."""
    if db.read_only:
        raise ValueError("reembed_all_nodes requires a writable OntologyDB.")  # noqa: TRY003

    nodes = db.list_all_nodes()
    if nodes:
        texts = [node_embedding_text(node) for node in nodes]
        vectors = llm.embed_texts(texts)
        if len(vectors) != len(nodes):
            raise ValueError(  # noqa: TRY003
                f"Embedding count mismatch: expected {len(nodes)}, got {len(vectors)}"
            )
        mapping = {node.id: vec for node, vec in zip(nodes, vectors, strict=True)}
        reembedded = db.replace_node_embeddings(mapping, prune_orphans=True)
    else:
        reembedded = 0

    provider_name, model_name = _resolve_embedding_provenance(llm)
    if provider_name:
        db.set_metadata("embedding_provider", provider_name)
    if model_name:
        db.set_metadata("embedding_model", model_name)
    db.set_metadata("embedding_dim", str(db.embedding_dim))
    db.set_metadata("reembedded_at", datetime.now(UTC).isoformat())

    return ReembedReport(
        total_nodes=len(nodes),
        reembedded=reembedded,
        provider=provider_name,
        model=model_name,
        embedding_dim=db.embedding_dim,
    )


def _build_node_source(base_meta: dict[str, Any], facets: dict[str, Any]) -> dict[str, Any]:
    """Combine file provenance with any author/title/kind extracted from text."""
    source = dict(base_meta)
    for src_key, target_key in (
        ("author", "author"),
        ("source_kind", "kind"),
        ("source_title", "title"),
        ("source_date", "date"),
    ):
        val = facets.get(src_key)
        if val not in (None, ""):
            source[target_key] = val
    return source
