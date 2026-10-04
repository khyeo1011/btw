"""Big O checker (Language Spec 9.1, Implementation Spec 8).

A degree is a pair (poly, log), meaning O(n^poly · log^log n), compared
lexicographically. A doomscroll runs n times unless its shape proves fewer
(`trips`): a counter stepping toward a fixed bound runs O(1) times, and one
that halves or doubles runs O(log n) times. A microservice's degree adds up
the trip counts of its nested doomscrolls, including the loops inside the
microservices it calls. A microservice on a call-graph cycle (calling itself
counts) is UNKNOWN, written O(?), and so is anything that calls it.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass

from btw import ast
from btw.diagnostics import Diagnostic, Edit, Fix, Severity
from btw.span import Pos, Span
from btw.tokens import Token, TokenKind as K

UNKNOWN = None
"""The degree of a recursive microservice: O(?)."""

type Degree = tuple[int, int] | None

CONSTANT, LOG, LINEAR = (0, 0), (0, 1), (1, 0)


@dataclass(frozen=True)
class Cost:
    """A degree, plus the `doomscroll` keyword of the innermost loop on the
    deepest path. `loop` is None when the degree is O(1) or UNKNOWN."""

    degree: Degree
    loop: Span | None = None


FREE = Cost(CONSTANT)
RECURSIVE = Cost(UNKNOWN)


def worst(costs: list[Cost]) -> Cost:
    """The max of the degrees. UNKNOWN beats everything, and of equal
    degrees the first one wins."""
    result = FREE
    for cost in costs:
        if cost.degree is UNKNOWN:
            return RECURSIVE
        if cost.degree > result.degree:
            result = cost
    return result


class Inference:
    """Memoized depth-first search over the call graph."""

    def __init__(self, program: ast.Program):
        self.services: dict[str, ast.Microservice] = {}
        for item in program.items:
            if isinstance(item, ast.Microservice):
                self.services.setdefault(item.name.name, item)  # first one wins
        self.constants = constants(program)
        self.done: dict[str, Cost] = {}
        self.in_progress: set[str] = set()
        self.scope: set[str] = set()  # the parameters and locals declared so far

    def service(self, name: str) -> Cost:
        """degFn(f): the cost of calling the microservice `name`."""
        if name in self.done:
            return self.done[name]
        if name in self.in_progress:
            return RECURSIVE  # we're already inside it: a cycle
        self.in_progress.add(name)
        cost = self.body(self.services[name])
        self.in_progress.remove(name)
        self.done[name] = cost
        return cost

    def microservice(self, ms: ast.Microservice) -> Cost:
        """Like `service`, but also for a duplicate whose name belongs to an
        earlier microservice."""
        if self.services[ms.name.name] is ms:
            return self.service(ms.name.name)
        return self.body(ms)

    def body(self, ms: ast.Microservice) -> Cost:
        outer, self.scope = self.scope, {p.name for p in ms.params}
        cost = self.cost(ms.body)
        self.scope = outer
        return cost

    def cost(self, node: ast.Node | None, before: ast.Stmt | None = None) -> Cost:
        """deg and degE from Language Spec 9.1, for any statement or expression.
        `before` is the statement right before a doomscroll in its block."""
        match node:
            case ast.While(cond, body):
                inner = worst([self.cost(cond), self.cost(body)])
                if inner.degree is UNKNOWN:
                    return RECURSIVE
                trip = self.trips(node, before)
                if trip == CONSTANT:
                    return inner  # a fixed-size loop isn't a nested doomscroll
                degree = (inner.degree[0] + trip[0], inner.degree[1] + trip[1])
                return Cost(degree, inner.loop or doomscroll_span(node))
            case ast.Call(callee, args):
                called = self.service(callee.name) if callee.name in self.services else FREE
                return worst([called, *map(self.cost, args)])
            case ast.Block(stmts):
                outer = set(self.scope)
                found = []
                for prev, stmt in zip([None, *stmts], stmts):
                    found.append(self.cost(stmt, prev))
                    if isinstance(stmt, ast.VarDecl):
                        self.scope.add(stmt.name.name)
                self.scope = outer
                return worst(found)
            case ast.If(cond, then, else_):
                return worst([self.cost(cond), self.cost(then), self.cost(else_)])
            case ast.VarDecl(value=e) | ast.Assign(value=e) | ast.Return(value=e):
                return self.cost(e)
            case ast.Print(value=e) | ast.ExprStmt(expr=e) | ast.Unary(operand=e):
                return self.cost(e)
            case ast.Binary(_, left, right):
                return worst([self.cost(left), self.cost(right)])
            case _:
                return FREE  # literals, names, touch grass, git log, git revert, a missing value

    def trips(self, loop: ast.While, before: ast.Stmt | None) -> Degree:
        """How many times `loop` runs: CONSTANT, LOG or LINEAR (Language Spec 9.1).

        Only `doomscroll v < E` (or <=, >, >=, !=, either way round) whose body
        changes the local `v` exactly once, as a top-level `v = v + c`,
        `v - c`, `v * c` or `v / c` with a literal or constant c, gets fewer
        than n trips.
        """
        if not (isinstance(loop.cond, ast.Binary) and loop.cond.op in ("<", "<=", ">", ">=", "!=")):
            return LINEAR
        for v, bound in ((loop.cond.left, loop.cond.right), (loop.cond.right, loop.cond.left)):
            if not isinstance(v, ast.Var) or v.name not in self.scope:
                continue  # a global could change in any call
            step = self.step(loop.body, v.name)
            if step is None:
                continue
            op, c = step
            declared = isinstance(before, ast.VarDecl) and before.name.name == v.name
            start = literal(before.value) if declared else None
            if op in ("+", "-"):
                return CONSTANT if start is not None and self.fixed(bound) else LINEAR
            k = self.constants.get(c.name) if isinstance(c, ast.Var) else literal(c)
            if op == "/" and k is not None and abs(k) >= 2:
                return LOG
            if op == "*" and k is not None and k >= 2 and start is not None and start > 0:
                return LOG
            return LINEAR
        return LINEAR

    def step(self, body: ast.Block, v: str) -> tuple[str, ast.Expr] | None:
        """(op, c) when `body` changes `v` only through one top-level
        `v = v op c`, with c a literal or a constant."""
        if writes(body, v) != 1:
            return None
        for stmt in body.stmts:
            match stmt:
                case ast.Assign(ast.Var(name), ast.Binary(op, ast.Var(left), c)) if name == left == v:
                    if op in ("+", "-", "*", "/") and self.fixed(c):
                        return op, c
        return None

    def fixed(self, e: ast.Expr) -> bool:
        """A literal, or a name that is a constant (not a local hiding one)."""
        if isinstance(e, ast.Var):
            return e.name in self.constants and e.name not in self.scope
        return literal(e) is not None


def constants(program: ast.Program) -> dict[str, int | None]:
    """Each `npm install -g` constant mapped to its value when that's a
    literal, None otherwise. A constant that some `sudo` changes isn't one."""
    found: dict[str, int | None] = {}
    for item in program.items:
        if isinstance(item, ast.GlobalDecl) and item.is_const:
            found.setdefault(item.name.name, literal(item.value))
    for name in sudo_targets(program):
        found.pop(name, None)
    return found


