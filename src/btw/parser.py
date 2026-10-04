"""The parser (Implementation Spec 6, Language Spec 3 and 4).

`parse(tokens, comments)` returns `(program, diagnostics)` and never raises.
Besides E400 it reports the two things only it can see in the token stream:
E408 for a missing `:wq` and W208 for a repeated arch line.
Recursive descent for items and statements, Pratt parsing for expressions.

Recovery follows matklad's "Resilient LL Parsing": every statement and item
gets one E400 at most, a broken statement is skipped up to the end of its
line (or a `}`), and a missing expression becomes an ErrorExpr so the
surrounding declaration still happens.
"""

import dataclasses
from enum import Enum

from btw import ast
from btw.diagnostics import Diagnostic, Edit, Fix, Severity
from btw.span import Pos, Span
from btw.tokens import Comment, Token, TokenKind as K

# How keywords and symbols appear in messages: single spaces between words,
# whatever the source has (Language Spec 4).
SPELLING: dict[K, str] = {
    K.ARCH: "i use arch btw",
    K.SERVE: "serve",
    K.WQ: ":wq",
    K.NPM_INSTALL_G: "npm install -g",
    K.NPM_INSTALL: "npm install",
    K.SUDO: "sudo",
    K.GIT_PUSH_FORCE: "git push --force",
    K.GIT_PUSH_NO_FORCE: "git push",
    K.GIT_REVERT: "git revert",
    K.GIT_LOG: "git log",
    K.GIT_BLAME: "git blame",
    K.CONSOLE_LOG: "console.log",
    K.VIBE_CHECK: "vibe check",
    K.SKILL_ISSUE: "skill issue",
    K.DOOMSCROLL: "doomscroll",
    K.TOUCH_GRASS: "touch grass",
    K.MICROSERVICE: "microservice",
    K.SHIP_IT: "ship it",
    K.LGTM: "LGTM",
    K.NOT_FOUND: "404",
    K.CURL: "curl",
}

# Tokens that can only start a statement, so at top level they get the
# "outside a `microservice` or `serve`" message (Language Spec 4).
STATEMENT_ONLY = {
    K.CONSOLE_LOG,
    K.GIT_PUSH_FORCE,
    K.SUDO,
    K.VIBE_CHECK,
    K.DOOMSCROLL,
    K.TOUCH_GRASS,
    K.SHIP_IT,
    K.GIT_REVERT,
    K.GIT_LOG,
    K.GIT_BLAME,
}

ITEM_START = {K.NPM_INSTALL, K.NPM_INSTALL_G, K.MICROSERVICE, K.SERVE}

EXPR_START = {K.INT, K.STRING, K.LGTM, K.NOT_FOUND, K.CURL, K.IDENT, K.LPAREN, K.BANG, K.MINUS}

# Binary operators: precedence level (Language Spec 3.1) and whether the
# level is non-associative. Pipes (level 1) are handled apart, in `expr`.
PIPE_LEVEL = 1
INFIX: dict[K, tuple[int, bool]] = {
    K.OR_OR: (2, False),
    K.AND_AND: (3, False),
    K.EQ_EQ: (4, True),
    K.BANG_EQ: (4, True),
    K.LT: (5, True),
    K.LE: (5, True),
    K.GT: (5, True),
    K.GE: (5, True),
    K.PLUS: (6, False),
    K.MINUS: (6, False),
    K.STAR: (7, False),
    K.SLASH: (7, False),
    K.PERCENT: (7, False),
}
PREFIX_LEVEL = 8

