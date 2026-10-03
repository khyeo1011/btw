# NOTES-harness

There is no Implementation Spec, so the decisions below define the CLI and the
golden test format. Language behavior still comes from `docs/SPEC.md`.

## CLI

```
btw check  FILE [--format short|pretty]   diagnostics to stdout
btw run    FILE [--format short|pretty]   interpret; diagnostics to stderr
btw build  FILE [-o OUT] [--format ...]   native binary (default OUT: FILE without .btw)
btw asm    FILE [-o OUT]                  assembly to stdout, or to OUT
btw tokens FILE                           one token per line
btw parse  FILE                           the AST
btw lsp                                   language server on stdio
```

`--format` defaults to `pretty` when the output stream is a terminal and to
`short` otherwise. Colors are used only in pretty mode, only on a terminal and
only when `NO_COLOR` is unset.

Exit codes:

| Code | Meaning                                                                    |
| ---- | -------------------------------------------------------------------------- |
| 0    | success; for `check`, no errors (warnings are fine)                        |
| 1    | hard or soft errors blocked the command                                    |
| N    | `btw run`: the program's own exit code (`ship it`, 1 or 128 at runtime)    |
| 2    | usage error, unreadable file, component not implemented, internal error    |

## Short diagnostic format

One line per diagnostic, sorted as in Language Spec 11:

```
PATH:LINE:COL: SEVERITY CODE: MESSAGE
```

LINE and COL are 1-based and refer to the start of the span. SEVERITY is
`error` for hard and soft errors and `warning` for warnings. Example:

```
tests/golden/p0_e404_undeclared_var.btw:3:17: error E404: Error 404: variable `x` not found. Did you forget to `npm install` it?
```

## Golden test format

Every `tests/golden/NAME.btw` can have these sidecar files:

| File         | Contents                                                                    |
| ------------ | --------------------------------------------------------------------------- |
| `NAME.diag`  | expected `btw check --format short` output with the `PATH:` prefix removed  |
| `NAME.exit`  | expected exit code of `btw run`, as one number and a newline                |
| `NAME.out`   | expected stdout of `btw run`                                                |
| `NAME.err`   | expected stderr of `btw run`                                                |

A missing `.diag`, `.out` or `.err` means "expected empty". `.exit` is the
switch for running: without it the test is check-only. Programs with errors
are check-only (errors block `run`), and so are programs that never terminate.

Runner steps, per program:

1. Run `btw check --format short NAME.btw`. Strip the path prefix and compare
   stdout with `NAME.diag`. The exit code must be 1 if `.diag` has an `error`
   line, else 0.
2. If there is no `NAME.exit`, stop.
3. Run `btw run NAME.btw`. Compare stdout with `.out`, stderr with `.err` and
   the exit code with `.exit`.
4. If `gcc` is available, `btw build` the program, run the binary and make the
   same three comparisons. Skipped while the native backend isn't implemented.

The tier is the number in the file name prefix (`p0_`, `p1_`, `p2_`).

## Golden tests

One line each.

## Spec questions

Ambiguities found while writing the tests. Each golden test avoids depending
on an open question.
