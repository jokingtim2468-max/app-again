"""Errors that carry enough context for the UI to tell the user what to fix."""

from __future__ import annotations


class TickbenchError(Exception):
    """Base error. `hint` is a one-line suggestion shown under the message."""

    def __init__(self, message: str, *, hint: str = "", line: int | None = None, file: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.line = line
        self.file = file

    def to_dict(self) -> dict:
        return {"message": self.message, "hint": self.hint, "line": self.line, "file": self.file,
                "kind": type(self).__name__}


class DataError(TickbenchError):
    pass


class ScriptError(TickbenchError):
    """The strategy script could not be parsed or failed while running."""


class UnsupportedFeature(ScriptError):
    """The script uses a built-in this interpreter does not implement."""


class Cancelled(TickbenchError):
    pass
