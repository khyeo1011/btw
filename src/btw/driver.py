"""Pipelines that wire the components together.

Components are imported lazily, so the CLI works before they exist: a missing
component module raises NotImplementedError. The interfaces the driver expects
are listed in NOTES-harness.md.
"""

import importlib
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import TextIO

from btw.diagnostics import Diagnostic, Severity, has_errors, line_span, sort_diagnostics


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


def lsp() -> None:
    _component("lsp").serve()


def lex(source: str):
    """Return (tokens, comments, diagnostics)."""
    return _component("lexer").lex(source)


def parse(source: str):
    """Return (program, comments, diagnostics)."""
    tokens, comments, lex_diagnostics = lex(source)
    program, parse_diagnostics = _component("parser").parse(tokens)
    return program, comments, [*lex_diagnostics, *parse_diagnostics]


def check(source: str, path: str):
    """Return (program, symbols, diagnostics), with diagnostics sorted."""
    program, comments, diagnostics = parse(source)
    symbols, check_diagnostics = _component("checker").check(program, comments, source)
    return program, symbols, sort_diagnostics([*diagnostics, *check_diagnostics])


def run(
    source: str, path: str, stdout: TextIO, stderr: TextIO
) -> tuple[list[Diagnostic], int | None]:
    """Check, then interpret. The exit code is None when errors blocked the run."""
    program, symbols, diagnostics = check(source, path)
    if has_errors(diagnostics):
        return diagnostics, None
    exit_code = _component("interpreter").run(program, symbols, stdout, stderr)
    return diagnostics, exit_code


def asm(source: str, path: str) -> tuple[list[Diagnostic], str | None]:
    """Check, then generate assembly. The text is None when errors blocked it."""
    program, symbols, diagnostics = check(source, path)
    if has_errors(diagnostics):
        return diagnostics, None
    text, codegen_diagnostics = _component("codegen").generate(program, symbols)
    diagnostics = sort_diagnostics([*diagnostics, *codegen_diagnostics])
    if has_errors(diagnostics):
        return diagnostics, None
    return diagnostics, text


def build(source: str, path: str, output: Path) -> list[Diagnostic]:
    """Check, generate assembly and link it with the C runtime into `output`."""
    diagnostics, text = asm(source, path)
    if text is None:
        return diagnostics
    runtime = resources.files("btw").joinpath("runtime.c")
    if not runtime.is_file():
        raise NotImplementedError("native runtime is not implemented yet")
    gcc = shutil.which("gcc")
    if gcc is None:
        raise BtwError("gcc not found. `btw build` needs gcc to assemble and link.")
    with tempfile.TemporaryDirectory() as tmp, resources.as_file(runtime) as runtime_path:
        assembly = Path(tmp) / "program.s"
        assembly.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [gcc, "-o", str(output), str(assembly), str(runtime_path)],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        diagnostics = sort_diagnostics([*diagnostics, _e502(source)])
    return diagnostics


def _e502(source: str) -> Diagnostic:
    return Diagnostic(
        "E502",
        Severity.ERROR,
        "Bad gateway: gcc rejected the generated assembly. "
        "That's a compiler bug, not a skill issue.",
        line_span(source, 0),
    )


def internal_error(source: str) -> Diagnostic:
    """E500, for an unexpected exception anywhere in the pipeline."""
    return Diagnostic(
        "E500",
        Severity.ERROR,
        "It works on my machine. Unfortunately, this is not my machine.",
        line_span(source, 0),
    )
