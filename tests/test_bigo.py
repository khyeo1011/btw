"""Big O checker: Language Spec 9.1, Implementation Spec 8."""

from pathlib import Path

import pytest

from btw import ast, driver
from btw.bigo import UNKNOWN, check_bigo, costs, format_complexity, infer, params_close
from btw.diagnostics import Edit, Fix, Severity
from btw.span import Pos, Span

GOLDEN = Path(__file__).parent / "golden"
BIG_O_CODES = {"E417", "W417", "W102", "W508", "W203"}


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
        ((0, 0), None, "O(1)"),
        ((0, 0), "m", "O(1)"),
        ((1, 0), None, "O(n)"),
        ((1, 0), "m", "O(m)"),
        ((2, 0), None, "O(n²)"),
        ((3, 0), "k", "O(k³)"),
        ((4, 0), None, "O(n^4)"),
        ((10, 0), None, "O(n^10)"),
        ((0, 1), None, "O(log n)"),
        ((1, 1), "m", "O(m log m)"),
        ((2, 1), None, "O(n² log n)"),
        ((0, 2), None, "O(log² n)"),
        ((3, 4), None, "O(n³ log^4 n)"),
        (UNKNOWN, None, "O(?)"),
    ],
)
def test_format_complexity(degree, var, text):
    assert format_complexity(degree, var) == text


@pytest.mark.parametrize(
    "degree, var, text",
    [
        ((0, 0), None, "O(1)"),
        ((1, 0), "m", "O(m)"),
        ((2, 0), None, "O(n^2)"),
        ((3, 0), "k", "O(k^3)"),
        ((1, 1), None, "O(n log n)"),
        ((2, 1), None, "O(n^2 log n)"),
        ((0, 3), None, "O(log^3 n)"),
        ((4, 0), None, "O(n^4)"),
    ],
)
def test_format_complexity_source_has_no_superscripts(degree, var, text):
    assert format_complexity(degree, var, source=True) == text


# Inference: loops and branches


def test_empty_body_is_constant():
    assert degrees("microservice f() O(1) {\n}") == {"f": (0, 0)}


def test_straight_line_code_is_constant():
    assert degrees("microservice f(n) {\n npm install x = n * 2\n ship it x\n}") == {"f": (0, 0)}


def test_one_loop_is_linear():
    assert degrees(f"microservice f(n) {{\n npm install i = 0\n {LOOP}\n}}") == {"f": (1, 0)}


def test_nested_loops_add_up():
    src = """microservice f(n) {
    doomscroll LGTM {
        doomscroll LGTM {
            doomscroll LGTM { touch grass }
        }
        touch grass
    }
}"""
    assert degrees(src) == {"f": (3, 0)}


def test_sibling_loops_take_the_max():
    src = "microservice f(n) {\n doomscroll LGTM { touch grass }\n doomscroll LGTM { touch grass }\n}"
    assert degrees(src) == {"f": (1, 0)}


def test_if_inside_loop_keeps_nesting():
    src = """microservice f(n) {
    doomscroll LGTM {
        vibe check n > 1 {
            doomscroll LGTM { touch grass }
        }
        touch grass
    }
}"""
    assert degrees(src) == {"f": (2, 0)}


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
    assert degrees(src) == {"f": (1, 0)}


def test_if_without_loop_is_constant():
    assert degrees("microservice f(n) {\n vibe check n > 1 { ship it 1 }\n}") == {"f": (0, 0)}


# Inference: trip counts. Every other doomscroll runs n times.


def degree(*lines: str, top: str = "") -> tuple[int, int] | None:
    """The degree of `microservice f(n)` with these body lines, after the
    top-level declarations in `top`."""
    f = "microservice f(n) {\n" + "\n".join(lines) + "\n}"
    return degrees(top, f)["f"] if top else degrees(f)["f"]


@pytest.mark.parametrize(
    "start, cond, step",
    [
        ("0", "i < 10", "i + 1"),
        ("0", "i <= 10", "i + 1"),
        ("0", "10 > i", "i + 1"),
        ("0", "10 >= i", "i + 1"),
        ("0", "i != 10", "i + 2"),
        ("10", "i > 0", "i - 1"),
        ("10", "i >= -3", "i - 1"),
        ("10", "0 < i", "i - 1"),
    ],
)
def test_counter_to_a_literal_is_constant(start, cond, step):
    lines = [f" npm install i = {start}", f" doomscroll {cond} {{ git push --force i = {step} }}"]
    assert degree(*lines) == (0, 0)


