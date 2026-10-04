import re
from pathlib import Path

import pytest

from btw.lexer import format_tokens, lex
from btw.span import Pos, Span
from btw.tokens import CommentKind, TokenKind as K

GOLDEN = Path(__file__).parent / "golden"


def toks(src):
    tokens, _, _ = lex(src)
    assert tokens[-1].kind is K.EOF
    return tokens[:-1]


def kinds(src):
    return [t.kind for t in toks(src)]


def codes(src):
    return [d.code for d in lex(src)[2]]


# Multi-word keywords


@pytest.mark.parametrize(
    "src, kind",
    [
        ("i use arch btw", K.ARCH),
        ("i   use\tarch \t btw", K.ARCH),
        ("npm install", K.NPM_INSTALL),
        ("npm \t  install", K.NPM_INSTALL),
        ("npm install -g", K.NPM_INSTALL_G),
        ("npm\tinstall\t\t-g", K.NPM_INSTALL_G),
        ("git push --force", K.GIT_PUSH_FORCE),
        ("git    push   --force", K.GIT_PUSH_FORCE),
        ("git revert", K.GIT_REVERT),
        ("git log", K.GIT_LOG),
        ("git  blame", K.GIT_BLAME),
        ("console.log", K.CONSOLE_LOG),
        ("vibe  check", K.VIBE_CHECK),
        ("skill\tissue", K.SKILL_ISSUE),
        ("touch grass", K.TOUCH_GRASS),
        ("ship   it", K.SHIP_IT),
    ],
)
def test_multi_word_keyword(src, kind):
    tokens = toks(src)
    assert [t.kind for t in tokens] == [kind]
    assert tokens[0].text == src
    assert tokens[0].span == Span(Pos(0, 0), Pos(0, len(src)))


def test_multi_word_keyword_does_not_cross_newline():
    assert kinds("vibe\ncheck") == [K.IDENT, K.NEWLINE, K.IDENT]


@pytest.mark.parametrize(
    "src, expected",
    [
        ("doomscrolling", [K.IDENT]),
        ("doomscroll", [K.DOOMSCROLL]),
        ("shipit", [K.IDENT]),
        ("npm_install", [K.IDENT]),
        ("ship itself", [K.IDENT, K.IDENT]),
        ("touch grassy", [K.IDENT, K.IDENT]),
        ("serve2", [K.IDENT]),
        ("LGTM", [K.LGTM]),
        ("lgtm", [K.IDENT]),
        ("sudo", [K.SUDO]),
        ("microservice", [K.MICROSERVICE]),
        ("O", [K.IDENT]),
        ("curl", [K.CURL]),
        ("curly", [K.IDENT]),
    ],
)
def test_word_boundaries(src, expected):
    assert kinds(src) == expected


def test_i_as_identifier():
    tokens = toks("npm install i = 1")
    assert [t.kind for t in tokens] == [K.NPM_INSTALL, K.IDENT, K.EQ, K.INT]
    assert tokens[1].text == "i"
    assert kinds("i use arch btw") == [K.ARCH]
    assert kinds("i use") == [K.IDENT, K.IDENT]


def test_git_push_without_force():
    tokens, _, diags = lex("git push x = 1")
    assert [t.kind for t in tokens[:-1]] == [K.GIT_PUSH_NO_FORCE, K.IDENT, K.EQ, K.INT]
    assert [d.code for d in diags] == ["E400"]
    assert diags[0].message == (
        "Updates were rejected because the tip of your current branch is behind. "
        "Use `git push --force`."
    )
    assert diags[0].span == tokens[0].span


def test_git_push_force_needs_boundary():
    assert kinds("git push --forced") == [K.GIT_PUSH_NO_FORCE, K.MINUS, K.MINUS, K.IDENT]


# Numbers


def test_404():
    tokens = toks("404")
    assert [t.kind for t in tokens] == [K.NOT_FOUND]
    assert tokens[0].value is None


@pytest.mark.parametrize("src, value", [("4040", 4040), ("1404", 1404), ("0", 0), ("403", 403)])
def test_ints(src, value):
    tokens = toks(src)
    assert [t.kind for t in tokens] == [K.INT]
    assert tokens[0].value == value
    assert codes(src) == []


