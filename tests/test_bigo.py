"""Big O checker: Language Spec 9.1, Implementation Spec 8."""

from pathlib import Path

import pytest

from btw import driver
from btw.bigo import UNKNOWN, check_bigo, costs, format_complexity, infer
from btw.diagnostics import Severity
from btw.span import Pos, Span

GOLDEN = Path(__file__).parent / "golden"
BIG_O_CODES = {"E417", "W417", "W102", "W508", "W203"}

# Goldens whose Big O lines need another card: suppression hides the W102.
WAITING = {"p2_w200_two_problems": "suppression (suppress.py)"}


def program(*services: str):
    src = "i use arch btw\n" + "\n".join(services) + "\nserve localhost:3000 {\n}\n:wq\n"
    prog, _ = driver.parse(src)
    return prog


def degrees(*services: str):
    return infer(program(*services))


def diags(*services: str):
    return [(d.code, d.message) for d in check_bigo(program(*services))]


LOOP = "doomscroll i < n { git push --force i = i + 1 }"


# format_complexity


@pytest.mark.parametrize(
    "degree, var, text",
    [
        (0, None, "O(1)"),
        (0, "m", "O(1)"),
        (1, None, "O(n)"),
        (1, "m", "O(m)"),
        (2, None, "O(n²)"),
        (3, "k", "O(k³)"),
        (4, None, "O(n^4)"),
        (10, None, "O(n^10)"),
        (UNKNOWN, None, "O(?)"),
    ],
)
def test_format_complexity(degree, var, text):
    assert format_complexity(degree, var) == text


# Inference: loops and branches


def test_empty_body_is_constant():
    assert degrees("microservice f() O(1) {\n}") == {"f": 0}


def test_straight_line_code_is_constant():
    assert degrees("microservice f(n) {\n npm install x = n * 2\n ship it x\n}") == {"f": 0}


def test_one_loop_is_linear():
    assert degrees(f"microservice f(n) {{\n npm install i = 0\n {LOOP}\n}}") == {"f": 1}


def test_nested_loops_add_up():
    src = """microservice f(n) {
    doomscroll LGTM {
        doomscroll LGTM {
            doomscroll LGTM { touch grass }
        }
        touch grass
    }
}"""
    assert degrees(src) == {"f": 3}


def test_sibling_loops_take_the_max():
    src = "microservice f(n) {\n doomscroll LGTM { touch grass }\n doomscroll LGTM { touch grass }\n}"
    assert degrees(src) == {"f": 1}


def test_if_inside_loop_keeps_nesting():
    src = """microservice f(n) {
    doomscroll LGTM {
        vibe check n > 1 {
            doomscroll LGTM { touch grass }
        }
        touch grass
    }
}"""
    assert degrees(src) == {"f": 2}


def test_loop_in_else_branch_counts():
    src = """microservice f(n) {
    vibe check n > 1 {
        ship it 1
    } skill issue vibe check n > 2 {
        ship it 2
    } skill issue {
        doomscroll LGTM { touch grass }
    }
}"""
    assert degrees(src) == {"f": 1}


def test_if_without_loop_is_constant():
    assert degrees("microservice f(n) {\n vibe check n > 1 { ship it 1 }\n}") == {"f": 0}


# Inference: calls (P1)


def test_call_costs_the_callee_degree():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n ship it g(n)\n}"
    assert degrees(f, g) == {"f": 1, "g": 1}


def test_call_inside_loop_nests():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n doomscroll LGTM {\n  g(n)\n  touch grass\n }\n}"
    assert degrees(f, g) == {"f": 2, "g": 1}


def test_call_in_loop_condition_runs_every_iteration():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n doomscroll g(n) > 0 { touch grass }\n}"
    assert degrees(f, g) == {"f": 2, "g": 1}


def test_call_in_if_condition_and_arguments():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n vibe check 1 + h(g(n)) > 0 { ship it 1 }\n}"
    h = "microservice h(n) {\n ship it n\n}"
    assert degrees(f, g, h) == {"f": 1, "g": 1, "h": 0}


def test_unknown_callee_is_ignored():
    assert degrees("microservice f(n) {\n ship it nope(n)\n}") == {"f": 0}


def test_calling_twice_is_not_recursion():
    f = "microservice f(n) {\n ship it g(n) + g(n)\n}"
    g = "microservice g(n) {\n ship it n\n}"
    assert degrees(f, g) == {"f": 0, "g": 0}


def test_diamond_is_not_recursion():
    a = "microservice a(n) {\n ship it b(n) + c(n)\n}"
    b = "microservice b(n) {\n ship it d(n)\n}"
    c = "microservice c(n) {\n ship it d(n)\n}"
    d = f"microservice d(n) {{\n {LOOP}\n}}"
    assert degrees(a, b, c, d) == {"a": 1, "b": 1, "c": 1, "d": 1}


