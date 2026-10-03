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
