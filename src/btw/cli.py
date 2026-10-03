"""Command line interface (NOTES-harness.md, "CLI")."""

import argparse
import sys
import traceback
from pathlib import Path

from btw import driver
from btw.diagnostics import has_errors
from btw.printing import print_diagnostics, resolve_format


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btw", description="The btw compiler.")
    commands = parser.add_subparsers(dest="command", required=True)

    file_args = argparse.ArgumentParser(add_help=False)
    file_args.add_argument("file", type=Path, help="a .btw source file")
    file_args.add_argument(
        "--format",
        choices=["short", "pretty"],
        help="diagnostic format (default: pretty on a terminal, else short)",
    )

    commands.add_parser("check", parents=[file_args], help="report diagnostics")
    commands.add_parser("run", parents=[file_args], help="interpret a program")
    build = commands.add_parser("build", parents=[file_args], help="build a native binary")
    build.add_argument("-o", dest="output", type=Path, help="output path")
    asm = commands.add_parser("asm", parents=[file_args], help="print the generated assembly")
    asm.add_argument("-o", dest="output", type=Path, help="write to a file instead")
    commands.add_parser("tokens", parents=[file_args], help="print the tokens")
    commands.add_parser("parse", parents=[file_args], help="print the AST")
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
    fmt = resolve_format(args.format, stream)
    print_diagnostics(diagnostics, str(args.file), source, stream, fmt)


def cmd_check(args: argparse.Namespace, source: str) -> int:
    _, _, diagnostics = driver.check(source, str(args.file))
    report(args, source, diagnostics, sys.stdout)
    return 1 if has_errors(diagnostics) else 0


def cmd_run(args: argparse.Namespace, source: str) -> int:
    diagnostics, exit_code = driver.run(source, str(args.file), sys.stdout, sys.stderr)
    if exit_code is None:
        report(args, source, diagnostics, sys.stderr)
        return 1
    return exit_code & 0xFF


def cmd_build(args: argparse.Namespace, source: str) -> int:
    output = args.output or args.file.with_suffix("")
    diagnostics = driver.build(source, str(args.file), output)
    report(args, source, diagnostics, sys.stderr)
    return 1 if has_errors(diagnostics) else 0


def cmd_asm(args: argparse.Namespace, source: str) -> int:
    diagnostics, text = driver.asm(source, str(args.file))
    report(args, source, diagnostics, sys.stderr)
    if text is None:
        return 1
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def cmd_tokens(args: argparse.Namespace, source: str) -> int:
    tokens, _, diagnostics = driver.lex(source)
    for token in tokens:
        print(token)
    report(args, source, diagnostics, sys.stderr)
    return 1 if has_errors(diagnostics) else 0


def cmd_parse(args: argparse.Namespace, source: str) -> int:
    program, _, diagnostics = driver.parse(source)
    print(program)
    report(args, source, diagnostics, sys.stderr)
    return 1 if has_errors(diagnostics) else 0


COMMANDS = {
    "check": cmd_check,
    "run": cmd_run,
    "build": cmd_build,
    "asm": cmd_asm,
    "tokens": cmd_tokens,
    "parse": cmd_parse,
}