def sudo_targets(node: object) -> set[str]:
    """The names that `sudo git push --force` and `sudo git revert` change."""
    match node:
        case ast.Assign(ast.Var(name), _, True) | ast.Revert(ast.Var(name), True):
            return {name}
        case ast.Program(items):
            return set().union(*map(sudo_targets, items))
        case ast.Microservice(body=b) | ast.Serve(body=b) | ast.While(body=b):
            return sudo_targets(b)
        case ast.Block(stmts):
            return set().union(*map(sudo_targets, stmts))
        case ast.If(_, then, else_):
            return sudo_targets(then) | sudo_targets(else_)
        case _:
            return set()


def writes(node: object, v: str) -> int:
    """How many statements in `node` assign, revert or redeclare `v`."""
    match node:
        case ast.Assign(ast.Var(name)) | ast.Revert(ast.Var(name)) | ast.VarDecl(ast.Ident(name)):
            return int(name == v)
        case ast.Block(stmts):
            return sum(writes(stmt, v) for stmt in stmts)
        case ast.If(_, then, else_):
            return writes(then, v) + writes(else_, v)
        case ast.While(_, body):
            return writes(body, v)
        case _:
            return 0


def literal(e: ast.Expr) -> int | None:
    """The value of `42` or `-42`, else None."""
    match e:
        case ast.IntLit(value):
            return value
        case ast.Unary("-", ast.IntLit(value)):
            return -value
        case _:
            return None