# Words from other languages: (words, btw form, roast), Language Spec 13. WORD
# in a roast stands for the word as written, in backticks.
FOREIGN_ROASTS = [
    (("if",), "vibe check", "`if` is a boomer conditional. Use `vibe check`."),
    (
        ("else",),
        "skill issue",
        "`else`? That's a `skill issue`. Literally, type `skill issue`.",
    ),
    (
        ("while", "for"),
        "doomscroll",
        "Nobody uses WORD anymore. Use `doomscroll`, like it's 2am.",
    ),
    (("break",), "touch grass", "Don't `break`. Go `touch grass`."),
    (("return",), "ship it", "No returns, only deploys. Use `ship it`."),
    (("let", "var"), "npm install", "WORD? Real variables come from `npm install`."),
    (
        ("const",),
        "npm install -g",
        "`const` is just a global install. Use `npm install -g`.",
    ),
    (
        ("function", "def", "fn", "func"),
        "microservice",
        "WORD is a monolith mindset. Use `microservice`.",
    ),
    (
        ("print", "printf", "echo", "puts"),
        "console.log",
        "WORD? Real developers debug with `console.log`.",
    ),
]
FOREIGN: dict[str, tuple[str, str]] = {
    word: (form, roast.replace("WORD", f"`{word}`"))
    for words, form, roast in FOREIGN_ROASTS
    for word in words
}
# Foreign words that also roast before `(...) {`, like `if (x > 1) {`.
FOREIGN_PAREN = {"if", "while", "for"}
# What can follow a foreign word at the start of a statement, but never an
# expression: the roast only replaces an E400 the statement gets anyway.
NOT_AN_EXPR_TAIL = {K.IDENT, K.INT, K.STRING, K.BANG, K.LBRACE, *SPELLING}

CHAINED = "Chained comparisons aren't a thing here. This isn't Python."
SUDO_MISUSE = "`sudo` only works with `git push --force` and `git revert`."
E408 = "Error: program never exited. Classic Vim user."
W208 = "208 Already Reported: we know you use Arch."
UNCLOSED_PAREN_JOKE = "Even Lisp programmers close their parentheses."
E500 = "It works on my machine. Unfortunately, this is not my machine."
SPRING_BOOT = "Error: port 8080 is already in use by a Spring Boot app you forgot about. Use 3000."
VOID_PIPE = "`console.log` returns nothing. It's void, like my weekend plans."


@dataclasses.dataclass
class _PipePrint(ast.ErrorExpr):
    """A pipeline ending in `console.log` (Language Spec 9.4), before the parser knows
    where it stands. As a whole expression statement it becomes a Print; anywhere else
    it's E405 and an ErrorExpr. It never reaches the AST.
    """

    value: ast.Expr = dataclasses.field(kw_only=True)
    keyword: Span = dataclasses.field(kw_only=True)  # the `console.log` stage


def found(tok: Token) -> str:
    """The "found WHAT" part of an E400 message (Language Spec 11)."""
    match tok.kind:
        case K.NEWLINE:
            return "end of line"
        case K.EOF:
            return "end of file"
        case K.IDENT:
            return f"`{tok.text}`, whoever that is"
        case K.INT:
            return f"a magic number `{tok.text}`"
        case K.STRING:
            return "a hardcoded string"
        case _:
            return f"`{SPELLING.get(tok.kind, tok.text)}`"


