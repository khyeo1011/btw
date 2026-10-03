"""Source positions (Implementation Spec 4.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Pos:
    """0-based line and column. Columns count UTF-16 code units."""

    line: int
    col: int


@dataclass(frozen=True)
class Span:
    """From `start` to `end`, end exclusive."""

    start: Pos
    end: Pos

    def contains(self, pos: Pos) -> bool:
        return self.start <= pos < self.end

    def merge(self, other: Span) -> Span:
        """The smallest span covering both."""
        return Span(min(self.start, other.start), max(self.end, other.end))