@pytest.mark.parametrize("src", ["007", "00", "0404"])
def test_leading_zeros(src):
    tokens, _, diags = lex(src)
    assert tokens[0].kind is K.INT
    assert [d.code for d in diags] == ["E400"]
    assert diags[0].message == "Leading zeros? This isn't octal, James Bond."


def test_largest_number():
    tokens = toks("9223372036854775807")
    assert tokens[0].value == 9223372036854775807
    assert codes("9223372036854775807") == []


@pytest.mark.parametrize("src", ["9223372036854775808", "99999999999999999999999"])
def test_number_too_large(src):
    tokens, _, diags = lex(src)
    assert tokens[0].kind is K.INT
    assert [d.code for d in diags] == ["E413"]
    assert diags[0].message == "Error: number too large. This isn't JavaScript, there's no BigInt here."
    assert diags[0].span == tokens[0].span


# localhost and :wq


def test_localhost():
    tokens = toks("serve localhost:3000 {")
    assert [t.kind for t in tokens] == [K.SERVE, K.LOCALHOST, K.LBRACE]
    assert tokens[1].text == "localhost:3000"
    assert tokens[1].value == 3000
    assert tokens[1].span == Span(Pos(0, 6), Pos(0, 20))


def test_localhost_other_port():
    assert toks("localhost:8080")[0].value == 8080


def test_localhost_without_port():
    assert kinds("localhost") == [K.IDENT]
    assert kinds("localhost:") == [K.IDENT, K.ERROR]


def test_wq():
    tokens = toks(":wq")
    assert [t.kind for t in tokens] == [K.WQ]
    assert tokens[0].span == Span(Pos(0, 0), Pos(0, 3))


# Operators


@pytest.mark.parametrize(
    "src, expected",
    [
        ("||", [K.OR_OR]),
        ("|", [K.PIPE]),
        ("|||", [K.OR_OR, K.PIPE]),
        ("<=", [K.LE]),
        ("<", [K.LT]),
        ("< =", [K.LT, K.EQ]),
        (">=", [K.GE]),
        (">", [K.GT]),
        ("==", [K.EQ_EQ]),
        ("=", [K.EQ]),
        ("== =", [K.EQ_EQ, K.EQ]),
        ("+ +", [K.PLUS, K.PLUS]),
        ("!=", [K.BANG_EQ]),
        ("!", [K.BANG]),
        ("!x", [K.BANG, K.IDENT]),
        ("&&", [K.AND_AND]),
        ("+-*/%^", [K.PLUS, K.MINUS, K.STAR, K.SLASH, K.PERCENT, K.CARET]),
        ("(){},", [K.LPAREN, K.RPAREN, K.LBRACE, K.RBRACE, K.COMMA]),
        ("/*", [K.SLASH, K.STAR]),
    ],
)
def test_operators(src, expected):
    assert kinds(src) == expected


@pytest.mark.parametrize("c", ["@", "&", ".", "é"])
def test_unexpected_character(c):
    tokens, _, diags = lex(f"x {c} y")
    assert [t.kind for t in tokens[:-1]] == [K.IDENT, K.ERROR, K.IDENT]
    assert [d.code for d in diags] == ["E400"]
    assert diags[0].message == f"Unexpected character `{c}`."
    assert diags[0].span == Span(Pos(0, 2), Pos(0, 3))



@pytest.mark.parametrize(
    "text, message",
    [
        ("===", "This isn't JavaScript. Use `==`."),
        ("++", "We don't do that here. Use `git push --force i = i + 1`."),
        (";", "Semicolons are deprecated. This is a modern language."),
    ],
)
def test_roast_tokens(text, message):
    tokens, _, diags = lex(f"x {text} y")
    assert [t.kind for t in tokens[:-1]] == [K.IDENT, K.ERROR, K.IDENT]
    assert tokens[1].text == text
    assert [(d.code, d.message) for d in diags] == [("E400", message)]
    assert diags[0].span == Span(Pos(0, 2), Pos(0, 2 + len(text)))


@pytest.mark.parametrize(
    "src, expected",
    [
        ("i++", [K.IDENT, K.ERROR]),
        ("a====b", [K.IDENT, K.ERROR, K.EQ, K.IDENT]),
        ("+++", [K.ERROR, K.PLUS]),
        ("x;;", [K.IDENT, K.ERROR, K.ERROR]),
        ("a !== b", [K.IDENT, K.BANG_EQ, K.EQ, K.IDENT]),
        ('";"', [K.STRING]),
        ("// ;", []),
    ],
)
def test_roast_tokens_in_context(src, expected):
    assert kinds(src) == expected