def test_counter_to_a_constant_is_constant():
    lines = [" npm install i = 0", " doomscroll i < LIMIT { git push --force i = i + STEP }"]
    assert degree(*lines, top="npm install -g LIMIT = 10\nnpm install -g STEP = n_steps()") == (0, 0)


def test_halving_is_log():
    assert degree(" doomscroll n > 0 { git push --force n = n / 2 }") == (0, 1)
    assert degree(" doomscroll n != 0 { git push --force n = n / -3 }") == (0, 1)
    assert degree(" doomscroll 1 < n { git push --force n = n / HALF }", top="npm install -g HALF = 2") == (0, 1)


def test_doubling_from_a_positive_literal_is_log():
    lines = [" npm install i = 1", " doomscroll i < n { git push --force i = i * 2 }"]
    assert degree(*lines) == (0, 1)


def test_trip_counts_add_up_when_nested():
    halving = "doomscroll k > 0 { git push --force k = k / 2 }"
    fixed = "doomscroll j < 3 { git push --force j = j + 1 }"
    # O(log n) inside O(n), and O(1) inside O(n)
    assert degree(f" doomscroll LGTM {{\n  npm install k = n\n  {halving}\n }}") == (1, 1)
    assert degree(f" doomscroll LGTM {{\n  npm install j = 0\n  {fixed}\n }}") == (1, 0)
    # O(log n) inside O(log n)
    src = f" doomscroll n > 0 {{\n  npm install k = n\n  {halving}\n  git push --force n = n / 2\n }}"
    assert degree(src) == (0, 2)
    # O(n) inside O(1)
    src = f" npm install j = 0\n doomscroll j < 3 {{\n  npm install i = 0\n  {LOOP}\n  git push --force j = j + 1\n }}"
    assert degree(src) == (1, 0)


@pytest.mark.parametrize(
    "lines",
    [
        # the bound isn't a literal or a constant
        [" npm install i = 0", " doomscroll i < n { git push --force i = i + 1 }"],
        # the start isn't a literal, or isn't declared right before the loop
        [" npm install i = n", " doomscroll i < 10 { git push --force i = i + 1 }"],
        [" npm install i = 0", " console.log i", " doomscroll i < 10 { git push --force i = i + 1 }"],
        # the step isn't a literal or a constant
        [" npm install i = 0", " doomscroll i < 10 { git push --force i = i + n }"],
        [" npm install k = 2", " doomscroll n > 0 { git push --force n = n / k }"],
        # the step is too small to halve or double
        [" doomscroll n > 0 { git push --force n = n / 1 }"],
        [" npm install i = 1", " doomscroll i < n { git push --force i = i * 1 }"],
        # 0 doubled stays 0, and doubling needs a literal start
        [" npm install i = 0", " doomscroll i < n { git push --force i = i * 2 }"],
        [" npm install i = n", " doomscroll i < n { git push --force i = i * 2 }"],
        # the step isn't `v = v op c`
        [" npm install i = 0", " doomscroll i < 10 { git push --force i = 1 + i }"],
        [" npm install i = 0", " doomscroll i < 10 { git push --force i = i % 3 }"],
        # the condition isn't a comparison of the counter
        [" npm install i = 0", " doomscroll i < 10 && LGTM { git push --force i = i + 1 }"],
        [" npm install i = 0", " doomscroll i == 0 { git push --force i = i + 1 }"],
        # the only assignment is inside a vibe check, or there are two
        [" npm install i = 0", " doomscroll i < 10 {\n  vibe check n > 1 { git push --force i = i + 1 }\n }"],
        [" npm install i = 0", " doomscroll i < 10 {\n  git push --force i = i + 1\n  git push --force i = i + 1\n }"],
        # a revert or a redeclaration changes it too
        [" doomscroll n > 0 {\n  git push --force n = n / 2\n  git revert n\n }"],
        [" doomscroll n > 0 {\n  npm install n = 8\n  git push --force n = n / 2\n }"],
    ],
)
def test_other_loops_are_linear(lines):
    assert degree(*lines) == (1, 0)


def test_assignment_in_a_nested_loop_counts():
    """Halving would make this O(n log n); the inner loop's write makes it O(n²)."""
    inner = "doomscroll LGTM { git push --force n = 5 }"
    assert degree(f" doomscroll n > 0 {{\n  git push --force n = n / 2\n  {inner}\n }}") == (2, 0)


def test_global_counter_is_linear():
    """A call in the body could change a global."""
    assert degree(" doomscroll g > 0 { git push --force g = g / 2 }", top="npm install g = 64") == (1, 0)