class _Parser:
    def __init__(self, tokens: list[Token]):
        if not tokens or tokens[-1].kind is not K.EOF:
            end = tokens[-1].span.end if tokens else Pos(0, 0)
            tokens = [*tokens, Token(K.EOF, "", Span(end, end))]
        self.toks = tokens
        self.i = 0
        self.diags: list[Diagnostic] = []
        self.items: list[ast.Item] = []
        self.has_arch = False
        self.seen_arch = False  # any arch line so far: every later one is W208
        self.errored = False  # the current statement or item already has its E400
        self.reported: set[Pos] = set()  # tokens that already carry a parser E400
        self.prev_end = tokens[0].span.start  # end of the last token consumed

    # Cursor

    def peek(self, n: int = 0) -> Token:
        return self.toks[min(self.i + n, len(self.toks) - 1)]

    def at(self, *kinds: K) -> bool:
        return self.peek().kind in kinds

    def advance(self) -> Token:
        tok = self.peek()
        if tok.kind is not K.EOF:
            self.i += 1
            if tok.kind is not K.NEWLINE:
                self.prev_end = tok.span.end
        return tok

    def skip_newlines(self) -> None:
        while self.at(K.NEWLINE):
            self.advance()

    def skip_until(self, *kinds: K) -> None:
        """Skip tokens up to one of `kinds`. Always stops at `:wq` and the end of file."""
        while not self.at(K.EOF, K.WQ, *kinds):
            self.advance()

    def line_start(self) -> bool:
        return self.i == 0 or self.toks[self.i - 1].kind is K.NEWLINE

    def span_from(self, start: Pos) -> Span:
        return Span(start, max(start, self.prev_end))

    # Errors

    def error(self, message: str, span: Span, fixes: list[Fix] | None = None) -> None:
        """Report an E400, unless this statement or item already has one."""
        if self.errored:
            return
        self.errored = True
        if span.start in self.reported:
            return
        self.reported.add(span.start)
        self.diags.append(
            Diagnostic("E400", Severity.ERROR, message, span, fixes=fixes or [])
        )

    def unexpected(self, expected: str) -> None:
        tok = self.peek()
        if tok.kind in (K.ERROR, K.GIT_PUSH_NO_FORCE):
            self.errored = True  # the lexer already reported this token
            return
        self.error(f"Syntax error: expected {expected}, found {found(tok)}.", tok.span)

    def roast_foreign(self) -> None:
        """E400 on a word from another language, with a fix that swaps in the btw form."""
        tok = self.peek()
        form, roast = FOREIGN[tok.text]
        self.error(roast, tok.span, [Fix(f"Use {form}", [Edit(tok.span, form)])])

    def foreign_statement(self) -> bool:
        """Whether a statement starts with a foreign word in a shape that can't be an
        expression statement (Language Spec 13)."""
        tok, nxt = self.peek(), self.peek(1)
        if tok.text not in FOREIGN:
            return False
        if nxt.kind in NOT_AN_EXPR_TAIL:
            return True
        if tok.text not in FOREIGN_PAREN or nxt.kind is not K.LPAREN:
            return False
        depth, j = 0, self.i + 1
        while self.toks[j].kind not in (K.EOF, K.WQ):
            if self.toks[j].kind is K.LPAREN:
                depth += 1
            elif self.toks[j].kind is K.RPAREN:
                depth -= 1
                if depth == 0:
                    return self.toks[j + 1].kind is K.LBRACE
            j += 1
        return False

    def error_expr(self) -> ast.ErrorExpr:
        """A placeholder where an expression should have been."""
        pos = self.peek().span.start
        return ast.ErrorExpr(span=Span(pos, pos))

    # Program and items

    def program(self, comments: list[Comment]) -> ast.Program:
        self.skip_newlines()
        if self.at(K.ARCH):
            self.has_arch = True
            self.arch_line()
        wq_span = trailing_span = None
        while True:
            self.skip_newlines()
            tok = self.peek()
            if tok.kind is K.EOF:
                break
            if tok.kind is K.WQ:
                self.unclosed_paren()
                self.advance()
                wq_span = tok.span
                trailing_span = self.trailing()
                break
            start = self.i
            item = self.item()
            if item is not None:
                self.items.append(item)
            if self.i == start:
                self.advance()  # never loop without progress
        if wq_span is None:
            self.unclosed_paren()
            self.missing_wq()
        return self.finish(comments, wq_span, trailing_span)

    def arch_line(self) -> None:
        """Consume an arch line. Every one after the first is W208 (Language Spec 4)."""
        tok = self.advance()
        if self.seen_arch:
            self.diags.append(
                Diagnostic("W208", Severity.WARNING, W208, tok.span, soft=True)
            )
        self.seen_arch = True

    def unclosed_paren(self) -> None:
        """E400 on the token that ends the program (`:wq` or the end of file) when a `(`
        is still open there.

        The lexer drops every newline after an unclosed `(`, so whatever the parser
        reported along the way, this names the cause. It takes the place of any other
        E400 on the same token, such as the outermost block's missing `}`.
        """
        depth = 0
        for tok in self.toks[: self.i]:
            if tok.kind is K.LPAREN:
                depth += 1
            elif tok.kind is K.RPAREN:
                depth = max(0, depth - 1)  # the same count the lexer keeps
        if depth == 0:
            return
        end = self.peek()
        message = (
            f"Syntax error: expected `)`, found {found(end)}. {UNCLOSED_PAREN_JOKE}"
        )
        self.diags = [
            d
            for d in self.diags
            if not (d.code == "E400" and d.span.start == end.span.start)
        ]
        self.diags.append(Diagnostic("E400", Severity.ERROR, message, end.span))
        self.reported.add(end.span.start)

    def finish(
        self, comments: list[Comment], wq_span: Span | None, trailing_span: Span | None
    ) -> ast.Program:
        span = Span(Pos(0, 0), self.toks[-1].span.end)
        return ast.Program(
            self.items, self.has_arch, wq_span, trailing_span, list(comments), span=span
        )

    def trailing(self) -> Span | None:
        """Everything after `:wq`, for E410: from the first real token to the end of file."""
        first = None
        while not self.at(K.EOF):
            tok = self.advance()
            if first is None and tok.kind is not K.NEWLINE:
                first = tok
        if first is None:
            return None
        return Span(first.span.start, self.peek().span.end)

    def missing_wq(self) -> None:
        """E408 on the last token that isn't a newline or the end of file (Language Spec 4).

        Its quick fix (P2) puts `:wq` on a line of its own after that token's
        line: at the newline that ends it (after any trailing comment), or at
        the end of file.
        """
        last, end = self.toks[-1], self.toks[-1]
        for i in range(len(self.toks) - 1, -1, -1):
            if self.toks[i].kind not in (K.NEWLINE, K.EOF):
                last, end = self.toks[i], self.toks[i + 1]
                break
        at = Span(end.span.start, end.span.start)
        if end.kind is K.NEWLINE:
            text = "\n:wq"
        else:
            text = ":wq\n" if end.span.start.col == 0 else "\n:wq\n"
        fix = Fix("Exit Vim", [Edit(at, text)])
        self.diags.append(
            Diagnostic("E408", Severity.ERROR, E408, last.span, fixes=[fix])
        )

    def item(self) -> ast.Item | None:
        saved, self.errored = self.errored, False
        tok = self.peek()
        node: ast.Item | None = None
        match tok.kind:
            case K.NPM_INSTALL | K.NPM_INSTALL_G:
                node = self.global_decl()
            case K.MICROSERVICE:
                node = self.microservice()
            case K.SERVE:
                node = self.serve()
            case K.ARCH:
                self.arch_line()
            case kind if kind in STATEMENT_ONLY:
                self.error(
                    f"Syntax error: `{SPELLING[kind]}` outside a `microservice` or `serve`. "
                    "Serverless still needs a server.",
                    tok.span,
                )
            case K.IDENT if tok.text in FOREIGN:
                self.roast_foreign()
            case _:
                self.unexpected("`microservice`, `serve` or `npm install`")
        if self.errored:
            self.sync_top()
        self.errored = saved
        return node

    def sync_top(self) -> None:
        """Skip to the next line that starts with an item keyword, or to `:wq`."""
        while not self.at(K.EOF, K.WQ):
            tok = self.peek()
            if tok.kind in ITEM_START and (
                self.line_start() or tok.kind in (K.MICROSERVICE, K.SERVE)
            ):
                return
            self.advance()

    def global_decl(self) -> ast.GlobalDecl | None:
        kw = self.advance()
        name = self.name()
        if name is None:
            return None
        value = self.binding_value()
        is_const = kw.kind is K.NPM_INSTALL_G
        return ast.GlobalDecl(name, is_const, value, span=self.span_from(kw.span.start))

    def microservice(self) -> ast.Microservice | None:
        kw = self.advance()
        name = self.name()
        if name is None:
            return None
        params = self.params()
        big_o = None
        tok = self.peek()
        if tok.kind is K.IDENT and tok.text == "O" and self.peek(1).kind is K.LPAREN:
            big_o = self.big_o()
        body = self.expect_block()
        return ast.Microservice(
            name, params, big_o, body, span=self.span_from(kw.span.start)
        )

    def params(self) -> list[ast.Ident]:
        params: list[ast.Ident] = []
        if not self.at(K.LPAREN):
            self.unexpected("`(`")
            return params
        self.advance()
        if self.at(K.RPAREN):
            self.advance()
            return params
        while True:
            param = self.name()
            if param is None:
                break
            params.append(param)
            if not self.at(K.COMMA):
                if not self.at(K.RPAREN):
                    self.unexpected("`)`")
                break
            self.advance()
        if not self.at(K.RPAREN):
            self.skip_until(K.RPAREN, K.LBRACE, K.NEWLINE)
        if self.at(K.RPAREN):
            self.advance()
        return params

    def big_o(self) -> ast.BigO:
        """`O(...)`: the degree for `O(1)`, `O(n)` and `O(n^k)`, otherwise unverifiable."""
        o = self.advance()
        lparen = self.advance()
        inner: list[Token] = []
        depth = 0
        while True:
            tok = self.peek()
            if tok.kind is K.RPAREN and depth == 0:
                break
            if tok.kind in (K.EOF, K.WQ, K.LBRACE, K.RBRACE, K.NEWLINE):
                self.unexpected("`)`")
                break
            depth += {K.LPAREN: 1, K.RPAREN: -1}.get(tok.kind, 0)
            inner.append(self.advance())
        closed = self.at(K.RPAREN)
        rparen = self.advance() if closed else None
        degree, var = classify_big_o(inner) if closed else (None, None)
        text = source_between(lparen, inner, rparen)
        return ast.BigO(degree, var, text, span=self.span_from(o.span.start))

    def serve(self) -> ast.Serve:
        kw = self.advance()
        port = 3000
        if self.at(K.LOCALHOST):
            tok = self.advance()
            port = tok.value if isinstance(tok.value, int) else 3000
            if port == 8080:  # the Language Spec 13 roast; other ports are accepted
                self.diags.append(
                    Diagnostic("E409", Severity.ERROR, SPRING_BOOT, tok.span)
                )
        else:
            self.unexpected("`localhost:3000`")
        body = self.expect_block()
        return ast.Serve(port, body, span=self.span_from(kw.span.start))

    # Blocks and statements

    def expect_block(self) -> ast.Block:
        """A block, after reporting and skipping anything before its `{`."""
        if not self.at(K.LBRACE):
            self.unexpected("`{`")
            j = self.i
            while self.toks[j].kind is K.NEWLINE:
                j += 1
            if self.toks[j].kind is K.LBRACE and j > self.i:
                self.i = (
                    j  # `{` on the next line: report it, then parse the block anyway
                )
            else:
                self.skip_until(K.LBRACE, K.NEWLINE, K.RBRACE)
            if not self.at(K.LBRACE):
                return ast.Block([], span=Span(self.prev_end, self.prev_end))
        return self.block()

    def block(self) -> ast.Block:
        lbrace = self.advance()
        stmts: list[ast.Stmt] = []
        while True:
            self.skip_newlines()
            tok = self.peek()
            if tok.kind is K.RBRACE:
                self.advance()
                break
            if tok.kind in (K.EOF, K.WQ, K.MICROSERVICE, K.SERVE):
                self.unexpected("`}`")  # close the block, leave the token to the caller
                break
            stmt = self.statement()
            if stmt is not None:
                stmts.append(stmt)
        return ast.Block(stmts, span=self.span_from(lbrace.span.start))

    def statement(self) -> ast.Stmt | None:
        saved, self.errored = self.errored, False
        start = self.i
        stmt = self.statement_body()
        if not self.errored and not self.at(K.NEWLINE, K.RBRACE, K.EOF):
            self.unexpected("end of line")
        if self.errored:
            self.sync_statement()
        if self.i == start and not self.at(K.RBRACE, K.EOF, K.WQ):
            self.advance()  # never loop without progress
        self.errored = saved
        return stmt

    def sync_statement(self) -> None:
        """Skip to the end of the line or the enclosing block's `}`, which stays.

        Braces opened while skipping are skipped up to their own `}`, so a broken
        `skill issue { ... }` can't close the block around it.
        """
        depth = 0
        while not self.at(K.EOF, K.WQ):
            kind = self.peek().kind
            if depth == 0 and kind in (K.NEWLINE, K.RBRACE):
                return
            if kind is K.LBRACE:
                depth += 1
            elif kind is K.RBRACE:
                depth -= 1
            self.advance()

    def statement_body(self) -> ast.Stmt | None:
        tok = self.peek()
        start = tok.span.start
        match tok.kind:
            case K.NPM_INSTALL | K.NPM_INSTALL_G:
                self.advance()
                name = self.name()
                if name is None:
                    return None
                value = self.binding_value()
                is_const = tok.kind is K.NPM_INSTALL_G
                return ast.VarDecl(name, is_const, value, span=self.span_from(start))
            case K.SUDO:
                return self.sudo()
            case K.GIT_PUSH_FORCE | K.GIT_PUSH_NO_FORCE:
                return self.assign(start, sudo=False)
            case K.GIT_REVERT:
                return self.revert(start, sudo=False)
            case K.GIT_LOG | K.GIT_BLAME:
                self.advance()
                target = self.target()
                node = ast.Log if tok.kind is K.GIT_LOG else ast.Blame
                return None if target is None else node(target, span=self.span_from(start))
            case K.VIBE_CHECK:
                return self.if_stmt()
            case K.DOOMSCROLL:
                self.advance()
                cond = self.expr()
                body = self.expect_block()
                return ast.While(cond, body, span=self.span_from(start))
            case K.TOUCH_GRASS:
                self.advance()
                return ast.Break(span=tok.span)
            case K.SHIP_IT:
                self.advance()
                value = None if self.at(K.NEWLINE, K.RBRACE, K.EOF) else self.expr()
                return ast.Return(value, span=self.span_from(start))
            case K.CONSOLE_LOG:
                self.advance()
                value = self.expr()
                return ast.Print(value, span=self.span_from(start))
            case K.ARCH:
                self.arch_line()
                return None
            case K.IDENT if self.foreign_statement():
                self.roast_foreign()
                return None
            case kind if kind in EXPR_START:
                expr = self.pipeline()
                if isinstance(expr, _PipePrint):
                    return ast.Print(expr.value, span=self.span_from(start))
                return ast.ExprStmt(expr, span=self.span_from(start))
            case K.LBRACE:
                # A stray block: report it, then parse it so its braces stay balanced.
                self.unexpected("a statement")
                self.block()
                return None
            case _:
                self.unexpected("a statement")
                return None

    def sudo(self) -> ast.Stmt | None:
        sudo = self.advance()
        tok = self.peek()
        match tok.kind:
            case K.GIT_PUSH_FORCE | K.GIT_PUSH_NO_FORCE:
                return self.assign(sudo.span.start, sudo=True)
            case K.GIT_REVERT:
                return self.revert(sudo.span.start, sudo=True)
            case K.ERROR:
                self.errored = True  # the lexer already reported it
            case _:
                self.error(SUDO_MISUSE, tok.span)
        if self.at(K.NEWLINE, K.RBRACE, K.EOF, K.WQ):
            return None
        # Parse what follows anyway, so its names still get checked.
        return self.statement_body()

    def assign(self, start: Pos, sudo: bool) -> ast.Assign | None:
        kw = self.advance()
        if kw.kind is K.GIT_PUSH_NO_FORCE:
            self.errored = True  # the lexer's E400 is this statement's one
        target = self.target()
        if target is None:
            return None
        value = self.binding_value()
        return ast.Assign(target, value, sudo, span=self.span_from(start))

    def revert(self, start: Pos, sudo: bool) -> ast.Revert | None:
        self.advance()
        target = self.target()
        if target is None:
            return None
        return ast.Revert(target, sudo, span=self.span_from(start))

    def if_stmt(self) -> ast.If:
        kw = self.advance()
        cond = self.expr()
        then = self.expect_block()
        else_: ast.Block | ast.If | None = None
        # Else lookahead: `skill issue` may start on a later line (Language Spec 3).
        j = self.i
        while self.toks[j].kind is K.NEWLINE:
            j += 1
        if self.toks[j].kind is K.SKILL_ISSUE:
            self.i = j
            self.advance()
            else_ = self.if_stmt() if self.at(K.VIBE_CHECK) else self.expect_block()
        return ast.If(cond, then, else_, span=self.span_from(kw.span.start))

    def name(self) -> ast.Ident | None:
        """A name at a declaration site. Reserved words are keyword tokens, so they fail here."""
        tok = self.peek()
        if tok.kind is K.IDENT:
            self.advance()
            return ast.Ident(tok.text, span=tok.span)
        self.unexpected("a name")
        return None

    def target(self) -> ast.Var | None:
        """The variable a statement uses: `git push --force x`, `git revert x`, `git log x`."""
        tok = self.peek()
        if tok.kind is K.IDENT:
            self.advance()
            return ast.Var(tok.text, span=tok.span)
        self.unexpected("a name")
        return None

    def binding_value(self) -> ast.Expr:
        """`= expr`. When either part is missing, an ErrorExpr keeps the binding alive."""
        if not self.at(K.EQ):
            self.unexpected("`=`")
            return self.error_expr()
        self.advance()
        return self.expr()

    # Expressions

    def expr(self, min_level: int = 0) -> ast.Expr:
        """An expression used as a value: a pipe into `console.log` is E405 here."""
        return self.void_check(self.pipeline(min_level))

    def void_check(self, expr: ast.Expr) -> ast.Expr:
        if isinstance(expr, _PipePrint):
            self.diags.append(
                Diagnostic("E405", Severity.ERROR, VOID_PIPE, expr.keyword)
            )
            return ast.ErrorExpr(span=expr.span)
        return expr

    def pipeline(self, min_level: int = 0) -> ast.Expr:
        """Pratt loop over binary operators of at least `min_level`, then pipe stages.

        The result can be a `_PipePrint`; only `statement_body` accepts one as is.
        """
        start = self.peek().span.start
        lhs = self.prefix()
        chained_level = None
        while True:
            op = self.peek()
            if op.kind is K.PIPE and min_level <= PIPE_LEVEL:
                return self.stages(start, lhs)
            if op.kind not in INFIX:
                break
            level, non_assoc = INFIX[op.kind]
            if level < min_level:
                break
            self.advance()
            rhs = self.expr(level + 1)
            span = self.span_from(start)
            if non_assoc and level == chained_level:
                self.error(CHAINED, op.span)
                lhs = ast.ErrorExpr(span=span)
            else:
                lhs = ast.Binary(op.text, lhs, rhs, span=span)
            chained_level = level if non_assoc else None
        return lhs

    def prefix(self) -> ast.Expr:
        tok = self.peek()
        match tok.kind:
            case K.BANG | K.MINUS:
                self.advance()
                operand = self.expr(PREFIX_LEVEL)
                return ast.Unary(tok.text, operand, span=self.span_from(tok.span.start))
            case K.INT:
                self.advance()
                value = tok.value if isinstance(tok.value, int) else 0
                return ast.IntLit(value, span=tok.span)
            case K.STRING:
                self.advance()
                value = tok.value if isinstance(tok.value, str) else ""
                return ast.StrLit(value, span=tok.span)
            case K.LGTM | K.NOT_FOUND:
                self.advance()
                return ast.BoolLit(tok.kind is K.LGTM, span=tok.span)
            case K.CURL:
                self.advance()
                return ast.Curl(span=tok.span)
            case K.IDENT:
                self.advance()
                if self.at(K.LPAREN):
                    return self.call(tok)
                return ast.Var(tok.text, span=tok.span)
            case K.LPAREN:
                # Grouping makes no node: the inner expression keeps its own span.
                self.advance()
                inner = self.expr()
                if self.at(K.RPAREN):
                    self.advance()
                else:
                    self.unexpected("`)`")
                return inner
            case _:
                self.unexpected("an expression")
                return self.error_expr()

    def stages(self, start: Pos, value: ast.Expr) -> ast.Expr:
        """`value | f | g(y) | console.log` (Language Spec 9.4).

        Each stage becomes a Call with the piped value as its first argument and the
        stage's own span; a final `console.log` makes a `_PipePrint`. Nothing but
        another `|` can follow a stage, since pipes have the lowest precedence.
        """
        while self.at(K.PIPE):
            self.advance()
            value = self.void_check(value)  # only the last stage may be `console.log`
            tok = self.peek()
            match tok.kind:
                case K.IDENT:
                    self.advance()
                    if self.at(K.LPAREN):
                        value = self.call(tok, first=value)
                    else:
                        callee = ast.Ident(tok.text, span=tok.span)
                        value = ast.Call(callee, [value], span=tok.span)
                case K.CONSOLE_LOG:
                    self.advance()
                    value = _PipePrint(
                        span=self.span_from(start), value=value, keyword=tok.span
                    )
                case _:
                    self.unexpected("a name")
                    return ast.ErrorExpr(span=self.span_from(start))
        return value

    def call(self, name: Token, first: ast.Expr | None = None) -> ast.Call:
        """`f(args)`. A pipe stage passes the piped value as `first`."""
        self.advance()  # (
        args: list[ast.Expr] = [] if first is None else [first]
        if not self.at(K.RPAREN):
            while True:
                args.append(self.expr())
                if not self.at(K.COMMA):
                    break
                self.advance()
        if self.at(K.RPAREN):
            self.advance()
        else:
            self.unexpected("`)`")
        callee = ast.Ident(name.text, span=name.span)
        return ast.Call(callee, args, span=self.span_from(name.span.start))


