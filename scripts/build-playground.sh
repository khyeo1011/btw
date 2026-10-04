#!/usr/bin/env bash
# Build the browser playground into SITE (default: _site/): the static files in
# playground/, the btw wheel, and the example programs from tests/golden/. The
# page runs btw on Pyodide, so the site needs no server beyond static files.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "${1:-_site}"
site="$(cd "${1:-_site}" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

examples=(
    p0_fizzbuzz
    p0_e417_big_o_underclaim
    p2_git_history
    p1_w509_infinite_doomscroll
    p2_e400_foreign_print
)

cd "$repo"
uv build --wheel --no-sources --quiet --out-dir "$work"
wheels=("$work"/btw-*.whl)
if [ "${#wheels[@]}" -ne 1 ]; then
    echo "expected one wheel, found: ${wheels[*]}" >&2
    exit 1
fi
wheel="$(basename "${wheels[0]}")"

cp playground/* "$site/"
cp "${wheels[0]}" "$site/"
mkdir -p "$site/examples"
for name in "${examples[@]}"; do
    cp "tests/golden/$name.btw" "$site/examples/"
done
printf '{"wheel": "%s"}\n' "$wheel" > "$site/playground.json"
echo "built: $site"
