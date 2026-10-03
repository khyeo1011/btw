# CLAUDE.md

btw is a joke programming language with a real compiler: a checker, an
interpreter (`btw run`), an x86-64 native backend (`btw build`) and an LSP
server. Python 3.14, managed with uv. Code lives in `src/btw/`.

## Sources of truth

- `docs/SPEC.md` is the Language Spec: grammar, types, diagnostics with exact
  messages, runtime behavior. It wins over everything else.
- `NOTES-harness.md` defines the CLI, diagnostic output formats and the golden
  test format. There is no separate Implementation Spec; that file stands in
  for it.
- `tests/golden/` is the behavioral contract. Each `.btw` program and its
  sidecar files were derived by hand from the spec.

## Rules

- Never edit a golden expectation to make an implementation pass. If you
  believe a golden file is wrong, write it up in your notes file with the spec
  section that proves it, and leave the file alone.
- Never run `pytest --bless`. It is for humans only.
- When the spec is ambiguous, record the question in `NOTES-<area>.md` instead
  of guessing silently.
- Messages, hovers and output are deterministic. Copy messages from the spec
  character for character, including the backticks.
- Positions are 0-based line and column internally (LSP convention) and
  printed 1-based by the CLI. Columns count UTF-16 code units.
- `src/btw/driver.py` imports components lazily inside functions. A component
  that doesn't exist yet raises `NotImplementedError`; the CLI turns that into
  a one-line message and exit code 2.
- Files have no trailing whitespace and non-empty files end with exactly one
  newline.

## Branches

Each agent works on its own branch in its own worktree: `agent/lexer`
(`../btw-lexer`), `agent/harness` (`../btw-harness`), `agent/editors`
(`../btw-editors`). Bring in `main` with a merge, never a rebase, and don't
commit to `main` directly.

## Commands

```
uv run pytest                      # all tests
uv run pytest --tier 0             # golden tests for P0 only
uv run btw check FILE.btw          # diagnostics
uv run btw run FILE.btw            # interpret
```