def classify_big_o(inner: list[Token]) -> tuple[int | None, str | None]:
    """(degree, variable) for `1`, `n` and `n^k`; (None, None) means unverifiable."""
    kinds = [t.kind for t in inner]
    if kinds == [K.INT] and inner[0].text == "1":
        return 0, None
    if kinds == [K.IDENT]:
        return 1, inner[0].text
    if kinds == [K.IDENT, K.CARET, K.INT] and isinstance(inner[2].value, int):
        return inner[2].value, inner[0].text
    return None, None


def source_between(lparen: Token, inner: list[Token], rparen: Token | None) -> str:
    """The source text between the parens, rebuilt from token spans.

    Gaps on one line become spaces (a tab inside an annotation comes back as a
    space); a line break, possible because newlines inside parens aren't
    tokens, becomes one space.
    """
    parts: list[str] = []
    prev = lparen.span.end
    for tok in inner:
        parts.append(gap(prev, tok.span.start))
        parts.append(tok.text)
        prev = tok.span.end
    if rparen is not None:
        parts.append(gap(prev, rparen.span.start))
    return "".join(parts)


def gap(a: Pos, b: Pos) -> str:
    if a.line == b.line:
        return " " * max(0, b.col - a.col)
    return " "


def parse(
    tokens: list[Token], comments: list[Comment] | None = None
) -> tuple[ast.Program, list[Diagnostic]]:
    """Parse a token stream that ends in EOF. Never raises."""
    comments = comments or []
    parser = _Parser(tokens)
    try:
        program = parser.program(comments)
    except Exception:  # a parser bug, or input nested deeper than the recursion limit
        parser.diags.append(
            Diagnostic("E500", Severity.ERROR, E500, Span(Pos(0, 0), Pos(0, 0)))
        )
        program = parser.finish(comments, None, None)
    return program, parser.diags