def test_constant_changed_by_sudo_is_not_constant():
    lines = [" npm install i = 0", " doomscroll i < LIMIT { git push --force i = i + 1 }"]
    top = "npm install -g LIMIT = 10\nmicroservice g() {\n sudo git push --force LIMIT = 1000\n}"
    assert degree(*lines, top=top) == (1, 0)


def test_fixed_size_loop_is_not_a_nested_doomscroll():
    src = f"microservice f(n) {{\n npm install j = 0\n doomscroll j < 3 {{\n  git push --force j = j + 1\n }}\n}}"
    assert costs(program(src))["f"].loop is None


# Inference: calls (P1)


def test_call_costs_the_callee_degree():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n ship it g(n)\n}"
    assert degrees(f, g) == {"f": (1, 0), "g": (1, 0)}


def test_call_inside_loop_nests():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n doomscroll LGTM {\n  g(n)\n  touch grass\n }\n}"
    assert degrees(f, g) == {"f": (2, 0), "g": (1, 0)}


def test_call_in_loop_condition_runs_every_iteration():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n doomscroll g(n) > 0 { touch grass }\n}"
    assert degrees(f, g) == {"f": (2, 0), "g": (1, 0)}


def test_call_in_if_condition_and_arguments():
    g = f"microservice g(n) {{\n {LOOP}\n}}"
    f = "microservice f(n) {\n vibe check 1 + h(g(n)) > 0 { ship it 1 }\n}"
    h = "microservice h(n) {\n ship it n\n}"
    assert degrees(f, g, h) == {"f": (1, 0), "g": (1, 0), "h": (0, 0)}


def test_unknown_callee_is_ignored():
    assert degrees("microservice f(n) {\n ship it nope(n)\n}") == {"f": (0, 0)}


def test_calling_twice_is_not_recursion():
    f = "microservice f(n) {\n ship it g(n) + g(n)\n}"
    g = "microservice g(n) {\n ship it n\n}"
    assert degrees(f, g) == {"f": (0, 0), "g": (0, 0)}


def test_diamond_is_not_recursion():
    a = "microservice a(n) {\n ship it b(n) + c(n)\n}"
    b = "microservice b(n) {\n ship it d(n)\n}"
    c = "microservice c(n) {\n ship it d(n)\n}"
    d = f"microservice d(n) {{\n {LOOP}\n}}"
    assert degrees(a, b, c, d) == {"a": (1, 0), "b": (1, 0), "c": (1, 0), "d": (1, 0)}


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
    assert degrees(h, g, f) == {"h": (0, 0), "g": UNKNOWN, "f": UNKNOWN}


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


def test_e417_log_underclaim():
    [d] = check_bigo(program(f"microservice f(n) O(log n) {{\n npm install i = 0\n {LOOP}\n}}"))
    assert d.message == "You said O(log n), but this is O(n). Skill issue."
    assert d.related == [(Span(Pos(3, 1), Pos(3, 11)), "nested doomscroll #1 starts here")]
    src = "microservice f(n) O(n) {\n doomscroll LGTM {\n  doomscroll n > 0 { git push --force n = n / 2 }\n }\n}"
    assert diags(src) == [("E417", "You said O(n), but this is O(n log n). Skill issue.")]


@pytest.mark.parametrize("sla", ["log n", "n log n", "n^2 log n", "n ^ 2 log n", "log^2 n", "m log m"])
def test_log_annotations_are_checked(sla):
    var = "m" if "m" in sla else "n"
    found = diags(f"microservice f({var}) O({sla}) {{\n ship it {var}\n}}")
    assert [c for c, _ in found] == ["W417"]


@pytest.mark.parametrize("sla", ["2^n", "n!", "n log m", "log log n", "log(n)", "n log", "sqrt n"])
def test_other_annotations_are_unverifiable(sla):
    assert [c for c, _ in diags(f"microservice f(n) O({sla}) {{\n ship it n\n}}")] == ["W203"]


def test_exact_log_annotations_are_clean():
    halving = "doomscroll n > 0 { git push --force n = n / 2 }"
    assert diags(f"microservice f(n) O(log n) {{\n {halving}\n}}") == []
    assert diags(f"microservice f(n) O(n log n) {{\n doomscroll LGTM {{\n  {halving}\n }}\n}}") == []


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
    [d] = check_bigo(program("microservice f(n) O(2^n) {\n ship it n\n}"))
    assert (d.code, d.severity, d.soft) == ("W203", Severity.WARNING, True)
    assert d.message == "I can't verify O(2^n). I'll take your word for it."
    assert d.span == Span(Pos(1, 18), Pos(1, 24))


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
def test_golden_big_o_lines(path):
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


