"""Language server (Implementation Spec 11), served over stdio by `btw-lsp`.

Diagnostics come from `driver.check` (lex, parse, check, Big O, suppression;
never codegen) on every didOpen, didChange and didSave. Hover text lives in
`hovers.py`. Code actions turn the diagnostics' quick fixes into edits,
semantic tokens give editors highlighting without a syntax file, and inlay
hints show the inferred O() of a microservice without an SLA. Completion
offers keyword snippets and the names in scope, and go to definition jumps to
the symbol's declaration. stdout is the protocol channel, so `main` points
`sys.stdout` at stderr before serving: a stray print can't corrupt the stream.
"""

from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Callable, Iterator
from dataclasses import fields
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from btw import ast, bigo, driver, hovers
from btw.checker import Symbol, SymbolKind
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span
from btw.tokens import TokenKind as K

log = logging.getLogger("btw.lsp")

server = LanguageServer("btw-lsp", "0.2.0", text_document_sync_kind=types.TextDocumentSyncKind.Full)

SEVERITY = {
    Severity.ERROR: types.DiagnosticSeverity.Error,
    Severity.WARNING: types.DiagnosticSeverity.Warning,
}


# Positions. Spans count UTF-16 code units; the client may have negotiated
# UTF-8 or UTF-32 instead (Neovim prefers UTF-8).


def source_lines(source: str) -> list[str]:
    return [line.removesuffix("\r") for line in source.split("\n")]


def width(char: str, encoding: str) -> int:
    match encoding:
        case types.PositionEncodingKind.Utf8:
            return len(char.encode("utf-8"))
        case types.PositionEncodingKind.Utf32:
            return 1
        case _:
            return 2 if ord(char) > 0xFFFF else 1


def to_client(lines: list[str], pos: Pos, encoding: str) -> types.Position:
    line = lines[pos.line] if pos.line < len(lines) else ""
    utf16 = units = 0
    for char in line:
        if utf16 >= pos.col:
            break
        utf16 += width(char, types.PositionEncodingKind.Utf16)
        units += width(char, encoding)
    return types.Position(line=pos.line, character=units + max(0, pos.col - utf16))


def from_client(lines: list[str], position: types.Position, encoding: str) -> Pos:
    line = lines[position.line] if position.line < len(lines) else ""
    utf16 = units = 0
    for char in line:
        if units >= position.character:
            break
        utf16 += width(char, types.PositionEncodingKind.Utf16)
        units += width(char, encoding)
    return Pos(position.line, utf16 + max(0, position.character - units))


def to_range(lines: list[str], span: Span, encoding: str) -> types.Range:
    return types.Range(
        start=to_client(lines, span.start, encoding), end=to_client(lines, span.end, encoding)
    )


# Diagnostics


def check(source: str) -> list[Diagnostic]:
    """btw's diagnostics for a document. Any exception becomes one E500."""
    try:
        _, _, diagnostics = driver.check(source, "")
    except Exception:
        log.exception("check failed")
        return [driver.internal_error(source)]
    return diagnostics


def to_lsp(
    diagnostic: Diagnostic, uri: str, lines: list[str], encoding: str
) -> types.Diagnostic:
    return types.Diagnostic(
        range=to_range(lines, diagnostic.span, encoding),
        severity=SEVERITY[diagnostic.severity],
        code=diagnostic.code,
        source="btw",
        message=diagnostic.message,
        related_information=[
            types.DiagnosticRelatedInformation(
                location=types.Location(uri=uri, range=to_range(lines, span, encoding)),
                message=message,
            )
            for span, message in diagnostic.related
        ]
        or None,
    )


def encoding(ls: LanguageServer) -> str:
    return ls.workspace.position_encoding or types.PositionEncodingKind.Utf16


def publish(ls: LanguageServer, uri: str, source: str, diagnostics: list[Diagnostic]) -> None:
    lines = source_lines(source)
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(
            uri=uri,
            diagnostics=[to_lsp(d, uri, lines, encoding(ls)) for d in diagnostics],
        )
    )


def guarded(handler: Callable[[LanguageServer, Any], Any]) -> Callable[[LanguageServer, Any], Any]:
    """Turn an exception in a handler into one E500 on its document, instead of
    killing the server or failing the request."""

    @functools.wraps(handler)
    def wrapper(ls: LanguageServer, params: Any) -> Any:
        try:
            return handler(ls, params)
        except Exception:
            log.exception("%s failed", handler.__name__)
            uri = params.text_document.uri
            source = ls.workspace.get_text_document(uri).source
            publish(ls, uri, source, [driver.internal_error(source)])
            return None

    return wrapper


