"""`btw loadtest`: empirical Big O (Language Spec 9.7).

Calls one microservice in the interpreter for growing n, counts steps
(doomscroll iterations plus microservice calls) and fits the slope of
ln(steps) against ln(n). Everything is counted, never timed, so the report
is the same on every machine.
"""

from __future__ import annotations

import io
import math
import sys

from btw import ast
from btw.bigo import SUPERPOLYNOMIAL, UNKNOWN, Degree, annotation, format_complexity, infer
from btw.checker import Symbols
from btw.driver import BtwError
from btw.interp import RECURSION_LIMIT, BreakSignal, Interpreter, RuntimeFault, wrap

SIZES = [8, 16, 32, 64, 128, 256, 512, 1024]
BUDGET = 3_000_000  # steps for the whole sweep, so any program finishes in seconds


class OverBudget(Exception):
    """The sweep took more steps than the budget."""


class CountingInterpreter(Interpreter):
    """The interpreter, counting each doomscroll iteration and microservice call."""

    def __init__(self, program: ast.Program, symbols: Symbols, budget: int) -> None:
        # Output is discarded, and stdin is empty (Language Spec 9.7).
        super().__init__(program, symbols, io.StringIO(), io.BytesIO())
        self.budget = budget
        self.steps = 0

    def step(self) -> None:
        self.steps += 1
        if self.steps > self.budget:
            raise OverBudget()

    def exec(self, stmt: ast.Stmt) -> None:
        if not isinstance(stmt, ast.While):
            return super().exec(stmt)
        while self.eval(stmt.cond):
            self.step()
            try:
                self.exec_block(stmt.body)
            except BreakSignal:
                break

    def call(self, service: ast.Microservice, args: list[int]) -> int:
        self.step()
        return super().call(service, args)


def parse_args(text: str, service: ast.Microservice) -> list[int | None]:
    """`1,n,5` → [1, None, 5]: None stands for the size."""
    template: list[int | None] = []
    for item in text.split(","):
        item = item.strip()
        if item == "n":
            template.append(None)
            continue
        try:
            template.append(wrap(int(item)))
        except ValueError:
            raise BtwError(f"--args: `{item}` is neither a number nor `n`") from None
    if len(template) != len(service.params):
        count = len(service.params)
        raise BtwError(
            f"`{service.name.name}` takes {count} argument{'' if count == 1 else 's'}, "
            f"but --args gives {len(template)}"
        )
    return template


def measure(
    program: ast.Program,
    symbols: Symbols,
    service: ast.Microservice,
    template: list[int | None],
    sizes: list[int] = SIZES,
    budget: int = BUDGET,
) -> tuple[list[tuple[int, int]], list[str]]:
    """Run the service once per size: the (n, steps) points and one line per size."""
    used = 0
    points: list[tuple[int, int]] = []
    lines: list[str] = []
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, RECURSION_LIMIT))
    try:
        for n in sizes:
            interp = CountingInterpreter(program, symbols, budget - used)
            try:
                for item in program.items:
                    if isinstance(item, ast.GlobalDecl):
                        interp.declare(item.name.sym, interp.eval(item.value))
                interp.call(service, [n if arg is None else arg for arg in template])
            except OverBudget:
                lines.append(f"n = {n}: over budget. Stopped.")
                break
            except RuntimeFault as fault:
                lines.append(f"n = {n}: {fault.message} Stopped.")
                break
            used += interp.steps
            points.append((n, interp.steps))
            lines.append(f"n = {n}: {interp.steps} step{'' if interp.steps == 1 else 's'}")
    finally:
        sys.setrecursionlimit(limit)
    return points, lines


def slope(points: list[tuple[int, int]]) -> float:
    """Least-squares slope of ln(steps) against ln(n)."""
    xs = [math.log(n) for n, _ in points]
    ys = [math.log(steps) for _, steps in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / sum((x - mx) ** 2 for x in xs)


def nearest(s: float) -> int:
    """Round to the nearest whole number, halves up."""
    return math.floor(s + 0.5)


def verdict(service: ast.Microservice, degree: Degree, s: float) -> list[str]:
    """The static and measured lines of Language Spec 9.7. A log factor is too
    small to measure, so only the power of n, k of (k, j), is compared."""
    big_o = service.big_o
    sla, var = annotation(big_o) if big_o is not None else (UNKNOWN, None)
    static = f"static {format_complexity(degree, var)}."
    if degree is not UNKNOWN and nearest(s) < degree[0]:
        static += " The static checker was being pessimistic."
    elif degree is not UNKNOWN and nearest(s) > degree[0]:
        static += " The static checker was being optimistic."
    measured = f"measured O({var or 'n'}^{round(s, 2) + 0.0:.2f})."  # + 0.0: no -0.00
    if big_o is None:
        measured += " No SLA, so nobody was notified."
    elif sla is UNKNOWN or sla is SUPERPOLYNOMIAL:
        measured += f" Your SLA says O({big_o.text}). I'll take your word for it."
    else:
        measured += f" Your SLA says {format_complexity(sla, var)}."
        if nearest(s) > sla[0]:
            measured += " The PM has been notified."
        elif nearest(s) == sla[0]:
            measured += " LGTM."
        else:
            measured += " Sandbagging your estimates?"
    return [static, measured]


def loadtest(program: ast.Program, symbols: Symbols, name: str, args: str = "n") -> str:
    """The whole report for `btw loadtest FILE NAME --args ARGS`."""
    service = next(
        (
            item
            for item in program.items
            if isinstance(item, ast.Microservice) and item.name.name == name
        ),
        None,
    )  # a duplicate keeps the first, as in the interpreter
    if service is None:
        raise BtwError(f"no microservice named `{name}`")
    points, lines = measure(program, symbols, service, parse_args(args, service))
    if len(points) < 2:
        raise BtwError(f"need at least 2 sizes to fit a slope. {lines[-1]}")
    lines += verdict(service, infer(program).get(name), slope(points))
    return "\n".join(lines) + "\n"
