"""x86-64 code generation (Implementation Spec 10).

`gen(program, symbols, annotate=False, source=None)` turns a checked program
with no errors into one GNU as file in Intel syntax, returned as
`(assembly_text, diagnostics)`. The driver links it with `runtime/btw_rt.c`.

It's a stack machine: every expression leaves exactly one 8-byte value
pushed, and the temporary stack is empty at every statement boundary. The
generator counts pushes at compile time (`depth`) and asserts both rules, and
uses the count to align `rsp` to 16 bytes before every call.

Part 1 covered globals, constants, `serve`, every expression and the
statements that don't need microservices or history. Part 2 adds
microservices, calls, the call depth limit and git history. The one thing
left is E501, reported before any assembly is written: history for more than
64 variables.
"""

from __future__ import annotations

from btw import ast
from btw.ast import Type
from btw.checker import Symbol, SymbolKind, Symbols
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span

INDENT = " " * 8
SERVE = "serve"
MAX_DEPTH = 1_000  # Language Spec 8: the 1,001st nested call overflows
MAX_TRACKED = 64  # Implementation Spec 10.7: the runtime's history table
ARG_REGISTERS = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")

ARITHMETIC = {"+": "add", "-": "sub", "*": "imul"}
COMPARISONS = {"==": "sete", "!=": "setne", "<": "setl", "<=": "setle", ">": "setg", ">=": "setge"}


def e501(construct: str, span: Span) -> Diagnostic:
    return Diagnostic(
        "E501",
        Severity.ERROR,
        f"Not implemented: `{construct}` in native builds. Try `btw run`.",
        span,
    )


def keyword_span(start: Pos, keyword: str) -> Span:
    return Span(start, Pos(start.line, start.col + len(keyword)))


# E501: what the native backend can't build yet


def tracked_ids(symbols: Symbols) -> dict[Symbol, int]:
    """The runtime's history id of every tracked variable, in the order the
    checker created them."""
    tracked = [sym for sym in symbols.all if sym.tracked]
    return {sym: k for k, sym in enumerate(tracked)}


def unsupported(program: ast.Program, ids: dict[Symbol, int]) -> list[Diagnostic]:
    """One E501 per `git revert` and `git log` on a variable past the
    runtime's 64 histories (Implementation Spec 10.7)."""
    found: list[Diagnostic] = []

    def too_many(target: ast.Var) -> bool:
        return ids.get(target.sym, 0) >= MAX_TRACKED

    def block(b: ast.Block) -> None:
        for s in b.stmts:
            stmt(s)

    def stmt(s: ast.Stmt) -> None:
        match s:
            case ast.If(then=then, else_=else_):
                block(then)
                if isinstance(else_, ast.Block):
                    block(else_)
                elif else_ is not None:
                    stmt(else_)
            case ast.While(body=body):
                block(body)
            case ast.Revert(name=target) if too_many(target):
                found.append(e501("git revert", s.span))
            case ast.Log(name=target) if too_many(target):
                found.append(e501("git log", s.span))

    for item in program.items:
        match item:
            case ast.Microservice(body=body) | ast.Serve(body=body):
                block(body)
    return found


# Assembly text helpers


def instruction(op: str, operands: str = "") -> str:
    """`        mov     rax, rcx`: the mnemonic padded so operands line up."""
    return f"{INDENT}{op:<7} {operands}".rstrip() if operands else f"{INDENT}{op}"


def escape(text: str) -> str:
    """A `.string` literal (Implementation Spec 10.8): backslash, quote, newline
    and tab escaped, every other byte outside printable ASCII in octal."""
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        match char:
            case "\\":
                out.append("\\\\")
            case '"':
                out.append('\\"')
            case "\n":
                out.append("\\n")
            case "\t":
                out.append("\\t")
            case _ if 0x20 <= byte < 0x7F:
                out.append(char)
            case _:
                out.append(f"\\{byte:03o}")
    return '"' + "".join(out) + '"'


def utf16_index(line: str, col: int) -> int:
    """The string index of a UTF-16 column (Language Spec 1)."""
    units = 0
    for index, char in enumerate(line):
        if units >= col:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(line)


# The generator