# Inference: recursion


def test_self_recursion_is_unknown():
    assert degrees("microservice f(n) {\n ship it f(n - 1)\n}") == {"f": UNKNOWN}


def test_self_recursion_inside_loop_is_unknown():
    src = "microservice f(n) {\n doomscroll LGTM {\n  f(n)\n  touch grass\n }\n}"
    assert degrees(src) == {"f": UNKNOWN}


def test_mutual_recursion_is_unknown():
    f = "microservice f(n) {\n ship it g(n)\n}"
    g = "microservice g(n) {\n ship it h(n)\n}"
    h = "microservice h(n) {\n ship it f(n)\n}"
    assert degrees(f, g, h) == {"f": UNKNOWN, "g": UNKNOWN, "h": UNKNOWN}


def test_mutual_recursion_found_from_any_start():
    # Inferred in source order, so the walk enters the cycle at g, not f.
    h = "microservice h(n) {\n ship it 1\n}"
    g = "microservice g(n) {\n ship it f(n) + h(n)\n}"
    f = "microservice f(n) {\n ship it g(n)\n}"
    assert degrees(h, g, f) == {"h": 0, "g": UNKNOWN, "f": UNKNOWN}


def test_unknown_is_contagious_to_callers():
    caller = f"microservice caller(n) {{\n {LOOP}\n ship it rec(n)\n}}"
    rec = "microservice rec(n) {\n ship it rec(n)\n}"
    assert degrees(caller, rec) == {"caller": UNKNOWN, "rec": UNKNOWN}


# Deepest loop span


def test_deepest_loop_is_innermost_doomscroll():
    src = """microservice f(n) {
    doomscroll LGTM { touch grass }
    doomscroll LGTM {
        doomscroll LGTM { touch grass }
        touch grass
    }
}"""
    # line 5 (0-based 4) is the innermost loop of the deepest nest
    assert costs(program(src))["f"].loop == Span(Pos(4, 8), Pos(4, 18))


def test_deepest_loop_follows_calls():
    f = "microservice f(n) {\n doomscroll LGTM {\n  g(n)\n  touch grass\n }\n}"
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    # g's loop is on line 9 (0-based 8), after the arch line and f
    assert costs(program(f, g))["f"].loop == Span(Pos(8, 1), Pos(8, 11))


def test_no_loop_without_doomscroll():
    assert costs(program("microservice f(n) {\n ship it n\n}"))["f"].loop is None
    assert costs(program("microservice f(n) {\n ship it f(n)\n}"))["f"].loop is None


# Verdicts: every row of the Language Spec 9.1 table


def test_exact_annotation_is_clean():
    assert diags(f"microservice f(n) O(n) {{\n {LOOP}\n}}") == []
    assert diags("microservice f(n) O(1) {\n ship it n\n}") == []
    assert diags("microservice f(n) O(n^0) {\n ship it n\n}") == []


def test_e417_underclaim():
    [d] = check_bigo(program(f"microservice f(n) O(1) {{\n doomscroll LGTM {{\n  {LOOP}\n }}\n}}"))
    assert (d.code, d.severity, d.soft) == ("E417", Severity.ERROR, True)
    assert d.message == "You said O(1), but this is O(n²). Skill issue."
    assert d.span == Span(Pos(1, 18), Pos(1, 22))
    assert d.help == "try `O(n²)`, then tell the PM it was always the plan"
    assert d.related == [(Span(Pos(3, 2), Pos(3, 12)), "nested doomscroll #2 starts here")]


def test_e417_uses_the_annotation_variable():
    src = f"microservice f(m) O(m) {{\n doomscroll LGTM {{\n  {LOOP}\n }}\n}}"
    assert diags(src) == [("E417", "You said O(m), but this is O(m²). Skill issue.")]


def test_w417_overclaim():
    [d] = check_bigo(program("microservice f(n) O(n^4) {\n ship it n\n}"))
    assert (d.code, d.severity, d.soft) == ("W417", Severity.WARNING, True)
    assert d.message == "Technically correct, but this is O(1). Sandbagging your estimates?"
    assert d.span == Span(Pos(1, 18), Pos(1, 24))


def test_w102_no_annotation():
    [d] = check_bigo(program(f"microservice count(n) {{\n {LOOP}\n}}"))
    assert (d.code, d.severity, d.soft) == ("W102", Severity.WARNING, True)
    assert d.message == "microservice `count` has no SLA. Inferred: O(n)."
    assert d.span == Span(Pos(1, 13), Pos(1, 18))


