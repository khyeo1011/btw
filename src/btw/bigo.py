"""Big O checker (Language Spec 9.1, Implementation Spec 8).

Every doomscroll counts as n iterations, so a microservice's degree is how
deeply its doomscrolls nest, including the loops inside the microservices it
calls. A microservice on a call-graph cycle (calling itself counts) is
UNKNOWN, written O(?), and so is anything that calls it.
"""

from __future__ import annotations

from dataclasses import dataclass

from btw import ast
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span

UNKNOWN = None
"""The degree of a recursive microservice: O(?)."""

type Degree = int | None


@dataclass(frozen=True)
class Cost:
    """A degree, plus the `doomscroll` keyword of the innermost loop on the
    deepest path. `loop` is None when the degree is 0 or UNKNOWN."""

    degree: Degree
    loop: Span | None = None


FREE = Cost(0)
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
        self.done: dict[str, Cost] = {}
        self.in_progress: set[str] = set()

    def service(self, name: str) -> Cost:
        """degFn(f): the cost of calling the microservice `name`."""
        if name in self.done:
            return self.done[name]
        if name in self.in_progress:
            return RECURSIVE  # we're already inside it: a cycle
        self.in_progress.add(name)
        cost = self.cost(self.services[name].body)
        self.in_progress.remove(name)
        self.done[name] = cost
        return cost

    def microservice(self, ms: ast.Microservice) -> Cost:
        """Like `service`, but also for a duplicate whose name belongs to an
        earlier microservice."""
        if self.services[ms.name.name] is ms:
            return self.service(ms.name.name)
        return self.cost(ms.body)

    def cost(self, node: ast.Node | None) -> Cost:
        """deg and degE from Language Spec 9.1, for any statement or expression."""
        match node:
            case ast.While(cond, body):
                inner = worst([self.cost(cond), self.cost(body)])
                if inner.degree is UNKNOWN:
                    return RECURSIVE
                return Cost(inner.degree + 1, inner.loop or doomscroll_span(node))
            case ast.Call(callee, args):
                called = self.service(callee.name) if callee.name in self.services else FREE
                return worst([called, *map(self.cost, args)])
            case ast.Block(stmts):
                return worst([self.cost(stmt) for stmt in stmts])
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


def format_complexity(degree: Degree, var: str | None = None) -> str:
    """O(1), O(n), O(n²), O(n³), O(n^4) and up, and O(?) for UNKNOWN."""
    n = var or "n"
    match degree:
        case None:
            return "O(?)"
        case 0:
            return "O(1)"
        case 1:
            return f"O({n})"
        case 2:
            return f"O({n}²)"
        case 3:
            return f"O({n}³)"
        case _:
            return f"O({n}^{degree})"


def check_bigo(program: ast.Program) -> list[Diagnostic]:
    """E417, W417, W102, W508 and W203 for every microservice."""
    inference = Inference(program)
    diagnostics: list[Diagnostic] = []
    for item in program.items:
        if isinstance(item, ast.Microservice):
            diagnostics += verdict(item, inference.microservice(item))
    return diagnostics


def verdict(ms: ast.Microservice, cost: Cost) -> list[Diagnostic]:
    """The verdict table of Language Spec 9.1."""
    big_o, d = ms.big_o, cost.degree
    found: list[Diagnostic] = []
    if big_o is not None and big_o.degree is None:
        found.append(warning("W203", f"I can't verify O({big_o.text}). I'll take your word for it.", big_o.span))
    if d is UNKNOWN:
        found.append(warning("W508", "Complexity: O(?). The halting problem is a skill issue.", ms.name.span))
    elif big_o is None:
        message = f"microservice `{ms.name.name}` has no SLA. Inferred: {format_complexity(d)}."
        found.append(warning("W102", message, ms.name.span))
    elif big_o.degree is None:
        pass  # unverifiable: W203 above
    elif big_o.degree < d:
        said, actual = format_complexity(big_o.degree, big_o.var), format_complexity(d, big_o.var)
        found.append(Diagnostic(
            "E417",
            Severity.ERROR,
            f"You said {said}, but this is {actual}. Skill issue.",
            big_o.span,
            soft=True,
            related=[(cost.loop, f"nested doomscroll #{d} starts here")],
            help=f"try `{actual}`, then tell the PM it was always the plan",
        ))
    elif big_o.degree > d:
        message = f"Technically correct, but this is {format_complexity(d, big_o.var)}. Sandbagging your estimates?"
        found.append(warning("W417", message, big_o.span))
    return found


def warning(code: str, message: str, span: Span) -> Diagnostic:
    return Diagnostic(code, Severity.WARNING, message, span, soft=True)
