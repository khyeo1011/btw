"""The lexer (Implementation Spec 5, Language Spec 2).

`lex(source)` returns `(tokens, comments, diagnostics)` and never raises.
"""

import json
from dataclasses import dataclass, field

from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span
from btw.tokens import Comment, CommentKind, Token, TokenKind as K

INT_MAX = 9223372036854775807

# Multi-word keywords (plus `console.log`), longest first where they share a prefix.
KEYWORDS: list[tuple[K, tuple[str, ...]]] = [
    (K.ARCH, ("i", "use", "arch", "btw")),
    (K.NPM_INSTALL_G, ("npm", "install", "-g")),
    (K.NPM_INSTALL, ("npm", "install")),
    (K.GIT_PUSH_FORCE, ("git", "push", "--force")),
    (K.GIT_PUSH_NO_FORCE, ("git", "push")),
    (K.GIT_REVERT, ("git", "revert")),
    (K.GIT_LOG, ("git", "log")),
    (K.CONSOLE_LOG, ("console.log",)),
    (K.VIBE_CHECK, ("vibe", "check")),
    (K.SKILL_ISSUE, ("skill", "issue")),
    (K.TOUCH_GRASS, ("touch", "grass")),
    (K.SHIP_IT, ("ship", "it")),
]

# Single-word keywords, checked after an identifier is scanned.
WORDS = {
    "serve": K.SERVE,
    "sudo": K.SUDO,
    "doomscroll": K.DOOMSCROLL,
    "microservice": K.MICROSERVICE,
    "LGTM": K.LGTM,
}

# Longest first, so `==` wins over `=`.
OPERATORS: list[tuple[str, K]] = [
    ("==", K.EQ_EQ),
    ("!=", K.BANG_EQ),
    ("<=", K.LE),
    (">=", K.GE),
    ("&&", K.AND_AND),
    ("||", K.OR_OR),
    ("+", K.PLUS),
    ("-", K.MINUS),
    ("*", K.STAR),
    ("/", K.SLASH),
    ("%", K.PERCENT),
    ("<", K.LT),
    (">", K.GT),
    ("!", K.BANG),
    ("=", K.EQ),
    ("|", K.PIPE),
    ("^", K.CARET),
    ("(", K.LPAREN),
    (")", K.RPAREN),
    ("{", K.LBRACE),
    ("}", K.RBRACE),
    (",", K.COMMA),
]

ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

# Roast tokens (Language Spec 13): habits from other languages. Each becomes
# one ERROR token with its E400, tried before the operators so `===` isn't
# `==` then `=`. None of them can start a valid token sequence.
ROASTS: list[tuple[str, str]] = [
    ("===", "This isn't JavaScript. Use `==`."),
    ("++", "We don't do that here. Use `git push --force i = i + 1`."),
    (";", "Semicolons are deprecated. This is a modern language."),
]


def is_ident_start(c: str) -> bool:
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def is_ident_char(c: str) -> bool:
    return is_ident_start(c) or ("0" <= c <= "9")


