"""The language server over stdio (Implementation Spec 11), driven by a minimal
JSON-RPC client."""

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from btw import driver, lsp
from btw.span import Pos, Span

GOLDEN = Path(__file__).parent / "golden"
TIMEOUT = 10


class Client:
    """Content-Length framed JSON-RPC over the server's stdin and stdout."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "from btw.lsp import main; main()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self) -> None:
        stdout = self.proc.stdout
        while True:
            headers = {}
            while (line := stdout.readline()) not in (b"\r\n", b""):
                name, _, value = line.decode("ascii").partition(":")
                headers[name.strip().lower()] = value.strip()
            if not headers:
                return  # end of stream
            body = stdout.read(int(headers["content-length"]))
            self.messages.put(json.loads(body))  # anything else on stdout fails here

    def send(self, message: dict) -> None:
        body = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        self.send({"method": method, "params": params})

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self.send({"id": self.next_id, "method": method, "params": params})
        return self.wait(lambda m: m.get("id") == self.next_id and "method" not in m)

    def wait(self, matches) -> dict:
        while True:
            message = self.messages.get(timeout=TIMEOUT)
            if matches(message):
                return message

    def diagnostics(self, uri: str) -> list[dict]:
        message = self.wait(
            lambda m: m.get("method") == "textDocument/publishDiagnostics"
            and m["params"]["uri"] == uri
        )
        return message["params"]["diagnostics"]

    def close(self) -> int:
        self.request("shutdown")
        self.notify("exit")
        self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=TIMEOUT)
        finally:
            self.proc.kill()
            self.proc.stdout.close()
            self.proc.stderr.close()


@pytest.fixture
def client():
    c = Client()
    reply = c.request(
        "initialize",
        {
            "processId": None,
            "rootUri": None,
            "capabilities": {"general": {"positionEncodings": ["utf-16"]}},
        },
    )
    c.capabilities = reply["result"]["capabilities"]
    assert c.capabilities["hoverProvider"]
    c.notify("initialized", {})
    yield c
    if c.proc.poll() is None:
        assert c.close() == 0


def open_doc(client: Client, uri: str, text: str) -> None:
    client.notify(
        "textDocument/didOpen",
        {"textDocument": {"uri": uri, "languageId": "btw", "version": 1, "text": text}},
    )


def test_did_open_publishes_e426(client):
    uri = "file:///p0_e426_missing_arch.btw"
    source = (GOLDEN / "p0_e426_missing_arch.btw").read_text(encoding="utf-8")
    open_doc(client, uri, source)
    [diagnostic] = client.diagnostics(uri)
    assert diagnostic["range"]["start"] == {"line": 0, "character": 0}  # line 1
    assert diagnostic["severity"] == 1
    assert diagnostic["code"] == "E426"
    assert diagnostic["source"] == "btw"
    assert diagnostic["message"] == "Fatal: `i use arch btw` not found. Are you on Windows?"


def test_did_change_clears_it_and_hover_answers(client):
    uri = "file:///demo.btw"
    source = (GOLDEN / "p0_e426_missing_arch.btw").read_text(encoding="utf-8")
    open_doc(client, uri, source)
    assert [d["code"] for d in client.diagnostics(uri)] == ["E426"]
    fixed = "i use arch btw\n" + source
    client.notify(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": fixed}],
        },
    )
    assert client.diagnostics(uri) == []
    reply = client.request(
        "textDocument/hover",
        {"textDocument": {"uri": uri}, "position": {"line": 1, "character": 2}},
    )
    assert reply["result"]["contents"] == {
        "kind": "markdown",
        "value": "**main().** Every program is secretly a dev server. "
        "Nobody knows what else is running on port 3000.",
    }


# Positions: spans count UTF-16 code units, and the client may pick UTF-8.


def test_positions_convert_to_the_negotiated_encoding():
    lines = ['console.log "é😀" x']
    x = Pos(0, len('console.log "é😀" '.encode("utf-16-le")) // 2)
    assert x.col == 18  # the emoji is two UTF-16 code units
    assert lsp.to_client(lines, x, "utf-16").character == 18
    assert lsp.to_client(lines, x, "utf-8").character == 21
    assert lsp.to_client(lines, x, "utf-32").character == 17
    for encoding in ("utf-8", "utf-16", "utf-32"):
        assert lsp.from_client(lines, lsp.to_client(lines, x, encoding), encoding) == x


def test_positions_past_the_end_of_a_line():
    assert lsp.to_client(["ab"], Pos(0, 5), "utf-8").character == 5
    assert lsp.to_client([""], Pos(3, 1), "utf-8").character == 1


def test_an_exception_becomes_one_e500(monkeypatch):
    def boom(source, path):
        raise RuntimeError("boom")

    monkeypatch.setattr(driver, "check", boom)
    [diagnostic] = lsp.check("i use arch btw\n")
    assert diagnostic.code == "E500"
    assert diagnostic.message == "It works on my machine. Unfortunately, this is not my machine."


# Code actions (P2): the Quick fix column of Language Spec 11


def apply_edits(source: str, edits: list[dict]) -> str:
    """Apply LSP TextEdits to an ASCII source, last first."""
    lines = source.split("\n")

    def index(position: dict) -> int:
        return sum(len(line) + 1 for line in lines[: position["line"]]) + position["character"]

    for edit in sorted(edits, key=lambda e: index(e["range"]["start"]), reverse=True):
        start, end = index(edit["range"]["start"]), index(edit["range"]["end"])
        source = source[:start] + edit["newText"] + source[end:]
    return source


def code_actions(client: Client, uri: str, start: dict, end: dict) -> list[dict]:
    reply = client.request(
        "textDocument/codeAction",
        {
            "textDocument": {"uri": uri},
            "range": {"start": start, "end": end},
            "context": {"diagnostics": []},
        },
    )
    return reply["result"]


LOOP = " npm install i = 0\n doomscroll i < n { git push --force i = i + 1 }"
SERVE = "serve localhost:3000 {\n console.log 1\n}\n"


@pytest.mark.parametrize(
    "source, code, title",
    [
        (SERVE + ":wq\n", "E426", "Install Arch"),
        ("i use arch btw\n" + SERVE, "E408", "Exit Vim"),
        ("i use arch btw\n" + SERVE.removesuffix("\n"), "E408", "Exit Vim"),
        ("i use arch btw\n" + SERVE + "// TODO ship\n", "E408", "Exit Vim"),
        ("i use arch btw\nserve localhost:3000 { console.log 1 } // TODO\n", "E408", "Exit Vim"),
        (
            "i use arch btw\nnpm install -g C = 1\nserve localhost:3000 {\n"
            " git push --force C = 2\n}\n:wq\n",
            "E403",
            "Run with sudo",
        ),
        (
            "i use arch btw\nnpm install -g C = 1\nserve localhost:3000 {\n"
            " git push --force C = 2\n git revert C\n}\n:wq\n",
            "E403",
            "Run with sudo",
        ),
        (
            f"i use arch btw\nmicroservice f(n) O(1) {{\n{LOOP}\n}}\n{SERVE}:wq\n",
            "E417",
            "Update SLA to O(n)",
        ),
        (
            f"i use arch btw\nmicroservice f(n) {{\n{LOOP}\n}}\n{SERVE}:wq\n",
            "W102",
            "Add SLA O(n)",
        ),
        (
            "i use arch btw\nserve localhost:3000 {\n npm install x = 2\n"
            " if (x > 1) {\n  console.log x\n }\n}\n:wq\n",
            "E400",
            "Use vibe check",
        ),
        (
            "i use arch btw\nconst X = 1\nserve localhost:3000 {\n console.log 1\n}\n:wq\n",
            "E400",
            "Use npm install -g",
        ),
        ("i use arch btw\nserve localhost:3000 {\n console.log true\n}\n:wq\n", "E404", "Use LGTM"),
        ("i use arch btw\nserve localhost:3000 {\n console.log !null\n}\n:wq\n", "E404", "Use 404"),
        (
            "i use arch btw\nserve localhost:3000 {\n npm install x = 1\n git push x = 2\n}\n:wq\n",
            "E400",
            "Add --force",
        ),
        ("i use arch btw\n" + SERVE + ":wq\nconsole.log 2\n\n", "E410", "Delete it"),
        (
            "i use arch btw\nserve localhost:3000 {\n npm install x = 1\n"
            " sudo git push --force x = 2\n sudo git revert x\n}\n:wq\n",
            "W100",
            "Remove sudo",
        ),
    ],
    ids=["e426", "e408", "e408_no_final_newline", "e408_comment_line", "e408_trailing_comment",
         "e403_push", "e403_revert", "e417", "w102", "e400_foreign_if", "e400_foreign_const",
         "e404_foreign_true", "e404_foreign_null", "e400_add_force", "e410", "w100"],
)
def test_quick_fixes_round_trip(client, source, code, title):
    """Every diagnostic of `code` offers `title`, and applying all of them
    (one at a time, rechecking in between) leaves a clean program."""
    uri = "file:///fix.btw"
    open_doc(client, uri, source)
    diagnostics = client.diagnostics(uri)
    assert {d["code"] for d in diagnostics} == {code}
    version = 1
    while diagnostics:
        target = diagnostics[0]
        cursor = target["range"]["start"]
        actions = code_actions(client, uri, cursor, cursor)
        [action] = [a for a in actions if a["diagnostics"][0]["code"] == code]
        assert action["title"] == title
        assert action["kind"] == "quickfix"
        source = apply_edits(source, action["edit"]["changes"][uri])
        version += 1
        client.notify(
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": source}]},
        )
        # A fix can leave a variable unused (e400_foreign_const); W226 has no fix.
        diagnostics = [d for d in client.diagnostics(uri) if d["code"] != "W226"]
    _, _, after = driver.check(source, "fix.btw")
    assert all(d.code == "W226" for d in after)


def test_code_actions_only_for_the_requested_range(client):
    uri = "file:///range.btw"
    source = "i use arch btw\nnpm install -g C = 1\nserve localhost:3000 {\n git push --force C = 2\n}\n"
    open_doc(client, uri, source)
    assert {d["code"] for d in client.diagnostics(uri)} == {"E403", "E408"}
    line1 = code_actions(client, uri, {"line": 0, "character": 0}, {"line": 0, "character": 0})
    assert line1 == []
    e403 = code_actions(client, uri, {"line": 3, "character": 5}, {"line": 3, "character": 5})
    assert [a["title"] for a in e403] == ["Run with sudo"]
    everything = code_actions(client, uri, {"line": 0, "character": 0}, {"line": 5, "character": 0})
    assert [a["title"] for a in everything] == ["Run with sudo", "Exit Vim"]


def test_overlaps():
    span = lsp.Span(Pos(1, 2), Pos(1, 5))
    assert lsp.overlaps(span, Pos(1, 2), Pos(1, 2))
    assert lsp.overlaps(span, Pos(1, 4), Pos(1, 4))
    assert not lsp.overlaps(span, Pos(1, 5), Pos(1, 5))
    assert lsp.overlaps(span, Pos(0, 0), Pos(1, 2))
    empty = lsp.Span(Pos(2, 0), Pos(2, 0))
    assert lsp.overlaps(empty, Pos(2, 0), Pos(2, 0))
    assert not lsp.overlaps(empty, Pos(2, 1), Pos(2, 1))


# relatedInformation (P2): E417 points at the innermost loop, E409 at the first declaration


def related(diagnostic: dict) -> list[tuple[int, int, int, str]]:
    """(line, start character, end character, message) for each related location."""
    return [
        (
            info["location"]["range"]["start"]["line"],
            info["location"]["range"]["start"]["character"],
            info["location"]["range"]["end"]["character"],
            info["message"],
        )
        for info in diagnostic.get("relatedInformation") or []
    ]


def test_e417_related_is_the_innermost_loop(client):
    uri = "file:///p0_e417_big_o_underclaim.btw"
    open_doc(client, uri, (GOLDEN / "p0_e417_big_o_underclaim.btw").read_text(encoding="utf-8"))
    [e417] = client.diagnostics(uri)
    assert e417["code"] == "E417"
    assert related(e417) == [(5, 8, 18, "nested doomscroll #2 starts here")]
    assert e417["relatedInformation"][0]["location"]["uri"] == uri


def test_e409_related_is_the_first_declaration(client):
    uri = "file:///p0_e409_already_installed.btw"
    open_doc(client, uri, (GOLDEN / "p0_e409_already_installed.btw").read_text(encoding="utf-8"))
    x, limit = [d for d in client.diagnostics(uri) if d["code"] == "E409"]
    assert related(x) == [(3, 16, 17, "`x` was first installed here")]
    assert related(limit) == [(1, 15, 20, "`LIMIT` was first installed here")]


@pytest.mark.parametrize(
    "items, expected",
    [
        ("microservice f() {\n}\nmicroservice f() {\n}\n", (1, 13, 14, "`f` was first deployed here")),
        ("npm install f = 1\nmicroservice f() {\n}\n", (1, 12, 13, "`f` was first installed here")),
        ("npm install x = 1\nnpm install x = 2\n", (1, 12, 13, "`x` was first installed here")),
        ("microservice f(n, n) O(1) {\n}\n", (1, 15, 16, "`n` was first installed here")),
        ("microservice f(f) O(1) {\n}\n", (1, 13, 14, "`f` was first deployed here")),
        ("serve localhost:3000 {\n}\n", (1, 0, 5, "port 3000 was first taken here")),
    ],
    ids=["microservice", "global_then_microservice", "global", "param", "param_shadows_microservice",
         "second_serve"],
)
def test_e409_related_kinds(client, items, expected):
    uri = "file:///e409.btw"
    open_doc(client, uri, f"i use arch btw\n{items}serve localhost:3000 {{\n}}\n:wq\n")
    e409s = [d for d in client.diagnostics(uri) if d["code"] == "E409"]
    assert [related(d) for d in e409s] == [[expected]]


# Semantic tokens (P2): the legend of Implementation Spec 11


def decode(data: list[int], legend: dict) -> list[tuple[int, int, int, str, list[str]]]:
    """(line, character, length, type, modifiers) from the relative encoding."""
    tokens, line, character = [], 0, 0
    for i in range(0, len(data), 5):
        delta_line, delta_start, length, kind, modifiers = data[i : i + 5]
        line += delta_line
        character = character + delta_start if delta_line == 0 else delta_start
        names = [m for bit, m in enumerate(legend["tokenModifiers"]) if modifiers & (1 << bit)]
        tokens.append((line, character, length, legend["tokenTypes"][kind], names))
    return tokens


SEMANTIC = """\
i use arch btw
npm install -g LIMIT = 3
microservice total(n) O(n) {
  npm install i = 0 // TODO faster
  doomscroll i < n { git push --force i = i + 1 }
  ship it i
}
serve localhost:3000 {
  console.log "sum"
  console.log total(LIMIT)
  vibe check LGTM && !404 { console.log nope }
}
:wq
"""


def semantic(client: Client, uri: str, source: str) -> list[tuple[str, str, list[str]]]:
    """(text, type, modifiers) for each semantic token of an ASCII document."""
    provider = client.capabilities["semanticTokensProvider"]
    assert provider["full"]
    open_doc(client, uri, source)
    client.diagnostics(uri)
    reply = client.request("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
    lines = source.split("\n")
    return [
        (lines[line][char : char + length], kind, modifiers)
        for line, char, length, kind, modifiers in decode(reply["result"]["data"], provider["legend"])
    ]


def test_semantic_tokens_legend(client):
    assert client.capabilities["semanticTokensProvider"]["legend"] == {
        "tokenTypes": [
            "keyword", "variable", "function", "parameter", "number", "string", "comment", "operator"
        ],
        "tokenModifiers": ["readonly"],
    }


def test_semantic_tokens(client):
    tokens = semantic(client, "file:///semantic.btw", SEMANTIC)
    assert tokens == [
        ("i use arch btw", "keyword", []),
        ("npm install -g", "keyword", []),
        ("LIMIT", "variable", ["readonly"]),
        ("=", "operator", []),
        ("3", "number", []),
        ("microservice", "keyword", []),
        ("total", "function", []),
        ("n", "parameter", []),
        ("O", "function", []),
        ("n", "parameter", []),
        ("npm install", "keyword", []),
        ("i", "variable", []),
        ("=", "operator", []),
        ("0", "number", []),
        ("// TODO faster", "comment", []),
        ("doomscroll", "keyword", []),
        ("i", "variable", []),
        ("<", "operator", []),
        ("n", "parameter", []),
        ("git push --force", "keyword", []),
        ("i", "variable", []),
        ("=", "operator", []),
        ("i", "variable", []),
        ("+", "operator", []),
        ("1", "number", []),
        ("ship it", "keyword", []),
        ("i", "variable", []),
        ("serve", "keyword", []),
        ("localhost:3000", "keyword", []),
        ("console.log", "function", []),
        ('"sum"', "string", []),
        ("console.log", "function", []),
        ("total", "function", []),
        ("LIMIT", "variable", ["readonly"]),
        ("vibe check", "keyword", []),
        ("LGTM", "keyword", []),
        ("&&", "operator", []),
        ("!", "operator", []),
        ("404", "keyword", []),
        ("console.log", "function", []),
        ("nope", "variable", []),
        (":wq", "keyword", []),
    ]


def test_semantic_tokens_in_a_broken_program(client):
    """Unresolved names are plain variables, ERROR tokens and punctuation are
    left out, and an unverifiable annotation still highlights."""
    source = "microservice f(n) O(log n) {\n ship it x @ 1\n}\n"
    assert semantic(client, "file:///broken.btw", source) == [
        ("microservice", "keyword", []),
        ("f", "function", []),
        ("n", "parameter", []),
        ("O", "function", []),
        ("log", "function", []),
        ("n", "parameter", []),
        ("ship it", "keyword", []),
        ("x", "variable", []),
        ("1", "number", []),
    ]


def test_semantic_tokens_use_the_negotiated_encoding():
    source = 'console.log "é😀" // TODO 🚀\n'
    lines = lsp.source_lines(source)
    data = lsp.encode(lines, lsp.classify(source), "utf-8")
    assert data == [
        0, 0, 11, 2, 0,  # console.log
        0, 12, 8, 5, 0,  # the string: quotes, 2 bytes for é and 4 for the emoji
        0, 9, 12, 6, 0,  # the comment
    ]
    utf16 = lsp.encode(lines, lsp.classify(source), "utf-16")
    assert utf16[5:] == [0, 12, 5, 5, 0, 0, 6, 10, 6, 0]


# Inlay hints (P2): the inferred O() after an unannotated microservice's parameters


QUADRATIC = (
    " npm install i = 0\n doomscroll i < n {\n"
    "  npm install j = 0\n  doomscroll j < n { git push --force j = j + 1 }\n"
    "  git push --force i = i + 1\n }"
)
HINTS = f"""\
i use arch btw
microservice pairs(n) {{
{QUADRATIC}
}}
microservice twice(a, b) O(1) {{
 ship it a + b
}}
microservice fact(n) {{
 ship it fact(n - 1)
}}
microservice wait( n ,
  m ) {{
{LOOP}
}}
{SERVE}:wq
"""


def inlay_hints(client: Client, uri: str, start: dict, end: dict) -> list[dict]:
    reply = client.request(
        "textDocument/inlayHint",
        {"textDocument": {"uri": uri}, "range": {"start": start, "end": end}},
    )
    return reply["result"]


def test_inlay_hints(client):
    assert client.capabilities["inlayHintProvider"]
    uri = "file:///hints.btw"
    open_doc(client, uri, HINTS)
    client.diagnostics(uri)
    hints = inlay_hints(client, uri, {"line": 0, "character": 0}, {"line": 40, "character": 0})
    summary = [
        (h["position"]["line"], h["position"]["character"], h["label"], h.get("paddingLeft"), h["kind"])
        for h in hints
    ]
    assert summary == [
        (1, 21, "O(n²)", True, 1),  # after `pairs(n)`
        (12, 20, "O(?)", True, 1),  # recursive: shown, not insertable
        (16, 5, "O(n)", True, 1),  # after the `)` on the parameter list's second line
    ]
    by_label = {h["label"]: h for h in hints}
    assert by_label["O(n²)"]["textEdits"] == [
        {"range": {"start": {"line": 1, "character": 21}, "end": {"line": 1, "character": 21}},
         "newText": " O(n^2)"}
    ]
    assert "textEdits" not in by_label["O(?)"]


def test_inlay_hints_round_trip(client):
    """Inserting every insertable hint leaves only the recursive one's W508."""
    uri = "file:///hints2.btw"
    open_doc(client, uri, HINTS)
    client.diagnostics(uri)
    hints = inlay_hints(client, uri, {"line": 0, "character": 0}, {"line": 40, "character": 0})
    edits = [edit for h in hints for edit in h.get("textEdits", [])]
    _, _, after = driver.check(apply_edits(HINTS, edits), "hints.btw")
    assert [d.code for d in after] == ["W508"]


