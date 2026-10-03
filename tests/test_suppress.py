"""Works on my machine: Language Spec 9.5, Implementation Spec 7 pass 8."""

from btw import driver
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span
from btw.suppress import W304_HARD, W304_NOTHING, apply, w200

DIRECTIVE = "// works on my machine"
E403 = "Permission denied. Are you root?"
E429 = "Error: technical debt limit exceeded (6/5 TODOs). Finish something."


def check(body: str, top: str = "") -> list[tuple[int, str, str]]:
    """(1-based line, code, message) for a program whose serve block holds `body`."""
    src = f"i use arch btw\n{top}serve localhost:3000 {{\n{body}\n}}\n:wq\n"
    _, _, diags = driver.check(src, "test.btw")
    return [(d.span.start.line + 1, d.code, d.message) for d in diags]


def codes(body: str, top: str = "") -> list[str]:
    return [code for _, code, _ in check(body, top)]


def test_messages():
    assert w200(1) == "200 OK (on my machine): 1 problem suppressed."
    assert w200(2) == "200 OK (on my machine): 2 problems suppressed."
    assert W304_HARD == "304 Not Modified: this one doesn't work on any machine."
    assert W304_NOTHING == "304 Not Modified: nothing to suppress. It works on every machine."


# The four goldens, one behavior each


def test_soft_error_suppressed():
    top = "npm install -g LIMIT = 10\n"
    body = f"    {DIRECTIVE}\n    git push --force LIMIT = 11\n    console.log LIMIT"
    assert check(body, top) == [(4, "W200", w200(1))]


def test_microservice_whole_body_suppressed():
    # W204 inside the body and W102 on the name: both start inside the item.
    top = f"{DIRECTIVE}\nmicroservice tally(n) {{\n    n + 1\n    ship it n * 3\n}}\n"
    assert check('    console.log tally(4)', top) == [(2, "W200", w200(2))]


def test_hard_error_only():
    body = f"    {DIRECTIVE}\n    console.log ghost"
    assert codes(body) == ["W304", "E404"]
    assert check(body)[0] == (3, "W304", W304_HARD)


def test_nothing_to_suppress():
    body = f'    {DIRECTIVE}\n    console.log "fine"'
    assert check(body) == [(3, "W304", W304_NOTHING)]


# Targets


def test_directive_span_is_the_comment():
    src = f"i use arch btw\nserve localhost:3000 {{\n    {DIRECTIVE}\n    console.log 1\n}}\n:wq\n"
    _, _, diags = driver.check(src, "test.btw")
    assert [d.span for d in diags] == [Span(Pos(2, 4), Pos(2, 4 + len(DIRECTIVE)))]
    assert diags[0].severity is Severity.WARNING and diags[0].soft


def test_skips_blank_lines_and_comments():
    top = "npm install -g LIMIT = 10\n"
    body = f"    {DIRECTIVE}\n\n    // TODO later\n\n    git push --force LIMIT = 11"
    assert codes(body, top) == ["W200"]


def test_only_the_next_statement():
    top = "npm install -g LIMIT = 10\n"
    body = f"    {DIRECTIVE}\n    console.log 1\n    git push --force LIMIT = 11"
    assert check(body, top) == [(4, "W304", W304_NOTHING), (6, "E403", E403)]


def test_statement_in_nested_block():
    top = "npm install -g LIMIT = 10\n"
    body = (
        "    vibe check LGTM {\n"
        "        doomscroll LGTM {\n"
        f"            {DIRECTIVE}\n"
        "            git push --force LIMIT = 11\n"
        "            touch grass\n"
        "        }\n"
        "    }"
    )
    assert check(body, top) == [(6, "W200", w200(1))]


def test_statement_in_else_branch():
    top = "npm install -g LIMIT = 10\n"
    body = (
        "    vibe check LGTM {\n"
        "        console.log 1\n"
        "    } skill issue vibe check 404 {\n"
        "        console.log 2\n"
        "    } skill issue {\n"
        f"        {DIRECTIVE}\n"
        "        git push --force LIMIT = 11\n"
        "    }"
    )
    assert codes(body, top) == ["W200"]


