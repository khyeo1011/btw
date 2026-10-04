import subprocess
import sys

from btw import ast
from btw.cli import dump
from btw.diagnostics import Diagnostic, Severity
from btw.driver import has_errors, line_span, sort_diagnostics
from btw.span import Pos, Span


def at(code, line, col, message="m", severity=Severity.ERROR):
    return Diagnostic(code, severity, message, Span(Pos(line, col), Pos(line, col + 1)))


def test_sorted_by_line_column_then_code():
    unsorted = [at("E418", 3, 0), at("E404", 1, 5), at("E409", 1, 2), at("E400", 1, 2)]
    assert [d.code for d in sort_diagnostics(unsorted)] == ["E400", "E409", "E404", "E418"]


def test_duplicates_keep_the_first_reported():
    lexer = at("E400", 2, 21, "Unexpected character `@`.")
    parser = at("E400", 2, 21, "Syntax error: expected end of line, found `@`.")
    assert sort_diagnostics([lexer, parser, at("E405", 2, 21)]) == [lexer, at("E405", 2, 21)]


def test_soft_errors_block_and_warnings_dont():
    soft = Diagnostic("E403", Severity.ERROR, "m", Span(Pos(0, 0), Pos(0, 1)), soft=True)
    assert has_errors([soft])
    assert not has_errors([at("W102", 0, 0, severity=Severity.WARNING)])


def test_line_span_covers_the_line_without_its_ending():
    assert line_span("i use arch btw\r\n:wq\n", 0) == Span(Pos(0, 0), Pos(0, 14))


def test_line_span_counts_utf16_units():
    assert line_span('"🚀"\n', 0) == Span(Pos(0, 0), Pos(0, 4))


def test_parse_dump_is_indented_with_spans():
    s = Span(Pos(0, 0), Pos(0, 1))
    program = ast.Program(
        [ast.Serve(3000, ast.Block([ast.Print(ast.IntLit(42, span=s), span=s)], span=s), span=s)],
        True,
        s,
        None,
        [],
        span=s,
    )
    assert dump(program) == [
        "Program 1:1-1:2",
        "  items: [",
        "    Serve 1:1-1:2",
        "      port: 3000",
        "      body: Block 1:1-1:2",
        "        stmts: [",
        "          Print 1:1-1:2",
        "            value: IntLit 1:1-1:2",
        "              ty: None",
        "              value: 42",
        "        ]",
        "  ]",
        "  has_arch: True",
        "  wq_span: 1:1-1:2",
        "  trailing_span: None",
        "  comments: []",
    ]


def test_closed_stdout_exits_quietly_like_sigpipe(tmp_path):
    # More output than a pipe buffer holds, so a write fails once the reader is gone.
    source = tmp_path / "many.btw"
    source.write_text(
        "i use arch btw\n"
        "serve localhost:3000 {\n"
        "    npm install i = 1\n"
        "    doomscroll i <= 200000 {\n"
        "        console.log i\n"
        "        git push --force i = i + 1\n"
        "    }\n"
        "}\n"
        ":wq\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "btw", "run", str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout.readline() == b"1\n"
    process.stdout.close()
    assert process.stderr.read() == b""
    assert process.wait() == 141
