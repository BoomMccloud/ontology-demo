"""Read registry revisions and prepare validated record edits for the worker."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from stock_ontology.config import Settings
from stock_ontology.db import OntologyDB
from stock_ontology.registry import (
    OntologyRegistry,
    create_minimal_registry,
    load_registry,
    normalize_name_key,
    normalize_ticker,
)
from stock_ontology.services.errors import ServiceError

RECORD_FIELDS = {
    "companies": {"name", "aliases", "ticker", "sector"},
    "themes": {"name", "aliases", "stage", "description"},
}


def edit_text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > 4000 or (required and not value.strip()):
        raise ServiceError("invalid", f"Enter a valid {field}.", key="service_error.invalid_field", params={"field": field})
    return value.strip()


def edit_aliases(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise ServiceError("invalid", "Enter alternate names as a list.", key="service_error.alternate_names_list")
    return unique_labels([edit_text(alias, "alternate name") for alias in value])


def unique_labels(labels: list[str], *, excluding: str = "") -> list[str]:
    seen = {normalize_name_key(excluding), ""}
    result = []
    for label in labels:
        key = normalize_name_key(label)
        if key not in seen:
            result.append(label)
            seen.add(key)
    return result


def identity_aliases(
    previous_name: str, name: str, aliases: list[str], *, keep_previous_name: bool, max_length: int,
) -> list[str]:
    """The one rule for a renamed or re-aliased record or node: keep the previous name as an alias
    when asked, drop duplicates and the name itself, and refuse an alias over the name length limit."""
    if keep_previous_name and name != previous_name:
        aliases = [*aliases, previous_name]
    aliases = unique_labels(aliases, excluding=name)
    if any(len(alias) > max_length for alias in aliases):
        raise ServiceError("invalid", "An alternate name exceeds the name length limit.", key="service_error.alternate_name_too_long")
    return aliases


def identity_labels(*labels: str | None) -> set[str]:
    """Normalized names, aliases and tickers that identify one record or node."""
    return set(map(normalize_name_key, (label or "" for label in labels))) - {""}


def labels_taken(introduced: set[str], others: Iterable[set[str]]) -> bool:
    """Whether a newly introduced label already identifies another record or node."""
    return any(introduced & labels for labels in others)


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"field": field, "before": before.get(field), "after": value}
        for field, value in after.items() if before.get(field) != value
    ]


class RegistryService:
    """Read the applied registry and review edits. Worker jobs publish and apply changes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_published(self) -> OntologyRegistry:
        """The published registry file, or the built-in minimal registry when there is none."""
        path = Path(self.settings.registry_path)
        return load_registry(path) if path.exists() else create_minimal_registry()

    def get_applied(self, db: OntologyDB) -> OntologyRegistry:
        """The registry this database adopted. A database that never recorded one starts from the
        published file, which its first write stamps. Later changes need explicit adoption."""
        return db.applied_registry() or self.get_published()

    def review_record_edit(
        self, db: OntologyDB, kind: str, record: str, changes: dict[str, Any], *,
        keep_previous_name: bool = False,
    ) -> dict[str, Any]:
        if kind not in RECORD_FIELDS or not changes or changes.keys() - RECORD_FIELDS[kind]:
            raise ServiceError("invalid", "Choose company or theme fields to edit.", key="service_error.choose_record_fields")
        current = self.get_published()
        applied = db.applied_registry()
        if not applied or applied.revision() != current.revision():
            raise ServiceError("conflict", "Apply the published registry before publishing another revision.", key="service_error.apply_before_publish")
        records = getattr(current, kind)
        if kind == "companies":
            match = current.resolve_company(record) or current.resolve_company("", ticker=record)
        else:
            match = current.resolve_theme(record)
        if match is None:
            raise ServiceError("not_found", "That registry record no longer exists.", key="service_error.registry_record_missing")
        index = records.index(match.spec)
        before = match.spec.model_dump(mode="json")
        after = before.copy()
        for field, value in changes.items():
            if field == "aliases":
                after[field] = edit_aliases(value)
            else:
                text = edit_text(value, field, required=field not in {"ticker", "description"})
                after[field] = (normalize_ticker(text) or None) if field == "ticker" else text
        current.check_metadata(after["name"], after.get("description", ""))
        after["aliases"] = identity_aliases(
            before["name"], after["name"], after["aliases"],
            keep_previous_name=keep_previous_name, max_length=current.metadata_max_length["name"],
        )
        if kind == "themes" and "stage" in changes and after["stage"] not in current._vocabulary("theme", "stage")["members"]:
            raise ServiceError("invalid", "Choose a stage from the published registry.", key="service_error.choose_stage")
        if "ticker" in changes and changes["ticker"].strip() and not after["ticker"]:
            raise ServiceError("invalid", "Enter a valid ticker.", key="service_error.invalid_ticker")

        def labels(item: dict[str, Any]) -> set[str]:
            return identity_labels(item["name"], item.get("ticker"), *item["aliases"])

        introduced = labels(after) - labels(before)
        if labels_taken(introduced, (labels(item.model_dump()) for idx, item in enumerate(records) if idx != index)):
            raise ServiceError("conflict", "A name, alternate name, or ticker already identifies another record.", key="service_error.identifier_taken")
        diff = changed_fields(before, after)
        if not diff:
            raise ServiceError("invalid", "Change at least one field before reviewing.", key="service_error.no_changes")
        official = current.official_definitions()
        official["version"] = current.version + 1
        official[kind][index] = after
        proposed = OntologyRegistry.model_validate(official)
        return {
            "diff": diff,
            "payload": {
                "browser_record": {"kind": kind, "record": record, "changes": changes,
                                   "keep_previous_name": keep_previous_name},
                "proposed": proposed.official_definitions(),
                "proposed_revision": proposed.revision(),
                "current_revision": current.revision(),
            },
        }

    @staticmethod
    def browser_publication(db: OntologyDB, target: OntologyRegistry, applied: OntologyRegistry | None) -> bool:
        """Identify the worker receipt for a browser record edit of the currently applied version."""
        if applied is None or not target.publications:
            return False
        receipt = target.publications[-1]
        if receipt.revision != target.revision() or receipt.previous_revision != applied.revision():
            return False
        return any(
            job.state == "succeeded" and bool(job.payload.get("browser_record"))
            and job.payload.get("proposed_revision") == receipt.revision
            for job in db.jobs.list(kind="registry.publish")
        )
