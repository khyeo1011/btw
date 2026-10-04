#!/usr/bin/env bash
# Check built distributions in DIST (default: dist/): the wheel and sdist hold
# the C runtime and license, and the installed wheel can check, run and build a
# golden program outside the repo. Used by CI and the release workflow.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
dist="$(cd "${1:-dist}" && pwd)"
wheels=("$dist"/*.whl)
sdists=("$dist"/*.tar.gz)
if [ "${#wheels[@]}" -ne 1 ] || [ ! -f "${wheels[0]}" ]; then
    echo "error: expected exactly one wheel in $dist" >&2
    exit 1
fi
if [ "${#sdists[@]}" -ne 1 ] || [ ! -f "${sdists[0]}" ]; then
    echo "error: expected exactly one sdist in $dist" >&2
    exit 1
fi
wheel="${wheels[0]}"
sdist="${sdists[0]}"

require() {
    local listing="$1" pattern="$2" what="$3"
    if ! grep -qE "$pattern" <<< "$listing"; then
        echo "error: $what is missing $pattern" >&2
        exit 1
    fi
}

wheel_files="$(python3 -m zipfile -l "$wheel")"
require "$wheel_files" '^btw/runtime/btw_rt\.c ' "the wheel"
require "$wheel_files" '\.dist-info/licenses/LICENSE ' "the wheel"
sdist_files="$(tar tzf "$sdist")"
require "$sdist_files" '/src/btw/runtime/btw_rt\.c$' "the sdist"
require "$sdist_files" '/LICENSE$' "the sdist"
require "$sdist_files" '/tests/golden/p0_hello\.btw$' "the sdist"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
uv venv --quiet --python 3.12 "$work/venv"
uv pip install --quiet --python "$work/venv/bin/python" "$wheel"
btw="$work/venv/bin/btw"
golden="$repo/tests/golden"

cd "$work"
"$btw" check "$golden/p0_fizzbuzz.btw" --format short
"$btw" run "$golden/p0_fizzbuzz.btw" > run.out
diff -u "$golden/p0_fizzbuzz.out" run.out
"$btw" build "$golden/p0_fizzbuzz.btw" -o fizzbuzz
./fizzbuzz > build.out
diff -u "$golden/p0_fizzbuzz.out" build.out
test -x "$work/venv/bin/btw-lsp"
echo "ok: $(basename "$wheel") and $(basename "$sdist")"
