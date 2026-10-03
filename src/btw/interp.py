"""Tree-walking interpreter (Implementation Spec 9, Language Spec 5, 6 and 10).

`run(program, symbols, stdout, stderr)` executes a checked program with no
errors and returns its exit code. It's the oracle for the native backend, so
it favors being obviously right over being fast.

Values are Python ints, always wrapped to signed 64 bits, and bools. Strings
only appear as the operand of `console.log`. Every declaration has its own
Symbol, so a frame is a flat dict keyed by Symbol and needs no scope logic.
"""

from __future__ import annotations

import sys
from typing import TextIO

from btw import ast
from btw.checker import Symbol, SymbolKind, Symbols

MAX_DEPTH = 1_000
HISTORY_LIMIT = 16
RECURSION_LIMIT = 50_000

DIVISION_BY_ZERO = (
    "Runtime error: division by zero. Have you tried turning it off and on again?"
)
STACK_OVERFLOW = "Stack overflow. Please search stackoverflow.com."

type Value = int | bool


# Arithmetic helpers (Language Spec 5)


def wrap(n: int) -> int:
    """Map any integer into the signed 64-bit range, two's complement."""
    n &= 0xFFFF_FFFF_FFFF_FFFF
    return n - (1 << 64) if n >= 1 << 63 else n


def div(a: int, b: int) -> int:
    """Truncate toward zero, like x86 `idiv`. The caller checks for zero."""
    q = abs(a) // abs(b)
    return wrap(q if (a < 0) == (b < 0) else -q)


def rem(a: int, b: int) -> int:
    """The remainder of `div`: it takes the sign of `a`. The caller checks for zero."""
    return wrap(a - b * div(a, b))


def format_value(value: Value) -> str:
    """Numbers in decimal, booleans as LGTM or 404 (Language Spec 0, decision 5)."""
    if isinstance(value, bool):
        return "LGTM" if value else "404"
    return str(value)


# Control flow


