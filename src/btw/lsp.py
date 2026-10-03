"""Language server (Implementation Spec 11), served over stdio by `btw-lsp`.

Diagnostics come from `driver.check` (lex, parse, check, Big O, suppression;
never codegen) on every didOpen, didChange and didSave. Hover text lives in
`hovers.py`. Code actions turn the diagnostics' quick fixes into edits, and
semantic tokens give editors highlighting without a syntax file. stdout is the protocol channel, so `main` points `sys.stdout` at
stderr before serving: a stray print can't corrupt the stream.
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

from btw import ast, driver, hovers
from btw.checker import Symbol, SymbolKind
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span
from btw.tokens import TokenKind as K

log = logging.getLogger("btw.lsp")

server = LanguageServer("btw-lsp", "0.1.0", text_document_sync_kind=types.TextDocumentSyncKind.Full)

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
}  # every keyword but console.log, which is a function like in the TextMate grammar
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
            case K.CONSOLE_LOG:
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