def test_inlay_hints_only_in_the_requested_range(client):
    uri = "file:///hints3.btw"
    open_doc(client, uri, HINTS)
    client.diagnostics(uri)
    hints = inlay_hints(client, uri, {"line": 9, "character": 0}, {"line": 13, "character": 0})
    assert [h["label"] for h in hints] == ["O(?)"]
    assert inlay_hints(client, uri, {"line": 1, "character": 22}, {"line": 11, "character": 0}) == []


def test_semantic_tokens_in_a_pipe():
    source = (
        "i use arch btw\nmicroservice f(n) O(1) { ship it n }\n"
        "serve localhost:3000 {\n npm install x = 3\n x | f | console.log\n}\n:wq\n"
    )
    line = source.split("\n")[4]
    assert [
        (line[span.start.col : span.end.col], kind)
        for span, kind, _ in lsp.classify(source)
        if span.start.line == 4
    ] == [("x", "variable"), ("|", "operator"), ("f", "function"), ("|", "operator"),
          ("console.log", "function")]


# Completion and go to definition (P2)

SCOPES = """\
i use arch btw
npm install -g LIMIT = 10
microservice total(n) O(1) {
    npm install sum = n
    ship it sum
}
serve localhost:3000 {
    npm install a = 1
    vibe check a > 0 {
        npm install inner = 2

    } skill issue vibe check a < 0 {
        npm install other = 3

    }
    npm install b = total(a)

}
:wq
"""