@pytest.mark.parametrize(
    "src", [src for name, (src, _) in UNCLOSED.items() if name.startswith("params_")]
)
def test_unclosed_params_get_no_w102_fix(src):
    _, _, found = driver.check(src, "test.btw")
    assert "E400" in [d.code for d in found]
    [w102] = [d for d in found if d.code == "W102"]
    assert w102.fixes == []


# Quick fixes (P2): Language Spec 11, the Quick fix column


def source(*services: str) -> str:
    return ARCH + "\n".join(services) + "\n" + SERVE


def tokens_and_service(src: str):
    tokens, _, _ = driver.lex(src)
    prog, _ = driver.parse(src)
    ms = next(item for item in prog.items if isinstance(item, ast.Microservice))
    return tokens, ms


def bigo_diagnostics(src: str):
    tokens, _, _ = driver.lex(src)
    prog, _ = driver.parse(src)
    return check_bigo(prog, tokens)


def utf16_index(src: str, pos: Pos) -> int:
    """The string index of a 0-based line and UTF-16 column."""
    index = sum(len(line) + 1 for line in src.split("\n")[: pos.line])
    units = 0
    while units < pos.col:
        units += 2 if ord(src[index]) > 0xFFFF else 1
        index += 1
    return index


def apply_fix(src: str, fix: Fix) -> str:
    for edit in sorted(fix.edits, key=lambda e: e.span.start, reverse=True):
        start, end = utf16_index(src, edit.span.start), utf16_index(src, edit.span.end)
        src = src[:start] + edit.text + src[end:]
    return src


LINEAR = " npm install i = 0\n doomscroll i < n { git push --force i = i + 1 }"
QUADRATIC = (
    " npm install i = 0\n doomscroll i < n {\n"
    "  npm install j = 0\n  doomscroll j < n { git push --force j = j + 1 }\n"
    "  git push --force i = i + 1\n }"
)
CUBIC = (
    " npm install i = 0\n doomscroll i < n {\n"
    "  npm install j = 0\n  doomscroll j < n {\n"
    "   npm install k = 0\n   doomscroll k < n { git push --force k = k + 1 }\n"
    "   git push --force j = j + 1\n  }\n"
    "  git push --force i = i + 1\n }"
)


@pytest.mark.parametrize(
    "service, close",
    [
        ("microservice f(n) {\n ship it n\n}", span(1, 16, 1, 17)),
        ("microservice f(n){\n ship it n\n}", span(1, 16, 1, 17)),
        ("microservice f() {\n ship it 1\n}", span(1, 15, 1, 16)),
        ("microservice f( ) {\n ship it 1\n}", span(1, 16, 1, 17)),
        ("microservice f(a, // TODO x\n   b\n  ) {\n ship it a\n}", span(3, 2, 3, 3)),
        ("microservice f(n)\n{\n ship it n\n}", span(1, 16, 1, 17)),
        ("microservice f(n)", span(1, 16, 1, 17)),
        ("microservice f(n) junk {\n ship it n\n}", span(1, 16, 1, 17)),
        ("microservice f(a b) {\n ship it a\n}", span(1, 18, 1, 19)),
        ("microservice f(n) O(1) {\n ship it n\n}", span(1, 16, 1, 17)),
        ("microservice f(n {\n ship it n\n}", None),
        ("microservice f(n\n{\n ship it n\n}", None),
        ("microservice f( {\n ship it 1\n}", None),
        ("microservice f(n O(n) {\n ship it n\n}", None),
    ],
    ids=[
        "space", "no_space", "zero", "zero_spaced", "multiline_comment", "brace_next_line",
        "no_body", "junk", "bad_param", "annotated", "missing", "missing_newline",
        "missing_zero", "missing_before_big_o",
    ],
)
def test_params_close(service, close):
    assert params_close(*tokens_and_service(source(service))) == close


@pytest.mark.parametrize("tail", ["microservice f(", "microservice f(a, b"])
def test_params_close_at_end_of_file(tail):
    assert params_close(*tokens_and_service(ARCH + tail)) is None


def test_w102_fix_linear():
    [d] = bigo_diagnostics(source(f"microservice count(n) {{\n{LINEAR}\n}}"))
    assert d.fixes == [Fix("Add SLA O(n)", [Edit(span(1, 21, 1, 21), " O(n)")])]


