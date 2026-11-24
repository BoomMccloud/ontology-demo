"""Service layer shared by the CLI, web app, and worker.

Adapters call these services instead of opening the notes folder or `ontology.db` for
writes. Reads open the database with `PRAGMA query_only = ON`; writes are submitted as
jobs to the command spool and applied by the worker. Errors are typed so adapters can map
them to stable HTTP statuses and CLI exit codes.
"""

from stock_ontology.services.errors import EXIT_CODES, ServiceError
from stock_ontology.services.graph import GraphQueries, GraphStore, node_to_dict, open_graph, reconcile_sentiment
from stock_ontology.services.notes import NoteRef, NoteSaveError, NotesService
from stock_ontology.services.processing import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    JobRef,
    ProcessingService,
    Submission,
    job_priority,
    spool_dir,
)
from stock_ontology.services.registry import RegistryService

__all__ = [
    "BACKOFF_SECONDS",
    "EXIT_CODES",
    "MAX_ATTEMPTS",
    "GraphQueries",
    "GraphStore",
    "JobRef",
    "NoteRef",
    "NoteSaveError",
    "NotesService",
    "ProcessingService",
    "RegistryService",
    "ServiceError",
    "Submission",
    "job_priority",
    "node_to_dict",
    "open_graph",
    "reconcile_sentiment",
    "spool_dir",
]