class RuntimeFault(Exception):
    """A runtime error: its exact stderr message and exit code (Language Spec 10)."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class BreakSignal(Exception):
    """`touch grass`."""


class ReturnSignal(Exception):
    """`ship it`: a return in a microservice, the exit code in `serve`."""

    def __init__(self, value: Value) -> None:
        super().__init__()
        self.value = value


# The interpreter


class Interpreter:
    def __init__(self, program: ast.Program, symbols: Symbols, stdout: TextIO) -> None:
        self.program = program
        self.symbols = symbols
        self.stdout = stdout
        self.globals: dict[Symbol, Value] = {}
        self.frame: dict[Symbol, Value] = {}
        self.depth = 0
        self.history: dict[Symbol, list[Value]] = {}
        self.services: dict[Symbol, ast.Microservice] = {}
        for item in program.items:
            if isinstance(item, ast.Microservice) and isinstance(item.name.sym, Symbol):
                self.services.setdefault(
                    item.name.sym, item
                )  # a duplicate keeps the first

    def run(self) -> int:
        """Global initializers in source order, then the `serve` body (Language Spec 10)."""
        for item in self.program.items:
            if isinstance(item, ast.GlobalDecl):
                self.declare(item.name.sym, self.eval(item.value))
        serve = next(item for item in self.program.items if isinstance(item, ast.Serve))
        try:
            self.exec_block(serve.body)
        except ReturnSignal as signal:
            return signal.value  # a number: shipping a boolean from serve is E418
        return 0

    # Variables

    def scope(self, sym: Symbol) -> dict[Symbol, Value]:
        if sym.kind in (SymbolKind.GLOBAL, SymbolKind.CONST):
            return self.globals
        return self.frame

    def declare(self, sym: Symbol, value: Value) -> None:
        """Bind a declaration. Running it again (in a loop) starts a fresh history."""
        self.scope(sym)[sym] = value
        if sym.tracked:
            self.history[sym] = [value]

    def assign(self, sym: Symbol, value: Value) -> None:
        """Change a variable and record the change as a commit."""
        self.scope(sym)[sym] = value
        if sym.tracked:
            history = self.history[sym]
            history.append(value)
            del history[:-HISTORY_LIMIT]

    def load(self, sym: Symbol) -> Value:
        return self.scope(sym)[sym]

    # Statements

    def exec_block(self, block: ast.Block) -> None:
        for stmt in block.stmts:
            self.exec(stmt)

    def exec(self, stmt: ast.Stmt) -> None:
        match stmt:
            case ast.VarDecl(name=name, value=value):
                self.declare(name.sym, self.eval(value))
            case ast.Assign(name=target, value=value):
                self.assign(target.sym, self.eval(value))
            case ast.If(cond=cond, then=then, else_=else_):
                if self.eval(cond):
                    self.exec_block(then)
                elif isinstance(else_, ast.Block):
                    self.exec_block(else_)
                elif else_ is not None:
                    self.exec(else_)
            case ast.While(cond=cond, body=body):
                while self.eval(cond):
                    try:
                        self.exec_block(body)
                    except BreakSignal:
                        break
            case ast.Break():
                raise BreakSignal()
            case ast.Return(value=value):
                raise ReturnSignal(0 if value is None else self.eval(value))
            case ast.Print(value=ast.StrLit(value=text)):
                self.stdout.write(text + "\n")
            case ast.Print(value=value):
                self.stdout.write(format_value(self.eval(value)) + "\n")
            case ast.Revert(name=target):
                self.revert(target)
            case ast.Log(name=target):
                self.log(target)
            case ast.ExprStmt(expr=expr):
                self.eval(expr)
            case _:
                raise AssertionError(f"unexpected statement {stmt!r}")

    def revert(self, target: ast.Var) -> None:
        """`git revert x` (Language Spec 9.3)."""
        history = self.history[target.sym]
        if len(history) < 2:
            raise RuntimeFault(f"fatal: bad revision '{target.name}~1'", 128)
        self.assign(target.sym, history[-2])

    def log(self, target: ast.Var) -> None:
        """`git log x`: newest first, HEAD on the first line (Language Spec 9.3)."""
        for i, value in enumerate(reversed(self.history[target.sym])):
            head = f" (HEAD -> {target.name})" if i == 0 else ""
            self.stdout.write(f"* {format_value(value)}{head}\n")

    # Expressions

    def eval(self, expr: ast.Expr) -> Value:
        match expr:
            case ast.IntLit(value=value):
                return wrap(value)
            case ast.BoolLit(value=value):
                return value
            case ast.Var(sym=sym):
                return self.load(sym)
            case ast.Unary(op="-", operand=operand):
                return wrap(-self.eval(operand))
            case ast.Unary(op="!", operand=operand):
                return not self.eval(operand)
            case ast.Binary(op="&&", left=left, right=right):
                return self.eval(left) and self.eval(right)
            case ast.Binary(op="||", left=left, right=right):
                return self.eval(left) or self.eval(right)
            case ast.Binary(op=op, left=left, right=right):
                return self.binary(op, self.eval(left), self.eval(right))
            case ast.Call(args=args, sym=sym):
                values = [self.eval(arg) for arg in args]  # left to right
                return self.call(self.services[sym], values)
            case _:
                raise AssertionError(f"unexpected expression {expr!r}")

    def binary(self, op: str, a: Value, b: Value) -> Value:
        match op:
            case "+":
                return wrap(a + b)
            case "-":
                return wrap(a - b)
            case "*":
                return wrap(a * b)
            case "/":
                if b == 0:
                    raise RuntimeFault(DIVISION_BY_ZERO, 1)
                return div(a, b)
            case "%":
                if b == 0:
                    raise RuntimeFault(DIVISION_BY_ZERO, 1)
                return rem(a, b)
            case "==":
                return a == b
            case "!=":
                return a != b
            case "<":
                return a < b
            case "<=":
                return a <= b
            case ">":
                return a > b
            case ">=":
                return a >= b
        raise AssertionError(f"unexpected operator {op!r}")

    def call(self, service: ast.Microservice, args: list[Value]) -> Value:
        """Enter a microservice. `serve` is depth 0, so call 1,001 overflows."""
        if self.depth >= MAX_DEPTH:
            raise RuntimeFault(STACK_OVERFLOW, 1)
        caller = self.frame
        self.frame = {param.sym: value for param, value in zip(service.params, args)}
        self.depth += 1
        try:
            self.exec_block(service.body)
        except ReturnSignal as signal:
            return signal.value  # a number: shipping a boolean is E418
        finally:
            self.depth -= 1
            self.frame = caller
        return 0  # falling off the end returns 0


def run(program: ast.Program, symbols: Symbols, stdout: TextIO, stderr: TextIO) -> int:
    """Run a checked program and return its exit code (Language Spec 10).

    The recursion limit goes back to its old value afterwards, so the raise
    doesn't leak into other components sharing the process (tests, the LSP).
    """
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, RECURSION_LIMIT))
    try:
        return Interpreter(program, symbols, stdout).run()
    except RuntimeFault as fault:
        stdout.flush()
        stderr.write(fault.message + "\n")
        stderr.flush()
        return fault.exit_code
    finally:
        stdout.flush()
        sys.setrecursionlimit(limit)
