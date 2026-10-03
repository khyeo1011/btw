"""Hover text (Language Spec 12)."""

from btw import hovers
from btw.span import Pos

SOURCE = """\
i use arch btw
npm install -g LIMIT = 10
npm install count = 0
// TODO one
// TODO two
microservice total(n) O(n) {
    npm install x = 0
    doomscroll x < n { git push --force x = x + 1 }
    ship it x
}
microservice square(n) O(n) {
    npm install i = 0
    doomscroll i < n { npm install j = 0
        doomscroll j < n { git push --force j = j + 1 }
        git push --force i = i + 1 }
    ship it i
}
microservice slow(n) O(n^2) { ship it n }
microservice loop(n) { ship it loop(n) }
microservice fuzzy(n) O(log n) { ship it n }
serve localhost:3000 {
    npm install ok = LGTM
    console.log total(LIMIT) + square(2) + slow(1) + loop(1) + fuzzy(1)
    console.log ok
}
:wq
"""


def text_at(line: int, word: str, offset: int = 0, source: str = SOURCE) -> str | None:
    """The hover text on the first `word` of a 1-based line."""
    col = source.split("\n")[line - 1].index(word) + offset
    found = hovers.hover(source, Pos(line - 1, col))
    return None if found is None else found[0]


def test_keywords():
    assert text_at(1, "arch") == hovers.ARCH
    assert text_at(8, "doomscroll") == (
        "**while.** Keeps going while the condition holds. Or forever. Mostly forever."
    )
    assert text_at(8, "push") == hovers.KEYWORDS[hovers.K.GIT_PUSH_FORCE]
    assert text_at(21, "localhost") == text_at(21, "serve") == hovers.SERVE
    assert text_at(22, "LGTM") == "**true.** Approved without reading."
    assert text_at(26, ":wq") == "**End of program.** The only known way out."


def test_keyword_span_is_the_whole_token():
    _, span = hovers.hover(SOURCE, Pos(7, 6))
    assert (span.start, span.end) == (Pos(7, 4), Pos(7, 14))


def test_todo_counts_the_whole_file():
    assert text_at(4, "TODO") == (
        "**Comment.** The only kind allowed. Technical debt: 2/5 TODOs used."
    )


def test_variables():
    assert text_at(3, "count") == "`npm install count` · number · declared on line 3"
    assert text_at(8, "x") == "`npm install x` · number · declared on line 7"
    assert text_at(24, "ok") == "`npm install ok` · boolean · declared on line 22"


def test_constant():
    assert text_at(23, "LIMIT") == (
        "`npm install -g LIMIT` · number · global install, modifying it needs `sudo`"
    )


def test_parameter():
    assert text_at(8, "n {") == "parameter `n` of `total` · number"


def test_microservice_verdicts():
    assert text_at(6, "total") == "`microservice total(n)` · SLA O(n) · inferred O(n) ✓"
    assert text_at(23, "total") == text_at(6, "total")
    assert text_at(11, "square") == "`microservice square(n)` · SLA O(n) · inferred O(n²) ✗"
    assert text_at(18, "slow") == "`microservice slow(n)` · SLA O(n²) · inferred O(1) ✗"
    assert text_at(19, "loop") == (
        "`microservice loop(n)` · no SLA · I had to read your code to find out it's O(?). "
        "Write an SLA."
    )
    assert text_at(20, "fuzzy") == "`microservice fuzzy(n)` · SLA O(log n) · inferred O(1)"


def test_microservice_without_sla_gets_taunted():
    source = """\
i use arch btw
microservice count(n) {
    npm install i = 0
    doomscroll i < n { git push --force i = i + 1 }
    ship it i
}
serve localhost:3000 {
    console.log count(3)
}
:wq
"""
    assert text_at(2, "count", source=source) == (
        "`microservice count(n)` · no SLA · I had to read your code to find out it's O(n). "
        "Write an SLA."
    )


def test_big_o_annotation():
    prefix = "**SLA.** Checked by counting nested doomscrolls. Verdict: "
    assert text_at(6, "O(n)") == prefix + "Correct! Are you an arch user as well?"
    assert text_at(11, "O(n)", 2) == prefix + "Go take a DSA course again."  # under-claim
    assert text_at(18, "O(n^2)") == prefix + "Go take a DSA course again."  # over-claim
    assert text_at(20, "O(log") == prefix + "can't verify O(log n). Inferred: O(1)."


def test_nothing_to_say():
    assert text_at(2, "10") is None
    assert text_at(5, "two") == text_at(4, "one")
    assert hovers.hover(SOURCE, Pos(0, 40)) is None


def test_broken_program_still_hovers():
    source = "serve localhost:3000 {\n    doomscroll LGTM {\n"
    assert text_at(2, "doomscroll", source=source) == hovers.KEYWORDS[hovers.K.DOOMSCROLL]