def utf16_len(s: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def match_keyword(src: str, i: int) -> tuple[K, int] | None:
    """Match a multi-word keyword starting at src[i].

    Returns the kind and the index just past the keyword's last character,
    or None when no keyword matches here.
    """
    for kind, words in KEYWORDS:
        j = i
        for n, word in enumerate(words):
            if n > 0:
                # At least one space or tab between words, never a newline.
                k = j
                while k < len(src) and src[k] in " \t":
                    k += 1
                if k == j:
                    break
                j = k
            if not src.startswith(word, j):
                break
            j += len(word)
        else:
            if j == len(src) or not is_ident_char(src[j]):
                return kind, j
    return None


@dataclass
class StringScan:
    end: int  # index just past the closing quote, or of the newline / end of file
    value: str  # the unescaped content
    bad_escapes: list[int] = field(default_factory=list)  # index of each bad escape's backslash
    terminated: bool = True


def scan_string(src: str, i: int) -> StringScan:
    """Scan a string literal whose opening quote is src[i]."""
    j = i + 1
    out: list[str] = []
    bad: list[int] = []
    while j < len(src) and src[j] not in "\r\n":
        c = src[j]
        if c == '"':
            return StringScan(j + 1, "".join(out), bad)
        if c == "\\" and j + 1 < len(src) and src[j + 1] not in "\r\n":
            if src[j + 1] in ESCAPES:
                out.append(ESCAPES[src[j + 1]])
            else:
                bad.append(j)
            j += 2
            continue
        out.append(c)  # a backslash right before the end of the line is kept as is
        j += 1
    return StringScan(j, "".join(out), bad, terminated=False)


class _Lexer:
    def __init__(self, src: str):
        self.src = src
        self.i = 0
        self.line = 0
        self.col = 0
        self.depth = 0  # paren depth: NEWLINE is suppressed while it's above 0
        self.tokens: list[Token] = []
        self.comments: list[Comment] = []
        self.diags: list[Diagnostic] = []

    def pos(self) -> Pos:
        return Pos(self.line, self.col)

    def pos_at(self, j: int) -> Pos:
        """Position of src[j], which must be on the current line at or after self.i."""
        return Pos(self.line, self.col + utf16_len(self.src[self.i : j]))

    def error(self, message: str, span: Span) -> None:
        self.diags.append(Diagnostic("E400", Severity.ERROR, message, span))

    def emit(self, kind: K, end: int, value: int | str | None = None) -> Token:
        """Emit src[self.i:end] as one token (it must not contain a newline) and move past it."""
        start, stop = self.pos(), self.pos_at(end)
        tok = Token(kind, self.src[self.i : end], Span(start, stop), value)
        self.tokens.append(tok)
        self.i, self.col = end, stop.col
        return tok

    def run(self) -> None:
        src = self.src
        if src.startswith("﻿"):
            self.i = 1  # the byte-order mark takes no column
        while self.i < len(src):
            self.step()
        self.tokens.append(Token(K.EOF, "", Span(self.pos(), self.pos())))

    def step(self) -> None:
        src, i = self.src, self.i
        c = src[i]

        if c in " \t":
            self.i, self.col = i + 1, self.col + 1
            return

        if c in "\r\n":
            end = i + 2 if src.startswith("\r\n", i) else i + 1
            if self.depth == 0:
                self.emit(K.NEWLINE, end)
            self.i, self.line, self.col = end, self.line + 1, 0
            return

        if src.startswith("//", i):
            self.comment()
            return

        if kw := match_keyword(src, i):
            kind, end = kw
            tok = self.emit(kind, end)
            if kind is K.GIT_PUSH_NO_FORCE:
                self.error(
                    "Updates were rejected because the tip of your current branch is behind. "
                    "Use `git push --force`.",
                    tok.span,
                )
            return

        if src.startswith("localhost:", i):
            end = i + len("localhost:")
            while end < len(src) and src[end].isascii() and src[end].isdigit():
                end += 1
            if end > i + len("localhost:"):
                self.emit(K.LOCALHOST, end, int(src[i + len("localhost:") : end]))
                return

        if src.startswith(":wq", i):
            self.emit(K.WQ, i + 3)
            return

        if "0" <= c <= "9":
            self.number()
            return

        if c == '"':
            self.string()
            return

        if is_ident_start(c):
            end = i + 1
            while end < len(src) and is_ident_char(src[end]):
                end += 1
            self.emit(WORDS.get(src[i:end], K.IDENT), end)
            return

        for text, message in ROASTS:
            if src.startswith(text, i):
                tok = self.emit(K.ERROR, i + len(text))
                self.error(message, tok.span)
                return

        for op, kind in OPERATORS:
            if src.startswith(op, i):
                self.emit(kind, i + len(op))
                if kind is K.LPAREN:
                    self.depth += 1
                elif kind is K.RPAREN:
                    self.depth = max(0, self.depth - 1)
                return

        tok = self.emit(K.ERROR, i + 1)
        self.error(f"Unexpected character `{c}`.", tok.span)

    def comment(self) -> None:
        src, i = self.src, self.i
        end = i
        while end < len(src) and src[end] not in "\r\n":
            end += 1
        text = src[i:end]
        body = text[2:].lstrip(" \t")
        if body.startswith("TODO"):
            kind = CommentKind.TODO
        elif body.lower().startswith("works on my machine"):
            kind = CommentKind.WOMM
        else:
            kind = CommentKind.BAD
        stop = self.pos_at(end)
        self.comments.append(Comment(kind, text, Span(self.pos(), stop)))
        self.i, self.col = end, stop.col

    def number(self) -> None:
        src, i = self.src, self.i
        end = i
        while end < len(src) and "0" <= src[end] <= "9":
            end += 1
        text = src[i:end]
        if text == "404":
            self.emit(K.NOT_FOUND, end)
            return
        value = int(text)
        tok = self.emit(K.INT, end, value)
        if len(text) > 1 and text[0] == "0":
            self.error("Leading zeros? This isn't octal, James Bond.", tok.span)
        elif value > INT_MAX:
            self.diags.append(
                Diagnostic(
                    "E413",
                    Severity.ERROR,
                    "Error: number too large. This isn't JavaScript, there's no BigInt here.",
                    tok.span,
                )
            )

    def string(self) -> None:
        scan = scan_string(self.src, self.i)
        start = self.i
        for b in scan.bad_escapes:
            esc_end = min(b + 2, scan.end)
            self.error(
                f"Syntax error: unknown escape `{self.src[b:esc_end]}`.",
                Span(self.pos_at(b), self.pos_at(esc_end)),
            )
        tok = self.emit(K.STRING, scan.end, scan.value)
        if not scan.terminated:
            self.error("Unterminated string. Like your side projects.", tok.span)
        assert start < self.i  # always progress


def lex(source: str) -> tuple[list[Token], list[Comment], list[Diagnostic]]:
    lx = _Lexer(source)
    try:
        lx.run()
    except Exception:
        # Never raise: report an internal error and end the stream where we stopped.
        lx.diags.append(
            Diagnostic(
                "E500",
                Severity.ERROR,
                "It works on my machine. Unfortunately, this is not my machine.",
                Span(Pos(0, 0), Pos(0, 0)),
            )
        )
        if not lx.tokens or lx.tokens[-1].kind is not K.EOF:
            lx.tokens.append(Token(K.EOF, "", Span(lx.pos(), lx.pos())))
    return lx.tokens, lx.comments, lx.diags


def format_tokens(tokens: list[Token]) -> str:
    """One token per line: kind, text, line:col (1-based, as the CLI prints positions)."""
    lines = []
    for t in tokens:
        text = json.dumps(t.text, ensure_ascii=False)
        lines.append(f"{t.kind.name:<17} {text} {t.span.start.line + 1}:{t.span.start.col + 1}")
    return "\n".join(lines) + "\n"