def doomscroll_span(loop: ast.While) -> Span:
    start = loop.span.start
    return Span(start, Pos(start.line, start.col + len("doomscroll")))


# Public API (Implementation Spec 8)


def costs(program: ast.Program) -> dict[str, Cost]:
    """Each microservice name mapped to its Cost, for hover and related info."""
    inference = Inference(program)
    return {name: inference.service(name) for name in inference.services}


def infer(program: ast.Program) -> dict[str, Degree]:
    """Each microservice name mapped to its degree, or UNKNOWN."""
    return {name: cost.degree for name, cost in costs(program).items()}


def format_complexity(degree: Degree, var: str | None = None, *, source: bool = False) -> str:
    """O(1), O(n), O(n²), O(n³), O(n^4) and up, each optionally followed by
    log n (O(log n), O(n log n), O(n² log² n)), and O(?) for UNKNOWN.

    With source=True, powers 2 and 3 come out as n^2 and log^3: the lexer
    doesn't accept superscripts, so quick-fix edits use this form.
    """
    if degree is UNKNOWN:
        return "O(?)"
    n = var or "n"
    poly, log = degree
    parts = [power(n, poly, source)] if poly else []
    if log:
        parts.append(f"{power('log', log, source)} {n}")
    return f"O({' '.join(parts) or '1'})"


def power(base: str, k: int, source: bool) -> str:
    match k:
        case 1:
            return base
        case 2 if not source:
            return f"{base}²"
        case 3 if not source:
            return f"{base}³"
        case _:
            return f"{base}^{k}"


NAME = r"[A-Za-z_][A-Za-z0-9_]*"
LOG_SLA = re.compile(
    rf"(?:(?P<poly>{NAME})(?:\s*\^\s*(?P<k>\d+))?\s+)?log(?:\s*\^\s*(?P<j>\d+))?\s+(?P<var>{NAME})"
)


def annotation(big_o: ast.BigO) -> tuple[Degree, str | None]:
    """(degree, variable) of an SLA, UNKNOWN when it's unverifiable.

    The parser checks `1`, `n` and `n^k`. The log forms `log n`, `n log n`,
    `n^k log n` and `log^j n` are read here from the source text, because
    ast.BigO.degree is a plain int.
    """
    if big_o.degree is not None:
        return (big_o.degree, 0), big_o.var
    m = LOG_SLA.fullmatch(big_o.text)
    if m is None or m["poly"] not in (None, m["var"]):
        return UNKNOWN, None
    k = int(m["k"] or 1) if m["poly"] else 0
    return (k, int(m["j"] or 1)), m["var"]


def check_bigo(program: ast.Program, tokens: list[Token] | None = None) -> list[Diagnostic]:
    """E417, W417, W102, W508 and W203 for every microservice.

    E417 and W417 carry their quick fixes (P2) either way. W102's fix inserts
    the SLA after the `)` of the parameter list, which only the tokens have,
    so without them W102 carries no fix.
    """
    inference = Inference(program)
    diagnostics: list[Diagnostic] = []
    for item in program.items:
        if isinstance(item, ast.Microservice):
            diagnostics += verdict(item, inference.microservice(item), tokens)
    return diagnostics


