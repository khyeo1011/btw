"""Hover text (Language Spec 12, Implementation Spec 11).

`hover(source, pos)` finds the comment, Big O annotation or token under `pos`
and returns its Markdown text and the span it covers, or None. It runs the
same pipeline as `btw check`, so identifiers show what the checker resolved.
"""

from __future__ import annotations

from dataclasses import fields

from btw import ast, bigo, driver
from btw.checker import MAX_TODOS, Symbol, SymbolKind
from btw.interp import HISTORY_LIMIT
from btw.span import Pos, Span
from btw.tokens import Comment, CommentKind, Token, TokenKind as K

ARCH = (
    "**Required first line.** Proves you're worthy. "
    "Without it the compiler assumes you're on Windows."
)
SERVE = (
    "**main().** Every program is secretly a dev server. "
    "Nobody knows what else is running on port 3000."
)

KEYWORDS: dict[K, str] = {
    K.ARCH: ARCH,
    K.SERVE: SERVE,
    K.LOCALHOST: SERVE,
    K.WQ: "**End of program.** The only known way out.",
    K.NPM_INSTALL: "**let.** Declares a variable. node_modules just got 200 MB heavier.",
    K.NPM_INSTALL_G: (
        "**const.** A global install. "
        "Changing it needs sudo, like everything else on your machine."
    ),
    K.GIT_PUSH_FORCE: (
        "**Assignment.** Overwrites the old value without asking. Your teammates love this."
    ),
    K.SUDO: (
        "**Permission override.** Lets you modify constants. "
        "With great power comes no code review."
    ),
    K.GIT_REVERT: "**Undo.** Restores the previous value as a new commit. History is forever.",
    K.GIT_LOG: (
        "**Print history.** Every value this variable ever had. Most of them were mistakes."
    ),
    K.CONSOLE_LOG: "**print.** Real debugging, in a compiled language.",
    K.VIBE_CHECK: "**if.** Runs the block when the vibes are LGTM.",
    K.SKILL_ISSUE: "**else.** For when the vibe check fails.",
    K.DOOMSCROLL: (
        "**while.** Keeps going while the condition holds. Or forever. Mostly forever."
    ),
    K.TOUCH_GRASS: "**break.** The only healthy way out of a doomscroll.",
    K.MICROSERVICE: "**function.** Independently deployable. Called from exactly one place.",
    K.SHIP_IT: "**return.** Straight to prod. Tests are a TODO.",
    K.LGTM: "**true.** Approved without reading.",
    K.NOT_FOUND: "**false.** Truth not found. Also the one number you can't type.",
}

NO_SLA = "I had to read your code to find out it's {}. Write an SLA."

WOMM = (
    "**Suppression.** Silences soft errors on the next statement "
    "and ships the bug to everyone else."
)


def todo(used: int) -> str:
    return f"**Comment.** The only kind allowed. Technical debt: {used}/{MAX_TODOS} TODOs used."


def sla(verdict: str) -> str:
    return f"**SLA.** Checked by counting nested doomscrolls. Verdict: {verdict}"


# Entry point


def hover(source: str, pos: Pos) -> tuple[str, Span] | None:
    """The Markdown hover for the position, and the span it covers."""
    tokens, comments, _ = driver.lex(source)
    program, _, _ = driver.check(source, "")
    for comment in comments:
        if comment.span.contains(pos):
            return comment_hover(comments, comment)
    for item in program.items:
        if isinstance(item, ast.Microservice) and item.big_o and item.big_o.span.contains(pos):
            return sla(annotation_verdict(program, item)), item.big_o.span
    token = token_at(tokens, pos)
    if token is None:
        return None
    if token.kind in KEYWORDS:
        return KEYWORDS[token.kind], token.span
    if token.kind is K.IDENT:
        node = name_at(program, pos)
        if node is not None and isinstance(node.sym, Symbol):
            return symbol_hover(program, node, node.sym), node.span
    return None


def token_at(tokens: list[Token], pos: Pos) -> Token | None:
    for token in tokens:
        if token.span.contains(pos):
            return token
    return None


def comment_hover(comments: list[Comment], comment: Comment) -> tuple[str, Span] | None:
    match comment.kind:
        case CommentKind.TODO:
            used = sum(c.kind is CommentKind.TODO for c in comments)
            return todo(used), comment.span
        case CommentKind.WOMM:
            return WOMM, comment.span
    return None  # a BAD comment already has its E406


# Identifiers


