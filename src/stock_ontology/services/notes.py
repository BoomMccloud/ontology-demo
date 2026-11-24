"""Raw notes: saving pasted text, listing notes with their extraction status, and discovery.

`NotesService` is the only code that writes the notes folder. It never writes `ontology.db`:
saving publishes the note and then queues a processing job for the worker. A note is written
to a hidden temp file, which discovery skips, and published with a hard link, which is atomic
and fails instead of replacing an existing file.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import re
import tempfile
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_ontology.config import SUPPORTED_EXTENSIONS, Settings
from stock_ontology.search import resolve_safe_note_path
from stock_ontology.services.errors import ServiceError
from stock_ontology.services.processing import ProcessingService

DEFAULT_NOTE_FOLDER = "_general"
MAX_NOTE_BYTES = 1_000_000
_MAX_SLUG_CHARS = 48
_FALLBACK_SLUG = "note"


class NoteSaveError(ValueError):
    """A rejected save. `code` selects the translated `notes_new.error_<code>` message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class NoteRef:
    file: str
    job_id: str


@dataclass(frozen=True)
class NoteFile:
    """One supported note on disk, with its status against the extraction log."""

    rel_path: str
    path: Path
    text: str
    content_hash: str
    size: int
    mtime: float
    status: str  # "ingested", "modified", or "not_ingested"
    doc_id: str | None
    ingested_at: str | None


def note_slug(title: str) -> str:
    """Return a filename-safe slug that keeps letters of any script."""
    normalized = unicodedata.normalize("NFC", title).lower()
    slug = re.sub(r"\W+", "_", normalized).strip("_")
    return slug[:_MAX_SLUG_CHARS].strip("_") or _FALLBACK_SLUG


def note_revision(text: str) -> str:
    """The content revision used by the extraction log and processing jobs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _publish(folder: Path, stem: str, payload: bytes) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix=".paste-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(tmp_name, 0o644)
        for attempt in itertools.count(1):
            name = f"{stem}.md" if attempt == 1 else f"{stem}-{attempt}.md"
            target = folder / name
            try:
                os.link(tmp_name, target)
            except FileExistsError:
                continue
            return target
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    raise AssertionError("unreachable")


def save_pasted_note(data_dir: Path, *, title: str, content: str) -> str:
    """Save `content` as a new note and return its path relative to `data_dir`."""
    if not title.strip():
        raise NoteSaveError("title")
    if not content.strip():
        raise NoteSaveError("content")
    try:
        payload = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise NoteSaveError("content") from exc
    if len(payload) > MAX_NOTE_BYTES:
        raise NoteSaveError("too_large")

    root = data_dir.resolve()
    folder = root / DEFAULT_NOTE_FOLDER
    if folder.is_symlink():
        raise NoteSaveError("generic")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        saved = _publish(folder, f"{date.today().isoformat()}_{note_slug(title)}", payload)
    except (FileExistsError, NotADirectoryError) as exc:
        raise NoteSaveError("generic") from exc
    return saved.relative_to(root).as_posix()


def iter_note_paths(data_dir: Path) -> Iterator[tuple[str, Path]]:
    """Supported, non-hidden notes under `data_dir` in path order."""
    if not data_dir.exists() or not data_dir.is_dir():
        return
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield rel.as_posix(), path


def scan_notes(data_dir: Path, log: dict[str, dict[str, Any]]) -> list[NoteFile]:
    """Read every note and derive its status from the extraction log."""
    notes: list[NoteFile] = []
    for rel_posix, path in iter_note_paths(data_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        content_hash = note_revision(text)
        stat = path.stat()
        entry = log.get(rel_posix)
        if entry is not None:
            status = "ingested" if entry["content_hash"] == content_hash else "modified"
        else:
            status = "not_ingested"
        notes.append(NoteFile(
            rel_path=rel_posix, path=path, text=text, content_hash=content_hash, size=stat.st_size,
            mtime=stat.st_mtime, status=status, doc_id=entry["doc_id"] if entry else None,
            ingested_at=entry["ingested_at"] if entry else None,
        ))
    return notes


def has_changes(data_dir: Path, log: dict[str, dict[str, Any]]) -> bool:
    """Whether a scan would find new, modified, moved, or deleted notes (by size and mtime)."""
    seen: set[str] = set()
    for rel_posix, path in iter_note_paths(data_dir):
        seen.add(rel_posix)
        entry = log.get(rel_posix)
        try:
            stat = path.stat()
        except OSError:
            return True
        if entry is None or entry.get("size") != stat.st_size or entry.get("mtime_ns") != stat.st_mtime_ns:
            return True
    return bool(set(log) - seen)


class NotesService:
    """Save, resolve, and list notes for every adapter."""

    def __init__(self, settings: Settings, processing: ProcessingService | None = None) -> None:
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.processing = processing or ProcessingService(settings)

    def save(self, title: str, text: str, *, queue: bool = True) -> NoteRef:
        """Publish a new note and, with `queue`, submit its processing job. Without it the
        worker's scan finds the note, and `job_id` is empty."""
        rel_path = save_pasted_note(self.data_dir, title=title, content=text)
        return NoteRef(rel_path, self.processing.request_processing(rel_path).job_id if queue else "")

    def resolve(self, file: str) -> Path:
        path = resolve_safe_note_path(self.data_dir, file)
        if path is None or not path.is_file():
            raise ServiceError("not_found", f"Note not found: {file}")
        return path

    def revision(self, file: str) -> str:
        return note_revision(self.resolve(file).read_text(encoding="utf-8"))

    def list(self, log: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"file": note.rel_path, "status": note.status, "revision": note.content_hash,
             "doc_id": note.doc_id, "ingested_at": note.ingested_at, "size_bytes": note.size}
            for note in scan_notes(self.data_dir, log)
        ]
