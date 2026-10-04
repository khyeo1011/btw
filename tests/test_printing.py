import io
import re

import pytest

from btw import printing
from btw.diagnostics import Diagnostic, Severity
from btw.printing import format_pretty, format_short, print_diagnostics, use_color
from btw.span import Pos, Span

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def diag(code, severity, message, start, end, soft=False, help=None):
    return Diagnostic(code, severity, message, Span(Pos(*start), Pos(*end)), soft=soft, help=help)


E404 = diag(
    "E404",
    Severity.ERROR,
    "Error 404: variable `x` not found. Did you forget to `npm install` it?",
    (2, 16),
    (2, 17),
)
E404_SOURCE = "i use arch btw\nserve localhost:3000 {\n    console.log x\n}\n:wq\n"

E403 = diag(
    "E403",
    Severity.ERROR,
    "Permission denied. Are you root?",
    (3, 4),
    (3, 26),
    soft=True,
    help="try `sudo git push --force LIMIT = ...`",
)
E403_SOURCE = (
    "i use arch btw\nnpm install -g LIMIT = 10\nserve localhost:3000 {\n"
    "    git push --force LIMIT = 11\n}\n:wq\n"
)

W410 = diag(
    "W410", Severity.WARNING, "This code never reaches prod.", (9, 4), (9, 23), soft=True
)
W410_SOURCE = "\n" * 9 + '    console.log "never"\n'


class TTY(io.StringIO):
    def isatty(self):
        return True


# Short format


def test_short_error_is_one_based():
    assert format_short(E404, "demo.btw") == (
        "demo.btw:3:17: error[E404]: "
        "Error 404: variable `x` not found. Did you forget to `npm install` it?"
    )


def test_short_soft_error_prints_as_error():
    assert format_short(E403, "demo.btw") == (
        "demo.btw:4:5: error[E403]: Permission denied. Are you root?"
    )


def test_short_warning():
    assert format_short(W410, "demo.btw") == (
        "demo.btw:10:5: warning[W410]: This code never reaches prod."
    )


def test_print_short_writes_one_line_each():
    stream = io.StringIO()
    print_diagnostics([E404, W410], "demo.btw", "", stream, "short")
    assert stream.getvalue() == (
        "demo.btw:3:17: error[E404]: "
        "Error 404: variable `x` not found. Did you forget to `npm install` it?\n"
        "demo.btw:10:5: warning[W410]: This code never reaches prod.\n"
    )


def test_short_never_has_color(monkeypatch):
    monkeypatch.setattr(printing.sys, "stdout", TTY())
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = TTY()
    print_diagnostics([E404], "demo.btw", "", stream, "short")
    assert "\x1b[" not in stream.getvalue()


def test_print_nothing_for_no_diagnostics():
    for fmt in ("short", "pretty"):
        stream = io.StringIO()
        print_diagnostics([], "demo.btw", "", stream, fmt)
        assert stream.getvalue() == ""


# Color


def test_color_when_stdout_is_a_terminal(monkeypatch):
    monkeypatch.setattr(printing.sys, "stdout", TTY())
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert use_color()


def test_no_color_when_stdout_is_not_a_terminal(monkeypatch):
    monkeypatch.setattr(printing.sys, "stdout", io.StringIO())
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert not use_color()


@pytest.mark.parametrize("value", ["1", ""])
def test_no_color_when_no_color_is_set(monkeypatch, value):
    monkeypatch.setattr(printing.sys, "stdout", TTY())
    monkeypatch.setenv("NO_COLOR", value)
    assert not use_color()


# Pretty format (Implementation Spec 3 and NOTES-harness.md)


def test_pretty_single_caret():
    assert format_pretty(E404, "demo.btw", E404_SOURCE, color=False) == (
        "error[E404]: Error 404: variable `x` not found. Did you forget to `npm install` it?\n"
        "  --> demo.btw:3:17\n"
        "   |\n"
        " 3 |     console.log x\n"
        "   |                 ^"
    )


def test_pretty_span_width_and_help():
    assert format_pretty(E403, "demo.btw", E403_SOURCE, color=False) == (
        "error[E403]: Permission denied. Are you root?\n"
        "  --> demo.btw:4:5\n"
        "   |\n"
        " 4 |     git push --force LIMIT = 11\n"
        "   |     ^^^^^^^^^^^^^^^^^^^^^^\n"
        "   = help: try `sudo git push --force LIMIT = ...`"
    )


