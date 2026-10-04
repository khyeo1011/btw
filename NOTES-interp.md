# Interpreter notes

Files: `src/btw/interp.py`, `tests/test_interp.py`. Specs: Language Spec 5,
6, 9.3, 9.4 and 10; Implementation Spec 9.

## Interface

- `run(program, symbols, stdout, stderr) -> int`, as in the NOTES-harness
  table. `driver.run` already called it, so the driver needed no change.
- The exit code is the raw value of `ship it` in `serve` (0 when there is
  none). `cli.cmd_run` keeps the low 8 bits, so `ship it -1` exits 255.
- Exported helpers, for the codegen's differential tests and anything else:
  `wrap`, `div`, `rem`, `format_value`, `MAX_DEPTH`, and the exact messages
  `DIVISION_BY_ZERO` and `STACK_OVERFLOW`.

## How it works

- One `Interpreter` per run. `globals` and the current call's `frame` are
  dicts keyed by Symbol: a GLOBAL or CONST symbol lives in `globals`,
  everything else in `frame`. Each call swaps in a fresh frame and puts the
  caller's back afterwards.
- Microservices are found by the Call's `sym`. When a name is deployed twice
  (E409, so never run), the first declaration wins, as in the checker.
- `touch grass` and `ship it` are the exceptions `BreakSignal` and
  `ReturnSignal`. Runtime errors raise `RuntimeFault(message, exit_code)`;
  `run` catches it, flushes stdout, writes the message and a newline to
  stderr, and returns the code.
- A print of a `StrLit` writes the text verbatim. Every other print goes
  through `format_value`: `LGTM`/`404` for bools, decimal for numbers. Bools
  are checked before ints, because `bool` is a subclass of `int`.
- History (P2) only exists for symbols the checker marked `tracked`. A
  declaration sets the list to `[value]`, so a re-run in a loop starts
  fresh. Each assignment and each revert appends and trims to 16 entries.
- Pipes (P2) are desugared by the parser into `Call` and `Print`, so the
  interpreter has no pipe code.

## Decisions where the spec is silent

1. **When the depth check runs.** The arguments are evaluated first (left
   to right), then the check runs on entry to the callee: entering at depth
   1,000 fails. Side effects in the arguments of the overflowing call
   happen before the error. The codegen should match by checking in the
   callee's prologue.
2. **Minimum divided by -1** wraps: `MIN / -1 = MIN` and `MIN % -1 = 0`.
   Language Spec 5 and 10 now define it that way, and
   `p0_div_min_neg1` tests it in both backends.
3. **The recursion limit.** Implementation Spec 9 says to call
   `sys.setrecursionlimit(50_000)` at startup. `run` raises the limit for
   the run and puts the old value back afterwards. Leaving it raised made
   `test_parser.py::test_deep_nesting_is_an_internal_error_not_a_crash`
   fail whenever the interpreter tests ran first in the same process, and
   the language server would have the same problem.
4. **stdout is flushed at the end of every run**, not only before a runtime
   error, so output never sits in a buffer after `run` returns.
5. **Integer literals are wrapped too**, as a defense. The checker already
   rejects literals above the maximum (E413), so this changes nothing for a
   checked program.

## Status

- Unit tests: the Language Spec 5 reference table (division, modulo and the
  three overflow rows), wrap edges, short-circuiting, evaluation order, the
  depth limit at 1,000 and 1,001, stdout flushed before stderr (a recording
  stream checks the order), frames, `ship it` from a loop in `serve`,
  nested `touch grass`, globals, and git history (revert, log, the 16-commit
  cap, the exit 128 error).
- Golden tests: every program with an `.out`, `.err` or `.exit` file passes
  the interpreter step, pipes and git history included. The native backend
  is compared against the same files (NOTES-codegen).