def test_w102_fix_constant():
    [d] = bigo_diagnostics(source("microservice f() {\n ship it 1\n}"))
    assert d.fixes == [Fix("Add SLA O(1)", [Edit(span(1, 16, 1, 16), " O(1)")])]


def test_w102_fix_quadratic_inserts_source_text():
    [d] = bigo_diagnostics(source(f"microservice f(n) {{\n doomscroll LGTM {{\n{LINEAR}\n }}\n}}"))
    assert d.fixes == [Fix("Add SLA O(n²)", [Edit(span(1, 17, 1, 17), " O(n^2)")])]


def test_w102_without_tokens_has_no_fix():
    [d] = check_bigo(program(f"microservice count(n) {{\n{LINEAR}\n}}"))
    assert d.code == "W102" and d.fixes == []


def test_driver_check_attaches_the_w102_fix():
    _, _, found = driver.check(source("microservice f() {\n ship it 1\n}"), "test.btw")
    [d] = [d for d in found if d.code == "W102"]
    assert d.fixes == [Fix("Add SLA O(1)", [Edit(span(1, 16, 1, 16), " O(1)")])]


def test_e417_fix():
    [d] = check_bigo(program(f"microservice f(n) O(1) {{\n doomscroll LGTM {{\n  {LOOP}\n }}\n}}"))
    assert d.fixes == [Fix("Update SLA to O(n²)", [Edit(span(1, 18, 1, 22), "O(n^2)")])]


def test_e417_fix_uses_the_annotation_variable():
    [d] = check_bigo(program(f"microservice f(m) O(m) {{\n doomscroll LGTM {{\n  {LOOP}\n }}\n}}"))
    assert d.fixes == [Fix("Update SLA to O(m²)", [Edit(span(1, 18, 1, 22), "O(m^2)")])]


def test_log_fixes_use_source_text():
    src = "microservice f(n) O(1) {\n doomscroll LGTM {\n  doomscroll n > 0 { git push --force n = n / 2 }\n }\n}"
    [d] = check_bigo(program(src))
    assert d.fixes == [Fix("Update SLA to O(n log n)", [Edit(span(1, 18, 1, 22), "O(n log n)")])]
    [d] = check_bigo(program("microservice f(n) O(n log n) {\n doomscroll n > 0 { git push --force n = n / 2 }\n}"))
    assert d.message == "Technically correct, but this is O(log n). Sandbagging your estimates?"
    assert d.fixes == [Fix("Tighten SLA", [Edit(span(1, 18, 1, 28), "O(log n)")])]


def test_w417_fix():
    [d] = check_bigo(program("microservice f(n) O(n^4) {\n ship it n\n}"))
    assert d.fixes == [Fix("Tighten SLA", [Edit(span(1, 18, 1, 24), "O(1)")])]


def test_w417_fix_uses_the_annotation_variable():
    [d] = check_bigo(program(f"microservice f(m) O(m^3) {{\n {LOOP}\n}}"))
    assert d.fixes == [Fix("Tighten SLA", [Edit(span(1, 18, 1, 24), "O(m)")])]


@pytest.mark.parametrize(
    "service, code",
    [
        (f"microservice count(n) {{\n{LINEAR}\n}}", "W102"),
        (f"microservice count(n){{\n{LINEAR}\n}}", "W102"),
        ("microservice f() {\n ship it 1\n}", "W102"),
        ("microservice f(a, // TODO 🚀 later\n  b\n  ) {\n ship it a + b\n}", "W102"),
        (f"microservice f(n) O(1) {{\n{LINEAR}\n}}", "E417"),
        ("microservice f(n) O(n^4) {\n ship it n\n}", "W417"),
        (f"microservice f(n) O(n^3) {{\n{LINEAR}\n}}", "W417"),
        (f"microservice f(n) {{\n{QUADRATIC}\n}}", "W102"),
        (f"microservice f(n) O(n) {{\n{CUBIC}\n}}", "E417"),
        (f"microservice f(n) O(n^4) {{\n{QUADRATIC}\n}}", "W417"),
    ],
    ids=["w102_linear", "w102_no_space", "w102_constant", "w102_multiline", "e417", "w417_constant",
         "w417_linear", "w102_quadratic", "e417_cubic", "w417_quadratic"],
)
def test_fix_round_trip(service, code):
    src = source(service)
    _, _, before = driver.check(src, "test.btw")
    assert [d.code for d in before] == [code]
    [fix] = before[0].fixes
    _, _, after = driver.check(apply_fix(src, fix), "test.btw")
    assert after == []
