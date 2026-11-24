"""View helpers shared by every web module: rail counts, facet formatting, result links, and note citations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from stock_ontology.i18n import DEFAULT_LANGUAGE, translate_enum, translate_facet_label
from stock_ontology.models import Node
from stock_ontology.search import resolve_safe_note_path
from stock_ontology.services import GraphStore

GENERAL_FOLDERS = {"_general", "(root)"}


def format_facet_value(value: Any, lang: str = DEFAULT_LANGUAGE) -> str:
    """Render any JSON facet value into a human-readable string."""
    if isinstance(value, bool):
        return translate_enum("bool", value, lang=lang)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        if {"amount", "currency"} <= set(value):
            prefix = "\u2265 " if value.get("qualifier") == "at_least" else ""
            return f"{prefix}{value['currency']} {value['amount']:,}"
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def format_facet_pairs(
    facets: dict[str, Any],
    keys: tuple[str, ...] | list[str],
    lang: str = DEFAULT_LANGUAGE,
) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for k in keys:
        if k in facets and facets[k] not in (None, "", [], {}):
            pairs.append(
                {
                    "key": k,
                    "label": translate_facet_label(k, lang=lang),
                    "value": format_facet_value(facets[k], lang=lang),
                }
            )
    return pairs


def build_rail_context(db: GraphStore) -> dict[str, Any]:
    """Compute lightweight sidebar navigation counts from read-only GraphStore."""
    stats = db.get_stats()
    all_entities = db.list_nodes(node_type="entity", limit=1000)
    company_count = sum(
        1
        for ent in all_entities
        if ent.facets.get("entity_type", "entity") == "company"
    )
    other_entity_count = len(all_entities) - company_count
    return {
        "total_nodes": stats["total_nodes"],
        "total_edges": stats["total_edges"],
        "company_count": company_count,
        "other_entity_count": other_entity_count,
        "theme_count": stats["nodes"]["theme"],
        "doc_count": stats["ingested_files"],
    }


def resolve_result_href(db: GraphStore, node: Node) -> str:
    if node.node_type == "entity":
        return f"/entity/{node.id}"
    if node.node_type == "theme":
        return f"/theme/{node.id}"
    for edge in db.get_incident_edges(node.id):
        nb = edge["neighbor"]
        if nb["node_type"] == "entity":
            return f"/entity/{nb['id']}#node-{node.id}"
    for edge in db.get_incident_edges(node.id):
        nb = edge["neighbor"]
        if nb["node_type"] == "theme":
            return f"/theme/{nb['id']}#node-{node.id}"
    return "/"


def strip_markdown_markers(line: str) -> str:
    cleaned = re.sub(r"^#{1,6}\s*", "", line.strip())
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", cleaned)
    return cleaned.strip()


def extract_title_and_excerpt(text: str, stem: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = ""
    excerpt = ""

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            title = strip_markdown_markers(s)
            break
        if not title and s.startswith("## "):
            title = strip_markdown_markers(s)

    if not title:
        title = stem.replace("_", " ").replace("-", " ").title()

    for line in lines:
        s = line.strip()
        if (
            not s
            or s.startswith("#")
            or s.startswith("|")
            or re.match(r"^[-*_]{3,}$", s)
        ):
            continue
        cleaned = strip_markdown_markers(s)
        if cleaned and cleaned != title:
            excerpt = cleaned[:177] + "..." if len(cleaned) > 180 else cleaned
            break

    return title, excerpt


def format_source_citation(
    file_path: str | None, data_dir: Path | None = None
) -> tuple[str, bool]:
    """Return `(human_label, note_exists_on_disk)` for a note's `file_path`."""
    if not file_path or not str(file_path).strip():
        return "", False

    raw = str(file_path).strip()
    if data_dir is not None:
        candidate = resolve_safe_note_path(data_dir, raw)
        if candidate is not None:
            text = candidate.read_text(encoding="utf-8", errors="replace")
            title, _ = extract_title_and_excerpt(text, candidate.stem)
            return title, True

    parts = [p for p in raw.replace("\\", "/").split("/") if p]
    filename = parts[-1] if parts else raw
    stem = re.sub(r"\.(?:md|markdown|txt)$", "", filename, flags=re.IGNORECASE)
    folder = parts[0] if len(parts) > 1 and parts[0] not in GENERAL_FOLDERS else ""

    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})[_\-\s]+(.+)$", stem)
    if date_match:
        date_str, rest = date_match.group(1), date_match.group(2)
    else:
        date_str, rest = "", stem

    tokens = [tok for tok in re.split(r"[\s_-]+", rest) if tok]
    title_part = " ".join(tok if tok.isupper() else tok.title() for tok in tokens)

    if folder and title_part:
        base = f"{folder} — {title_part}"
    else:
        base = title_part or folder or stem
    label = f"{base} ({date_str})" if date_str else base
    return label, False
