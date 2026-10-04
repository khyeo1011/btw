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


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def format_summary(diagnostics: list[Diagnostic]) -> str | None:
    """The pretty-mode summary line (Language Spec 13); soft errors count as errors."""
    errors = sum(d.severity is Severity.ERROR for d in diagnostics)
    warnings = len(diagnostics) - errors
    if errors:
        parts = [count(errors, "error")] + ([count(warnings, "warning")] if warnings else [])
        return f"build failed: {', '.join(parts)}. Skill issue."
    if warnings:
        return f"{count(warnings, 'warning')}. LGTM anyway."
    return None


def format_pretty(diagnostic: Diagnostic, path: str, source: str, color: bool) -> str:
    """Render one diagnostic as the block described in NOTES-harness.md.

    Returns the block without a trailing newline. With color=False the result
    contains no escape codes; with color=True, stripping the escape codes must
    give exactly the color=False result.
    """

    def paint(text: str, style: str) -> str:
        return f"{style}{text}{RESET}" if color else text

    start, end = diagnostic.span.start, diagnostic.span.end
    tone = YELLOW if diagnostic.severity is Severity.WARNING else RED
    lines = source.split("\n")
    text = lines[start.line].removesuffix("\r") if start.line < len(lines) else ""
    number = str(start.line + 1)
    gutter = " " * (len(number) + 1)
    bar = paint("|", BLUE)

    first = _char_index(text, start.col)
    last = _char_index(text, end.col) if end.line == start.line else len(text)
    pad = "".join("\t" if ch == "\t" else " " for ch in text[:first])
    pad += " " * (first - len(text[:first]))
    carets = paint("^" * max(1, last - first), tone)

    block = [
        paint(f"{severity_label(diagnostic)}[{diagnostic.code}]", tone)
        + paint(f": {diagnostic.message}", BOLD),
        f"{gutter}{paint('-->', BLUE)} {path}:{number}:{start.col + 1}",
        f"{gutter} {bar}",
        f"{paint(' ' + number, BLUE)} {bar}" + (f" {text}" if text else ""),
        f"{gutter} {bar} {pad}{carets}",
    ]
    if diagnostic.help:
        block.append(f"{gutter} {paint('=', BLUE)} help: {diagnostic.help}")
    return "\n".join(block)


def _char_index(text: str, units: int) -> int:
    """Turn a UTF-16 column into an index into `text`. Past the end of the
    line, each further unit counts as one character."""
    count = 0
    for index, ch in enumerate(text):
        if count >= units:
            return index
        count += 2 if ord(ch) > 0xFFFF else 1
    return len(text) + max(0, units - count)


def use_color() -> bool:
    """Colors only when stdout is a terminal and NO_COLOR isn't set."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def print_diagnostics(
    diagnostics: list[Diagnostic],
    path: str,
    source: str,
    stream: TextIO,
    fmt: str,
    summary: bool = False,
) -> None:
    if fmt == "short":
        for diagnostic in diagnostics:
            print(format_short(diagnostic, path), file=stream)
        return
    color = use_color()
    blocks = [format_pretty(d, path, source, color) for d in diagnostics]
    if summary and (line := format_summary(diagnostics)):
        blocks.append(line)
    if blocks:
        print("\n\n".join(blocks), file=stream)
