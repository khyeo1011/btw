"""Semantic checker (Implementation Spec 7, Language Spec 4 to 11).

`check(program, comments)` resolves every name, fills `sym` on Var, Call and
Ident nodes and `ty` on every expression, and returns `(symbols,
diagnostics)`. Big O (`bigo.py`) and suppression (`suppress.py`) are separate
passes that the driver runs afterwards.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from btw import ast
from btw.ast import Type
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span
from btw.tokens import Comment, CommentKind

MAX_PARAMS = 6
MAX_TODOS = 5


class SymbolKind(Enum):
    LOCAL = "local"
    PARAM = "param"
    GLOBAL = "global"
    CONST = "const"
    MICROSERVICE = "microservice"


@dataclass(eq=False)
class Symbol:
    """Implementation Spec 4.5. Compared and hashed by identity, so the interpreter
    and the codegen can key frames and slots by Symbol."""

    name: str
    kind: SymbolKind
    ty: Type
    decl_span: Span
    owner: str  # the microservice's name, "serve" or "global"
    arity: int | None = None  # microservices only
    tracked: bool = False  # used by `git revert` or `git log` (P2)
    slot: int | None = None  # filled in by the codegen

    @property
    def is_const(self) -> bool:
        return self.kind is SymbolKind.CONST


@dataclass
class Symbols:
    """Everything the checker declared.

    `globals` maps each top-level name (global, constant or microservice) to its
    symbol; a duplicate keeps the first one. `frames` maps each owner
    (`"serve"` or a microservice name) to its parameters and locals in
    declaration order, which is the codegen's slot order. `all` holds every
    symbol in the order the checker created it.
    """

    globals: dict[str, Symbol] = field(default_factory=dict)
    frames: dict[str, list[Symbol]] = field(default_factory=dict)
    all: list[Symbol] = field(default_factory=list)


# Messages (Language Spec 11)


def e404_variable(name: str) -> str:
    return f"Error 404: variable `{name}` not found. Did you forget to `npm install` it?"


def e404_microservice(name: str) -> str:
    return f"Error 404: microservice `{name}` not found. Did you forget to deploy it?"


def e409_installed(name: str) -> str:
    return f"npm ERR! `{name}` is already installed. Use `git push --force` to update it."


def e409_deployed(name: str) -> str:
    return f"Error: microservice `{name}` is already deployed."


def e405_microservice_value(name: str) -> str:
    return f"`{name}` is a microservice. Call it: `{name}(...)`."


def e405_variable_called(name: str) -> str:
    return f"`{name}` is a variable, not a microservice."


def e413_params(name: str, count: int) -> str:
    return (
        f"Error: `{name}` takes {count} parameters. "
        "That's not a microservice, that's a monolith."
    )


def e418_condition(keyword: str, got: Type) -> str:
    return f"I'm a teapot: `{keyword}` needs LGTM or 404, got a {got.value}."


def e418_assign(name: str, declared: Type, pushed: Type) -> str:
    return (
        f"I'm a teapot: `{name}` was installed as a {declared.value}, "
        f"you pushed a {pushed.value}. Dependency conflict."
    )


def e418_logic(op: str) -> str:
    return f"I'm a teapot: `{op}` needs booleans, got a number. Truthiness is a JavaScript thing."


def e418_sort(op: str) -> str:
    return (
        f"I'm a teapot: can't sort booleans with `{op}`. "
        "LGTM isn't bigger than 404, just more optimistic."
    )


def e422(name: str, expected: int, got: int) -> str:
    noun = "argument" if expected == 1 else "arguments"
    return f"Error: microservice `{name}` expects {expected} {noun}, got {got}. Breaking API change?"


def e429(total: int) -> str:
    return f"Error: technical debt limit exceeded ({total}/{MAX_TODOS} TODOs). Finish something."


E403 = "Permission denied. Are you root?"
E405_TOUCH_GRASS = "Error: `touch grass` outside a `doomscroll`. You were never scrolling."
E405_GLOBAL_FLAG = "npm ERR! `-g` installs go at the top level."
E405_POSTINSTALL = "npm ERR! postinstall scripts are disabled. Globals can't call microservices."
E406 = "Error: comments must be `// TODO`. Documentation is a TODO."
E409_SERVE = "Error: port 3000 is already in use."
E410 = "Error: code after `:wq`. You already left Vim."
E415 = "Error: strings are for `console.log` only. Everything else is a number."
E418_COMPARE = "I'm a teapot: can't compare a number with a boolean."
E418_ARGUMENT = "I'm a teapot: microservices take numbers, got a boolean."
E418_RETURN = "I'm a teapot: microservices ship numbers, got a boolean. Ship 1 or 0 like it's 1972."
E418_EXIT = "I'm a teapot: exit codes are numbers, got a boolean. The OS doesn't do code review."
E426 = "Fatal: `i use arch btw` not found. Are you on Windows?"
E503 = "Error: no server running. Nothing is listening on localhost:3000."
W509 = "Infinite doomscroll detected. Go touch grass."

ARITHMETIC = {"+", "-", "*", "/", "%"}
ORDERING = {"<", "<=", ">", ">="}
EQUALITY = {"==", "!="}
LOGIC = {"&&", "||"}

SERVE = "serve"
GLOBAL = "global"


def keyword_span(start: Pos, keyword: str) -> Span:
    """The span of a keyword written with single spaces, starting at `start`."""
    return Span(start, Pos(start.line, start.col + len(keyword)))


def known(*types: Type) -> bool:
    return all(t is not Type.UNKNOWN for t in types)


class Checker:
    def __init__(self) -> None:
        self.diags: list[Diagnostic] = []
        self.symbols = Symbols()
        # The scope stack of the body being walked: globals first, then the
        # microservice's parameters, then one dict per open block.
        self.scopes: list[dict[str, Symbol]] = []
        self.owner = SERVE
        self.loop_depth = 0
        self.in_global_init = False

    # Reporting

    def error(self, code: str, message: str, span: Span, *, soft: bool = False, **kw) -> None:
        self.diags.append(Diagnostic(code, Severity.ERROR, message, span, soft=soft, **kw))

    def warning(self, code: str, message: str, span: Span) -> None:
        self.diags.append(Diagnostic(code, Severity.WARNING, message, span, soft=True))

    # Symbols and scopes

    def new_symbol(
        self, name: ast.Ident, kind: SymbolKind, ty: Type, owner: str, arity: int | None = None
    ) -> Symbol:
        sym = Symbol(name.name, kind, ty, name.span, owner, arity)
        name.sym = sym
        self.symbols.all.append(sym)
        if kind in (SymbolKind.LOCAL, SymbolKind.PARAM) or (
            kind is SymbolKind.CONST and owner != GLOBAL
        ):
            self.symbols.frames.setdefault(owner, []).append(sym)
        return sym

    def lookup(self, name: str) -> Symbol | None:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    # Pass 1: structure

    def structure(self, program: ast.Program) -> None:
        if not program.has_arch:
            # Line 1 in full: a span to the start of line 2 covers the whole line.
            self.error("E426", E426, Span(Pos(0, 0), Pos(1, 0)))
        if program.trailing_span is not None:
            self.error("E410", E410, program.trailing_span)
        serves = [item for item in program.items if isinstance(item, ast.Serve)]
        if not serves:
            end = program.span.end
            self.error("E503", E503, program.wq_span or Span(end, end))
        for extra in serves[1:]:
            self.error("E409", E409_SERVE, keyword_span(extra.span.start, "serve"))

    # Pass 2: hoisting

    def hoist(self, program: ast.Program) -> None:
        table = self.symbols.globals
        for item in program.items:
            match item:
                case ast.GlobalDecl(name=name, is_const=is_const):
                    kind = SymbolKind.CONST if is_const else SymbolKind.GLOBAL
                    # The type comes from the initializer, in pass 3.
                    sym = self.new_symbol(name, kind, Type.UNKNOWN, GLOBAL)
                    if name.name in table:
                        self.error("E409", e409_installed(name.name), name.span)
                    else:
                        table[name.name] = sym
                case ast.Microservice(name=name, params=params):
                    sym = self.new_symbol(
                        name, SymbolKind.MICROSERVICE, Type.NUMBER, GLOBAL, len(params)
                    )
                    previous = table.get(name.name)
                    if previous is None:
                        table[name.name] = sym
                    elif previous.kind is SymbolKind.MICROSERVICE:
                        self.error("E409", e409_deployed(name.name), name.span)
                    else:
                        self.error("E409", e409_installed(name.name), name.span)
                    if len(params) > MAX_PARAMS:
                        self.error("E413", e413_params(name.name, len(params)), name.span)

    # Pass 3: global initializers

    def global_initializers(self, program: ast.Program) -> None:
        microservices = {
            name: sym
            for name, sym in self.symbols.globals.items()
            if sym.kind is SymbolKind.MICROSERVICE
        }
        above: dict[str, Symbol] = {}
        self.scopes = [microservices, above]
        self.owner = GLOBAL
        self.in_global_init = True
        for item in program.items:
            if not isinstance(item, ast.GlobalDecl):
                continue
            sym = item.name.sym
            assert isinstance(sym, Symbol)
            sym.ty = self.expr(item.value)
            if self.symbols.globals.get(sym.name) is sym:
                above[sym.name] = sym
        self.in_global_init = False

    # Pass 4: bodies

    def bodies(self, program: ast.Program) -> None:
        for item in program.items:
            match item:
                case ast.Microservice(name=name, params=params, body=body):
                    self.owner = name.name
                    self.symbols.frames.setdefault(self.owner, [])
                    scope: dict[str, Symbol] = {}
                    self.scopes = [self.symbols.globals, scope]
                    for param in params:
                        visible = self.lookup(param.name)
                        sym = self.new_symbol(param, SymbolKind.PARAM, Type.NUMBER, self.owner)
                        if visible is not None:
                            self.error("E409", e409_installed(param.name), param.span)
                        else:
                            scope[param.name] = sym
                    self.loop_depth = 0
                    self.block(body)
                case ast.Serve(body=body):
                    self.owner = SERVE
                    self.symbols.frames.setdefault(self.owner, [])
                    self.scopes = [self.symbols.globals, {}]
                    self.loop_depth = 0
                    self.block(body)

    def in_microservice(self) -> bool:
        return self.owner not in (SERVE, GLOBAL)

    def block(self, block: ast.Block) -> None:
        self.scopes.append({})
        for stmt in block.stmts:
            self.stmt(stmt)
        self.scopes.pop()

    def stmt(self, stmt: ast.Stmt) -> None:
        match stmt:
            case ast.VarDecl(name=name, is_const=is_const, value=value):
                if is_const:
                    self.error(
                        "E405", E405_GLOBAL_FLAG, keyword_span(stmt.span.start, "npm install -g")
                    )
                ty = self.expr(value)
                kind = SymbolKind.CONST if is_const else SymbolKind.LOCAL
                visible = self.lookup(name.name)
                sym = self.new_symbol(name, kind, ty, self.owner)
                if visible is not None:
                    self.error("E409", e409_installed(name.name), name.span)
                else:
                    self.scopes[-1][name.name] = sym
            case ast.Assign(name=target, value=value, sudo=sudo):
                sym = self.target(target)
                ty = self.expr(value)
                if sym is None:
                    return
                if sym.is_const and not sudo:
                    span = Span(stmt.span.start, target.span.end)
                    self.e403(span, f"sudo git push --force {sym.name} = ...")
                if known(sym.ty, ty) and sym.ty is not ty:
                    self.error("E418", e418_assign(sym.name, sym.ty, ty), value.span)
            case ast.If(cond=cond, then=then, else_=else_):
                self.condition(cond, "vibe check")
                self.block(then)
                match else_:
                    case ast.Block():
                        self.block(else_)
                    case ast.If():
                        self.stmt(else_)
            case ast.While(cond=cond, body=body):
                self.condition(cond, "doomscroll")
                if isinstance(cond, ast.BoolLit) and cond.value and not way_out(body.stmts):
                    self.warning("W509", W509, keyword_span(stmt.span.start, "doomscroll"))
                self.loop_depth += 1
                self.block(body)
                self.loop_depth -= 1
            case ast.Break():
                if self.loop_depth == 0:
                    self.error("E405", E405_TOUCH_GRASS, stmt.span)
            case ast.Return(value=value):
                if value is None:
                    return
                ty = self.expr(value)
                if ty is Type.BOOLEAN:
                    message = E418_RETURN if self.in_microservice() else E418_EXIT
                    self.error("E418", message, value.span)
            case ast.Print(value=value):
                self.expr(value, string_ok=True)
            case ast.Revert(name=target, sudo=sudo):
                sym = self.target(target)
                if sym is not None and sym.is_const and not sudo:
                    self.e403(Span(stmt.span.start, target.span.end), f"sudo git revert {sym.name}")
            case ast.Log(name=target):
                self.target(target)
            case ast.ExprStmt(expr=expr):
                self.expr(expr)

    def e403(self, span: Span, suggestion: str) -> None:
        self.error("E403", E403, span, soft=True, help=f"try `{suggestion}`")

    def target(self, var: ast.Var) -> Symbol | None:
        """Resolve the variable an assignment, revert or log changes or reads."""
        sym = self.lookup(var.name)
        var.sym = sym
        if sym is None:
            self.error("E404", e404_variable(var.name), var.span)
            var.ty = Type.UNKNOWN
            return None
        if sym.kind is SymbolKind.MICROSERVICE:
            self.error("E405", e405_microservice_value(var.name), var.span)
            var.ty = Type.UNKNOWN
            return None
        var.ty = sym.ty
        return sym

    def condition(self, cond: ast.Expr, keyword: str) -> None:
        ty = self.expr(cond)
        if ty is Type.NUMBER:
            self.error("E418", e418_condition(keyword, ty), cond.span)

    # Expressions

    def expr(self, e: ast.Expr, string_ok: bool = False) -> Type:
        """Type `e`, fill its `ty`, and return the type its parent sees.

        A string outside `console.log` is E415 and looks UNKNOWN to its parent, so
        it never causes a second error. Its own `ty` stays STRING.
        """
        ty = self.infer(e)
        e.ty = ty
        if ty is Type.STRING and not string_ok:
            self.error("E415", E415, e.span)
            return Type.UNKNOWN
        return ty

    def infer(self, e: ast.Expr) -> Type:
        match e:
            case ast.IntLit():
                return Type.NUMBER
            case ast.BoolLit():
                return Type.BOOLEAN
            case ast.StrLit():
                return Type.STRING
            case ast.ErrorExpr():
                return Type.UNKNOWN
            case ast.Var(name=name):
                sym = self.lookup(name)
                e.sym = sym
                if sym is None:
                    self.error("E404", e404_variable(name), e.span)
                    return Type.UNKNOWN
                if sym.kind is SymbolKind.MICROSERVICE:
                    self.error("E405", e405_microservice_value(name), e.span)
                    return Type.UNKNOWN
                return sym.ty
            case ast.Unary(op=op, operand=operand):
                ty = self.expr(operand)
                if op == "!":
                    if ty is Type.NUMBER:
                        self.error(
                            "E418", "I'm a teapot: `!` needs a boolean, got a number.", operand.span
                        )
                    return Type.BOOLEAN
                if ty is Type.BOOLEAN:
                    self.error(
                        "E418", f"I'm a teapot: `{op}` needs a number, got a boolean.", operand.span
                    )
                return Type.NUMBER
            case ast.Binary(op=op, left=left, right=right):
                return self.binary(e, op, left, right)
            case ast.Call():
                return self.call(e)
        raise AssertionError(f"unknown expression {e!r}")

    def binary(self, e: ast.Binary, op: str, left: ast.Expr, right: ast.Expr) -> Type:
        lt = self.expr(left)
        rt = self.expr(right)
        if op in ARITHMETIC:
            for side, ty in ((left, lt), (right, rt)):
                if ty is Type.BOOLEAN:
                    self.error("E418", f"I'm a teapot: can't apply `{op}` to a boolean.", side.span)
            return Type.NUMBER
        if op in LOGIC:
            for side, ty in ((left, lt), (right, rt)):
                if ty is Type.NUMBER:
                    self.error("E418", e418_logic(op), side.span)
            return Type.BOOLEAN
        if known(lt, rt):
            if lt is not rt:
                self.error("E418", E418_COMPARE, e.span)
            elif op in ORDERING and lt is Type.BOOLEAN:
                self.error("E418", e418_sort(op), e.span)
        if op in EQUALITY or op in ORDERING:
            return Type.BOOLEAN
        raise AssertionError(f"unknown operator {op!r}")

    def call(self, e: ast.Call) -> Type:
        name = e.callee.name
        arg_types = [self.expr(arg) for arg in e.args]
        sym = self.lookup(name)
        e.sym = e.callee.sym = sym
        if self.in_global_init:
            self.error("E405", E405_POSTINSTALL, e.span)
            return Type.NUMBER if sym is not None else Type.UNKNOWN
        if sym is None:
            self.error("E404", e404_microservice(name), e.callee.span)
            return Type.UNKNOWN
        if sym.kind is not SymbolKind.MICROSERVICE:
            self.error("E405", e405_variable_called(name), e.callee.span)
            return Type.UNKNOWN
        assert sym.arity is not None
        if len(e.args) != sym.arity:
            self.error("E422", e422(name, sym.arity, len(e.args)), e.span)
        for arg, ty in zip(e.args, arg_types):
            if ty is Type.BOOLEAN:
                self.error("E418", E418_ARGUMENT, arg.span)
        return Type.NUMBER

    # Pass 7: comments

    def comments(self, comments: Iterable[Comment]) -> None:
        comments = list(comments)
        todos = [c for c in comments if c.kind is CommentKind.TODO]
        for comment in todos[MAX_TODOS:]:
            self.error("E429", e429(len(todos)), comment.span)
        for comment in comments:
            if comment.kind is CommentKind.BAD:
                self.error("E406", E406, comment.span)


def way_out(stmts: list[ast.Stmt], nested: bool = False) -> bool:
    """Whether a doomscroll body can leave the loop: a `ship it` anywhere, or a
    `touch grass` that isn't inside a nested doomscroll (Language Spec 6, W509)."""
    for stmt in stmts:
        match stmt:
            case ast.Return():
                return True
            case ast.Break() if not nested:
                return True
            case ast.If(then=then, else_=else_):
                if way_out(then.stmts, nested):
                    return True
                if isinstance(else_, ast.Block) and way_out(else_.stmts, nested):
                    return True
                if isinstance(else_, ast.If) and way_out([else_], nested):
                    return True
            case ast.While(body=body):
                if way_out(body.stmts, nested=True):
                    return True
    return False


def finish(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Pass 9: sort by line, column and code, and drop exact duplicates (same code
    and span), keeping the first one reported."""
    unique: dict[tuple[str, Span], Diagnostic] = {}
    for diagnostic in diagnostics:
        unique.setdefault((diagnostic.code, diagnostic.span), diagnostic)
    return sorted(unique.values(), key=lambda d: (d.span.start, d.code))


def check(
    program: ast.Program, comments: Iterable[Comment] | None = None
) -> tuple[Symbols, list[Diagnostic]]:
    """Implementation Spec 7, passes 1 to 5, 7 and 9. `comments` defaults to the
    program's own."""
    checker = Checker()
    checker.structure(program)
    checker.hoist(program)
    checker.global_initializers(program)
    checker.bodies(program)
    checker.comments(program.comments if comments is None else comments)
    return checker.symbols, finish(checker.diags)
