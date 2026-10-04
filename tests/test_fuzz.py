"""Differential fuzzing: random well-typed programs through the interpreter and
the native backend (Implementation Spec 13, "differential testing").

Each seed generates one program that the checker should accept with no
errors. The interpreter must run it without crashing, and the native binary
must match the interpreter byte for byte: stdout, stderr and exit code.

The generator is seeded, so every run produces the same programs (no
randomness, Language Spec decision 20). `--fuzz N` runs N seeds; a failing
seed's program is in the assertion message.

Programs always terminate: each doomscroll has its own counter that nothing
else assigns or reverts, microservice fK only calls fJ for J < K, and a
static budget bounds loop trips times calls.
"""

import io
import random
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from btw import driver
from btw.diagnostics import Severity

needs_gcc = pytest.mark.skipif(shutil.which("gcc") is None, reason="native: gcc not found")

RUNTIME_ERRORS = {
    "Runtime error: division by zero. Have you tried turning it off and on again?\n",
    "Stack overflow. Please search stackoverflow.com.\n",
    "curl: (52) Empty reply from server.\n",
    "curl: (8) Weird server reply.\n",
}

BUDGET = 3000  # loop iterations plus calls, per run
MAX_DEPTH = 3  # expression nesting
MAX_NESTING = 3  # block nesting

LITERALS = [
    "0", "1", "2", "3", "5", "7", "10", "100", "403", "405", "4040",
    "2147483647", "2147483648", "4294967296", "3037000500",
    "9223372036854775807", "(-9223372036854775807 - 1)",
]  # fmt: skip
DIVISORS = ["1", "2", "3", "7", "-1", "-2", "-3", "10", "4294967296"]
STRINGS = ['""', '"hi"', '"a\\tb"', '"line\\nbreak"', '"quote \\" and \\\\"', '"héllo 🚀"']
CURL_TOKENS = ["0", "1", "-1", "42", "007", "-00", "9223372036854775807", "-9223372036854775808"]
CURL_BAD = ["+5", "12abc", "9223372036854775808", "-", "1.5"]


@dataclass
class Var:
    name: str
    ty: str  # "num" or "bool"
    kind: str  # "const", "global", "local", "param" or "counter"
    history: bool  # a global, a constant or a variable in `serve` (Language Spec 9.3)


