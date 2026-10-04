# Load test notes

Files: `src/btw/loadtest.py`, `tests/test_loadtest.py`, plus `loadtest` in
`src/btw/driver.py` and `src/btw/cli.py`. Specs: Language Spec 9.7 (new),
Implementation Spec 3 (new row).

## Interface

| Function                                            | Returns                                                  |
| --------------------------------------------------- | -------------------------------------------------------- |
| `loadtest(program, symbols, name, args="n")`        | the whole report, one string ending in a newline         |
| `measure(program, symbols, service, template, ...)` | the `(n, steps)` points and one line per size            |
| `slope(points)`                                     | the least-squares slope of ln(steps) against ln(n)       |
| `verdict(service, degree, s)`                       | the static and measured lines                            |

`driver.loadtest(source, path, name, args)` returns `(diagnostics, report)`,
and the report is None when hard errors blocked it. Usage problems raise
`BtwError`, which the CLI turns into exit code 2.

## How it works

`CountingInterpreter` subclasses the interpreter. It overrides `exec` for
`ast.While` only, counting one step per iteration, and wraps `call`, counting
one step per call. Every other node goes through the interpreter unchanged,
so the load test runs exactly the semantics `btw run` does.

## Decisions made with the user (2026-10-03)

1. **Steps are iterations plus calls**, the entry call included, so a
   constant microservice takes 1 step (ln is defined) and recursion is
   measured.
2. **Soft errors don't block it**, so the pitch's own example (E417 on
   `pairs`) gets measured. Decision 17 already says such code is well defined.
3. **Verdicts round the slope** to the nearest degree, halves up.
4. **Exit code 0** whenever it runs, whatever the verdict.
5. **No wall-clock timeout**: it would make the output machine-dependent.
   A step budget of 3,000,000 for the whole sweep bounds the runtime instead
   (a cubic microservice stops at n = 256 after about 6 s). A budget per size
   let a cubic one run for 18 s.

## Decisions after merging #31 (pair degrees)

#31 made a degree a pair (k, j), O(n^k · log^j n), and gave halving loops
O(log n) and fixed-bound loops O(1). Three consequences for 9.7:

1. **Only k is compared.** A log factor barely moves the slope over n = 8 to
   1024 (O(log n) measures 0.18 to 0.20, O(n log n) 1.20), so `round(s)` is
   compared with k. O(log n) and O(n log n) SLAs on matching code get LGTM.
2. **The pessimistic example is a `lo`/`hi` binary search**, which 9.1 still
   calls O(n) (its counter changes inside a `vibe check`). The halving loop
   is now inferred correctly.
3. **Superpolynomial SLAs are echoed** ("I'll take your word for it"), not
   judged. 9.1 always gives them W417, but a power-law fit can't measure
   c^n or n!: recursive fib with `O(2^n)`, a correct SLA, stops at n = 32
   and fits 5.57 on two sizes. Calling that sandbagging would be wrong.

## Decisions where the spec is silent

1. **The usage messages** (`btw: no microservice named `x``, the `--args`
   ones, "need at least 2 sizes") aren't spec text, like the other `btw:`
   messages of the CLI.
2. **Diagnostics go to stderr even when the load test runs**, without the
   summary line, so E417 shows up next to the measured verdict. `btw run`
   prints nothing on success; the load test is a report, so it shows them.
3. **A duplicate microservice** (E409, a hard error) never gets this far;
   `loadtest` still takes the first declaration, as the interpreter does.
4. **Global initializers can't call microservices** (E405), so they never
   add steps.
