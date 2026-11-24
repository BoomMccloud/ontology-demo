"""Typed service errors with stable codes for HTTP and CLI adapters."""

from __future__ import annotations

# CLI exit codes. 1 stays the generic failure and 2 is Typer's usage error.
EXIT_CODES = {"not_found": 3, "conflict": 4, "invalid": 5, "unavailable": 6}


class ServiceError(Exception):
    """A request the service rejected. `code` is one of `EXIT_CODES`.

    `message` is the English text for the CLI and logs. `key` and `params` name the
    locale string the web layer shows instead, in the viewer's language. `enums` maps a
    param to its enum group (as in `translate_enum`) so its value is translated too.
    """

    def __init__(
        self, code: str, message: str, *, key: str | None = None,
        params: dict[str, object] | None = None, enums: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.key = key
        self.params = params or {}
        self.enums = enums or {}

    def to_json(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}
