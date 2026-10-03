"""Diagnostic types shared by every component (Language Spec 11)."""

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    SOFT_ERROR = "soft error"
    WARNING = "warning"


@dataclass(frozen=True, order=True)
class Position:
    """0-based line and column. Columns count UTF-16 code units."""

    line: int
    column: int


@dataclass(frozen=True)
class Span:
    start: Position
    end: Position


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    span: Span
    help: str | None = None

    @property
    def blocking(self) -> bool:
        """Hard and soft errors block `btw run` and `btw build`."""
        return self.severity is not Severity.WARNING


def line_span(source: str, line: int) -> Span:
    """The span of a whole line, for diagnostics positioned on "line 1"."""
    lines = source.split("\n")
    text = lines[line].removesuffix("\r") if line < len(lines) else ""
    return Span(Position(line, 0), Position(line, len(text.encode("utf-16-le")) // 2))


def sort_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Sort by line, column and code, dropping exact duplicates (same code and span)."""
    unique = {(d.code, d.span): d for d in reversed(diagnostics)}
    return sorted(unique.values(), key=lambda d: (d.span.start, d.code))


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(d.blocking for d in diagnostics)