# Comments


@pytest.mark.parametrize(
    "src, kind",
    [
        ("// TODO fix this", CommentKind.TODO),
        ("//TODO", CommentKind.TODO),
        ("//   \tTODO: later", CommentKind.TODO),
        ("// todo", CommentKind.BAD),
        ("// Todo", CommentKind.BAD),
        ("// works on my machine", CommentKind.WOMM),
        ("//works on my machine", CommentKind.WOMM),
        ("// Works On My Machine, trust me", CommentKind.WOMM),
        ("// this adds one", CommentKind.BAD),
        ("//", CommentKind.BAD),
    ],
)
def test_comment_kinds(src, kind):
    tokens, comments, diags = lex(src)
    assert [t.kind for t in tokens] == [K.EOF]
    assert [c.kind for c in comments] == [kind]
    assert comments[0].text == src
    assert comments[0].span == Span(Pos(0, 0), Pos(0, len(src)))
    assert diags == []  # E406 is the checker's job


def test_comment_after_code():
    tokens, comments, _ = lex("x = 1 // TODO\ny")
    assert [t.kind for t in tokens] == [K.IDENT, K.EQ, K.INT, K.NEWLINE, K.IDENT, K.EOF]
    assert comments[0].span == Span(Pos(0, 6), Pos(0, 13))


# Strings


def test_string():
    tokens, _, diags = lex('console.log "Fizz"')
    assert [t.kind for t in tokens[:-1]] == [K.CONSOLE_LOG, K.STRING]
    assert tokens[1].text == '"Fizz"'
    assert tokens[1].value == "Fizz"
    assert tokens[1].span == Span(Pos(0, 12), Pos(0, 18))
    assert diags == []


def test_string_escapes():
    tokens, _, diags = lex(r'"a\nb\tc\"d\\e"')
    assert tokens[0].kind is K.STRING
    assert tokens[0].value == 'a\nb\tc"d\\e'
    assert diags == []


def test_bad_escape():
    tokens, _, diags = lex(r'"a\qb" x')
    assert [t.kind for t in tokens[:-1]] == [K.STRING, K.IDENT]
    assert tokens[0].text == r'"a\qb"'
    assert [d.code for d in diags] == ["E400"]
    assert diags[0].span == Span(Pos(0, 2), Pos(0, 4))


def test_unterminated_string():
    tokens, _, diags = lex('console.log "oops\nx')
    assert [t.kind for t in tokens[:-1]] == [K.CONSOLE_LOG, K.STRING, K.NEWLINE, K.IDENT]
    assert tokens[1].text == '"oops'
    assert tokens[1].value == "oops"
    assert [d.code for d in diags] == ["E400"]
    assert diags[0].message == "Unterminated string. Like your side projects."
    assert diags[0].span == Span(Pos(0, 12), Pos(0, 17))


def test_unterminated_string_at_eof():
    tokens, _, diags = lex('"oops')
    assert [t.kind for t in tokens] == [K.STRING, K.EOF]
    assert tokens[0].value == "oops"
    assert [d.code for d in diags] == ["E400"]


def test_unterminated_string_crlf():
    tokens, _, _ = lex('"oops\r\nx')
    assert tokens[0].text == '"oops'
    assert [t.kind for t in tokens] == [K.STRING, K.NEWLINE, K.IDENT, K.EOF]


def test_escaped_quote_does_not_end_string():
    tokens, _, diags = lex(r'"say \"hi\""')
    assert [t.kind for t in tokens] == [K.STRING, K.EOF]
    assert tokens[0].value == 'say "hi"'
    assert diags == []


def test_comment_marker_inside_string():
    tokens, comments, _ = lex('"a // b"')
    assert tokens[0].value == "a // b"
    assert comments == []


# Newlines


def test_crlf():
    tokens = toks("x\r\ny\r\n")
    assert [t.kind for t in tokens] == [K.IDENT, K.NEWLINE, K.IDENT, K.NEWLINE]
    assert tokens[1].text == "\r\n"
    assert tokens[2].span.start == Pos(1, 0)


