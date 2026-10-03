"""Works on my machine (Language Spec 9.5, Implementation Spec 7 pass 8).

`apply(program, diagnostics)` runs every `// works on my machine` directive
over the diagnostics collected so far, in source order. A directive targets
the first statement or item that starts after it, nested blocks included,
and removes the soft diagnostics (E403, E417 and every warning) whose span
starts inside that target. Each directive then gets exactly one W200 or
W304 of its own, which no other directive can remove.
"""

from __future__ import annotations

from collections.abc import Iterator

from btw import ast
from btw.diagnostics import Diagnostic, Severity
from btw.tokens import Comment, CommentKind

W304_HARD = "304 Not Modified: this one doesn't work on any machine."
W304_NOTHING = "304 Not Modified: nothing to suppress. It works on every machine."

UNSUPPRESSIBLE = {"E429"}
"""Technical debt can only be refinanced (Language Spec 9.6)."""


def w200(count: int) -> str:
    problems = "problem" if count == 1 else "problems"
    return f"200 OK (on my machine): {count} {problems} suppressed."


def suppressible(diag: Diagnostic) -> bool:
    return diag.soft and diag.code not in UNSUPPRESSIBLE


def block_targets(block: ast.Block) -> Iterator[ast.Node]:
    """Every statement in `block`, and every statement nested inside them."""
    for stmt in block.stmts:
        yield stmt
        match stmt:
            case ast.If():
                yield from if_targets(stmt)
            case ast.While(body=body):
                yield from block_targets(body)


def if_targets(stmt: ast.If) -> Iterator[ast.Node]:
    """The statements of every branch. An `else vibe check` is part of its
    statement, not a statement of its own."""
    yield from block_targets(stmt.then)
    match stmt.else_:
        case ast.If():
            yield from if_targets(stmt.else_)
        case ast.Block():
            yield from block_targets(stmt.else_)


def targets(program: ast.Program) -> list[ast.Node]:
    """Every item and statement in the program, in source order."""
    nodes: list[ast.Node] = []
    for item in program.items:
        nodes.append(item)
        match item:
            case ast.Microservice(body=body) | ast.Serve(body=body):
                nodes.extend(block_targets(body))
    return sorted(nodes, key=lambda node: node.span.start)


def target_of(directive: Comment, nodes: list[ast.Node]) -> ast.Node | None:
    """The first statement or item that starts after the directive."""
    return next((node for node in nodes if node.span.start >= directive.span.end), None)


def apply(program: ast.Program, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Return the diagnostics after suppression, plus one W200 or W304 per
    directive."""
    nodes = targets(program)
    kept = list(diagnostics)
    verdicts: list[Diagnostic] = []
    for directive in program.comments:
        if directive.kind is not CommentKind.WOMM:
            continue
        target = target_of(directive, nodes)
        inside = [] if target is None else [d for d in kept if target.span.contains(d.span.start)]
        removed = [d for d in inside if suppressible(d)]
        if removed:
            code, message = "W200", w200(len(removed))
            gone = {id(d) for d in removed}
            kept = [d for d in kept if id(d) not in gone]
        elif inside:
            code, message = "W304", W304_HARD
        else:
            code, message = "W304", W304_NOTHING
        verdicts.append(Diagnostic(code, Severity.WARNING, message, directive.span, soft=True))
    return kept + verdicts
