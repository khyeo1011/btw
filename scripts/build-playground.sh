#!/usr/bin/env bash
# Build the browser playground into SITE (default: _site/): the static files in
# playground/, the btw wheel, and the example programs from tests/golden/, with
# their .in stdin when they have one. The page runs btw on Pyodide, so the site
# needs no server beyond static files.
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
    p2_curl_sum
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
    if [ -f "tests/golden/$name.in" ]; then
        cp "tests/golden/$name.in" "$site/examples/"
    fi
done
printf '{"wheel": "%s"}\n' "$wheel" > "$site/playground.json"

# Stamp the page with a hash of everything else it loads. The page puts it in
# every URL, so a deploy can't pair a new page with files cached from an old
# one (the wheel's name doesn't change between versions).
build="$(cd "$site" && find . -type f ! -name index.html -print0 | sort -z |
    xargs -0 sha256sum | sha256sum | cut -c1-12)"
stamp='<meta name="btw-build" content="dev">'
if [ "$(grep -cF "$stamp" "$site/index.html")" -ne 1 ]; then
    echo "index.html must contain $stamp exactly once" >&2
    exit 1
fi
sed -i "s|$stamp|<meta name=\"btw-build\" content=\"$build\">|" "$site/index.html"
echo "built: $site"