class Codegen:
    def __init__(
        self,
        program: ast.Program,
        symbols: Symbols,
        ids: dict[Symbol, int],
        annotate: bool,
        source: str | None,
    ) -> None:
        self.program = program
        self.symbols = symbols
        self.ids = ids  # history ids of the tracked variables
        self.annotate = annotate
        self.source_lines = source.split("\n") if source is not None else None
        self.text: list[str] = []
        self.strings: dict[str, str] = {}  # contents to label, in first-use order
        self.labels = 0
        self.depth = 0  # temporaries pushed right now, tracked at compile time
        self.loop_ends: list[str] = []  # innermost last, for `touch grass`
        self.ret_label = ""
        self.div_zero_used = False
        self.stack_overflow_used = False

    # Emitting

    def emit(self, op: str, operands: str = "", note: str | None = None) -> None:
        line = instruction(op, operands)
        if note and self.annotate:
            line = f"{line:<39} # {note}"
        self.text.append(line)

    def label(self, name: str) -> None:
        self.text.append(f"{name}:")

    def new_label(self, *kinds: str) -> list[str]:
        """`.Lelse3`, `.Lendif3`: one number shared by the labels of a construct."""
        self.labels += 1
        return [f".L{kind}{self.labels}" for kind in kinds]

    def push(self, operand: str, note: str | None = None) -> None:
        self.emit("push", operand, note)
        self.depth += 1

    def pop(self, register: str) -> None:
        assert self.depth > 0, "pop from an empty temporary stack"
        self.emit("pop", register)
        self.depth -= 1

    def call(self, function: str) -> None:
        """Implementation Spec 10.6: rsp is aligned when an even number of
        temporaries is pushed, so pad by 8 bytes when the count is odd."""
        if self.depth % 2:
            self.emit("sub", "rsp, 8", "align the stack for the call")
            self.emit("call", function)
            self.emit("add", "rsp, 8")
        else:
            self.emit("call", function)

    def string(self, text: str) -> str:
        if text not in self.strings:
            self.strings[text] = f".Lstr{len(self.strings)}"
        return self.strings[text]

    # Annotations (Implementation Spec 10.9)

    def source_text(self, start: Pos, end: Pos) -> str:
        """The source from `start` to `end`, or to the end of `start`'s line when
        `end` is on a later line."""
        assert self.source_lines is not None
        line = self.source_lines[start.line].removesuffix("\r")
        stop = utf16_index(line, end.col) if end.line == start.line else len(line)
        return line[utf16_index(line, start.col) : stop].strip()

    def comment(self, start: Pos, end: Pos, prefix: str = "") -> None:
        """`# line 6: vibe check (i % 15 == 0)` before a statement's code."""
        if not self.annotate:
            return
        text = f"line {start.line + 1}"
        if self.source_lines is not None:
            text += f": {prefix}{self.source_text(start, end)}"
        self.text.append("")
        self.text.append(f"{INDENT}# {text}")

    # Variables (Implementation Spec 10.3)

    def location(self, sym: Symbol) -> str:
        if sym.kind in (SymbolKind.GLOBAL, SymbolKind.CONST):
            return f"qword ptr [rip + btw_g_{sym.name}]"
        assert sym.slot is not None, f"no slot for {sym.name}"
        return f"qword ptr [rbp - {8 * (sym.slot + 1)}]"

    # The file (Implementation Spec 10.2)

    def generate(self) -> str:
        serve = next(item for item in self.program.items if isinstance(item, ast.Serve))
        globals_ = [item for item in self.program.items if isinstance(item, ast.GlobalDecl)]
        self.function_main(serve, globals_)
        for item in self.program.items:
            if isinstance(item, ast.Microservice):
                self.function_microservice(item)
        self.handlers()

        out = [f"{INDENT}.intel_syntax noprefix", ""]
        if self.strings:
            out.append(f"{INDENT}.section .rodata")
            out += [f"{label}: .string {escape(text)}" for text, label in self.strings.items()]
            out.append("")
        out.append(f"{INDENT}.data")
        for item in globals_:
            out.append(f"btw_g_{item.name.name}: .quad 0")
        out.append("btw_depth: .quad 0")
        out.append("")
        out.append(f"{INDENT}.text")
        out.append(f"{INDENT}.globl main")
        out += self.text
        out.append("")
        out.append(f'{INDENT}.section .note.GNU-stack,"",@progbits')
        return "\n".join(out) + "\n"

    def prologue(self, symbol: str, owner: str) -> None:
        """Implementation Spec 10.3: the label, then `push rbp`, `mov rbp, rsp`
        and `sub rsp, FRAME`, with one 8-byte slot per parameter and local in
        `symbols.frames` order. FRAME is rounded up to 16 bytes, so rsp stays
        aligned (10.6), and the `sub` is left out when there are no slots."""
        slots = self.symbols.frames.get(owner, [])
        for k, sym in enumerate(slots):
            sym.slot = k
        frame = (8 * len(slots) + 15) // 16 * 16
        self.ret_label = f".Lret_{owner}"
        self.label(symbol)
        self.emit("push", "rbp")
        self.emit("mov", "rbp, rsp")
        if frame:
            self.emit("sub", f"rsp, {frame}", "slots: " + ", ".join(sym.name for sym in slots))

    def epilogue(self, note: str, leaving: tuple[tuple[str, str, str], ...] = ()) -> None:
        """`ship it` jumps to the return label with its value in rax; falling
        off the end leaves 0 there. `leaving` runs between the label and
        `leave`, and must not touch rax."""
        self.text.append("")
        self.emit("xor", "eax, eax", note)
        self.label(self.ret_label)
        for op, operands, comment in leaving:
            self.emit(op, operands, comment)
        self.emit("leave")
        self.emit("ret")

    def function_main(self, serve: ast.Serve, globals_: list[ast.GlobalDecl]) -> None:
        """Global initializers in source order, then the `serve` body
        (Language Spec 10). `ship it` jumps to `.Lret_serve` with the exit
        code in rax. `serve` is a reserved word, so the label can't collide
        with a microservice's `.Lret_NAME`, even one named `main`."""
        self.prologue("main", SERVE)
        for item in globals_:
            self.comment(item.span.start, item.span.end)
            self.store(item.name.sym, item.value, "btw_rt_hist_reset")
        self.comment(serve.span.start, serve.body.span.start)
        self.block(serve.body)
        self.epilogue("falling off the end of serve exits with 0")

    def handlers(self) -> None:
        """The shared runtime error handlers, after every function so any of
        them can jump here. They never return, so they just align rsp."""
        if self.div_zero_used:
            self.text.append("")
            self.label(".Ldiv_zero")
            self.emit("and", "rsp, -16", "never returns, so just align")
            self.emit("call", "btw_rt_div_zero")
        if self.stack_overflow_used:
            self.text.append("")
            self.label(".Lstack_overflow")
            self.emit("and", "rsp, -16", "never returns, so just align")
            self.emit("call", "btw_rt_stack_overflow")

    def function_microservice(self, item: ast.Microservice) -> None:
        """`btw_fn_NAME` (Implementation Spec 10.3). The parameters arrive in
        rdi, rsi, rdx, rcx, r8 and r9 and are copied into slots 0 to 5 right
        after the prologue, so the body treats them like any other local.

        The call depth (Implementation Spec 10.5) is counted in the callee,
        after the arguments were evaluated, as the interpreter does: `serve`
        is depth 0, so entering at depth 1,001 overflows. The decrement before
        `leave` makes no call, so the return value in rax survives."""
        name = item.name.name
        if not self.annotate:
            self.text.append("")  # the annotation brings its own blank line
        self.comment(item.span.start, item.body.span.start)
        self.prologue(f"btw_fn_{name}", name)
        self.stack_overflow_used = True
        self.emit("inc", "qword ptr [rip + btw_depth]", "one call deeper")
        self.emit("cmp", f"qword ptr [rip + btw_depth], {MAX_DEPTH}")
        self.emit("jg", ".Lstack_overflow", "past 1,000 nested calls?")
        for param, register in zip(item.params, ARG_REGISTERS, strict=False):
            sym = param.sym
            assert isinstance(sym, Symbol), f"unresolved parameter {param.name}"
            self.emit("mov", f"{self.location(sym)}, {register}", sym.name)
        self.block(item.body)
        self.epilogue(
            "falling off the end ships 0",
            (("dec", "qword ptr [rip + btw_depth]", "back to the caller's depth"),),
        )

    # Statements (Implementation Spec 10.5)

    def block(self, block: ast.Block) -> None:
        for stmt in block.stmts:
            self.stmt(stmt)

    def stmt(self, stmt: ast.Stmt, else_if: bool = False) -> None:
        assert self.depth == 0, f"{self.depth} temporaries before line {stmt.span.start.line + 1}"
        match stmt:
            case ast.If(cond=cond, then=then, else_=else_):
                self.comment(stmt.span.start, then.span.start, "skill issue " if else_if else "")
                self.lower_if(cond, then, else_)
            case ast.While(cond=cond, body=body):
                self.comment(stmt.span.start, body.span.start)
                self.lower_while(cond, body)
            case _:
                self.comment(stmt.span.start, stmt.span.end)
                self.simple(stmt)
        assert self.depth == 0, f"{self.depth} temporaries after line {stmt.span.start.line + 1}"

    def simple(self, stmt: ast.Stmt) -> None:
        match stmt:
            case ast.VarDecl(name=name, value=value):
                self.store(name.sym, value, "btw_rt_hist_reset")
            case ast.Assign(name=target, value=value):
                self.store(target.sym, value, "btw_rt_hist_commit")
            case ast.Revert(name=target):
                self.history_target(target.sym)
                self.call("btw_rt_hist_revert")
                self.emit("mov", f"{self.location(target.sym)}, rax", target.name)
            case ast.Log(name=target):
                self.history_target(target.sym)
                self.emit("mov", f"rdx, {int(target.sym.ty is Type.BOOLEAN)}", "print as LGTM/404?")
                self.call("btw_rt_hist_log")
            case ast.Break():
                self.emit("jmp", self.loop_ends[-1], "touch grass")
            case ast.Return(value=None):
                self.emit("xor", "eax, eax")
                self.emit("jmp", self.ret_label, "ship it")
            case ast.Return(value=value):
                self.expr(value)
                self.pop("rax")
                self.emit("jmp", self.ret_label, "ship it")
            case ast.Print(value=ast.StrLit(value=text)):
                self.emit("lea", f"rdi, [rip + {self.string(text)}]")
                self.call("btw_rt_print_str")
            case ast.Print(value=value):
                self.expr(value)
                self.pop("rdi")
                match value.ty:
                    case Type.NUMBER:
                        self.call("btw_rt_print_int")
                    case Type.BOOLEAN:
                        self.call("btw_rt_print_bool")
                    case ty:
                        raise AssertionError(f"can't print a {ty}")
            case ast.ExprStmt(expr=expr):
                self.expr(expr)
                self.emit("add", "rsp, 8", "drop the unused value")
                self.depth -= 1
            case _:
                raise AssertionError(f"unexpected statement {stmt!r}")

    def store(self, sym: Symbol, value: ast.Expr, history: str) -> None:
        """Evaluate into a variable. A tracked one (Language Spec 9.3) also
        tells the runtime: `btw_rt_hist_reset` for a declaration, so one that
        runs again starts a fresh history, `btw_rt_hist_commit` for an
        assignment, wherever it is."""
        self.expr(value)
        self.pop("rax")
        self.emit("mov", f"{self.location(sym)}, rax", sym.name)
        if sym in self.ids:
            self.emit("mov", f"rdi, {self.ids[sym]}", f"history of {sym.name}")
            self.emit("mov", "rsi, rax")
            self.call(history)

    def history_target(self, sym: Symbol) -> None:
        """rdi and rsi for `git revert` and `git log`: the history id and the
        variable's name, for `(HEAD -> x)` and `fatal: bad revision 'x~1'`."""
        self.emit("mov", f"rdi, {self.ids[sym]}", f"history of {sym.name}")
        self.emit("lea", f"rsi, [rip + {self.string(sym.name)}]")

    def lower_if(self, cond: ast.Expr, then: ast.Block, else_: ast.Block | ast.If | None) -> None:
        else_label, end_label = self.new_label("else", "endif")
        self.expr(cond)
        self.pop("rax")
        self.emit("test", "rax, rax")
        self.emit("jz", else_label if else_ is not None else end_label, "404: skip the block")
        self.block(then)
        if else_ is not None:
            self.emit("jmp", end_label)
            self.label(else_label)
            if isinstance(else_, ast.If):
                self.stmt(else_, else_if=True)
            else:
                self.comment(else_.span.start, else_.span.start, "skill issue")
                self.block(else_)
        self.label(end_label)

    def lower_while(self, cond: ast.Expr, body: ast.Block) -> None:
        loop_label, end_label = self.new_label("loop", "loop")
        end_label += "_end"
        self.label(loop_label)
        self.expr(cond)
        self.pop("rax")
        self.emit("test", "rax, rax")
        self.emit("jz", end_label, "404: stop scrolling")
        self.loop_ends.append(end_label)
        self.block(body)
        self.loop_ends.pop()
        self.emit("jmp", loop_label, "keep scrolling")
        self.label(end_label)

    # Expressions (Implementation Spec 10.4)

    def expr(self, expr: ast.Expr) -> None:
        before = self.depth
        self.lower_expr(expr)
        assert self.depth == before + 1, f"expression left {self.depth - before} values"

    def lower_expr(self, expr: ast.Expr) -> None:
        match expr:
            case ast.IntLit(value=value):
                if -(2**31) <= value < 2**31:
                    self.push(str(value))  # push sign-extends a 32-bit immediate
                else:
                    self.emit("mov", f"rax, {value}")
                    self.push("rax")
            case ast.BoolLit(value=value):
                self.push("1" if value else "0", "LGTM" if value else "404")
            case ast.Var(sym=sym):
                self.push(self.location(sym), sym.name)
            case ast.Unary(op="-", operand=operand):
                self.expr(operand)
                self.pop("rax")
                self.emit("neg", "rax")
                self.push("rax")
            case ast.Unary(op="!", operand=operand):
                self.expr(operand)
                self.pop("rax")
                self.emit("xor", "rax, 1")
                self.push("rax")
            case ast.Binary(op="&&" | "||" as op, left=left, right=right):
                self.short_circuit(op, left, right)
            case ast.Binary(op=op, left=left, right=right):
                self.expr(left)
                self.expr(right)
                self.pop("rcx")
                self.pop("rax")
                self.binary(op)
            case ast.Call(callee=callee, args=args):
                self.lower_call(callee.name, args)
            case _:
                raise AssertionError(f"unexpected expression {expr!r}")

    def lower_call(self, name: str, args: list[ast.Expr]) -> None:
        """Implementation Spec 10.4: evaluate the arguments left to right, pop
        them into the argument registers in reverse order, then `call` pads
        rsp when an odd number of temporaries is still pushed (10.6). Nothing
        stays in a register across the call: rax is pushed right away."""
        assert len(args) <= len(ARG_REGISTERS), f"{name} has {len(args)} arguments"
        for arg in args:
            self.expr(arg)
        for register in reversed(ARG_REGISTERS[: len(args)]):
            self.pop(register)
        self.call(f"btw_fn_{name}")
        self.push("rax", f"{name}(...)")

    def binary(self, op: str) -> None:
        """rax op rcx, then push the result."""
        if op in ARITHMETIC:
            self.emit(ARITHMETIC[op], "rax, rcx")
            self.push("rax")
        elif op in ("/", "%"):
            self.div_zero_used = True
            self.emit("test", "rcx, rcx")
            self.emit("jz", ".Ldiv_zero", "dividing by zero?")
            # idiv traps on the minimum / -1, so x / -1 is a wrapping `neg` and x % -1 is 0
            idiv, done = self.new_label("idiv", "divdone")
            self.emit("cmp", "rcx, -1")
            self.emit("jne", idiv)
            self.emit("neg" if op == "/" else "xor", "rax" if op == "/" else "eax, eax")
            self.emit("jmp", done)
            self.label(idiv)
            self.emit("cqo")
            self.emit("idiv", "rcx")
            if op == "%":
                self.emit("mov", "rax, rdx")
            self.label(done)
            self.push("rax", "quotient" if op == "/" else "remainder")
        elif op in COMPARISONS:
            self.emit("cmp", "rax, rcx")
            self.emit(COMPARISONS[op], "al")
            self.emit("movzx", "eax, al")
            self.push("rax")
        else:
            raise AssertionError(f"unexpected operator {op!r}")

    def short_circuit(self, op: str, left: ast.Expr, right: ast.Expr) -> None:
        """`&&` skips the right side when the left is 404, `||` when it's LGTM."""
        kind, jump, value = ("false", "jz", "0") if op == "&&" else ("true", "jnz", "1")
        decided, end = self.new_label(kind, "end")
        self.expr(left)
        self.pop("rax")
        self.emit("test", "rax, rax")
        self.emit(jump, decided)
        self.expr(right)
        self.emit("jmp", end)
        self.label(decided)
        self.depth -= 1  # this path never pushed the right side
        self.push(value, "LGTM" if value == "1" else "404")
        self.label(end)


def gen(
    program: ast.Program, symbols: Symbols, annotate: bool = False, source: str | None = None
) -> tuple[str, list[Diagnostic]]:
    """Assembly for a checked program with no errors. With `annotate`, each
    statement gets a comment with its line number, plus its source text when
    `source` is given. Unsupported constructs give E501 and no assembly."""
    ids = tracked_ids(symbols)
    diagnostics = unsupported(program, ids)
    if diagnostics:
        return "", diagnostics
    return Codegen(program, symbols, ids, annotate, source).generate(), []
