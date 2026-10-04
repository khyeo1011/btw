#!/usr/bin/env bash
# Check the standalone executables in DIST (default: dist/) from a directory
# outside the repo, with no Python on PATH: `btw` can check, run and build a
# golden program, and `btw-lsp` answers an LSP initialize request. Used by the
# release workflow after scripts/build-exe.sh.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
dist="$(cd "${1:-dist}" && pwd)"
btw="$dist/btw"
lsp="$dist/btw-lsp"
for exe in "$btw" "$lsp"; do
    if [ ! -x "$exe" ]; then
        echo "error: $exe is missing or not executable" >&2
        exit 1
    fi
done
golden="$repo/tests/golden"
python="$(command -v python3)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# Keep gcc and as reachable but hide every Python, so the executables have to
# bring their own.
mkdir bin
for tool in gcc as ld cc collect2; do
    if path="$(command -v "$tool")"; then ln -s "$path" "bin/$tool"; fi
done
clean_path="$work/bin"

PATH="$clean_path" "$btw" check "$golden/p0_fizzbuzz.btw" --format short
PATH="$clean_path" "$btw" run "$golden/p0_fizzbuzz.btw" > run.out
diff -u "$golden/p0_fizzbuzz.out" run.out
PATH="$clean_path" "$btw" build "$golden/p0_fizzbuzz.btw" -o fizzbuzz
./fizzbuzz > build.out
diff -u "$golden/p0_fizzbuzz.out" build.out

# One initialize request, then shutdown and exit; the reply must carry the
# server's name.
"$python" - "$lsp" "$clean_path" <<'EOF'
import json
import subprocess
import sys

def frame(message):
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)

requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"processId": None, "rootUri": None, "capabilities": {}}},
    {"jsonrpc": "2.0", "method": "initialized", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
    {"jsonrpc": "2.0", "method": "exit"},
]
done = subprocess.run(
    [sys.argv[1]], input=b"".join(map(frame, requests)), capture_output=True,
    env={"PATH": sys.argv[2]}, timeout=60,
)
if b'"name": "btw-lsp"' not in done.stdout and b'"name":"btw-lsp"' not in done.stdout:
    sys.exit(f"error: btw-lsp did not answer initialize\n{done.stdout!r}\n{done.stderr.decode()}")
EOF
echo "ok: $(basename "$btw") and $(basename "$lsp")"
