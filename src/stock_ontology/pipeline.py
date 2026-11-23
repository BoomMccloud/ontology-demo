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

from stock_ontology.config import SUPPORTED_EXTENSIONS
from stock_ontology.db import OntologyDB, node_meta
from stock_ontology.llm import LLMClient
from stock_ontology.registry import FacetSchemaError, OntologyRegistry, create_minimal_registry
from stock_ontology.models import (
    Edge,
    Node,
    NodeType,
    derive_sentiment_from_stance,
    facets_list_to_dict,
    normalize_sentiment,
)
from stock_ontology.vocab import ENTITY_TYPE, STAGE

# Most recently updated entities and themes listed in the extraction catalog (each type),
# in addition to every entity/theme the note names.
CATALOG_RECENT_BUDGET = 500

# Extraction calls per note: the first plus 2 regenerations when the result breaks the registry
# (a missing required facet, a wrong kind, or an over-length name or summary). After that the note fails.
MAX_EXTRACTION_ATTEMPTS = 3

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """Summary of one ingestion pipeline run."""

    files_scanned: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    files_moved: int = 0
    nodes_created_or_updated: int = 0
    edges_created_or_updated: int = 0
    # Extracted edges held in `pending_edges` because the registry does not map their relation: name -> count.
    unmapped_relations_pending: dict[str, int] = field(default_factory=dict)
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
        if registry is not None:
            # The DB enforces, migrates and stamps under the registry this run writes with.
            db.use_registry(registry)

    @staticmethod
    def _required_subtype(item: Any, field: str) -> str | None:
        """The extracted subtype. An omitted or unknown value stays None, so the write is refused."""
        value = getattr(item, field)
        return str(value) if field in item.model_fields_set and value is not None else None

    def _scan_files(self) -> dict[str, tuple[Path, int, int]]:
        """Return `{rel_posix_path: (abs_path, size, mtime_ns)}` for notes, without reading them."""
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")  # noqa: TRY003

        found: dict[str, tuple[Path, int, int]] = {}
        for path in sorted(self.data_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.data_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                st = path.stat()
            except OSError:
                st = None
            found[rel.as_posix()] = (path, st.st_size if st else -1, st.st_mtime_ns if st else -1)
        return found

    def _build_existing_catalog(self, text: str = "") -> str:
        """List entities/themes named in `text` first, then the most recently updated ones."""
        mentioned = self.db.find_nodes_mentioned_in(text, ("entity", "theme")) if text else []
        recent = self.db.list_nodes(node_type="entity", limit=CATALOG_RECENT_BUDGET) + self.db.list_nodes(
            node_type="theme", limit=CATALOG_RECENT_BUDGET
        )
        seen: set[str] = set()
        ordered: list[Node] = []
        for node in mentioned + recent:
            if node.id not in seen:
                seen.add(node.id)
                ordered.append(node)
        lines: list[str] = []
        for node in ordered:
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
        required = self.registry.entity_type_required_facets()
        if required:
            lines.append("")
            lines.append("Required entity facets (put each in `facets`):")
            lines.extend(f"- {entity_type}: {', '.join(keys)}" for entity_type, keys in required.items())
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
        needs_embedding: list[Node],
    ) -> tuple[Node, bool]:
        """Reuse an entity/theme only on an exact or registry match; otherwise create it.

        Embedding similarity never merges nodes: near-duplicates are proposed by `audit` as
        registry merge suggestions for a human to approve. Nodes whose embedding text changed
        are appended to `needs_embedding` so the caller can embed them in one batch.
        """
        existing = self._find_exact(
            node_type=node_type, temp_id=temp_id, name=name, aliases=aliases, facets=facets
        )

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
                self.db.upsert_node(existing)
                needs_embedding.append(existing)
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
        self.db.upsert_node(node)
        needs_embedding.append(node)
        return node, True

    def _find_exact(
        self,
        *,
        node_type: NodeType,
        temp_id: str,
        name: str,
        aliases: list[str],
        facets: dict[str, Any] | None = None,
    ) -> Node | None:
        """Existing node by ID, exact name/alias, or the registry's official name/aliases."""
        # If the LLM returned an already-existing DB ID in `temp_id`, reuse it.
        existing = self.db.get_node(temp_id)
        if existing is not None and existing.node_type == node_type:
            return existing
        for label in [name, *aliases]:
            found = self.db.find_by_name_or_alias(label, node_type=node_type)
            if found is not None:
                return found
        return self._find_by_registry(node_type=node_type, name=name, aliases=aliases, facets=facets or {})

    def _find_by_registry(
        self, *, node_type: NodeType, name: str, aliases: list[str], facets: dict[str, Any]
    ) -> Node | None:
        """Map a registry company/theme match to the stored node carrying any of its labels."""
        labels: list[str] = []
        if node_type == "entity" and facets.get("entity_type") == "company":
            ticker = facets.get("ticker")
            company = self.registry.resolve_company(
                name, ticker=str(ticker) if ticker else None, aliases=aliases
            )
            if company is not None:
                labels = [company.spec.name, *company.spec.aliases]
                if company.spec.ticker:
                    labels.append(company.spec.ticker)
        elif node_type == "theme":
            theme = self.registry.resolve_theme(name, aliases=aliases)
            if theme is not None:
                labels = [theme.spec.name, *theme.spec.aliases]
        for label in labels:
            found = self.db.find_by_name_or_alias(label, node_type=node_type)
            if found is None:
                continue
            if node_type == "entity" and found.facets.get("entity_type") != "company":
                continue
            return found
        return None

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
        _, node_type, entity_type = node_meta(node)
        return node_type, entity_type

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
        size: int | None = None,
        mtime_ns: int | None = None,
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

        # Company IDs touched by this note join the run's consensus targets only after the
        # note's transaction commits; a rolled-back note contributes none.
        note_companies: set[str] = set()
        if not text.strip():
            with self.db.transaction():
                self._clear_prior_artifacts(doc_id, replace_old_doc_id, note_companies)
                self.db.upsert_ingestion_log(
                    rel_path, doc_id, content_hash, now_iso, size=size, mtime_ns=mtime_ns
                )
            affected_company_ids.update(note_companies)
            report.files_processed += 1
            return

        for attempt in range(1, MAX_EXTRACTION_ATTEMPTS + 1):
            extraction = self.llm.extract_document(
                text=text,
                source_meta=source_meta,
                existing_catalog=self._build_existing_catalog(text),
                known_facets=self.db.get_known_facet_keys(),
            )
            note_companies.clear()
            pending: dict[str, int] = {}
            try:
                # All writes for this note commit together or not at all, so a failure partway
                # leaves no partial rows behind and no ingestion log entry.
                with self.db.transaction():
                    # Always clear this note's prior artifacts (including leftovers from a failed run).
                    self._clear_prior_artifacts(doc_id, replace_old_doc_id, note_companies)
                    nodes_written, edges_written = self._write_extraction(
                        extraction=extraction,
                        doc_id=doc_id,
                        source_meta=source_meta,
                        now=now,
                        affected_company_ids=note_companies,
                        pending_relations=pending,
                    )
                    note_companies.update(self.db.get_doc_affected_company_ids(doc_id))
                    self.db.upsert_ingestion_log(
                        rel_path, doc_id, content_hash, now_iso, size=size, mtime_ns=mtime_ns
                    )
            except FacetSchemaError as exc:
                if attempt == MAX_EXTRACTION_ATTEMPTS:
                    raise
                logger.warning("Regenerating extraction for %s (attempt %d): %s", rel_path, attempt, exc)
                continue
            break
        affected_company_ids.update(note_companies)
        report.nodes_created_or_updated += nodes_written
        report.edges_created_or_updated += edges_written
        for relation, count in pending.items():
            report.unmapped_relations_pending[relation] = report.unmapped_relations_pending.get(relation, 0) + count
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
        pending_relations: dict[str, int],
    ) -> tuple[int, int]:
        """Write resolved entities/themes, doc-scoped events/views, and edges; return counts.

        An edge whose relation the registry does not map is held in `pending_edges` with its raw
        relation, not written to `edges`; its name is counted in `pending_relations`.
        """
        nodes_written = 0
        edges_written = 0
        ref_map: dict[str, str] = {}
        local_nodes: dict[str, Node] = {}
        needs_embedding: list[Node] = []

        # 1. Resolve canonical entities & themes.
        for ent in extraction.entities:
            ent_facets = facets_list_to_dict(ent.facets)
            # A facet-list `entity_type` still wins over the field, but only as a member.
            ent_facets["entity_type"] = ENTITY_TYPE.coerce(ent_facets.get("entity_type")) or self._required_subtype(ent, "entity_type"
            )
            node, updated = self._resolve_canonical_node(
                node_type="entity",
                temp_id=ent.temp_id,
                name=ent.name,
                summary=ent.summary,
                aliases=ent.aliases,
                facets=self.registry.drop_uncoercible_optional("entity", ent_facets),
                prefix="ent",
                needs_embedding=needs_embedding,
            )
            ref_map[ent.temp_id] = node.id
            local_nodes[node.id] = node
            if updated:
                nodes_written += 1
            if node.facets.get("entity_type") == "company":
                affected_company_ids.add(node.id)

        for thm in extraction.themes:
            thm_facets = facets_list_to_dict(thm.facets)
            thm_facets["stage"] = STAGE.coerce(thm_facets.get("stage")) or self._required_subtype(thm, "stage"
            )
            node, updated = self._resolve_canonical_node(
                node_type="theme",
                temp_id=thm.temp_id,
                name=thm.name,
                summary=thm.summary,
                aliases=thm.aliases,
                facets=self.registry.drop_uncoercible_optional("theme", thm_facets),
                prefix="thm",
                needs_embedding=needs_embedding,
            )
            ref_map[thm.temp_id] = node.id
            local_nodes[node.id] = node
            if updated:
                nodes_written += 1

        # New or changed canonical nodes are embedded in one call per note.
        unique_embed = list({n.id: n for n in needs_embedding}.values())
        if unique_embed:
            vectors = self.llm.embed_texts([node_embedding_text(n) for n in unique_embed])
            self.db.replace_node_embeddings(
                {n.id: v for n, v in zip(unique_embed, vectors, strict=True)}, prune_orphans=False
            )

        # 2. Build doc-scoped events and views.
        doc_nodes: list[Node] = []
        for ev in extraction.events:
            node = _build_event_node(
                ev,
                event_type=self._required_subtype(ev, "event_type"),
                doc_id=doc_id,
                source_meta=source_meta,
                now=now,
            )
            ref_map[ev.temp_id] = node.id
            local_nodes[node.id] = node
            doc_nodes.append(node)
        for vw in extraction.views:
            node = _build_view_node(
                vw,
                view_type=self._required_subtype(vw, "view_type"),
                doc_id=doc_id,
                source_meta=source_meta,
                now=now,
            )
            ref_map[vw.temp_id] = node.id
            local_nodes[node.id] = node
            doc_nodes.append(node)

        # An optional official facet that cannot be coerced to its kind is dropped; the note is kept.
        for node in doc_nodes:
            node.facets = self.registry.drop_uncoercible_optional(node.node_type, node.facets)

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
            # `basis` is set by code, never taken from the LLM.
            canon_facets["basis"] = "extracted"
            canon_facets = self.registry.drop_uncoercible_optional(None, canon_facets)
            if not canon.matched:
                self.db.insert_pending_edge(
                    Edge(
                        id=f"pedge_{uuid.uuid4().hex[:12]}",
                        from_id=from_id,
                        to_id=to_id,
                        relation=ex_edge.relation,
                        facets=canon_facets,
                        source_doc_id=doc_id,
                        created_at=now,
                    )
                )
                pending_relations[canon.relation] = pending_relations.get(canon.relation, 0) + 1
                continue
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
        event_nodes = self.db.get_nodes([item["id"] for item in overview["events"]])
        view_nodes = self.db.get_nodes([item["id"] for item in overview["views"]])
        theme_nodes = self.db.get_nodes([item["id"] for item in overview["themes"]])
        prior = self.db.get_entity_consensus(company_id)

        if not event_nodes and not view_nodes:
            if prior is not None:
                prior.facets["status"] = "superseded"
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
            facets=self.registry.drop_uncoercible_optional("view", facets),
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
        on_disk = self._scan_files()
        report.files_scanned = len(on_disk)
        log = self.db.get_ingestion_log()
        affected_company_ids: set[str] = set()

        # 1. Read only files whose size or modification time changed (or everything on --force).
        to_check: dict[str, tuple[str, str, int, int]] = {}
        for rel_path, (path, size, mtime_ns) in on_disk.items():
            entry = log.get(rel_path)
            if (
                not force
                and entry is not None
                and entry.get("size") == size
                and entry.get("mtime_ns") == mtime_ns
            ):
                report.files_skipped += 1
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                report.errors.append((rel_path, f"Could not read note: {exc}"))
                continue
            to_check[rel_path] = (text, _sha256_text(text), size, mtime_ns)

        # 2. Relink notes that moved: a vanished logged path whose content hash uniquely
        #    matches a new path keeps its doc and artifacts; nothing is re-extracted.
        vanished = sorted(set(log) - set(on_disk))
        new_paths = [p for p in to_check if p not in log]
        by_hash_old: dict[str, list[str]] = {}
        for rel in vanished:
            by_hash_old.setdefault(log[rel]["content_hash"], []).append(rel)
        by_hash_new: dict[str, list[str]] = {}
        for rel in new_paths:
            by_hash_new.setdefault(to_check[rel][1], []).append(rel)
        for content_hash, olds in by_hash_old.items():
            news = by_hash_new.get(content_hash, [])
            if len(olds) != 1 or len(news) != 1:
                continue
            old_rel, new_rel = olds[0], news[0]
            _, _, size, mtime_ns = to_check.pop(new_rel)
            self.db.relink_document(
                log[old_rel]["doc_id"], old_rel, new_rel, size=size, mtime_ns=mtime_ns
            )
            vanished.remove(old_rel)
            report.files_moved += 1

        # 3. Clean up files removed from disk.
        for deleted_rel in vanished:
            doc_id = log[deleted_rel]["doc_id"]
            deleted_companies = self.db.get_doc_affected_company_ids(doc_id)
            with self.db.transaction():
                self.db.delete_document_artifacts(doc_id)
                self.db.delete_ingestion_log(deleted_rel)
            affected_company_ids.update(deleted_companies)
            report.files_deleted += 1

        # 4. Process new or modified files.
        used_doc_ids = {e["doc_id"] for rel, e in self.db.get_ingestion_log().items()}
        for rel_path, (text, content_hash, size, mtime_ns) in to_check.items():
            existing_entry = log.get(rel_path)
            if not force and existing_entry and existing_entry["content_hash"] == content_hash:
                # Touched but unchanged: remember the new size/mtime so the next run skips the read.
                self.db.update_ingestion_stat(rel_path, size, mtime_ns)
                report.files_skipped += 1
                continue

            old_doc_id = existing_entry["doc_id"] if existing_entry is not None else None
            doc_id = old_doc_id or _new_doc_id(rel_path, used_doc_ids)
            used_doc_ids.add(doc_id)
            try:
                self._process_document(
                    rel_path=rel_path,
                    doc_id=doc_id,
                    text=text,
                    content_hash=content_hash,
                    replace_old_doc_id=old_doc_id,
                    affected_company_ids=affected_company_ids,
                    report=report,
                    size=size,
                    mtime_ns=mtime_ns,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append((rel_path, str(exc)))

        # 3. Synthesize consensus views in the DB for affected companies.
        if rebuild_consensus:
            target_company_ids = sorted(
                n.id
                for n in self.db.list_nodes(node_type="entity", limit=5000)
                if n.facets.get("entity_type") == "company"
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


def _new_doc_id(rel_path: str, used: set[str]) -> str:
    """Path-derived doc ID, salted if a moved note already holds the plain one."""
    candidate = f"doc_{hashlib.sha256(rel_path.encode('utf-8')).hexdigest()[:12]}"
    salt = 0
    while candidate in used:
        salt += 1
        candidate = f"doc_{hashlib.sha256(f'{rel_path}#{salt}'.encode()).hexdigest()[:12]}"
    return candidate


def _resolve_sentiment(*candidates: Any) -> str:
    """First candidate that normalizes to a valid sentiment, in the order given; else neutral."""
    for candidate in candidates:
        value = normalize_sentiment(candidate)
        if value is not None:
            return value
    return "neutral"


def _build_event_node(
    ev: Any, *, event_type: str | None, doc_id: str, source_meta: dict[str, Any], now: datetime
) -> Node:
    facets = facets_list_to_dict(ev.facets)
    facets["event_type"] = event_type
    if ev.event_date:
        facets["event_date"] = ev.event_date
    facets["status"] = ev.status
    explicit = ev.sentiment if "sentiment" in ev.model_fields_set else None
    # Precedence: explicitly extracted field, then a sentiment facet, then the model default.
    facets["sentiment"] = _resolve_sentiment(explicit, facets.get("sentiment"), ev.sentiment)
    facets["source"] = _build_node_source(source_meta, facets)
    return Node(
        id=_make_node_id("evt", ev.name),
        node_type="event",
        name=ev.name.strip(),
        summary=ev.summary.strip(),
        aliases=[],
        facets=facets,
        source_doc_id=doc_id,
        created_at=now,
        updated_at=now,
    )


def _build_view_node(
    vw: Any, *, view_type: str | None, doc_id: str, source_meta: dict[str, Any], now: datetime
) -> Node:
    facets = facets_list_to_dict(vw.facets)
    vtype = view_type
    if vtype == "consensus":
        vtype = "pm_view"
    facets["view_type"] = vtype
    facets["stance"] = vw.stance
    # Precedence: extracted field, then a sentiment facet, then the stance.
    facets["sentiment"] = _resolve_sentiment(
        vw.sentiment, facets.get("sentiment"), derive_sentiment_from_stance(facets["stance"])
    )
    facets["support_strength"] = vw.support_strength
    facets["conviction"] = vw.conviction
    if vw.as_of:
        facets["as_of"] = vw.as_of
    facets["source"] = _build_node_source(source_meta, facets)
    return Node(
        id=_make_node_id("vw", vw.name),
        node_type="view",
        name=vw.name.strip(),
        summary=vw.summary.strip(),
        aliases=[],
        facets=facets,
        source_doc_id=doc_id,
        created_at=now,
        updated_at=now,
    )


def reembed_nodes(db: OntologyDB, llm: Any, node_ids: list[str]) -> int:
    """Recompute and store embeddings for `node_ids` (e.g. merge survivors); returns the count."""
    if db.read_only:
        raise ValueError("reembed_nodes requires a writable OntologyDB.")  # noqa: TRY003
    nodes = db.get_nodes(node_ids)
    if not nodes:
        return 0
    vectors = llm.embed_texts([node_embedding_text(node) for node in nodes])
    mapping = {node.id: vec for node, vec in zip(nodes, vectors, strict=True)}
    return db.replace_node_embeddings(mapping, prune_orphans=False)

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
