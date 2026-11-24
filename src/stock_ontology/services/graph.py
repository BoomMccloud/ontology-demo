"""Read-only graph queries shared by the web entity page and the CLI entity read.

This is a thin layer over the existing `OntologyDB` overview methods; moving query meaning
out of storage is a later phase. It also adds the consensus status from the refresh rows,
so a consensus whose replacement is pending or failed is shown as stale.
"""

from __future__ import annotations

from typing import Any

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB, node_to_dict, reconcile_sentiment
from stock_ontology.models import Node
from stock_ontology.registry import OntologyRegistry
from stock_ontology.search import node_source_file

# Adapters annotate the read-only connection with this name instead of importing storage.
GraphStore = OntologyDB

__all__ = ["GraphQueries", "GraphStore", "node_to_dict", "open_graph", "reconcile_sentiment"]


def open_graph(settings: Settings, registry: OntologyRegistry | None = None) -> OntologyDB:
    """Open `ontology.db` read-only (`PRAGMA query_only = ON`). Raises FileNotFoundError."""
    return OntologyDB(
        settings.db_path, embedding_dim=settings.embedding_dim, read_only=True, registry=registry
    )


class GraphQueries:
    def __init__(self, db: OntologyDB) -> None:
        self.db = db

    def find_entity(self, query: str) -> Node | None:
        node = self.db.get_node(query)
        if node is not None and node.node_type == "entity":
            return node
        return self.db.find_by_name_or_alias(query, node_type="entity")

    def consensus_status(self, entity_id: str) -> dict[str, Any]:
        """`current`, `pending`, `failed`, or `unavailable`; a shown consensus is stale unless current."""
        has_consensus = self.db.get_entity_consensus(entity_id) is not None
        refresh = self.db.jobs.consensus_state(entity_id)
        state = refresh["state"] if refresh and refresh["completed_revision"] < refresh["target_revision"] else "current"
        if not has_consensus:
            return {"state": "unavailable" if state == "current" else state, "stale": False}
        return {"state": state, "stale": state != "current"}

    def entity_overview(self, entity_id: str) -> dict[str, Any]:
        """Entity, consensus with its status, and cited evidence. Raises KeyError."""
        overview = self.db.get_entity_overview(entity_id)
        entity = overview["entity"]
        if entity["node_type"] != "entity":
            raise KeyError(entity_id)
        nodes = {node.id: node for node in self.db.get_nodes([item["id"] for item in overview["events"] + overview["views"]])}

        def cited(item: dict[str, Any]) -> dict[str, Any]:
            node = nodes.get(item["id"])
            return {
                "id": item["id"], "name": item["name"], "summary": item["summary"],
                "relation": item.get("relation"), "sentiment": item.get("effective_sentiment"),
                "date": (item.get("facets") or {}).get("event_date"),
                "source": {"file": node_source_file(node) if node else "", "doc_id": node.source_doc_id if node else None},
            }

        consensus = overview["consensus"]
        status = self.consensus_status(entity_id)
        consensus_json = None
        if consensus is not None:
            facets = consensus.get("facets", {})
            citations = sorted(
                edge["neighbor"]["id"]
                for edge in self.db.get_incident_edges(consensus["id"])
                if edge["relation"] in ("SUPPORTS", "CONTRADICTS") and edge["direction"] == "incoming"
            )
            consensus_json = {
                "id": consensus["id"], "summary": consensus["summary"], "stance": facets.get("stance"),
                "support_strength": facets.get("support_strength"), "conviction": facets.get("conviction"),
                "pillars": facets.get("pillars", []), "as_of": facets.get("as_of"), "citations": citations,
                "state": status["state"], "stale": status["stale"],
            }
        return {
            "entity": {
                "id": entity["id"], "name": entity["name"], "aliases": entity.get("aliases", []),
                "facets": entity.get("facets", {}),
            },
            "consensus": consensus_json,
            "consensus_status": status["state"],
            "events": [cited(item) for item in overview["events"]],
            "views": [cited(item) for item in overview["views"]],
            "themes": [{"id": t["id"], "name": t["name"], "relation": t.get("relation")} for t in overview["themes"]],
            "related_entities": [
                {"id": r["id"], "name": r["name"], "relation": r.get("relation")} for r in overview["related_entities"]
            ],
        }
