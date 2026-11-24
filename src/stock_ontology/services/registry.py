"""The one read path for the registry that graph writes are checked against."""

from __future__ import annotations

from pathlib import Path

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.registry import OntologyRegistry, create_minimal_registry, load_registry


class RegistryService:
    """Reads the applied registry. Publish and apply stay operator CLI commands run as worker jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_published(self) -> OntologyRegistry:
        """The published registry file, or the built-in minimal registry when there is none."""
        path = Path(self.settings.registry_path)
        return load_registry(path) if path.exists() else create_minimal_registry()

    def get_applied(self, db: OntologyDB) -> OntologyRegistry:
        """The registry this database adopted. A database that never recorded one starts from the
        published file, which its first write stamps; later changes need `registry-apply`."""
        return db.applied_registry() or self.get_published()
