"""Read-only raw research notes catalog browser and XSS-safe Markdown renderer."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from stock_ontology.config import note_revision
from stock_ontology.i18n import DEFAULT_LANGUAGE, translate, translate_facet_label
from stock_ontology.search import resolve_safe_note_path
from stock_ontology.services import GraphStore
from stock_ontology.services.notes import scan_notes
from stock_ontology.vocab import ENTITY_TYPE
from stock_ontology.web.shared import (
    GENERAL_FOLDERS,
    extract_title_and_excerpt,
    relationship_editor_model,
    strip_markdown_markers,
)

AUTHOR_FOLDER_ROOTS = {"authors", "analysts", "people", "persons"}

_ANALYST_ROLE_RE = re.compile(
    r"\b(?:analyst|research(?:er)?|strategist|portfolio\s+manager|fund\s+manager|author|economist|desk|pm)\b",
    re.IGNORECASE,
)
_NON_AUTHOR_ROLE_RE = re.compile(
    r"\b(?:ceo|cfo|coo|cto|cio|cmo|chief\s+\w+\s+officer|president|chairman|chair|board|director|committee|attorney|minister|senator|governor|founder|co-founder|executive|svp|evp|vp)\b",
    re.IGNORECASE,
)
_HEADER_AUTHOR_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:(?:\*{1,2}|_{1,2})(?:authors?|analysts?|prepared\s+by|written\s+by):(?:\*{1,2}|_{1,2})|(?:\*{1,2}|_{1,2})?(?:authors?|analysts?|prepared\s+by|written\s+by)(?:\*{1,2}|_{1,2})?:)\s*(.+)$",
    re.IGNORECASE,
)


def _is_research_analyst_role(role: str) -> bool:
    """Return True when an entity's role identifies a research analyst or note author."""
    return bool(role and _ANALYST_ROLE_RE.search(role))


def _is_non_author_role(role: str) -> bool:
    """Return True for corporate executives, board/committee members, or public officials."""
    return bool(role and _NON_AUTHOR_ROLE_RE.search(role))


def _extract_note_date(filename: str, modified_at: str) -> str:
    """Extract leading YYYY-MM-DD from filename or fall back to modified date."""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})\b", filename)
    if match:
        return match.group(1)
    return modified_at[:10] if len(modified_at) >= 10 else ""


def _clean_author_token(raw_token: str) -> str:
    cleaned = strip_markdown_markers(raw_token)
    cleaned = re.sub(r"<br\s*/?>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" \t\r\n\"'[]")
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_note_authors(text: str) -> list[str]:
    """Extract explicit authors from YAML frontmatter or leading metadata headers."""
    lines = text.splitlines()
    raw_values: list[str] = []

    idx = 0
    if lines and lines[0].strip() == "---":
        idx = 1
        in_authors_list = False
        while idx < len(lines) and idx < 40:
            line = lines[idx]
            stripped = line.strip()
            idx += 1
            if stripped == "---":
                break
            fm_match = re.match(r"^(authors?)\s*:\s*(.*)$", stripped, re.IGNORECASE)
            if fm_match:
                val = fm_match.group(2).strip()
                if val:
                    raw_values.append(val.strip("[]"))
                    in_authors_list = False
                else:
                    in_authors_list = True
                continue
            if in_authors_list and stripped.startswith("- "):
                raw_values.append(stripped[2:].strip())
            elif stripped and ":" in stripped:
                in_authors_list = False

    non_empty_seen = 0
    for line in lines[idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        non_empty_seen += 1
        if non_empty_seen > 25 or stripped.startswith("## "):
            break
        match = _HEADER_AUTHOR_RE.match(stripped)
        if match:
            raw_values.append(match.group(1))

    authors: list[str] = []
    seen: set[str] = set()
    for raw_val in raw_values:
        for part in re.split(r"[,;](?![^(]*\))", raw_val):
            name = _clean_author_token(part)
            if not name or len(name) < 2 or len(name) > 80:
                continue
            if name.lower() in {"n/a", "none", "unknown", "-", "tbd"}:
                continue
            if "http://" in name.lower() or "https://" in name.lower():
                continue
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                authors.append(name)
    return authors


def _slug_key(value: str) -> str:
    """Normalize names, tickers, and folder names for matching."""
    return re.sub(r"[^a-z0-9]+", "", value.strip().casefold())


def _ascii_initial(value: str) -> str:
    """Return uppercase ASCII A-Z initial for quick-filter index bars, or empty string."""
    stripped = value.strip()
    if not stripped:
        return ""
    first = stripped[0].upper()
    return first if first.isascii() and first.isalpha() else ""


def _format_inline_markdown(escaped_text: str, *, allow_br: bool = False) -> str:
    """Apply safe inline bold/italic/code formatting to already HTML-escaped text."""
    text = escaped_text
    if allow_br:
        text = re.sub(r"&lt;br\s*/?&gt;", "\n", text, flags=re.IGNORECASE)

    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        idx = len(code_spans)
        code_spans.append(f"<code>{match.group(1)}</code>")
        return f"@@CODE{idx}@@"

    text = re.sub(r"`([^`\n]+)`", _stash_code, text)
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)

    for idx, span in enumerate(code_spans):
        text = text.replace(f"@@CODE{idx}@@", span)

    if allow_br:
        text = text.replace("\n", "<br>")
    return text


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped or "-" not in stripped:
        return False
    return bool(re.match(r"^\|?[\s:\-|]+\|[\s:\-|]*$", stripped))


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]



