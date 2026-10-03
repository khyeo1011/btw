"""AST nodes (Implementation Spec 4.4).

Every node has a keyword-only `span`, so node fields stay positional:
`IntLit(42, span=s)`. The checker fills `ty` on expressions and `sym` on
Var, Call and Ident.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from btw.span import Span

if TYPE_CHECKING:
    from btw.tokens import Comment


class Type(Enum):
    """Implementation Spec 4.5. UNKNOWN never produces a type error."""

    NUMBER = "number"
    BOOLEAN = "boolean"
    STRING = "string"
    UNKNOWN = "unknown"


@dataclass
class Node:
    span: Span = field(kw_only=True)


@dataclass
class Expr(Node):
    ty: Type | None = field(default=None, kw_only=True)


# Names


@dataclass
class Ident(Node):
    """A name at a declaration site, or the callee of a Call."""

    name: str
    sym: object | None = field(default=None, kw_only=True)  # checker Symbol


# Expressions


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class StrLit(Expr):
    value: str  # already unescaped


@dataclass
class Var(Expr):
    name: str
    sym: object | None = field(default=None, kw_only=True)  # checker Symbol


@dataclass
class Unary(Expr):
    op: str  # "!" or "-"
    operand: Expr


@dataclass
class Binary(Expr):
    op: str  # "+", "==", "&&", ...
    left: Expr
    right: Expr


@dataclass
class Call(Expr):
    """Pipes desugar into Call and Print."""

    callee: Ident
    args: list[Expr]
    sym: object | None = field(default=None, kw_only=True)  # checker Symbol


@dataclass
class ErrorExpr(Expr):
    """Parser placeholder for a missing or broken expression."""


# Statements


@dataclass
class Block(Node):
    stmts: list[Stmt]


@dataclass
class VarDecl(Node):
    name: Ident
    is_const: bool  # true inside a block is E405, reported by the checker
    value: Expr


@dataclass
class Assign(Node):
    name: Var
    value: Expr
    sudo: bool


@dataclass
class If(Node):
    cond: Expr
    then: Block
    else_: Block | If | None


@dataclass
class While(Node):
    cond: Expr
    body: Block


@dataclass
class Break(Node):
    pass


@dataclass
class Return(Node):
    value: Expr | None


@dataclass
class Print(Node):
    value: Expr


@dataclass
class Revert(Node):
    """P2."""

    name: Var
    sudo: bool


@dataclass
class Log(Node):
    """P2."""

    name: Var


@dataclass
class ExprStmt(Node):
    expr: Expr


type Stmt = VarDecl | Assign | If | While | Break | Return | Print | Revert | Log | ExprStmt


# Top level


@dataclass
class GlobalDecl(Node):
    name: Ident
    is_const: bool
    value: Expr


@dataclass
class BigO(Node):
    degree: int | None  # None means unverifiable
    var: str | None  # "n" in O(n²); None for O(1)
    text: str  # raw source between the parens


@dataclass
class Microservice(Node):
    name: Ident
    params: list[Ident]
    big_o: BigO | None
    body: Block


@dataclass
class Serve(Node):
    port: int
    body: Block


type Item = GlobalDecl | Microservice | Serve


@dataclass
class Program(Node):
    items: list[Item]
    has_arch: bool
    wq_span: Span | None  # None when `:wq` is missing (E408)
    trailing_span: Span | None  # everything after `:wq`, for E410
    comments: list[Comment]
