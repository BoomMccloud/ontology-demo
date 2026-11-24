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
    "services": "services",
    "worker": "worker",
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
    "services": {"shared", "ontology", "storage", "search"},
    "worker": {"shared", "ontology", "storage", "llm", "pipeline", "governance", "services"},
    "web": {"shared", "ontology", "llm", "search", "agent", "governance", "services"},
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


def _writable_db_opens(path: Path) -> list[int]:
    """Line numbers of `OntologyDB(...)` calls that do not pass `read_only=True`."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name != "OntologyDB":
            continue
        read_only = next((kw.value for kw in node.keywords if kw.arg == "read_only"), None)
        if not (isinstance(read_only, ast.Constant) and read_only.value is True):
            lines.append(node.lineno)
    return lines


def test_only_worker_job_executors_open_a_writable_database() -> None:
    """The worker is the only writer: every other module opens ontology.db with query_only."""
    offenders = [
        f"{p.relative_to(SRC)}:{line}"
        for p in _source_files()
        if _module_for(p) not in {"worker", "storage"}
        for line in _writable_db_opens(p)
    ]
    assert offenders == [], offenders