def test_newline_suppressed_in_parens():
    assert kinds("f(a,\n  b\n)\nx") == [
        K.IDENT, K.LPAREN, K.IDENT, K.COMMA, K.IDENT, K.RPAREN, K.NEWLINE, K.IDENT,
    ]
    assert kinds("((\n)\n)\n") == [K.LPAREN, K.LPAREN, K.RPAREN, K.RPAREN, K.NEWLINE]


def test_stray_rparen_does_not_go_negative():
    assert kinds(")\n(\n)\n") == [K.RPAREN, K.NEWLINE, K.LPAREN, K.RPAREN, K.NEWLINE]


def test_blank_lines():
    assert kinds("\n\n") == [K.NEWLINE, K.NEWLINE]


def test_bom_skipped():
    tokens = toks("﻿i use arch btw")
    assert tokens[0].kind is K.ARCH
    assert tokens[0].span.start == Pos(0, 0)


# Positions


def test_positions():
    tokens = toks("i use arch btw\n\nserve localhost:3000 {\n\tconsole.log x\n}")
    by_text = {t.text: t.span for t in tokens if t.kind is not K.NEWLINE}
    assert by_text["serve"] == Span(Pos(2, 0), Pos(2, 5))
    assert by_text["console.log"] == Span(Pos(3, 1), Pos(3, 12))
    assert by_text["x"] == Span(Pos(3, 13), Pos(3, 14))
    assert by_text["}"] == Span(Pos(4, 0), Pos(4, 1))


def test_eof_position():
    tokens, _, _ = lex("x\n")
    assert tokens[-1].span == Span(Pos(1, 0), Pos(1, 0))


def test_positions_after_emoji_string():
    tokens = toks('console.log "😀" x')
    assert tokens[1].span == Span(Pos(0, 12), Pos(0, 16))  # the emoji is 2 UTF-16 units
    assert tokens[2].span == Span(Pos(0, 17), Pos(0, 18))


def test_positions_after_emoji_comment():
    tokens, comments, _ = lex("// TODO 🚀🚀\nx")
    assert comments[0].span == Span(Pos(0, 0), Pos(0, 12))
    assert tokens[0].span == Span(Pos(0, 12), Pos(0, 13))  # the NEWLINE
    assert tokens[1].span.start == Pos(1, 0)


def test_unexpected_emoji_is_two_units_wide():
    tokens = toks("🚀 x")
    assert tokens[0].kind is K.ERROR
    assert tokens[0].span == Span(Pos(0, 0), Pos(0, 2))
    assert tokens[1].span.start == Pos(0, 3)


# Robustness and output


@pytest.mark.parametrize("src", ["", '"', "\\", "\r", "//", "localhost:", '"\\', "\x00", "\ud800"])
def test_never_raises(src):
    tokens, _, diags = lex(src)
    assert tokens[-1].kind is K.EOF
    assert all(d.code != "E500" for d in diags)


def test_format_tokens():
    tokens, _, _ = lex('i use arch btw\nconsole.log "hi"')
    assert format_tokens(tokens) == (
        'ARCH              "i use arch btw" 1:1\n'
        'NEWLINE           "\\n" 1:15\n'
        'CONSOLE_LOG       "console.log" 2:1\n'
        'STRING            "\\"hi\\"" 2:13\n'
        'EOF               "" 2:17\n'
    )


# Golden corpus: ERROR tokens only where the .diag expects E400

GOLDEN_FILES = sorted(GOLDEN.glob("*.btw"))


@pytest.mark.skipif(not GOLDEN_FILES, reason="no tests/golden/*.btw yet")
@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_error_tokens(path):
    tokens, _, diags = lex(path.read_text(encoding="utf-8"))
    diag_file = path.with_suffix(".diag")
    expected = diag_file.read_text(encoding="utf-8") if diag_file.exists() else ""
    e400_at = {
        (int(m[1]), int(m[2]))
        for m in re.finditer(r"^(\d+):(\d+): error\[E400\]", expected, re.MULTILINE)
    }
    for t in tokens:
        if t.kind is K.ERROR:
            pos = (t.span.start.line + 1, t.span.start.col + 1)
            assert pos in e400_at, f"unexpected ERROR token {t.text!r} at {pos[0]}:{pos[1]}"
    expected_lines = expected.splitlines()
    for d in diags:
        line = f"{d.span.start.line + 1}:{d.span.start.col + 1}: error[{d.code}]: {d.message}"
        assert line in expected_lines, f"lexer reported {line!r}, not in {diag_file.name}"