# Debug dump for `btw parse`


def format_ast(program: ast.Program) -> str:
    """An indented tree, one node per line: label, node kind, span, scalar fields."""
    lines: list[str] = []
    _dump(program, "", 0, lines)
    return "\n".join(lines) + "\n"


def format_span(span: Span) -> str:
    """1-based, like every position the CLI prints."""
    return f"{span.start.line + 1}:{span.start.col + 1}-{span.end.line + 1}:{span.end.col + 1}"


def _scalar(value: object) -> str:
    if isinstance(value, Span):
        return format_span(value)
    if isinstance(value, Enum):
        return value.name
    return repr(value)


def _dump(node: object, label: str, indent: int, lines: list[str]) -> None:
    pad = "  " * indent + (f"{label}: " if label else "")
    if isinstance(node, Comment):
        lines.append(
            f"{pad}Comment {format_span(node.span)} {node.kind.name} {node.text!r}"
        )
        return
    if not isinstance(node, ast.Node):
        lines.append(f"{pad}{_scalar(node)}")
        return
    scalars: list[str] = []
    children: list[tuple[str, object]] = []
    for f in dataclasses.fields(node):
        if f.name == "span":
            continue
        value = getattr(node, f.name)
        if f.name in ("ty", "sym") and value is None:
            continue
        if isinstance(value, list):
            children += [(f"{f.name}[{n}]", item) for n, item in enumerate(value)]
        elif isinstance(value, ast.Node):
            children.append((f.name, value))
        elif f.name == "sym":
            scalars.append(f"sym={getattr(value, 'name', type(value).__name__)}")
        else:
            scalars.append(f"{f.name}={_scalar(value)}")
    head = f"{pad}{type(node).__name__} {format_span(node.span)}"
    lines.append(" ".join([head, *scalars]))
    for child_label, child in children:
        _dump(child, child_label, indent + 1, lines)