def scope_at(line: int, col: int) -> list[str]:
    return [sym.name for sym in lsp.in_scope(SCOPES, Pos(line - 1, col))]


def test_names_in_scope():
    top = ["LIMIT", "total"]
    assert scope_at(5, 4) == top + ["n", "sum"]
    assert scope_at(4, 4) == top + ["n"]  # not yet declared
    assert scope_at(11, 8) == top + ["a", "inner"]
    assert scope_at(14, 8) == top + ["a", "other"]  # the `skill issue vibe check` branch
    assert scope_at(17, 4) == top + ["a", "b"]  # inner and other are out of scope
    assert scope_at(16, 4) == top + ["a"]  # b's own initializer
    assert scope_at(20, 0) == top  # after :wq


def test_completion_items():
    items = {item.label: item for item in lsp.completions(SCOPES, Pos(16, 4))}
    loop = items["doomscroll"]
    assert loop.insert_text == "doomscroll $1 {\n\t$0\n}"  # cursor in the condition first
    assert loop.insert_text_format == lsp.types.InsertTextFormat.Snippet
    assert items["total"].kind == lsp.types.CompletionItemKind.Function
    assert items["total"].detail == "microservice/1"
    assert items["LIMIT"].kind == lsp.types.CompletionItemKind.Constant
    assert items["b"].detail == "number"


