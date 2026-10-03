"""Tokens and comments (Implementation Spec 4.3)."""

from dataclasses import dataclass
from enum import Enum, auto

from btw.span import Span


class TokenKind(Enum):
    # keywords
    ARCH = auto()
    SERVE = auto()
    LOCALHOST = auto()
    WQ = auto()
    NPM_INSTALL_G = auto()
    NPM_INSTALL = auto()
    SUDO = auto()
    GIT_PUSH_FORCE = auto()
    GIT_PUSH_NO_FORCE = auto()
    GIT_REVERT = auto()
    GIT_LOG = auto()
    CONSOLE_LOG = auto()
    VIBE_CHECK = auto()
    SKILL_ISSUE = auto()
    DOOMSCROLL = auto()
    TOUCH_GRASS = auto()
    MICROSERVICE = auto()
    SHIP_IT = auto()
    LGTM = auto()
    NOT_FOUND = auto()
    # values
    IDENT = auto()
    INT = auto()
    STRING = auto()
    # operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    EQ_EQ = auto()
    BANG_EQ = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    AND_AND = auto()
    OR_OR = auto()
    BANG = auto()
    EQ = auto()
    PIPE = auto()
    CARET = auto()
    # punctuation
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    # structure
    NEWLINE = auto()
    EOF = auto()
    ERROR = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str  # the raw lexeme
    span: Span
    value: int | str | None = None  # INT: the number, LOCALHOST: the port, STRING: unescaped text


class CommentKind(Enum):
    TODO = "TODO"
    WOMM = "WOMM"  # // works on my machine
    BAD = "BAD"  # anything else: E406, reported by the checker


@dataclass(frozen=True)
class Comment:
    kind: CommentKind
    text: str  # from `//` to the end of the line, newline excluded
    span: Span