def test_compound_statement_covers_its_body():
    top = "npm install -g LIMIT = 10\n"
    body = (
        f"    {DIRECTIVE}\n"
        "    vibe check LGTM {\n"
        "        git push --force LIMIT = 11\n"
        "        git push --force LIMIT = 12\n"
        "    }"
    )
    assert check(body, top) == [(4, "W200", w200(2))]


def test_big_o_underclaim_suppressed():
    top = (
        f"{DIRECTIVE}\n"
        "microservice f(n) O(1) {\n"
        "    npm install i = 0\n"
        "    doomscroll i < n {\n"
        "        git push --force i = i + 1\n"
        "    }\n"
        "    ship it i\n"
        "}\n"
    )
    assert codes("    console.log f(3)", top) == ["W200"]


def test_global_item():
    top = f"{DIRECTIVE}\nnpm install -g X = 1\n"
    assert check("    console.log X", top) == [(2, "W304", W304_NOTHING)]


def test_serve_item():
    top = f"npm install -g LIMIT = 10\n{DIRECTIVE}\n"
    assert codes("    git push --force LIMIT = 11", top) == ["W200"]


# Hard errors and E429


def test_hard_errors_stay_beside_suppressed_soft_ones():
    top = "npm install -g LIMIT = 10\n"
    body = f"    {DIRECTIVE}\n    git push --force LIMIT = ghost"
    assert codes(body, top) == ["W200", "E404"]


def test_e429_not_suppressed():
    # Marked soft on purpose: E429 stays even if a component gets `soft` wrong.
    e429 = Diagnostic("E429", Severity.ERROR, E429, Span(Pos(3, 4), Pos(3, 11)), soft=True)
    src = f"i use arch btw\nserve localhost:3000 {{\n    {DIRECTIVE}\n    console.log 1\n}}\n:wq\n"
    program, _ = driver.parse(src)
    out = apply(program, [e429])
    assert out[0] is e429
    assert [(d.code, d.message) for d in out[1:]] == [("W304", W304_HARD)]


def test_e429_in_target_from_the_checker():
    todos = "".join(f"    // TODO {i}\n" for i in range(6))
    body = f"    {DIRECTIVE}\n    vibe check LGTM {{\n{todos}        console.log 1\n    }}"
    found = check(body)
    assert [c for _, c, _ in found] == ["W304", "E429"]
    assert found[0][2] == W304_HARD


# Defaults where Language Spec 9.5 is silent (NOTES-suppress.md)


def test_no_following_statement_is_nothing_to_suppress():
    src = f"i use arch btw\nserve localhost:3000 {{\n    console.log 1\n}}\n{DIRECTIVE}\n:wq\n"
    _, _, diags = driver.check(src, "test.btw")
    assert [(d.span.start.line, d.code, d.message) for d in diags] == [(4, "W304", W304_NOTHING)]


def test_last_line_of_a_block_targets_the_next_statement_outside():
    top = "npm install -g LIMIT = 10\n"
    body = (
        "    vibe check LGTM {\n"
        "        git push --force LIMIT = 11\n"
        f"        {DIRECTIVE}\n"
        "    }\n"
        "    git push --force LIMIT = 12"
    )
    assert check(body, top) == [
        (5, "E403", E403),
        (6, "W200", w200(1)),
    ]


def test_two_directives_on_one_target():
    top = "npm install -g LIMIT = 10\n"
    body = f"    {DIRECTIVE}\n    {DIRECTIVE}\n    git push --force LIMIT = 11"
    assert check(body, top) == [(4, "W200", w200(1)), (5, "W304", W304_NOTHING)]


def test_outer_directive_takes_what_an_inner_one_would():
    top = "npm install -g LIMIT = 10\n"
    body = (
        f"    {DIRECTIVE}\n"
        "    doomscroll LGTM {\n"
        f"        {DIRECTIVE}\n"
        "        git push --force LIMIT = 11\n"
        "        touch grass\n"
        "    }"
    )
    assert check(body, top) == [(4, "W200", w200(1)), (6, "W304", W304_NOTHING)]


def test_directive_warnings_are_never_suppressed():
    # The inner directive's W304 starts inside the outer directive's target.
    body = (
        f"    {DIRECTIVE}\n"
        "    doomscroll LGTM {\n"
        f"        {DIRECTIVE}\n"
        "        touch grass\n"
        "    }"
    )
    assert codes(body) == ["W304", "W304"]