class Generator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.names = 0
        self.lines: list[str] = []
        self.scopes: list[list[Var]] = []
        self.fns: list[tuple[str, int, int]] = []  # name, arity, cost of one call
        self.owner = "global"
        self.callable: list[tuple[str, int, int]] = []
        self.cost = 0  # work so far in the current microservice or serve
        self.mult = 1  # trips of the enclosing loops
        self.loops = 0  # enclosing doomscrolls in the current body
        self.nesting = 0

    def fresh(self, prefix: str) -> str:
        self.names += 1
        return f"{prefix}{self.names}"

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    def emit(self, line: str) -> None:
        self.lines.append("    " * self.nesting + line)

    def visible(self, ty: str | None = None) -> list[Var]:
        return [v for scope in self.scopes for v in scope if ty is None or v.ty == ty]

    def declare(self, var: Var) -> None:
        self.scopes[-1].append(var)

    # Expressions

    def num(self, depth: int = 0) -> str:
        rng = self.rng
        leaf = depth >= MAX_DEPTH or self.chance(0.3)
        choice = rng.random()
        if leaf or choice < 0.2:
            names = self.visible("num")
            if names and self.chance(0.5):
                return rng.choice(names).name
            if self.owner != "global" and self.chance(0.03):
                return "curl"
            return rng.choice(LITERALS)
        if choice < 0.55:
            op = rng.choice("+-*/%")
            right = rng.choice(DIVISORS) if op in "/%" and self.chance(0.7) else self.num(depth + 1)
            return f"({self.num(depth + 1)} {op} {right})"
        if choice < 0.65:
            operand = self.num(depth + 1)
            return f"-({operand})" if operand.startswith("-") else f"-{operand}"
        if choice < 0.9 and (call := self.call(depth)):
            return call
        if (pipe := self.pipe(depth)):
            return f"({pipe})"
        return rng.choice(LITERALS)

    def boolean(self, depth: int = 0) -> str:
        rng = self.rng
        leaf = depth >= MAX_DEPTH or self.chance(0.2)
        choice = rng.random()
        if leaf or choice < 0.15:
            names = self.visible("bool")
            if names and self.chance(0.5):
                return rng.choice(names).name
            return rng.choice(["LGTM", "404"])
        if choice < 0.5:
            op = rng.choice(["<", "<=", ">", ">=", "==", "!="])
            return f"({self.num(depth + 1)} {op} {self.num(depth + 1)})"
        if choice < 0.6:
            op = rng.choice(["==", "!="])
            return f"({self.boolean(depth + 1)} {op} {self.boolean(depth + 1)})"
        if choice < 0.85:
            op = rng.choice(["&&", "||"])
            return f"({self.boolean(depth + 1)} {op} {self.boolean(depth + 1)})"
        return f"!{self.boolean(depth + 1)}"

    def expr(self, ty: str) -> str:
        return self.num() if ty == "num" else self.boolean()

    def pick_fn(self) -> tuple[str, int] | None:
        """A microservice this body may call within the budget, or None."""
        options = [f for f in self.callable if self.cost + self.mult * f[2] <= BUDGET]
        if not options:
            return None
        name, arity, cost = self.rng.choice(options)
        self.cost += self.mult * cost
        return name, arity

    def call(self, depth: int) -> str | None:
        if not (fn := self.pick_fn()):
            return None
        name, arity = fn
        return f"{name}({', '.join(self.num(depth + 1) for _ in range(arity))})"

    def pipe(self, depth: int) -> str | None:
        """`a | f | g(b)`, every stage taking the piped value first (Language Spec 9.4)."""
        stages = []
        for _ in range(self.rng.randint(1, 2)):
            if not (fn := self.pick_fn()):
                break
            name, arity = fn
            if arity == 0:
                break
            extra = [self.num(depth + 1) for _ in range(arity - 1)]
            stages.append(f"{name}({', '.join(extra)})" if extra or self.chance(0.5) else name)
        if not stages:
            return None
        return " | ".join([self.num(depth + 1), *stages])

    # Statements

    def block(self, statements: int) -> None:
        self.nesting += 1
        self.scopes.append([])
        for _ in range(statements):
            self.statement()
        self.scopes.pop()
        self.nesting -= 1

    def statement(self) -> None:
        rng = self.rng
        kinds = ["decl", "decl", "assign", "assign", "print", "print", "print", "call"]
        if self.nesting <= MAX_NESTING:
            kinds += ["if", "if", "loop"]
        if self.loops:
            kinds += ["break"]
        if self.owner == "serve" or self.chance(0.3):
            kinds += ["history"]
        if self.chance(0.3):
            kinds += ["ship"]
        match rng.choice(kinds):
            case "decl":
                ty = "num" if self.chance(0.7) else "bool"
                value = self.expr(ty)
                name = self.fresh("v")
                self.emit(f"npm install {name} = {value}")
                self.declare(Var(name, ty, "local", self.owner == "serve"))
            case "assign":
                targets = [v for v in self.visible() if v.kind != "counter"]
                if not targets:
                    return self.print()
                var = rng.choice(targets)
                sudo = "sudo " if var.kind == "const" or self.chance(0.05) else ""
                self.emit(f"{sudo}git push --force {var.name} = {self.expr(var.ty)}")
            case "print":
                self.print()
            case "call":
                if not (call := self.call(0)):
                    return self.print()
                self.emit(call)
            case "if":
                self.vibe_check()
            case "loop":
                self.doomscroll()
            case "break":
                if self.chance(0.7):
                    self.emit(f"vibe check {self.boolean()} {{ touch grass }}")
                else:
                    self.emit("touch grass")
            case "history":
                self.history()
            case "ship":
                value = self.num() if self.chance(0.8) else ""
                self.emit(f"vibe check {self.boolean()} {{ ship it {value} }}")

    def print(self) -> None:
        choice = self.rng.random()
        if choice < 0.15:
            text = self.rng.choice(STRINGS)
            self.emit(f"console.log {text}" if self.chance(0.7) else f"{text} | console.log")
        elif choice < 0.25 and (pipe := self.pipe(0)):
            self.emit(f"{pipe} | console.log")
        elif choice < 0.6:
            self.emit(f"console.log {self.boolean()}")
        else:
            self.emit(f"console.log {self.num()}")

    def vibe_check(self) -> None:
        self.emit(f"vibe check {self.boolean()} {{")
        self.block(self.rng.randint(0, 3))
        while self.chance(0.4):
            else_if = f"vibe check {self.boolean()} " if self.chance(0.5) else ""
            if self.chance(0.5):
                self.emit(f"}} skill issue {else_if}{{")
            else:
                self.emit("}")
                self.emit(f"skill issue {else_if}{{")
            self.block(self.rng.randint(0, 3))
            if not else_if:
                break
        self.emit("}")

    def doomscroll(self) -> None:
        trips = self.rng.randint(0, 4)
        if self.cost + self.mult * trips > BUDGET:
            return self.print()
        counter = self.fresh("i")
        self.emit(f"npm install {counter} = 0")
        self.declare(Var(counter, "num", "counter", self.owner == "serve"))
        condition = f"{counter} < {trips}"
        if self.chance(0.3):
            condition = f"{condition} && {self.boolean(1)}"
        self.emit(f"doomscroll {condition} {{")
        self.cost += self.mult * trips
        self.mult *= max(trips, 1)
        self.loops += 1
        self.block(self.rng.randint(1, 4))
        self.loops -= 1
        self.mult //= max(trips, 1)
        self.emit(f"    git push --force {counter} = {counter} + 1")
        self.emit("}")

    def history(self) -> None:
        names = [v for v in self.visible() if v.history]
        if not names:
            return self.print()
        var = self.rng.choice(names)
        match self.rng.choice(["revert", "log", "blame"]):
            case "revert" if var.kind != "counter":
                sudo = "sudo " if var.kind == "const" else ""
                self.emit(f"{sudo}git revert {var.name}")
            case "blame":
                self.emit(f"git blame {var.name}")
            case _:
                self.emit(f"git log {var.name}")

    # Items

    def program(self) -> tuple[str, bytes]:
        rng = self.rng
        self.emit("i use arch btw")
        self.scopes.append([])
        for _ in range(rng.randint(0, 4)):
            const = self.chance(0.5)
            ty = "num" if self.chance(0.7) else "bool"
            name = self.fresh("G" if const else "g")
            self.emit(f"npm install{' -g' if const else ''} {name} = {self.expr(ty)}")
            self.declare(Var(name, ty, "const" if const else "global", True))
        for _ in range(rng.randint(0, 4)):
            name, arity = self.fresh("f"), rng.randint(0, 6)
            params = [self.fresh("p") for _ in range(arity)]
            self.emit(f"microservice {name}({', '.join(params)}) {{")
            self.enter(name, [Var(p, "num", "param", False) for p in params])
            self.block(rng.randint(1, 5))
            if self.chance(0.7):
                self.emit(f"    ship it {self.num()}")
            self.scopes.pop()
            self.emit("}")
            self.fns.append((name, arity, 1 + self.cost))
        self.emit("serve localhost:3000 {")
        self.enter("serve", [])
        self.block(rng.randint(3, 10))
        if self.chance(0.3):
            self.emit(f"    ship it {self.num()}")
        self.emit("}")
        self.emit(":wq")
        tokens = [rng.choice(CURL_TOKENS) for _ in range(rng.randint(0, 12))]
        if self.chance(0.2):
            tokens.append(rng.choice(CURL_BAD))
        separators = [rng.choice([" ", "\t", "\n", "\r\n", "  "]) for _ in tokens]
        stdin = "".join(t + s for t, s in zip(tokens, separators))
        return "\n".join(self.lines) + "\n", stdin.encode()

    def enter(self, owner: str, params: list[Var]) -> None:
        self.owner = owner
        self.callable = list(self.fns)
        self.cost = 0
        self.scopes.append(params)


