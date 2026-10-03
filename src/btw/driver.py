"""Check, run and build pipelines (Implementation Spec 2, 7, 10.1).

Components are imported lazily, so the CLI works before they exist: a missing
component module raises NotImplementedError. The function names the driver
calls are listed in NOTES-harness.md.
"""

import importlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import ModuleType
from typing import TextIO

from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span

RUNTIME = Path(__file__).resolve().parents[2] / "runtime" / "btw_rt.c"


class BtwError(Exception):
    """A fatal problem outside the program itself. The CLI prints it and exits 2."""


def _component(name: str) -> ModuleType:
    module = f"btw.{name}"
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as error:
        if error.name != module:
            raise
        raise NotImplementedError(f"{name} is not implemented yet") from None


# Diagnostics helpers


def sort_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Sort by line, column and code. Of exact duplicates (same code and span),
    keep the first one reported."""
    unique: dict[tuple[str, Span], Diagnostic] = {}
    for diagnostic in diagnostics:
        unique.setdefault((diagnostic.code, diagnostic.span), diagnostic)
    return sorted(unique.values(), key=lambda d: (d.span.start, d.code))


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    """Hard and soft errors block `btw run` and `btw build`; warnings don't."""
    return any(d.severity is Severity.ERROR for d in diagnostics)


def line_span(source: str, line: int) -> Span:
    """The whole of one line, for diagnostics positioned on "line 1"."""
    lines = source.split("\n")
    text = lines[line].removesuffix("\r") if line < len(lines) else ""
    return Span(Pos(line, 0), Pos(line, len(text.encode("utf-16-le")) // 2))


def internal_error(source: str) -> Diagnostic:
    """E500, for an unexpected exception anywhere in the pipeline."""
    return Diagnostic(
        "E500",
        Severity.ERROR,
        "It works on my machine. Unfortunately, this is not my machine.",
        line_span(source, 0),
    )


# Pipelines


def lsp() -> None:
    _component("lsp").main()


def lex(source: str):
    """Return (tokens, comments, diagnostics)."""
    return _component("lexer").lex(source)


def _parse(source: str):
    """Return (tokens, program, diagnostics)."""
    tokens, comments, lex_diagnostics = lex(source)
    program, parse_diagnostics = _component("parser").parse(tokens, comments)
    return tokens, program, [*lex_diagnostics, *parse_diagnostics]


def parse(source: str):
    """Return (program, diagnostics)."""
    _, program, diagnostics = _parse(source)
    return program, diagnostics


def check(source: str, path: str):
    """Return (program, symbols, diagnostics): Implementation Spec 7, passes 1 to 9."""
    tokens, program, diagnostics = _parse(source)
    symbols, check_diagnostics = _component("checker").check(program, program.comments)
    diagnostics += check_diagnostics
    try:
        bigo = _component("bigo")
    except NotImplementedError:
        pass  # until the Big O card lands, there are no Big O diagnostics
    else:
        diagnostics += bigo.check_bigo(program)
    try:
        suppress = _component("suppress")
    except NotImplementedError:
        pass  # P2: without it, nothing is suppressed
    else:
        diagnostics = suppress.apply(program, diagnostics)
    return program, symbols, sort_diagnostics(diagnostics)


def run(
    source: str, path: str, stdout: TextIO, stderr: TextIO
) -> tuple[list[Diagnostic], int | None]:
    """Check, then interpret. The exit code is None when errors blocked the run."""
    program, symbols, diagnostics = check(source, path)
    if has_errors(diagnostics):
        return diagnostics, None
    exit_code = _component("interp").run(program, symbols, stdout, stderr)
    return diagnostics, exit_code


def asm(source: str, path: str, annotate: bool = False) -> tuple[list[Diagnostic], str | None]:
    """Check, then generate assembly. The text is None when errors (E501 included)
    blocked it."""
    program, symbols, diagnostics = check(source, path)
    if has_errors(diagnostics):
        return diagnostics, None
    text, codegen_diagnostics = _component("codegen").gen(program, symbols, annotate=annotate)
    diagnostics = sort_diagnostics([*diagnostics, *codegen_diagnostics])
    if has_errors(diagnostics):
        return diagnostics, None
    return diagnostics, text


def build(
    source: str, path: str, output: Path, keep_asm: bool = False
) -> tuple[list[Diagnostic], str | None]:
    """Check, generate assembly and link it with the C runtime into `output`.

    Returns the diagnostics and, when gcc failed (E502), gcc's stderr.
    """
    diagnostics, text = asm(source, path)
    if text is None:
        return diagnostics, None
    if not RUNTIME.is_file():
        raise NotImplementedError("native runtime is not implemented yet")
    gcc = shutil.which("gcc")
    if gcc is None:
        raise BtwError("gcc not found. `btw build` needs gcc to assemble and link.")
    if keep_asm:
        output.with_name(output.name + ".s").write_text(text, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        assembly = Path(tmp) / "prog.s"
        assembly.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [gcc, "-o", str(output), str(assembly), str(RUNTIME)],
            capture_output=True,
            text=True,
        )
    if result.returncode == 0:
        return diagnostics, None
    e502 = Diagnostic(
        "E502",
        Severity.ERROR,
        "Bad gateway: gcc rejected the generated assembly. "
        "That's a compiler bug, not a skill issue.",
        line_span(source, 0),
    )
    return sort_diagnostics([*diagnostics, e502]), result.stderr