def test_w508_recursion():
    [d] = check_bigo(program("microservice f(n) O(n) {\n ship it f(n - 1)\n}"))
    assert (d.code, d.severity, d.soft) == ("W508", Severity.WARNING, True)
    assert d.message == "Complexity: O(?). The halting problem is a skill issue."
    assert d.span == Span(Pos(1, 13), Pos(1, 14))


def test_w508_replaces_w102():
    assert diags("microservice f(n) {\n ship it f(n)\n}") == [
        ("W508", "Complexity: O(?). The halting problem is a skill issue.")
    ]


def test_w508_replaces_e417_and_w417():
    assert [c for c, _ in diags("microservice f(n) O(1) {\n ship it f(n)\n}")] == ["W508"]


def test_w203_unverifiable():
    [d] = check_bigo(program("microservice f(n) O(n log n) {\n ship it n\n}"))
    assert (d.code, d.severity, d.soft) == ("W203", Severity.WARNING, True)
    assert d.message == "I can't verify O(n log n). I'll take your word for it."
    assert d.span == Span(Pos(1, 18), Pos(1, 28))


def test_w203_skips_the_comparison():
    assert [c for c, _ in diags(f"microservice f(n) O(2^n) {{\n {LOOP}\n}}")] == ["W203"]


def test_w203_and_w508_together():
    assert [c for c, _ in diags("microservice f(n) O(n!) {\n ship it f(n)\n}")] == ["W203", "W508"]


def test_duplicate_microservice_gets_its_own_verdict():
    first = "microservice f(n) O(1) {\n ship it n\n}"
    second = f"microservice f(n) O(1) {{\n {LOOP}\n}}"
    assert [c for c, _ in diags(first, second)] == ["E417"]


# Golden files: the Big O lines of every .diag


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.btw")), ids=lambda p: p.stem)
def test_golden_big_o_lines(path, request):
    if path.stem in WAITING:
        request.applymarker(pytest.mark.xfail(reason=WAITING[path.stem], strict=True))
    _, _, found = driver.check(path.read_text(encoding="utf-8"), str(path))
    got = [
        f"{d.span.start.line + 1}:{d.span.start.col + 1}: {d.severity.value}[{d.code}]: {d.message}"
        for d in found
        if d.code in BIG_O_CODES
    ]
    sidecar = path.with_suffix(".diag")
    lines = sidecar.read_text(encoding="utf-8").splitlines() if sidecar.exists() else []
    assert got == [line for line in lines if line.split("[")[1][:4] in BIG_O_CODES]


# Unclosed `(`: the parser reports it (NOTES-parser, "Unclosed `(`"). That
# matters here because W102's fix needs the `)` that closes the parameters.

ARCH = "i use arch btw\n"
SERVE = "serve localhost:3000 {\n}\n:wq\n"
LISP = " Even Lisp programmers close their parentheses."


def span(line: int, col: int, end_line: int, end_col: int) -> Span:
    return Span(Pos(line, col), Pos(end_line, end_col))


def close_paren(found: str, *where: int):
    """The E400 for a missing `)` found on its own token, with a 0-based span."""
    return (f"Syntax error: expected `)`, found {found}.", span(*where))


def missing_name(*where: int):
    return ("Syntax error: expected a name, found `{`.", span(*where))


def unclosed_at_wq(line: int):
    """The file-level E400 on `:wq` when a `(` is still open at the end of the program."""
    return (f"Syntax error: expected `)`, found `:wq`.{LISP}", span(line, 0, line, 3))


def unclosed_at_eof(line: int, col: int):
    return (f"Syntax error: expected `)`, found end of file.{LISP}", span(line, col, line, col))