def refresh(ls: LanguageServer, uri: str) -> None:
    source = ls.workspace.get_text_document(uri).source
    publish(ls, uri, source, check(source))


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
@guarded
def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    refresh(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
@guarded
def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    refresh(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
@guarded
def did_save(ls: LanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    refresh(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
@guarded
def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
    )


# Code actions (P2): the quick fixes the diagnostics carry


def overlaps(span: Span, start: Pos, end: Pos) -> bool:
    """Whether a requested range touches a diagnostic. An empty range is a
    cursor: it touches the characters it sits on, and empty spans at it."""
    if span.start == span.end:
        return start <= span.start <= end
    return span.start <= end and start < span.end


@server.feature(
    types.TEXT_DOCUMENT_CODE_ACTION,
    types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
)
@guarded
def code_action(ls: LanguageServer, params: types.CodeActionParams) -> list[types.CodeAction]:
    uri = params.text_document.uri
    source = ls.workspace.get_text_document(uri).source
    lines = source_lines(source)
    start = from_client(lines, params.range.start, encoding(ls))
    end = from_client(lines, params.range.end, encoding(ls))
    actions = []
    for diagnostic in check(source):
        if not diagnostic.fixes or not overlaps(diagnostic.span, start, end):
            continue
        for fix in diagnostic.fixes:
            edits = [
                types.TextEdit(range=to_range(lines, edit.span, encoding(ls)), new_text=edit.text)
                for edit in fix.edits
            ]
            actions.append(
                types.CodeAction(
                    title=fix.title,
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=[to_lsp(diagnostic, uri, lines, encoding(ls))],
                    edit=types.WorkspaceEdit(changes={uri: edits}),
                )
            )
    return actions


# Semantic tokens (P2): highlighting without a syntax file

TOKEN_TYPES = ["keyword", "variable", "function", "parameter", "number", "string", "comment", "operator"]
TOKEN_MODIFIERS = ["readonly"]
LEGEND = types.SemanticTokensLegend(token_types=TOKEN_TYPES, token_modifiers=TOKEN_MODIFIERS)

KEYWORD_KINDS = {
    K.ARCH, K.SERVE, K.LOCALHOST, K.WQ, K.NPM_INSTALL_G, K.NPM_INSTALL, K.SUDO,
    K.GIT_PUSH_FORCE, K.GIT_PUSH_NO_FORCE, K.GIT_REVERT, K.GIT_LOG, K.VIBE_CHECK,
    K.SKILL_ISSUE, K.DOOMSCROLL, K.TOUCH_GRASS, K.MICROSERVICE, K.SHIP_IT, K.LGTM,
    K.NOT_FOUND,
}  # every keyword but console.log and curl, functions like in the TextMate grammar
OPERATOR_KINDS = {
    K.PLUS, K.MINUS, K.STAR, K.SLASH, K.PERCENT, K.EQ_EQ, K.BANG_EQ, K.LT, K.LE,
    K.GT, K.GE, K.AND_AND, K.OR_OR, K.BANG, K.EQ, K.PIPE, K.CARET,
}
SYMBOL_TYPES = {
    SymbolKind.LOCAL: "variable",
    SymbolKind.GLOBAL: "variable",
    SymbolKind.CONST: "variable",
    SymbolKind.PARAM: "parameter",
    SymbolKind.MICROSERVICE: "function",
}
BIG_O_FUNCTIONS = {"O", "log"}


def names(node: object) -> Iterator[ast.Ident | ast.Var]:
    """Every Ident and Var in the tree below `node`."""
    if isinstance(node, list):
        for child in node:
            yield from names(child)
    elif isinstance(node, ast.Ident | ast.Var):
        yield node
    elif isinstance(node, ast.Node):
        for f in fields(node):
            if f.name not in ("span", "sym", "ty", "comments"):
                yield from names(getattr(node, f.name))


def classify(source: str) -> list[tuple[Span, str, bool]]:
    """(span, token type, readonly) for everything worth highlighting, in order.

    Keywords, numbers, strings, operators and comments come from the lexer.
    Names take their symbol's kind from the checked AST: a constant is a
    readonly variable, and a name the checker couldn't resolve is a plain
    variable. Inside a Big O annotation, `O` and `log` are functions and the
    size variable is a parameter.
    """
    tokens, comments, _ = driver.lex(source)
    program, _, _ = driver.check(source, "")
    symbols: dict[Span, Symbol] = {
        node.span: node.sym for node in names(program) if isinstance(node.sym, Symbol)
    }
    annotations = [
        item.big_o.span
        for item in program.items
        if isinstance(item, ast.Microservice) and item.big_o is not None
    ]
    found: list[tuple[Span, str, bool]] = [(c.span, "comment", False) for c in comments]
    for token in tokens:
        match token.kind:
            case K.CONSOLE_LOG | K.CURL:
                found.append((token.span, "function", False))
            case kind if kind in KEYWORD_KINDS:
                found.append((token.span, "keyword", False))
            case kind if kind in OPERATOR_KINDS:
                found.append((token.span, "operator", False))
            case K.INT:
                found.append((token.span, "number", False))
            case K.STRING:
                found.append((token.span, "string", False))
            case K.IDENT if any(a.contains(token.span.start) for a in annotations):
                kind = "function" if token.text in BIG_O_FUNCTIONS else "parameter"
                found.append((token.span, kind, False))
            case K.IDENT:
                sym = symbols.get(token.span)
                if sym is None:
                    found.append((token.span, "variable", False))
                else:
                    found.append((token.span, SYMBOL_TYPES[sym.kind], sym.kind is SymbolKind.CONST))
    return sorted(found, key=lambda entry: entry[0].start)


def encode(lines: list[str], classified: list[tuple[Span, str, bool]], encoding: str) -> list[int]:
    """The LSP's relative five-integer encoding. Tokens can't span lines, so
    one that does (nothing in btw should) is left out."""
    data: list[int] = []
    previous = types.Position(line=0, character=0)
    for span, kind, readonly in classified:
        if span.start.line != span.end.line or span.start == span.end:
            continue
        start, end = to_client(lines, span.start, encoding), to_client(lines, span.end, encoding)
        delta_line = start.line - previous.line
        delta_start = start.character - (previous.character if delta_line == 0 else 0)
        data += [delta_line, delta_start, end.character - start.character,
                 TOKEN_TYPES.index(kind), int(readonly)]
        previous = start
    return data


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL, LEGEND)
@guarded
def semantic_tokens(ls: LanguageServer, params: types.SemanticTokensParams) -> types.SemanticTokens:
    source = ls.workspace.get_text_document(params.text_document.uri).source
    return types.SemanticTokens(data=encode(source_lines(source), classify(source), encoding(ls)))


# Inlay hints (P2): the inferred O() of a microservice without an SLA


def inferred_hints(source: str) -> list[tuple[Pos, str, str | None]]:
    """(position just after the `)`, label, text to insert) for each
    unannotated microservice. The label is the W102 spelling (O(n), O(n²),
    O(?) when recursive); the text is what Add SLA inserts (O(n^2)), or None
    for O(?), which isn't a valid SLA."""
    tokens, program = driver.lex(source)[0], driver.check(source, "")[0]
    inference = bigo.Inference(program)
    hints = []
    for item in program.items:
        if not isinstance(item, ast.Microservice) or item.big_o is not None:
            continue
        close = bigo.params_close(tokens, item)
        if close is None:
            continue
        degree = inference.microservice(item).degree
        text = None if degree is bigo.UNKNOWN else bigo.format_complexity(degree, source=True)
        hints.append((close.end, bigo.format_complexity(degree), text))
    return hints


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
@guarded
def inlay_hint(ls: LanguageServer, params: types.InlayHintParams) -> list[types.InlayHint]:
    source = ls.workspace.get_text_document(params.text_document.uri).source
    lines = source_lines(source)
    start = from_client(lines, params.range.start, encoding(ls))
    end = from_client(lines, params.range.end, encoding(ls))
    hints = []
    for pos, label, text in inferred_hints(source):
        if not start <= pos <= end:
            continue
        position = to_client(lines, pos, encoding(ls))
        edit = types.TextEdit(range=types.Range(start=position, end=position), new_text=f" {text}")
        hints.append(
            types.InlayHint(
                position=position,
                label=label,
                kind=types.InlayHintKind.Type,
                padding_left=True,
                tooltip="Inferred by the Big O checker. Write it down as an SLA.",
                text_edits=[edit] if text is not None else None,
            )
        )
    return hints


# Hover


@server.feature(types.TEXT_DOCUMENT_HOVER)
@guarded
def hover(ls: LanguageServer, params: types.HoverParams) -> types.Hover | None:
    source = ls.workspace.get_text_document(params.text_document.uri).source
    lines = source_lines(source)
    found = hovers.hover(source, from_client(lines, params.position, encoding(ls)))
    if found is None:
        return None
    text, span = found
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=text),
        range=to_range(lines, span, encoding(ls)),
    )