def test_definition():
    def at(line: int, word: str) -> Pos:
        return Pos(line - 1, SCOPES.split("\n")[line - 1].index(word))

    assert lsp.definition(SCOPES, at(16, "total")) == Span(at(3, "total"), Pos(2, 18))
    assert lsp.definition(SCOPES, at(5, "sum")).start == at(4, "sum")
    assert lsp.definition(SCOPES, Pos(3, len("    npm install sum = "))).start == at(3, "n)")
    assert lsp.definition(SCOPES, at(2, "npm")) is None  # a keyword


def test_completion_and_definition_over_the_protocol(client):
    uri = "file:///scopes.btw"
    open_doc(client, uri, SCOPES)
    client.diagnostics(uri)
    assert client.capabilities["completionProvider"] is not None
    assert client.capabilities["definitionProvider"]
    reply = client.request(
        "textDocument/completion",
        {"textDocument": {"uri": uri}, "position": {"line": 16, "character": 4}},
    )
    labels = [item["label"] for item in reply["result"]]
    assert "doomscroll" in labels and "b" in labels and "inner" not in labels
    reply = client.request(
        "textDocument/definition",
        {"textDocument": {"uri": uri}, "position": {"line": 15, "character": 20}},
    )
    assert reply["result"] == {
        "uri": uri,
        "range": {"start": {"line": 2, "character": 13}, "end": {"line": 2, "character": 18}},
    }


def test_curl_is_a_function_like_console_log():
    source = "i use arch btw\nserve localhost:3000 {\n    console.log curl\n}\n:wq\n"
    lines = source.split("\n")
    kinds = {
        lines[span.start.line][span.start.col : span.end.col]: kind
        for span, kind, _ in lsp.classify(source)
    }
    assert kinds["curl"] == kinds["console.log"] == "function"
