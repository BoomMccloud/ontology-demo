"""Typed service errors with stable codes for HTTP and CLI adapters."""

from __future__ import annotations

# CLI exit codes. 1 stays the generic failure and 2 is Typer's usage error.
EXIT_CODES = {"not_found": 3, "conflict": 4, "invalid": 5, "unavailable": 6}


class ServiceError(Exception):
    """A request the service rejected. `code` is one of `EXIT_CODES`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_json(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}
