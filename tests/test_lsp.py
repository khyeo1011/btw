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
from btw.span import Pos

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
    assert reply["result"]["capabilities"]["hoverProvider"]
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
    ],
    ids=["e426", "e408", "e408_no_final_newline", "e408_comment_line", "e408_trailing_comment",
         "e403_push", "e403_revert", "e417", "w102"],
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
        diagnostics = client.diagnostics(uri)
    _, _, after = driver.check(source, "fix.btw")
    assert after == []


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
    x, limit = client.diagnostics(uri)
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