@cache
def generate(seed: int) -> tuple[str, bytes]:
    return Generator(seed).program()


@cache
def interpret(seed: int) -> tuple[str, str, int]:
    source, stdin = generate(seed)
    stdout, stderr = io.StringIO(), io.StringIO()
    diagnostics, code = driver.run(source, "fuzz.btw", stdout, stderr, io.BytesIO(stdin))
    errors = [f"{d.code}: {d.message}" for d in diagnostics if d.severity is Severity.ERROR]
    assert code is not None, f"the checker rejected seed {seed}:\n{errors}\n\n{source}"
    return stdout.getvalue(), stderr.getvalue(), code & 0xFF


def native(seed: int, tmp_path: Path) -> tuple[str, str, int]:
    source, stdin = generate(seed)
    binary = tmp_path / "prog"
    diagnostics, gcc_stderr = driver.build(source, "fuzz.btw", binary)
    assert gcc_stderr is None, f"{gcc_stderr}\n\n{source}"
    assert not driver.has_errors(diagnostics), f"{diagnostics}\n\n{source}"
    result = subprocess.run([binary], input=stdin, capture_output=True, timeout=5)
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def pytest_generate_tests(metafunc):
    if "seed" in metafunc.fixturenames:
        metafunc.parametrize("seed", range(metafunc.config.getoption("--fuzz")))


def test_interpreter_runs(seed):
    source, _ = generate(seed)
    _, stderr, _ = interpret(seed)
    assert stderr in RUNTIME_ERRORS | {""} or stderr.startswith("fatal: bad revision"), source


@needs_gcc
def test_native_matches_interpreter(seed, tmp_path):
    source, stdin = generate(seed)
    assert native(seed, tmp_path) == interpret(seed), f"stdin: {stdin!r}\n\n{source}"
