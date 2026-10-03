# CLAUDE.md

btw is a joke programming language with a real compiler: a checker, an
interpreter (`btw run`), an x86-64 native backend (`btw build`) and a language
server. Python and uv; code in `src/btw/`.

## Source of truth

- `docs/SPEC.md` (Language Spec) decides language behavior. Diagnostic
  messages must match it character for character, backticks included.
- `docs/IMPL_SPEC.md` (Implementation Spec) decides how the pieces fit: repo
  layout, CLI, core types, each component, testing.
- `NOTES-harness.md` records harness decisions where the Implementation Spec
  is silent, including the function names `src/btw/driver.py` calls.
- `tests/golden/` is the behavioral contract, derived by hand from the spec
  and reviewed by a human.
- When the spec is ambiguous or disagrees with a test, stop and ask instead of
  inventing behavior. If you're blocked, write the question in your
  `NOTES-<area>.md` and move on to something else.

## Commands

```
uv sync                                        # install
uv run pytest                                  # everything
uv run pytest -k p0_fizzbuzz                   # one golden test
uv run pytest --tier 0                         # golden tests for P0 only
uv run btw check FILE.btw [--format short]     # diagnostics (pretty by default)
uv run btw run FILE.btw                        # interpret
uv run btw build FILE.btw [-o OUT] [--keep-asm]
uv run btw asm FILE.btw [--annotate]
uv run btw tokens FILE.btw                     # debug dump
uv run btw parse FILE.btw                      # debug dump
uv run btw lsp                                 # language server, same as btw-lsp
```

## Hard rules

- Don't edit the contract files `src/btw/span.py`, `src/btw/diagnostics.py`
  and `src/btw/ast.py`.
- Never edit expected-output files (`tests/golden/*.diag`, `.out`, `.err`,
  `.exit`) to make a test pass, and never run `pytest --bless`. If you believe
  an expectation is wrong, write it up in your notes file with the spec
  section that proves it.
- Only touch the files your card owns.
- No randomness, no network calls, no new dependencies.
- Commit small, and run the tests before every commit.
- A component that doesn't exist yet raises `NotImplementedError`; the driver
  imports components lazily and the CLI turns that into exit code 2.
- No trailing whitespace; non-empty files end with exactly one newline.

## Python

- Dataclasses, `match` statements, type hints.
- Python integers never overflow: wrap every arithmetic result to signed
  64 bits. `/` truncates toward zero and `%` takes the sign of the left
  operand, unlike Python's `//` and `%`. Language Spec 5 has the reference
  values to test against.
- Positions are 0-based line and column (UTF-16 code units) internally and
  1-based when the CLI prints them.

## pygls 2 (language server)

- `LanguageServer` comes from `pygls.lsp.server`, not `pygls.server`.
- Publish with `ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=..., diagnostics=[...]))`.
- Document text: `ls.workspace.get_text_document(uri).source`.
- Renamed: `window_show_message`, `workspace_apply_edit`, `protocol.notify`.
- lsprotocol 2025 renamed many types: read the installed package, don't guess.
- Never write to stdout from the server; it's the protocol channel. Log to
  stderr.

## Codegen

- Target: Linux x86-64, System V, GNU as in Intel syntax, linked by gcc with
  `runtime/btw_rt.c` (Implementation Spec 10).
- Every expression leaves exactly one value pushed; the temporary stack is
  empty at every statement boundary.
- Align `rsp` to 16 bytes before every call.
- Prefix user symbols: `btw_fn_NAME`, `btw_g_NAME`.
- After every change, build the golden programs and compare against the
  interpreter.

## Branches

Each agent works on its own branch in its own worktree: `agent/lexer`
(`../btw-lexer`), `agent/harness` (`../btw-harness`), `agent/editors`
(`../btw-editors`). Bring in `main` with a merge, never a rebase, and don't
commit to `main` directly.