def render_markdown_safe(text: str) -> str:
    """Render Markdown notes into HTML after escaping all untrusted input first."""
    escaped = html.escape(text.replace("\r\n", "\n").replace("\r", "\n"), quote=True)
    lines = escaped.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code blocks
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            out.append(f"<pre class=\"note-code-block\"><code>{chr(10).join(code_lines)}</code></pre>")
            continue

        # Horizontal rules
        if re.match(r"^([-*_])(?:\s*\1){2,}\s*$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # Headings (# through ####)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            content = _format_inline_markdown(heading_match.group(2))
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Markdown tables
        if stripped.startswith("|") and i + 1 < n and _is_table_separator(lines[i + 1]):
            headers = _split_table_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|") and lines[i].strip():
                rows.append(_split_table_row(lines[i]))
                i += 1
            col_count = len(headers)
            table_parts = ['<table class="catalog-table note-table"><thead><tr>']
            for cell in headers:
                table_parts.append(f"<th>{_format_inline_markdown(cell, allow_br=True)}</th>")
            table_parts.append("</tr></thead><tbody>")
            for row in rows:
                table_parts.append("<tr>")
                for col_idx in range(col_count):
                    cell = row[col_idx] if col_idx < len(row) else ""
                    table_parts.append(f"<td>{_format_inline_markdown(cell, allow_br=True)}</td>")
                table_parts.append("</tr>")
            table_parts.append("</tbody></table>")
            out.append("".join(table_parts))
            continue

        # Blockquotes (note: '>' was escaped to '&gt;')
        if stripped.startswith("&gt;"):
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith("&gt;"):
                q_line = re.sub(r"^&gt;\s?", "", lines[i].strip())
                quote_lines.append(_format_inline_markdown(q_line))
                i += 1
            out.append(f"<blockquote>{'<br>'.join(quote_lines)}</blockquote>")
            continue

        # Unordered / ordered lists
        ul_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        ol_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ul_match or ol_match:
            is_ordered = ol_match is not None
            tag = "ol" if is_ordered else "ul"
            pattern = r"^\s*\d+\.\s+(.+)$" if is_ordered else r"^\s*[-*+]\s+(.+)$"
            items: list[str] = []
            while i < n:
                curr = lines[i]
                if not curr.strip():
                    break
                m = re.match(pattern, curr)
                if m:
                    items.append(f"<li>{_format_inline_markdown(m.group(1))}</li>")
                    i += 1
                elif curr.startswith("  ") and items and not re.match(r"^\s*[-*+\d]+\.?\s+", curr):
                    items[-1] = items[-1][:-5] + " " + _format_inline_markdown(curr.strip()) + "</li>"
                    i += 1
                else:
                    break
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        # Paragraph
        para_lines: list[str] = []
        while i < n:
            curr = lines[i]
            c_strip = curr.strip()
            if (
                not c_strip
                or c_strip.startswith("```")
                or c_strip.startswith("&gt;")
                or re.match(r"^#{1,4}\s+", c_strip)
                or re.match(r"^([-*_])(?:\s*\1){2,}\s*$", c_strip)
                or re.match(r"^[-*+]\s+", c_strip)
                or re.match(r"^\d+\.\s+", c_strip)
                or (c_strip.startswith("|") and i + 1 < n and _is_table_separator(lines[i + 1]))
            ):
                break
            para_lines.append(_format_inline_markdown(c_strip))
            i += 1
        out.append(f"<p>{' '.join(para_lines)}</p>")

    return "\n".join(out)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    return f"{size_bytes / 1024:.1f} KB"


def _scan_raw_notes(
    data_dir: Path, db: GraphStore
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Notes and their extraction status from `NotesService`, with catalog presentation fields."""
    doc_counts = db.get_doc_node_counts()
    notes: list[dict[str, Any]] = []
    note_texts_lower: dict[str, str] = {}

    for note in scan_notes(data_dir, db.get_ingestion_log()):
        rel = Path(note.rel_path)
        text = note.text
        title, excerpt = extract_title_and_excerpt(text, note.path.stem)
        parts = rel.parts
        folder = parts[0] if len(parts) > 1 else "(root)"
        subdir = rel.parent.as_posix() if rel.parent.as_posix() != "." else "(root)"
        counts = doc_counts.get(note.doc_id, {}) if note.doc_id else {}
        modified_at = datetime.fromtimestamp(note.mtime, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
        notes.append(
            {
                "rel_path": note.rel_path,
                "folder": folder,
                "subdir": subdir,
                "filename": note.path.name,
                "title": title,
                "excerpt": excerpt,
                "note_date": _extract_note_date(note.path.name, modified_at),
                "header_authors": _extract_note_authors(text),
                "size_bytes": note.size,
                "size_label": _format_size(note.size),
                "line_count": len(text.splitlines()),
                "modified_at": modified_at,
                "status": note.status,
                "doc_id": note.doc_id,
                "ingested_at": note.ingested_at,
                "extracted_events": int(counts.get("event", 0)),
                "extracted_views": int(counts.get("view", 0)),
                "extracted_total": int(counts.get("total", 0)),
            }
        )
        note_texts_lower[note.rel_path] = text.casefold()

    return notes, note_texts_lower


# ---------------------------------------------------------------------------
# Note page presentation models. `build_catalog_context` hands the note reader
# (`partials/note_reader.html`) one `NoteDetail`, built by `_note_detail`, so the
# template decides no links or labels. Enum codes (`reasons`) stay raw for `t_enum`.
# `tests/test_web_notes.py::test_note_page_templates_only_see_presentation_models` enforces this.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteLink:
    """A labeled link on the note page."""

    label: str
    href: str


@dataclass(frozen=True)
class NoteCompanyChip:
    """The company the note's folder matches."""

    label: str
    href: str


@dataclass(frozen=True)
class NoteAuthorChip:
    """An author linked to the note, with why it is linked."""

    name: str
    href: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class NoteEntity:
    id: str
    name: str
    kind: str
    href: str


@dataclass(frozen=True)
class NoteRelationship:
    id: str
    start: str
    relation: str
    end: str
    pending: bool
    start_id: str
    end_id: str


@dataclass(frozen=True)
class NoteEntityType:
    key: str
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class NoteExtraction:
    status: str
    actions_enabled: bool
    # State of the note's latest job (`queued`, `running`, `succeeded`, `failed`, ...), or "".
    job_state: str = ""
    content_hash: str = ""
    entities: tuple[NoteEntity, ...] = ()
    relationships: tuple[NoteRelationship, ...] = ()
    choices: tuple[NoteEntity, ...] = ()
    entity_types: tuple[NoteEntityType, ...] = ()
    relations: tuple[str, ...] = ()
    # The `static/editor.js` relationship editor model, or None when relationships cannot be corrected.
    relationship_model: dict[str, Any] | None = None


def _note_extraction(
    db: GraphStore, file: str, raw_text: str, actions_enabled: bool, lang: str, job_state: str = "",
) -> NoteExtraction:
    entry = db.get_note_state(file)
    content_hash = note_revision(raw_text)
    if not entry or not entry["entities_recorded"] or entry["content_hash"] != content_hash:
        return NoteExtraction("not-processed", actions_enabled, job_state)

    doc_id = entry["doc_id"]
    entities = tuple(
        NoteEntity(node.id, node.name, node.facets["entity_type"], f"/entity/{quote(node.id, safe='')}")
        for node in db.list_note_entities(doc_id)
    )
    relationships = tuple(
        NoteRelationship(
            id=edge["edge_id"], start=edge["from_name"], relation=edge["relation"], end=edge["to_name"],
            pending=pending, start_id=edge["from_id"], end_id=edge["to_id"],
        )
        for pending in (False, True) for edge in db.list_note_edges(doc_id, pending=pending)
    )
    relations = tuple(sorted(spec.name for spec in db.registry.relations)) if actions_enabled else ()
    available_nodes = []
    if relations:
        available_nodes = db.list_all_nodes()
    elif actions_enabled:
        available_nodes = db.list_nodes(node_type="entity", limit=-1)
    available_nodes.sort(key=lambda node: node.name.casefold())

    choices = ()
    entity_types = ()
    if actions_enabled:
        choices = tuple(
            NoteEntity(node.id, node.name, node.facets["entity_type"], "")
            for node in available_nodes if node.node_type == "entity"
        )
        entity_types = tuple(
            NoteEntityType(kind, tuple(
                (key, translate_facet_label(key, lang=lang))
                for key in sorted(db.registry.required_facets("entity", kind) - {"entity_type"})
            ))
            for kind in ENTITY_TYPE.members
        )
    return NoteExtraction(
        "extracted", actions_enabled, job_state, content_hash, entities, relationships, choices, entity_types,
        relations, relationship_editor_model(db.registry, available_nodes, lang) if relations else None,
    )


def safe_return_path(raw: str) -> str:
    """Accept only a same-site path for a note's return link; anything else becomes ``""``."""
    value = raw.strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return ""
    return value


@dataclass(frozen=True)
class NoteDetail:
    """Everything the note reader shows for one raw note."""

    rel_path: str
    title: str
    folder: str
    subject_label: str
    company: NoteCompanyChip | None
    authors: tuple[NoteAuthorChip, ...]
    # Set only when the reader arrived from a page outside the catalog. The breadcrumb is the
    # one link to the note's catalog parent, so there is never a second link to the same place.
    return_link: NoteLink | None
    extraction: NoteExtraction
    show_raw: bool
    body_html: str
    raw_lines: tuple[str, ...]
    prev_link: NoteLink | None
    next_link: NoteLink | None


def _note_detail(
    note_meta: dict[str, Any],
    raw_text: str,
    *,
    fmt: str,
    view_mode: str,
    active_group: dict[str, Any] | None,
    sibling_list: list[dict[str, Any]],
    matched_company: dict[str, Any] | None,
    author_groups: list[dict[str, Any]],
    extraction: NoteExtraction,
    lang: str,
    alpha: str = "",
    return_to: str = "",
) -> NoteDetail:
    """Map a resolved note and its catalog lookups to the note reader's model."""
    rel_path = str(note_meta["rel_path"])
    folder = str(note_meta["folder"])
    subject_label = str(note_meta["subject_label"])

    company = None
    if matched_company:
        ticker = matched_company.get("ticker")
        label = f"{matched_company['name']} ({ticker})" if ticker else str(matched_company["name"])
        company = NoteCompanyChip(label=label, href=f"/entity/{matched_company['id']}")

    authors = tuple(
        NoteAuthorChip(
            name=str(grp["name"]),
            href=grp["entity_href"] or None,
            reasons=tuple(
                next((n["link_reasons"] for n in grp["notes"] if n["rel_path"] == rel_path), [])
            ),
        )
        for grp in author_groups
        if any(n["rel_path"] == rel_path for n in grp["notes"])
    )

    # The list letter filter rides along so Back and Prev/Next return to the same list state.
    alpha_query = f"&alpha={quote(alpha)}" if alpha else ""
    if view_mode == "company":
        list_query = f"view=company&dir={quote(folder)}{alpha_query}"
    elif view_mode == "author" and active_group:
        list_query = f"view=author&author={quote(str(active_group['id']))}{alpha_query}"
    else:
        list_query = f"view={view_mode}{alpha_query}"

    # A reader who arrived from Search or a research page gets a link back there; the breadcrumb
    # still names the note's predictable parent in the catalog.
    return_link = None
    if return_to:
        back_key = "catalog.back_to_search" if return_to.startswith("/search") else "catalog.back_to_previous"
        return_link = NoteLink(label=translate(back_key, lang=lang), href=return_to)
        list_query += f"&back={quote(return_to, safe='')}"

    def _sibling(sib: dict[str, Any]) -> NoteLink:
        return NoteLink(
            label=str(sib["title"]), href=f"/catalog?{list_query}&file={quote(str(sib['rel_path']))}"
        )

    prev_link = None
    next_link = None
    for idx, sib in enumerate(sibling_list):
        if sib["rel_path"] == rel_path:
            if idx > 0:
                prev_link = _sibling(sibling_list[idx - 1])
            if idx + 1 < len(sibling_list):
                next_link = _sibling(sibling_list[idx + 1])
            break

    show_raw = fmt == "raw"
    return NoteDetail(
        rel_path=rel_path,
        title=str(note_meta["title"]),
        folder=folder,
        subject_label=subject_label,
        company=company,
        authors=authors,
        return_link=return_link,
        extraction=extraction,
        show_raw=show_raw,
        body_html="" if show_raw else render_markdown_safe(raw_text),
        raw_lines=tuple(raw_text.splitlines()) if show_raw else (),
        prev_link=prev_link,
        next_link=next_link,
    )


def build_catalog_context(
    db: GraphStore,
    data_dir: Path,
    *,
    view: str = "company",
    selected_dir: str = "",
    selected_author: str = "",
    selected_person: str = "",
    selected_alpha: str = "",
    selected_file: str = "",
    note_format: str = "rendered",
    return_to: str = "",
    actions_enabled: bool = False,
    note_job_state: Callable[[str], str] | None = None,
    lang: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Build single-pane directory catalog context (By Company, By Author, or All Notes)."""
    raw_view = view.strip().lower()
    if raw_view in ("author", "authors", "person", "people"):
        view_mode = "author"
    elif raw_view == "all":
        view_mode = "all"
    else:
        view_mode = "company"

    active_author = selected_author.strip() or selected_person.strip()
    alpha_clean = selected_alpha.strip().upper()
    active_alpha = (
        alpha_clean[0]
        if len(alpha_clean) == 1 and alpha_clean.isascii() and alpha_clean.isalpha()
        else ""
    )
    fmt = "raw" if note_format.strip().lower() == "raw" else "rendered"

    stats = db.get_stats()
    data_dir_exists = data_dir.exists() and data_dir.is_dir()
    notes, note_texts_lower = _scan_raw_notes(data_dir, db)
    notes_by_path = {n["rel_path"]: n for n in notes}

    all_entities = db.list_nodes(node_type="entity", limit=1000)
    company_lookup: dict[str, dict[str, Any]] = {}
    person_lookup: dict[str, dict[str, Any]] = {}
    person_nodes: list[dict[str, Any]] = []

    for ent in all_entities:
        etype = str(ent.facets.get("entity_type", "entity"))
        if etype == "company":
            cons = db.get_entity_consensus(ent.id)
            comp_info = {
                "id": ent.id,
                "name": ent.name,
                "ticker": str(ent.facets.get("ticker", "")),
                "sector": str(ent.facets.get("sector", "")),
                "consensus_stance": str(cons.facets.get("stance", "")) if cons else "",
            }
            candidates = [ent.name, comp_info["ticker"], *ent.aliases]
            for cand in candidates:
                sk = _slug_key(cand)
                if sk and sk not in company_lookup:
                    company_lookup[sk] = comp_info
        elif etype == "person":
            p_info = {
                "id": ent.id,
                "name": ent.name,
                "aliases": list(ent.aliases),
                "role": str(ent.facets.get("role", "")),
                "organization": str(ent.facets.get("organization", "")),
                "credibility": str(ent.facets.get("credibility", "")),
                "entity_href": f"/entity/{ent.id}",
            }
            person_nodes.append(p_info)
            for cand in [ent.name, *ent.aliases]:
                sk = _slug_key(cand)
                if sk and sk not in person_lookup:
                    person_lookup[sk] = p_info

    general_label = translate("catalog.general_label", lang=lang)

    def _subject_label_for_folder(folder_name: str) -> str:
        matched_co = company_lookup.get(_slug_key(folder_name))
        if matched_co is not None:
            return str(matched_co["name"])
        if folder_name in GENERAL_FOLDERS:
            return general_label
        return folder_name

    for note in notes:
        note["subject_label"] = _subject_label_for_folder(note["folder"])

    # 1. Group raw notes by directory (By Company vs. author/other folders)
    dir_buckets: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        dir_buckets.setdefault(note["folder"], []).append(note)

    company_groups: list[dict[str, Any]] = []
    other_dir_groups: list[dict[str, Any]] = []

    for folder_name, folder_notes in dir_buckets.items():
        sorted_notes = sorted(folder_notes, key=lambda n: n["rel_path"], reverse=True)
        ingested_cnt = sum(1 for n in sorted_notes if n["status"] == "ingested")
        folder_slug = _slug_key(folder_name)
        matched_company = company_lookup.get(folder_slug)
        matched_person = person_lookup.get(folder_slug) if matched_company is None else None
        is_author_root = folder_name.lower() in AUTHOR_FOLDER_ROOTS
        is_general = folder_name in GENERAL_FOLDERS

        dir_label = (
            matched_company["name"]
            if matched_company is not None
            else (general_label if is_general else folder_name)
        )
        group_obj = {
            "key": folder_name,
            "dir_label": dir_label,
            "initial": _ascii_initial(dir_label),
            "entity": matched_company,
            "matched_person": matched_person,
            "notes": sorted_notes,
            "note_count": len(sorted_notes),
            "ingested_count": ingested_cnt,
            "latest_date": max((n["note_date"] for n in sorted_notes), default=""),
            "is_general": is_general,
            "is_person_dir": is_author_root or matched_person is not None,
        }

        if group_obj["is_person_dir"]:
            other_dir_groups.append(group_obj)
        else:
            company_groups.append(group_obj)

    company_groups.sort(key=lambda g: (1 if g["is_general"] else 0, g["key"].casefold()))
    other_dir_groups.sort(key=lambda g: g["key"].casefold())
    company_letters = sorted({g["initial"] for g in company_groups if g["initial"]})
    filtered_company_groups = (
        [g for g in company_groups if g["initial"] == active_alpha]
        if active_alpha
        else company_groups
    )

    # 2. Group raw notes by Author (research analysts & note authors only; excludes company executives)
    log = db.get_ingestion_log()
    doc_id_to_path = {entry["doc_id"]: fp for fp, entry in log.items()}
    person_links_by_id = db.get_entity_document_links(entity_type="person")

    qualifying_persons: list[dict[str, Any]] = []
    for p_info in person_nodes:
        pid = p_info["id"]
        role = p_info["role"]
        links = person_links_by_id.get(pid, [])
        has_authored = any(lk.get("relation") == "AUTHORED_BY" for lk in links)
        if _is_research_analyst_role(role) or (has_authored and not _is_non_author_role(role)):
            qualifying_persons.append(p_info)

    author_note_reasons: dict[str, dict[str, set[str]]] = {}
    author_meta_by_key: dict[str, dict[str, Any]] = {}

    # (a) Explicit note headers / YAML frontmatter authors
    for note in notes:
        for author_name in note.get("header_authors", []):
            p_match = person_lookup.get(_slug_key(author_name))
            if p_match is not None:
                author_meta_by_key.setdefault(p_match["id"], p_match)
                author_note_reasons.setdefault(p_match["id"], {}).setdefault(
                    note["rel_path"], set()
                ).add("authored")
            else:
                synth_id = f"header_author_{_slug_key(author_name)}"
                if synth_id and synth_id not in author_meta_by_key:
                    author_meta_by_key[synth_id] = {
                        "id": synth_id,
                        "name": author_name,
                        "aliases": [],
                        "role": "Research Analyst",
                        "organization": "",
                        "credibility": "",
                        "entity_href": None,
                    }
                if synth_id:
                    author_note_reasons.setdefault(synth_id, {}).setdefault(
                        note["rel_path"], set()
                    ).add("authored")

    # (b) Direct disk folders named after an author (top-level or authors/<Name>/...)
    for note in notes:
        rel_parts = note["rel_path"].split("/")
        folder_candidates: list[str] = []
        if len(rel_parts) >= 2 and rel_parts[0].lower() in AUTHOR_FOLDER_ROOTS:
            if len(rel_parts) >= 3:
                folder_candidates.append(rel_parts[1])
        elif len(rel_parts) >= 2:
            folder_candidates.append(rel_parts[0])

        for cand in folder_candidates:
            p_match = person_lookup.get(_slug_key(cand))
            if p_match is not None:
                author_meta_by_key.setdefault(p_match["id"], p_match)
                author_note_reasons.setdefault(p_match["id"], {}).setdefault(
                    note["rel_path"], set()
                ).add("folder")
            elif len(rel_parts) >= 3 and rel_parts[0].lower() in AUTHOR_FOLDER_ROOTS:
                synth_id = f"dir_author_{_slug_key(cand)}"
                if synth_id not in author_meta_by_key:
                    author_meta_by_key[synth_id] = {
                        "id": synth_id,
                        "name": cand.replace("_", " ").replace("-", " "),
                        "aliases": [],
                        "role": "Directory",
                        "organization": "",
                        "credibility": "",
                        "entity_href": None,
                    }
                author_note_reasons.setdefault(synth_id, {}).setdefault(
                    note["rel_path"], set()
                ).add("folder")

    # (c) Graph provenance for qualifying analysts/authors (AUTHORED_BY / other edges to doc-scoped nodes)
    for p_info in qualifying_persons:
        pid = p_info["id"]
        author_meta_by_key.setdefault(pid, p_info)
        reasons_map = author_note_reasons.setdefault(pid, {})

        for link in person_links_by_id.get(pid, []):
            candidate_paths: set[str] = set()
            if link.get("doc_id") and link["doc_id"] in doc_id_to_path:
                candidate_paths.add(doc_id_to_path[link["doc_id"]])
            if link.get("file_path"):
                candidate_paths.add(str(link["file_path"]))
            reason = "authored" if link.get("relation") == "AUTHORED_BY" else "graph"
            for fp in candidate_paths:
                if fp in notes_by_path:
                    reasons_map.setdefault(fp, set()).add(reason)

    # (d) Text mention fallback ONLY for qualifying research analysts/authors
    for p_info in qualifying_persons:
        pid = p_info["id"]
        reasons_map = author_note_reasons.setdefault(pid, {})
        names_to_check = [p_info["name"], *p_info["aliases"]]
        searchable = [n.strip().casefold() for n in names_to_check if len(n.strip()) >= 4]
        if not searchable:
            continue
        for rel_path, text_low in note_texts_lower.items():
            if rel_path in reasons_map:
                continue
            if any(name_low in text_low for name_low in searchable):
                reasons_map.setdefault(rel_path, set()).add("mentioned")

    author_groups: list[dict[str, Any]] = []
    assigned_paths: set[str] = set()
    reason_order = {"folder": 0, "authored": 1, "graph": 2, "mentioned": 3}

    for pid, reasons_map in author_note_reasons.items():
        if not reasons_map:
            continue
        meta = author_meta_by_key[pid]
        p_notes: list[dict[str, Any]] = []
        for rel_path, reason_set in reasons_map.items():
            base_note = notes_by_path.get(rel_path)
            if base_note is None:
                continue
            assigned_paths.add(rel_path)
            ordered_reasons = sorted(reason_set, key=lambda r: reason_order.get(r, 9))
            p_notes.append({**base_note, "link_reasons": ordered_reasons})
        p_notes.sort(key=lambda n: n["rel_path"], reverse=True)
        if p_notes:
            companies = sorted({str(n["subject_label"]) for n in p_notes})
            all_reasons = sorted(
                {r for n in p_notes for r in n["link_reasons"]},
                key=lambda r: reason_order.get(r, 9),
            )
            initial = _ascii_initial(meta["name"])
            author_groups.append(
                {
                    **meta,
                    "notes": p_notes,
                    "note_count": len(p_notes),
                    "companies": companies,
                    "link_reasons": all_reasons,
                    "initial": initial,
                }
            )

    author_groups.sort(key=lambda p: (-p["note_count"], p["name"].casefold()))
    author_letters = sorted({g["initial"] for g in author_groups if g["initial"]})
    filtered_author_groups = (
        [g for g in author_groups if g["initial"] == active_alpha]
        if active_alpha
        else author_groups
    )

    all_notes: list[dict[str, Any]] = []
    for item in sorted(notes, key=lambda n: n["rel_path"], reverse=True):
        all_notes.append(
            {
                **item,
                "initial": _ascii_initial(item["title"]) or _ascii_initial(item["subject_label"]),
            }
        )
    all_note_letters = sorted({n["initial"] for n in all_notes if n["initial"]})
    filtered_all_notes = (
        [n for n in all_notes if n["initial"] == active_alpha]
        if active_alpha
        else all_notes
    )
    unassigned_author_notes = [n for n in all_notes if n["rel_path"] not in assigned_paths]
    unassigned_companies = sorted({str(n["subject_label"]) for n in unassigned_author_notes})

    # 3. Determine active filter group & visible notes
    active_group: dict[str, Any] | None = None
    visible_notes: list[dict[str, Any]] = list(all_notes)

    if view_mode == "company" and selected_dir:
        for grp in company_groups + other_dir_groups:
            if grp["key"] == selected_dir:
                active_group = {"kind": "directory", "label": grp["dir_label"], **grp}
                visible_notes = grp["notes"]
                break
    elif view_mode == "author" and active_author:
        if active_author == "__unassigned__":
            active_group = {
                "kind": "author",
                "id": "__unassigned__",
                "name": translate("catalog.unassigned_authors", lang=lang),
                "label": translate("catalog.unassigned_authors", lang=lang),
                "notes": unassigned_author_notes,
                "note_count": len(unassigned_author_notes),
                "companies": unassigned_companies,
            }
            visible_notes = unassigned_author_notes
        else:
            sel_norm = active_author.casefold()
            for grp in author_groups:
                if grp["id"] == active_author or grp["name"].casefold() == sel_norm:
                    active_group = {"kind": "author", "label": grp["name"], **grp}
                    visible_notes = grp["notes"]
                    break

    # 4. Optional selected raw note preview
    active_note: NoteDetail | None = None
    if selected_file.strip():
        candidate = resolve_safe_note_path(data_dir, selected_file.strip())
        if candidate is None:
            raise FileNotFoundError(f"Raw note not found: {selected_file}")

        canonical_rel = candidate.relative_to(data_dir.resolve()).as_posix()
        raw_text = candidate.read_text(encoding="utf-8", errors="replace")
        note_meta = notes_by_path.get(canonical_rel)
        if note_meta is None:
            title, excerpt = extract_title_and_excerpt(raw_text, candidate.stem)
            stat = candidate.stat()
            rel_parts = candidate.relative_to(data_dir.resolve()).parts
            fallback_folder = rel_parts[0] if len(rel_parts) > 1 else "(root)"
            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            note_meta = {
                "rel_path": canonical_rel,
                "folder": fallback_folder,
                "subject_label": _subject_label_for_folder(fallback_folder),
                "filename": candidate.name,
                "title": title,
                "excerpt": excerpt,
                "note_date": _extract_note_date(candidate.name, modified_at),
                "header_authors": _extract_note_authors(raw_text),
                "size_label": _format_size(stat.st_size),
                "line_count": len(raw_text.splitlines()),
                "modified_at": modified_at,
                "status": "not_ingested",
                "extracted_events": 0,
                "extracted_views": 0,
                "extracted_total": 0,
            }

        sibling_list: list[dict[str, Any]] = []
        if active_group is not None:
            sibling_list = active_group["notes"]
        elif view_mode == "all":
            sibling_list = filtered_all_notes
        else:
            for grp in company_groups + other_dir_groups:
                if grp["key"] == note_meta["folder"]:
                    sibling_list = grp["notes"]
                    break

        with db.transaction():
            extraction = _note_extraction(
                db, canonical_rel, raw_text, actions_enabled, lang,
                note_job_state(canonical_rel) if note_job_state is not None else "",
            )
        active_note = _note_detail(
            note_meta,
            raw_text,
            fmt=fmt,
            view_mode=view_mode,
            active_group=active_group,
            sibling_list=sibling_list,
            matched_company=company_lookup.get(_slug_key(note_meta["folder"])),
            author_groups=author_groups,
            extraction=extraction,
            lang=lang,
            alpha=active_alpha,
            return_to=safe_return_path(return_to),
        )

    ingested_notes = sum(1 for n in notes if n["status"] == "ingested")
    total_dirs = len(company_groups) + len(other_dir_groups)

    try:
        data_dir_label = str(data_dir)
    except Exception:  # noqa: BLE001
        data_dir_label = "data"

    view_key = {
        "author": "catalog.view_author",
        "all": "catalog.view_all",
    }.get(view_mode, "catalog.view_company")
    view_label = translate(view_key, lang=lang)
    page_context = (
        translate("page_context.catalog_file", lang=lang, file=active_note.title)
        if active_note is not None
        else translate("page_context.catalog_view", lang=lang, view=view_label)
    )

    return {
        "stats": stats,
        "data_dir_label": data_dir_label,
        "data_dir_exists": data_dir_exists,
        "view_mode": view_mode,
        "selected_dir": selected_dir,
        "selected_author": active_author,
        "selected_person": active_author,
        "selected_alpha": active_alpha,
        "selected_file": active_note.rel_path if active_note else "",
        "note_format": fmt,
        "company_groups": company_groups,
        "filtered_company_groups": filtered_company_groups,
        "company_letters": company_letters,
        "other_dir_groups": other_dir_groups,
        "author_groups": author_groups,
        "filtered_author_groups": filtered_author_groups,
        "author_letters": author_letters,
        "person_groups": author_groups,
        "unassigned_author_notes": unassigned_author_notes,
        "unassigned_companies": unassigned_companies,
        "unassigned_person_notes": unassigned_author_notes,
        "all_notes": all_notes,
        "filtered_all_notes": filtered_all_notes,
        "all_note_letters": all_note_letters,
        "active_group": active_group,
        "visible_notes": visible_notes,
        "active_note": active_note,
        "total_notes": len(notes),
        "ingested_notes": ingested_notes,
        "total_dirs": total_dirs,
        "page_context": page_context,
    }
