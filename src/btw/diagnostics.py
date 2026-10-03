"""Diagnostics shared by every component (Implementation Spec 4.2)."""

from dataclasses import dataclass, field
from enum import Enum

from btw.span import Span


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Edit:
    span: Span
    text: str


@dataclass(frozen=True)
class Fix:
    """A quick fix (P2): a title plus the edits that apply it."""

    title: str
    edits: list[Edit]


@dataclass(frozen=True)
class Diagnostic:
    code: str  # "E404", "W508"
    severity: Severity
    message: str  # exact text from the Language Spec catalog
    span: Span
    soft: bool = False  # E403, E417 and every warning: suppressible
    related: list[tuple[Span, str]] = field(default_factory=list)  # P2
    fixes: list[Fix] = field(default_factory=list)  # P2
    help: str | None = None  # printed by the CLI in pretty mode