UNCLOSED = {
    # microservice parameter lists
    "params_zero_eof": (ARCH + "microservice f(", [unclosed_at_eof(1, 15)]),
    "params_zero_before_brace": (
        ARCH + "microservice f( {\n ship it 1\n}\n" + SERVE,
        [missing_name(1, 16, 1, 17), unclosed_at_wq(6)],
    ),
    "params_zero_before_newline": (
        ARCH + "microservice f(\n{\n ship it 1\n}\n" + SERVE,
        [missing_name(2, 0, 2, 1), unclosed_at_wq(7)],
    ),
    "params_one_eof": (ARCH + "microservice f(n", [unclosed_at_eof(1, 16)]),
    "params_one_before_brace": (
        ARCH + "microservice f(n {\n ship it n\n}\n" + SERVE,
        [close_paren("`{`", 1, 17, 1, 18), unclosed_at_wq(6)],
    ),
    "params_one_before_newline": (
        ARCH + "microservice f(n\n{\n ship it n\n}\n" + SERVE,
        [close_paren("`{`", 2, 0, 2, 1), unclosed_at_wq(7)],
    ),
    "params_one_before_big_o": (
        ARCH + "microservice f(n O(n) {\n ship it n\n}\n" + SERVE,
        [close_paren("`O`, whoever that is", 1, 17, 1, 18), unclosed_at_wq(6)],
    ),
    "params_one_before_serve": (
        ARCH + "microservice f(n\n" + SERVE,
        [close_paren("`serve`", 2, 0, 2, 5), unclosed_at_wq(4)],
    ),
    "params_many_eof": (ARCH + "microservice f(a, b", [unclosed_at_eof(1, 19)]),
    "params_many_before_brace": (
        ARCH + "microservice f(a, b, c {\n ship it a\n}\n" + SERVE,
        [close_paren("`{`", 1, 23, 1, 24), unclosed_at_wq(6)],
    ),
    "params_many_trailing_comma": (
        ARCH + "microservice f(a, b, {\n ship it a\n}\n" + SERVE,
        [missing_name(1, 21, 1, 22), unclosed_at_wq(6)],
    ),
    "params_multiline": (
        ARCH + "microservice f(a,\n  b,\n  c {\n ship it a\n}\n" + SERVE,
        [close_paren("`{`", 3, 4, 3, 5), unclosed_at_wq(8)],
    ),
    "params_multiline_comment": (
        ARCH + "microservice f(a, // TODO more\n  b {\n ship it a\n}\n" + SERVE,
        [close_paren("`{`", 2, 4, 2, 5), unclosed_at_wq(7)],
    ),
    # call arguments
    "call": (
        ARCH + "serve localhost:3000 {\n f(1\n}\n:wq\n",
        [close_paren("`}`", 3, 0, 3, 1), unclosed_at_wq(4)],
    ),
    "call_many_args": (
        ARCH + "serve localhost:3000 {\n console.log f(1, 2\n}\n:wq\n",
        [close_paren("`}`", 3, 0, 3, 1), unclosed_at_wq(4)],
    ),
    "call_nested": (
        ARCH + "serve localhost:3000 {\n console.log f(g(1)\n}\n:wq\n",
        [close_paren("`}`", 3, 0, 3, 1), unclosed_at_wq(4)],
    ),
    "call_in_microservice": (
        ARCH + "microservice f(n) O(1) {\n ship it g(n\n}\n" + SERVE,
        [close_paren("`}`", 3, 0, 3, 1), unclosed_at_wq(6)],
    ),
    "call_eof": (ARCH + "serve localhost:3000 {\n console.log f(1", [unclosed_at_eof(2, 16)]),
    # grouping
    "group": (
        ARCH + "serve localhost:3000 {\n console.log (1 + 2\n}\n:wq\n",
        [close_paren("`}`", 3, 0, 3, 1), unclosed_at_wq(4)],
    ),
    "group_condition": (
        ARCH + "serve localhost:3000 {\n vibe check (1 == 1 {\n  console.log 1\n }\n}\n:wq\n",
        [close_paren("`{`", 2, 20, 2, 21), unclosed_at_wq(6)],
    ),
    "group_global": (
        ARCH + "npm install x = (1 + 2\n" + SERVE,
        [close_paren("`serve`", 2, 0, 2, 5), unclosed_at_wq(4)],
    ),
    "group_eof": (ARCH + "serve localhost:3000 {\n console.log (1", [unclosed_at_eof(2, 15)]),
    # Big O annotations
    "big_o_before_brace": (
        ARCH + "microservice f(n) O(n {\n ship it n\n}\n" + SERVE,
        [close_paren("`{`", 1, 22, 1, 23), unclosed_at_wq(6)],
    ),
    "big_o_before_newline": (
        ARCH + "microservice f(n) O(n\n{\n ship it n\n}\n" + SERVE,
        [close_paren("`{`", 2, 0, 2, 1), unclosed_at_wq(7)],
    ),
    "big_o_nested": (
        ARCH + "microservice f(n) O(log(n) {\n ship it n\n}\n" + SERVE,
        [close_paren("`{`", 1, 27, 1, 28), unclosed_at_wq(6)],
    ),
    "big_o_eof": (ARCH + "microservice f(n) O(n", [unclosed_at_eof(1, 21)]),
}


def syntax_errors(src: str):
    _, found = driver.parse(src)
    return [(d.message, d.span) for d in found if d.code == "E400"]


@pytest.mark.parametrize("src, expected", UNCLOSED.values(), ids=UNCLOSED.keys())
def test_unclosed_paren_is_reported(src, expected):
    assert syntax_errors(src) == expected


def test_closed_multiline_params_with_comment_are_clean():
    src = ARCH + "microservice f(a, // TODO more\n  b\n  ) O(1) {\n ship it a\n}\n" + SERVE
    assert syntax_errors(src) == []