def test_pretty_warning_with_two_digit_gutter():
    assert format_pretty(W410, "demo.btw", W410_SOURCE, color=False) == (
        "warning[W410]: This code never reaches prod.\n"
        "   --> demo.btw:10:5\n"
        "    |\n"
        ' 10 |     console.log "never"\n'
        "    |     ^^^^^^^^^^^^^^^^^^^"
    )


def test_pretty_keeps_tabs_in_the_padding():
    d = diag("E404", Severity.ERROR, "m", (0, 13), (0, 14))
    text = format_pretty(d, "t.btw", "\tconsole.log x\n", color=False)
    assert text.splitlines()[-1] == "   | \t            ^"


def test_pretty_zero_width_span_past_the_end_of_the_line():
    d = diag("E400", Severity.ERROR, "m", (0, 19), (0, 19))
    text = format_pretty(d, "t.btw", "    console.log 1 +\n", color=False)
    assert text.splitlines()[-1] == "   | " + " " * 19 + "^"


def test_pretty_multi_line_span_stops_at_the_end_of_the_line():
    d = diag("E400", Severity.ERROR, "m", (0, 4), (1, 1))
    text = format_pretty(d, "t.btw", "    abc\nd\n", color=False)
    assert text.splitlines()[-1] == "   |     ^^^"


def test_pretty_empty_line_has_no_trailing_space():
    d = diag("E503", Severity.ERROR, "m", (1, 0), (1, 0))
    text = format_pretty(d, "t.btw", "i use arch btw\n", color=False)
    assert text.splitlines()[-2:] == [" 2 |", "   | ^"]


def test_pretty_strips_carriage_returns():
    d = diag("E404", Severity.ERROR, "m", (0, 0), (0, 1))
    text = format_pretty(d, "t.btw", "a\r\nb\r\n", color=False)
    assert text.splitlines()[-2:] == [" 1 | a", "   | ^"]


@pytest.mark.parametrize(
    "d, source", [(E404, E404_SOURCE), (E403, E403_SOURCE), (W410, W410_SOURCE)]
)
def test_pretty_color_only_adds_escape_codes(d, source):
    colored = format_pretty(d, "demo.btw", source, color=True)
    assert "\x1b[" in colored
    assert ANSI.sub("", colored) == format_pretty(d, "demo.btw", source, color=False)


@pytest.mark.parametrize(
    "d, source", [(E404, E404_SOURCE), (E403, E403_SOURCE), (W410, W410_SOURCE)]
)
def test_pretty_has_no_trailing_whitespace(d, source):
    for line in format_pretty(d, "demo.btw", source, color=False).split("\n"):
        assert line == line.rstrip()


def test_print_pretty_separates_blocks_with_a_blank_line(monkeypatch):
    monkeypatch.setattr(printing.sys, "stdout", io.StringIO())
    stream = io.StringIO()
    print_diagnostics([E404, E404], "demo.btw", E404_SOURCE, stream, "pretty")
    block = format_pretty(E404, "demo.btw", E404_SOURCE, color=False)
    assert stream.getvalue() == f"{block}\n\n{block}\n"


# Summary line (Language Spec 13), pretty mode only


@pytest.mark.parametrize(
    "diagnostics, line",
    [
        ([E404, E403, W410], "build failed: 2 errors, 1 warning. Skill issue."),
        ([E404], "build failed: 1 error. Skill issue."),
        ([W410], "1 warning. LGTM anyway."),
        ([W410, W410], "2 warnings. LGTM anyway."),
        ([], None),
    ],
)
def test_format_summary(diagnostics, line):
    assert printing.format_summary(diagnostics) == line


def test_summary_ends_pretty_output(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    stream = io.StringIO()
    print_diagnostics([W410], "demo.btw", W410_SOURCE, stream, "pretty", summary=True)
    assert stream.getvalue().endswith("^\n\n1 warning. LGTM anyway.\n")


def test_no_summary_in_short_mode_or_when_clean():
    stream = io.StringIO()
    print_diagnostics([W410], "demo.btw", W410_SOURCE, stream, "short", summary=True)
    print_diagnostics([], "demo.btw", "", stream, "pretty", summary=True)
    assert "LGTM" not in stream.getvalue()
    assert stream.getvalue().count("\n") == 1
