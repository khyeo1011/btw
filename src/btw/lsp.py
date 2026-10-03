"""Language server (Implementation Spec 11), served over stdio by `btw-lsp`.

Diagnostics come from `driver.check` (lex, parse, check, Big O, suppression;
never codegen) on every didOpen, didChange and didSave. Hover text lives in
`hovers.py`. stdout is the protocol channel, so `main` points `sys.stdout` at
stderr before serving: a stray print can't corrupt the stream.
"""

from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Callable
from typing import Any

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from btw import driver, hovers
from btw.diagnostics import Diagnostic, Severity
from btw.span import Pos, Span

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
