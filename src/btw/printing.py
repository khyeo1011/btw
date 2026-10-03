"""Short and pretty diagnostic formats (NOTES-harness.md)."""

import os
from typing import TextIO

from btw.diagnostics import Diagnostic, Severity

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
RED = "\x1b[1;31m"
YELLOW = "\x1b[1;33m"
BLUE = "\x1b[1;34m"


def severity_label(diagnostic: Diagnostic) -> str:
    """Soft errors print as `error`: they block just like hard ones."""
    return "warning" if diagnostic.severity is Severity.WARNING else "error"


def format_short(diagnostic: Diagnostic, path: str) -> str:
    start = diagnostic.span.start
    return (
        f"{path}:{start.line + 1}:{start.column + 1}: "
        f"{severity_label(diagnostic)} {diagnostic.code}: {diagnostic.message}"
    )


def format_pretty(diagnostic: Diagnostic, path: str, source: str, color: bool) -> str:
    """Render one diagnostic as the multi-line block described in NOTES-harness.md.

    Returns the block without a trailing newline. With color=False the result
    contains no escape codes; with color=True, stripping the escape codes must
    give exactly the color=False result.
    """
    # TODO(human): H1 — render header, --> line, gutter, source line, carets and help line.
    raise NotImplementedError("pretty diagnostics are not implemented yet")


def use_color(stream: TextIO) -> bool:
    """Colors only on a terminal, and only when NO_COLOR is unset."""
    return stream.isatty() and "NO_COLOR" not in os.environ


def resolve_format(requested: str | None, stream: TextIO) -> str:
    if requested is not None:
        return requested
    return "pretty" if stream.isatty() else "short"


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
    color = use_color(stream)
    blocks = [format_pretty(d, path, source, color) for d in diagnostics]
    if blocks:
        print("\n\n".join(blocks), file=stream)
