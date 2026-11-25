"""SQLite + sqlite-vec persistence for the 4-node stock ontology.

`schema` defines tables, row mapping, and facet merge rules. `storage` owns the
`OntologyDB` connection and every read and write. Import from this package, not
from the submodules, so callers don't depend on the split.
"""

from stock_ontology.db.jobs import TERMINAL_STATES, Job, JobStore, LeaseLostError
from stock_ontology.db.schema import (
    SIGNAL_CATEGORY_ALIASES,
    THEME_EXPOSURE_RELATIONS,
    merge_edge_facets,
    node_meta,
    node_to_dict,
    reconcile_sentiment,
)
from stock_ontology.db.storage import EdgeRejected, OntologyDB, RegistryChangedError

__all__ = [
    "TERMINAL_STATES",
    "EdgeRejected",
    "Job",
    "JobStore",
    "LeaseLostError",
    "RegistryChangedError",
    "SIGNAL_CATEGORY_ALIASES",
    "THEME_EXPOSURE_RELATIONS",
    "OntologyDB",
    "merge_edge_facets",
    "node_meta",
    "node_to_dict",
    "reconcile_sentiment",
]
