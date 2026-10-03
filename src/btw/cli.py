"""Command line interface (Implementation Spec 3)."""

import argparse
import dataclasses
import sys
import traceback
from enum import Enum
from pathlib import Path

from btw import driver
from btw.printing import print_diagnostics
from btw.span import Span


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btw", description="The btw compiler.")
    commands = parser.add_subparsers(dest="command", required=True)

    file_args = argparse.ArgumentParser(add_help=False)
    file_args.add_argument("file", type=Path, help="a .btw source file")
    file_args.add_argument(
        "--format",
        choices=["pretty", "short"],
        default="pretty",
        help="diagnostic format (default: pretty; short is for tests)",
    )

    commands.add_parser("check", parents=[file_args], help="report diagnostics")
    commands.add_parser("run", parents=[file_args], help="interpret a program")
    build = commands.add_parser("build", parents=[file_args], help="build a native binary")
    build.add_argument("-o", dest="output", type=Path, help="default: FILE without .btw")
    build.add_argument("--keep-asm", action="store_true", help="also write OUT.s")
    asm = commands.add_parser("asm", parents=[file_args], help="print the generated assembly")
    asm.add_argument("--annotate", action="store_true", help="add source-line comments")
    commands.add_parser("tokens", parents=[file_args], help="debug: one token per line")
    commands.add_parser("parse", parents=[file_args], help="debug: indented AST with spans")
    commands.add_parser("lsp", help="start the language server on stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = ""
    try:
        if args.command == "lsp":
            driver.lsp()
            return 0
        source = read_source(args.file)
        return COMMANDS[args.command](args, source)
    except NotImplementedError as error:
        print(f"btw: {error}", file=sys.stderr)
        return 2
    except driver.BtwError as error:
        print(f"btw: {error}", file=sys.stderr)
        return 2
    except Exception:
        path = str(args.file) if hasattr(args, "file") else "btw"
        print_diagnostics([driver.internal_error(source)], path, source, sys.stderr, "short")
        traceback.print_exc()
        return 2


def read_source(path: Path) -> str:
    """Read UTF-8 source, skipping a leading byte-order mark (Language Spec 1)."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except OSError as error:
        raise driver.BtwError(f"can't read {path}: {error.strerror}") from None
    except UnicodeDecodeError:
        raise driver.BtwError(f"{path} is not valid UTF-8") from None


def report(args: argparse.Namespace, source: str, diagnostics, stream) -> None:
    print_diagnostics(diagnostics, str(args.file), source, stream, args.format)


def cmd_check(args: argparse.Namespace, source: str) -> int:
    _, _, diagnostics = driver.check(source, str(args.file))
    report(args, source, diagnostics, sys.stdout)
    return 1 if driver.has_errors(diagnostics) else 0


def cmd_run(args: argparse.Namespace, source: str) -> int:
    diagnostics, exit_code = driver.run(source, str(args.file), sys.stdout, sys.stderr)
    if exit_code is None:
        report(args, source, diagnostics, sys.stderr)
        return 1
    return exit_code & 0xFF


def cmd_build(args: argparse.Namespace, source: str) -> int:
    output = args.output or args.file.with_suffix("")
    diagnostics, gcc_stderr = driver.build(source, str(args.file), output, args.keep_asm)
    report(args, source, diagnostics, sys.stderr)
    if gcc_stderr is not None:
        sys.stderr.write(gcc_stderr)
        return 3
    return 1 if driver.has_errors(diagnostics) else 0


def cmd_asm(args: argparse.Namespace, source: str) -> int:
    diagnostics, text = driver.asm(source, str(args.file), args.annotate)
    report(args, source, diagnostics, sys.stderr)
    if text is None:
        return 1
    sys.stdout.write(text)
    return 0


def cmd_tokens(args: argparse.Namespace, source: str) -> int:
    tokens, _, diagnostics = driver.lex(source)
    for token in tokens:
        value = "" if token.value is None else f" {token.value!r}"
        print(f"{format_span(token.span)} {token.kind.name} {token.text!r}{value}")
    report(args, source, diagnostics, sys.stderr)
    return 0


def cmd_parse(args: argparse.Namespace, source: str) -> int:
    program, diagnostics = driver.parse(source)
    for line in dump(program):
        print(line)
    report(args, source, diagnostics, sys.stderr)
    return 0


def format_span(span: Span) -> str:
    """1-based, like every position the CLI prints."""
    return f"{span.start.line + 1}:{span.start.col + 1}-{span.end.line + 1}:{span.end.col + 1}"


def dump(value, label: str = "", indent: int = 0) -> list[str]:
    """An indented tree of AST nodes, one node or field per line, with spans."""
    pad = "  " * indent
    prefix = f"{pad}{label}: " if label else pad
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = [f"{prefix}["]
        for item in value:
            lines += dump(item, "", indent + 1)
        return lines + [f"{pad}]"]
    if dataclasses.is_dataclass(value) and isinstance(getattr(value, "span", None), Span):
        lines = [f"{prefix}{type(value).__name__} {format_span(getattr(value, 'span'))}"]
        for f in dataclasses.fields(value):
            if f.name == "span":
                continue
            lines += dump(getattr(value, f.name), f.name, indent + 1)
        return lines
    if isinstance(value, Span):
        return [f"{prefix}{format_span(value)}"]
    if isinstance(value, Enum):
        return [f"{prefix}{value.name}"]
    if value is not None and not isinstance(value, (bool, int, str)):
        return [f"{prefix}{getattr(value, 'name', type(value).__name__)}"]
    return [f"{prefix}{value!r}"]


COMMANDS = {
    "check": cmd_check,
    "run": cmd_run,
    "build": cmd_build,
    "asm": cmd_asm,
    "tokens": cmd_tokens,
    "parse": cmd_parse,
}