def name_at(node: object, pos: Pos) -> ast.Ident | ast.Var | None:
    """The Ident or Var under `pos` in the tree below `node`.

    Names are leaves and never overlap, so this walks the whole tree instead
    of pruning at nodes whose span misses `pos`: a desugared pipe stage (Call
    or Print) has the stage's span, which doesn't cover its first argument
    (Language Spec 9.4), so pruning would hide the `x` in `x | f`.
    """
    if isinstance(node, list):
        for child in node:
            if (found := name_at(child, pos)) is not None:
                return found
        return None
    if not isinstance(node, ast.Node):
        return None
    if isinstance(node, ast.Ident | ast.Var):
        return node if node.span.contains(pos) else None
    children = (f.name for f in fields(node) if f.name not in ("span", "sym", "ty", "comments"))
    for name in children:
        if (found := name_at(getattr(node, name), pos)) is not None:
            return found
    return None


def symbol_hover(program: ast.Program, node: ast.Ident | ast.Var, sym: Symbol) -> str:
    """The identifier rows of Language Spec 12."""
    ty = sym.ty.value
    match sym.kind:
        case SymbolKind.CONST:
            return (
                f"`npm install -g {sym.name}` · {ty} · global install, modifying it needs `sudo`"
            )
        case SymbolKind.GLOBAL | SymbolKind.LOCAL:
            line = sym.decl_span.start.line + 1
            text = f"`npm install {sym.name}` · {ty} · declared on line {line}"
            if sym.kind is SymbolKind.LOCAL and sym.owner != "serve":
                return text  # microservice locals have no history (Language Spec 9.3)
            n = min(1 + commits(program, sym), HISTORY_LIMIT)
            return f"{text} · {n} commit{'' if n == 1 else 's'}"
        case SymbolKind.PARAM:
            return f"parameter `{sym.name}` of `{sym.owner}` · {ty}"
        case SymbolKind.MICROSERVICE:
            ms = microservice_for(program, node, sym)
            if ms is None:
                return f"`microservice {sym.name}`"
            return microservice_hover(program, ms)


def commits(node: object, sym: Symbol) -> int:
    """The `git push --force` and `git revert` statements on `sym` below `node`."""
    if isinstance(node, list):
        return sum(commits(child, sym) for child in node)
    if not isinstance(node, ast.Node):
        return 0
    own = isinstance(node, ast.Assign | ast.Revert) and node.name.sym is sym
    children = (f.name for f in fields(node) if f.name not in ("span", "sym", "ty", "comments"))
    return own + sum(commits(getattr(node, name), sym) for name in children)


def microservice_for(
    program: ast.Program, node: ast.Ident | ast.Var, sym: Symbol
) -> ast.Microservice | None:
    """The microservice whose name is `node`, else the first one named like `sym`."""
    services = [item for item in program.items if isinstance(item, ast.Microservice)]
    for ms in services:
        if ms.name is node:
            return ms
    for ms in services:
        if ms.name.name == sym.name:
            return ms
    return None


# Big O


def inferred(program: ast.Program, ms: ast.Microservice) -> bigo.Degree:
    return bigo.Inference(program).microservice(ms).degree


def microservice_hover(program: ast.Program, ms: ast.Microservice) -> str:
    """`microservice total(n)` · SLA O(n) · inferred O(n) ✓"""
    params = ", ".join(p.name for p in ms.params)
    header = f"`microservice {ms.name.name}({params})`"
    d = inferred(program, ms)
    if ms.big_o is None:
        found = bigo.format_complexity(d)
        return f"{header} · no SLA · {NO_SLA.format(found)}"
    k, var = bigo.annotation(ms.big_o)
    found = bigo.format_complexity(d, var)
    if k is bigo.UNKNOWN:
        return f"{header} · SLA O({ms.big_o.text}) · inferred {found}"
    claimed = f"O({ms.big_o.text})" if k is bigo.SUPERPOLYNOMIAL else bigo.format_complexity(k, var)
    if d is bigo.UNKNOWN:
        return f"{header} · SLA {claimed} · inferred {found}"
    return f"{header} · SLA {claimed} · inferred {found} {'✓' if k == d else '✗'}"


def annotation_verdict(program: ast.Program, ms: ast.Microservice) -> str:
    """Correct, wrong (an under- or over-claim), O(?) for recursion, or
    unverifiable. Neither of the last two is checked."""
    assert ms.big_o is not None
    k, var = bigo.annotation(ms.big_o)
    d = inferred(program, ms)
    if d is bigo.UNKNOWN:
        return "O(?)."
    if k is bigo.UNKNOWN:
        return f"can't verify O({ms.big_o.text}). Inferred: {bigo.format_complexity(d, var)}."
    if k == d:
        return "Correct! Are you an arch user as well?"
    return "Go take a DSA course again."
