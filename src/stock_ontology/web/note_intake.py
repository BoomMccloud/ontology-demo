"""Save pasted text as a new `.md` note in the default notes folder.

This is the web app's only filesystem write. It never touches `ontology.db`: a saved note
reaches the ontology through the next `ingest` or `watch` run. A note is written to a hidden
temp file, which the ingestion scan skips, and published with a hard link, which is atomic
and fails instead of replacing an existing file.
"""

from __future__ import annotations

import itertools
import os
import re
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

DEFAULT_NOTE_FOLDER = "_general"
MAX_NOTE_BYTES = 1_000_000
_MAX_SLUG_CHARS = 48
_FALLBACK_SLUG = "note"


class NoteSaveError(ValueError):
    """A rejected save. `code` selects the translated `notes_new.error_<code>` message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def note_slug(title: str) -> str:
    """Return a filename-safe slug that keeps letters of any script."""
    normalized = unicodedata.normalize("NFC", title).lower()
    slug = re.sub(r"\W+", "_", normalized).strip("_")
    return slug[:_MAX_SLUG_CHARS].strip("_") or _FALLBACK_SLUG


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
