#!/usr/bin/env bash
# Build the standalone `btw` and `btw-lsp` executables into DIST (default:
# dist/) with PyInstaller. Each is one file that carries its own Python, pygls
# and the C runtime, so it runs without Python or a checkout; `btw build` still
# needs gcc and GNU as on Linux x86-64. PyInstaller is a build tool only: it
# runs through `uv run --with` and isn't a dependency of the package.
set -euo pipefail

pyinstaller="pyinstaller==6.22.3"

repo="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "${1:-dist}"
dist="$(cd "${1:-dist}" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The entry scripts must not be named btw.py, or they shadow the package.
cat > "$work/entry_btw.py" <<'EOF'
import sys

from btw.cli import main

sys.exit(main())
EOF
cat > "$work/entry_btw-lsp.py" <<'EOF'
from btw.lsp import main

main()
EOF

cd "$repo"
uv sync --locked --quiet
for name in btw btw-lsp; do
    # --collect-data btw: the C runtime (btw/runtime/btw_rt.c) for `btw build`.
    # --collect-submodules btw: the driver imports components lazily by name.
    uv run --no-sync --with "$pyinstaller" pyinstaller \
        --onefile --noconfirm --clean --log-level WARN \
        --name "$name" \
        --collect-data btw \
        --collect-submodules btw \
        --distpath "$dist" \
        --workpath "$work/build-$name" \
        --specpath "$work" \
        "$work/entry_$name.py"
done
echo "built: $dist/btw $dist/btw-lsp"