# Tokens that can't come before the `)` of a parameter list. Reaching one
# first means the `)` is missing: newlines aren't tokens inside parens, so it's
# usually the body's `{`, and a `(` means recovery swallowed an annotation.
PAST_PARAMS = {K.LPAREN, K.LBRACE, K.RBRACE, K.NEWLINE, K.WQ, K.EOF}


def params_close(tokens: list[Token], ms: ast.Microservice) -> Span | None:
    """The span of the `)` that closes the parameter list of `ms`, or None when
    it's missing.

    The AST doesn't keep that `)`, so this scans the tokens from the end of the
    last parameter, or from just past the `(` when there are none. The scan
    gives up at the start of the body or at any token in PAST_PARAMS.
    """
    anchor = ms.params[-1].span.end if ms.params else ms.name.span.end
    i = bisect_left(tokens, anchor, key=lambda tok: tok.span.start)
    if not ms.params:
        if i == len(tokens) or tokens[i].kind is not K.LPAREN:
            return None
        i += 1
    for tok in tokens[i:]:
        if tok.span.start >= ms.body.span.start or tok.kind in PAST_PARAMS:
            return None
        if tok.kind is K.RPAREN:
            return tok.span
    return None


def add_sla(ms: ast.Microservice, degree: Degree, tokens: list[Token] | None) -> list[Fix]:
    """W102's quick fix: ` O(n)` inserted right after the parameter list."""
    close = params_close(tokens, ms) if tokens is not None else None
    if close is None:
        return []
    title, text = format_complexity(degree), format_complexity(degree, source=True)
    return [Fix(f"Add SLA {title}", [Edit(Span(close.end, close.end), f" {text}")])]


def verdict(ms: ast.Microservice, cost: Cost, tokens: list[Token] | None = None) -> list[Diagnostic]:
    """The verdict table of Language Spec 9.1, with the quick fixes of Language Spec 11."""
    big_o, d = ms.big_o, cost.degree
    k, var = annotation(big_o) if big_o is not None else (UNKNOWN, None)
    found: list[Diagnostic] = []
    if big_o is not None and k is UNKNOWN:
        found.append(warning("W203", f"I can't verify O({big_o.text}). I'll take your word for it.", big_o.span))
    if d is UNKNOWN:
        found.append(warning("W508", "Complexity: O(?). The halting problem is a skill issue.", ms.name.span))
    elif big_o is None:
        message = f"microservice `{ms.name.name}` has no SLA. Inferred: {format_complexity(d)}."
        found.append(warning("W102", message, ms.name.span, add_sla(ms, d, tokens)))
    elif k is UNKNOWN:
        pass  # unverifiable: W203 above
    elif k < d:
        said, actual = format_complexity(k, var), format_complexity(d, var)
        text = format_complexity(d, var, source=True)
        found.append(Diagnostic(
            "E417",
            Severity.ERROR,
            f"You said {said}, but this is {actual}. Skill issue.",
            big_o.span,
            soft=True,
            related=[(cost.loop, f"nested doomscroll #{sum(d)} starts here")],
            help=f"try `{actual}`, then tell the PM it was always the plan",
            fixes=[Fix(f"Update SLA to {actual}", [Edit(big_o.span, text)])],
        ))
    elif k > d:
        actual = format_complexity(d, var)
        message = f"Technically correct, but this is {actual}. Sandbagging your estimates?"
        fix = Fix("Tighten SLA", [Edit(big_o.span, format_complexity(d, var, source=True))])
        found.append(warning("W417", message, big_o.span, [fix]))
    return found


def warning(code: str, message: str, span: Span, fixes: list[Fix] | None = None) -> Diagnostic:
    return Diagnostic(code, Severity.WARNING, message, span, soft=True, fixes=fixes or [])
