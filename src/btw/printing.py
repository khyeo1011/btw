"""Short and pretty diagnostic output (Implementation Spec 3)."""

import os
import sys
from typing import TextIO

from btw.diagnostics import Diagnostic, Severity

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
RED = "\x1b[1;31m"
YELLOW = "\x1b[1;33m"
BLUE = "\x1b[1;34m"


def severity_label(diagnostic: Diagnostic) -> str:
    return "warning" if diagnostic.severity is Severity.WARNING else "error"


def format_short(diagnostic: Diagnostic, path: str) -> str:
    start = diagnostic.span.start
    return (
        f"{path}:{start.line + 1}:{start.col + 1}: "
        f"{severity_label(diagnostic)}[{diagnostic.code}]: {diagnostic.message}"
    )


def format_pretty(diagnostic: Diagnostic, path: str, source: str, color: bool) -> str:
    """Render one diagnostic as the block described in NOTES-harness.md.

    Returns the block without a trailing newline. With color=False the result
    contains no escape codes; with color=True, stripping the escape codes must
    give exactly the color=False result.
    """
    # TODO(human): H1 — render header, --> line, gutter, source line, carets and help line.
    raise NotImplementedError("pretty diagnostics are not implemented yet")


def use_color() -> bool:
    """Colors only when stdout is a terminal and NO_COLOR isn't set."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def print_diagnostics(
    diagnostics: list[Diagnostic],
    path: str,
    source: str,
    stream: TextIO,
    fmt: str,
) -> None:
    if fmt == "short":
        for diagnostic in diagnostics:
            print(format_short(diagnostic, path), file=stream)
        return
    color = use_color()
    blocks = [format_pretty(d, path, source, color) for d in diagnostics]
    if blocks:
        print("\n\n".join(blocks), file=stream)
