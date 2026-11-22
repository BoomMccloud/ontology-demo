"""Offline check that modules only import from the layers docs/architecture allows.

See docs/architecture/README.md for the layers. If this test fails, either move the
code to the right module or, if the new dependency is intended, update the doc and
ALLOWED together.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = "stock_ontology"
SRC = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# First path segment under stock_ontology -> module name in the docs.
MODULE_OF: dict[str, str] = {
    "config": "shared",
    "i18n": "shared",
    "models": "ontology",
    "registry": "ontology",
    "vocab": "ontology",
    "db": "storage",
    "llm": "llm",
    "search": "search",
    "pipeline": "pipeline",
    "agent": "agent",
    "audit": "governance",
    "repair": "governance",
    "web": "web",
    "cli": "cli",
}

ALLOWED: dict[str, set[str]] = {
    "shared": set(),
    "ontology": set(),
    "storage": {"ontology"},
    "llm": {"shared", "ontology"},
    "search": {"shared", "ontology", "storage", "llm"},
    "pipeline": {"shared", "ontology", "storage", "llm"},
    "agent": {"shared", "ontology", "storage", "llm", "search"},
    "governance": {"shared", "ontology", "storage"},
    "web": {"shared", "ontology", "storage", "llm", "search", "agent", "governance"},
    "cli": set(MODULE_OF.values()),
}


def _module_for(path: Path) -> str | None:
    rel = path.relative_to(SRC)
    head = rel.parts[0].removesuffix(".py")
    return MODULE_OF.get(head)


def _imported_heads(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    heads: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            if parts[0] == PACKAGE and len(parts) > 1:
                heads.add(parts[1])
    return heads


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.name != "__init__.py" or p.parent != SRC)


def test_every_source_file_belongs_to_a_module() -> None:
    unmapped = [str(p.relative_to(SRC)) for p in _source_files() if _module_for(p) is None]
    assert unmapped == [], f"Add these to MODULE_OF and docs/architecture: {unmapped}"


def test_imports_follow_layers() -> None:
    violations: list[str] = []
    for path in _source_files():
        module = _module_for(path)
        assert module is not None
        for head in _imported_heads(path):
            target = MODULE_OF.get(head)
            if target is None or target == module:
                continue
            if target not in ALLOWED[module]:
                violations.append(f"{path.relative_to(SRC)} ({module}) imports {head} ({target})")
    assert violations == [], "\n".join(violations)


def test_only_storage_touches_sqlite() -> None:
    """SQL lives in stock_ontology.db so a schema change can't silently break other modules."""
    pattern = re.compile(r"\.conn\b|\bimport sqlite3\b|\bsqlite_vec\b")
    offenders = [
        str(p.relative_to(SRC))
        for p in _source_files()
        if _module_for(p) != "storage" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders
