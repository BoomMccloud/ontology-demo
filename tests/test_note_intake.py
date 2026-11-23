"""Unit tests for saving pasted text as a note (proposal `paste-note`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_ontology.web.note_intake import (
    DEFAULT_NOTE_FOLDER,
    MAX_NOTE_BYTES,
    NoteSaveError,
    note_slug,
    save_pasted_note,
)


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("NVDA channel check", "nvda_channel_check"),
        ("  ../../evil  ", "evil"),
        ("英伟达 渠道调研", "英伟达_渠道调研"),
        ("...", "note"),
        ("/\\", "note"),
    ],
)
def test_note_slug_is_filename_safe_with_a_fallback(title: str, slug: str) -> None:
    assert note_slug(title) == slug


def test_note_slug_is_bounded() -> None:
    assert len(note_slug("a" * 500)) <= 48


def test_save_uses_default_folder_and_suffixes_a_collision(tmp_path: Path) -> None:
    first = save_pasted_note(tmp_path, title="Same", content="one\n")
    second = save_pasted_note(tmp_path, title="Same", content="two\n")
    assert first.startswith(f"{DEFAULT_NOTE_FOLDER}/") and first.endswith("_same.md")
    assert second == first.removesuffix(".md") + "-2.md"
    assert (tmp_path / first).read_text(encoding="utf-8") == "one\n"
    assert (tmp_path / second).read_text(encoding="utf-8") == "two\n"


@pytest.mark.parametrize(
    ("title", "content", "code"),
    [
        ("   ", "text", "title"),
        ("title", " \n ", "content"),
        ("title", "bad \ud800", "content"),
        ("title", "x" * (MAX_NOTE_BYTES + 1), "too_large"),
        ("title", "é" * (MAX_NOTE_BYTES // 2 + 1), "too_large"),
    ],
)
def test_save_rejects_invalid_input_and_writes_nothing(
    tmp_path: Path, title: str, content: str, code: str
) -> None:
    with pytest.raises(NoteSaveError) as err:
        save_pasted_note(tmp_path, title=title, content=content)
    assert err.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_save_accepts_content_at_the_size_limit(tmp_path: Path) -> None:
    rel = save_pasted_note(tmp_path, title="limit", content="x" * MAX_NOTE_BYTES)
    assert (tmp_path / rel).stat().st_size == MAX_NOTE_BYTES


def test_save_refuses_when_default_folder_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / DEFAULT_NOTE_FOLDER
    blocker.write_text("keep", encoding="utf-8")
    with pytest.raises(NoteSaveError) as err:
        save_pasted_note(tmp_path, title="title", content="text")
    assert err.value.code == "generic"
    assert blocker.read_text(encoding="utf-8") == "keep"