# Completion and go to definition


SNIPPETS = {
    "i use arch btw": "i use arch btw",
    "serve localhost:3000": "serve localhost:3000 {\n\t$0\n}",
    ":wq": ":wq",
    "microservice": "microservice ${1:name}($2) {\n\t$0\n}",
    "npm install": "npm install ${1:name} = $0",
    "npm install -g": "npm install -g ${1:NAME} = $0",
    "git push --force": "git push --force ${1:name} = $0",
    "git revert": "git revert $0",
    "git log": "git log $0",
    "sudo": "sudo ",
    "console.log": "console.log $0",
    "vibe check": "vibe check $1 {\n\t$0\n}",
    "skill issue": "skill issue {\n\t$0\n}",
    "doomscroll": "doomscroll $1 {\n\t$0\n}",
    "touch grass": "touch grass",
    "ship it": "ship it $0",
    "LGTM": "LGTM",
    "404": "404",
    "curl": "curl",
}

COMPLETION_KINDS = {
    SymbolKind.LOCAL: types.CompletionItemKind.Variable,
    SymbolKind.GLOBAL: types.CompletionItemKind.Variable,
    SymbolKind.CONST: types.CompletionItemKind.Constant,
    SymbolKind.PARAM: types.CompletionItemKind.Variable,
    SymbolKind.MICROSERVICE: types.CompletionItemKind.Function,
}


def locals_before(block: ast.Block, pos: Pos) -> Iterator[Symbol]:
    """Locals declared in `block`, or in a nested block around `pos`, before `pos`."""
    for stmt in block.stmts:
        if stmt.span.start >= pos:
            return
        if isinstance(stmt, ast.VarDecl) and stmt.span.end <= pos:
            if isinstance(stmt.name.sym, Symbol):
                yield stmt.name.sym
        for f in fields(stmt):
            child = getattr(stmt, f.name)
            while isinstance(child, ast.If) and not child.then.span.contains(pos):
                child = child.else_  # walk down `skill issue vibe check` chains
            if isinstance(child, ast.If):
                child = child.then
            if isinstance(child, ast.Block) and child.span.contains(pos):
                yield from locals_before(child, pos)


def in_scope(source: str, pos: Pos) -> list[Symbol]:
    """Every name usable at `pos`: globals, constants and microservices, then the
    parameters and earlier locals of the microservice or `serve` around it."""
    program, symbols, _ = driver.check(source, "")
    names = list(symbols.globals.values())
    for item in program.items:
        if isinstance(item, ast.Microservice | ast.Serve) and item.body.span.contains(pos):
            if isinstance(item, ast.Microservice):
                names += [p.sym for p in item.params if isinstance(p.sym, Symbol)]
            names += locals_before(item.body, pos)
    return names


def completions(source: str, pos: Pos) -> list[types.CompletionItem]:
    items = [
        types.CompletionItem(
            label=label,
            kind=types.CompletionItemKind.Keyword,
            insert_text=snippet,
            insert_text_format=types.InsertTextFormat.Snippet,
        )
        for label, snippet in SNIPPETS.items()
    ]
    for sym in in_scope(source, pos):
        is_ms = sym.kind is SymbolKind.MICROSERVICE
        detail = f"microservice/{sym.arity}" if is_ms else sym.ty.value
        kind = COMPLETION_KINDS[sym.kind]
        items.append(types.CompletionItem(label=sym.name, kind=kind, detail=detail))
    return items


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
@guarded
def completion(ls: LanguageServer, params: types.CompletionParams) -> list[types.CompletionItem]:
    source = ls.workspace.get_text_document(params.text_document.uri).source
    return completions(source, from_client(source_lines(source), params.position, encoding(ls)))


def definition(source: str, pos: Pos) -> Span | None:
    """The declaration of the name under `pos`: the symbol's `decl_span`."""
    program, _, _ = driver.check(source, "")
    node = hovers.name_at(program, pos)
    if node is None or not isinstance(node.sym, Symbol):
        return None
    return node.sym.decl_span


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
@guarded
def goto_definition(ls: LanguageServer, params: types.DefinitionParams) -> types.Location | None:
    uri = params.text_document.uri
    source = ls.workspace.get_text_document(uri).source
    lines = source_lines(source)
    span = definition(source, from_client(lines, params.position, encoding(ls)))
    if span is None:
        return None
    return types.Location(uri=uri, range=to_range(lines, span, encoding(ls)))


def main() -> None:
    """The `btw-lsp` entry point: serve stdio until the client says exit."""
    # WARNING, not INFO: pygls logs every message at INFO, and Neovim files all
    # of a server's stderr under [ERROR] in its LSP log.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format="btw-lsp %(levelname)s %(name)s: %(message)s",
    )
    protocol = sys.stdout.buffer
    sys.stdout = sys.stderr  # nothing but the protocol may reach the real stdout
    server.start_io(sys.stdin.buffer, protocol)
