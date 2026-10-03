# Codegen part 2 notes

Files: `src/btw/codegen.py`, `tests/test_codegen.py`. Specs: Implementation
Spec 10.3 to 10.7, Language Spec 8, 9.3 and 10. Part 1 is in
`NOTES-codegen.md`, and its "Part 2 (not started)" section is now done.
`runtime/btw_rt.c` didn't need any changes: part 1 had already written all
of 10.7.

## Suite summary

```
$ uv run pytest -q -rxs
XFAIL tests/test_checker.py::test_golden_diagnostics[p2_e405_pipe_console_log_value] - pipes (parser card)
XFAIL tests/test_checker.py::test_golden_diagnostics[p2_pipes] - pipes (parser card)
XFAIL tests/test_golden.py::test_golden[p2_e405_pipe_console_log_value] - waiting on pipes (parser card)
XFAIL tests/test_golden.py::test_golden[p2_pipes] - waiting on pipes (parser card)
XFAIL tests/test_parser.py::test_golden_syntax_errors[p2_e405_pipe_console_log_value] - pipes are another card
XFAIL tests/test_parser.py::test_golden_syntax_errors[p2_pipes] - pipes are another card
SKIPPED [1] tests/test_codegen.py:584: doesn't build: E400, E415, W204
1084 passed, 1 skipped, 6 xfailed in 21.41s

$ uv run pytest -q --tier 1 tests/test_golden.py
64 passed in 11.14s
```

Before part 2: 1003 passed, 18 xfailed. The 12 xfails that are gone were all
"native: not yet (E501)". The 6 left are the pipes goldens, which don't parse
yet. That's the parser card's job, not codegen's. The one skip is
`p2_pipes` in the alignment probe, for the same reason.

## What works

The goal is met: all 21 P0 and P1 goldens that have a `.out` file pass
natively, byte for byte against the same `.out`/`.err`/`.exit` files the
interpreter matches. Every P2 golden that parses passes natively too, git
history included.

1. **Microservices** (commit `e221063`). `btw_fn_NAME` uses the frame shape
   from 10.3, and parameters are copied from `rdi`, `rsi`, `rdx`, `rcx`,
   `r8`, `r9` into slots 0 to 5. `ship it` jumps to `.Lret_NAME`, and
   falling off the end returns 0. `main` and the microservices now share
   `prologue`/`epilogue` helpers. Part 1's `main` text is the same apart
   from the return label (decision 1 below).
2. **Calls** (commit `26351ad`). Arguments are evaluated left to right,
   popped into the registers in reverse order, and then `call` pads
   `rsp` by 8 when the static depth is odd. Nothing stays in a register
   across the call.
3. **Call depth limit** (same commit). After each microservice's prologue:
   `inc`/`cmp 1000`/`jg .Lstack_overflow`. Before its `leave`: `dec`. The
   handler does `and rsp, -16` and calls `btw_rt_stack_overflow`. `serve` is
   depth 0. Like the interpreter (NOTES-interp decision 1), the check runs in
   the callee after the arguments are evaluated: `down(999, 0)` in
   `arguments_run_before_the_depth_check` fails with division by zero, not
   stack overflow, in both backends.
4. **Git history** (commit `689b7e4`). Tracked symbols get ids 0 to 63 in
   `symbols.all` order. Declarations (global initializers included) call
   `btw_rt_hist_reset`, and assignments call `btw_rt_hist_commit`, including
   assignments to a tracked global from inside a microservice. `git revert`
   calls `btw_rt_hist_revert` and stores `rax`. `git log` passes
   `rdx = 1` for booleans. Each tracked name is a `.LstrN` string, shared
   with any identical `console.log` literal.

Tests added to `tests/test_codegen.py`:

- Assembly shape: the prologue/epilogue with six parameters, an empty
  microservice, argument pops in reverse order, padding at odd depth and
  none at even depth, all six registers, labels for a microservice named
  `main`, the overflow handler only when microservices exist, the
  `--annotate` header, history call sequences, and the 64/65 boundary.
- Differential (native against the interpreter): libc names (`main`,
  `printf`, `exit`), nested calls in arguments, short circuits skipping
  calls, every statement inside microservices, recursion up to and past
  1,000, overflow at odd depth, arguments evaluated before the depth check,
  division by zero inside a call, history changed from microservices and in
  loops, the 16-commit cap, revert toggling, and the exit-128 error.
- **Alignment probe.** A test runtime `#include`s the real
  `runtime/btw_rt.c` with every function renamed, then wraps each one with
  a check: at `-O0` with a frame pointer, `rbp` is 16-aligned exactly when
  the caller's `rsp` was aligned at the call. A misaligned call exits 99.
  The probe runs over every differential program and every golden with a
  run sidecar. `test_alignment_probe_catches_a_missing_pad` monkeypatches
  out the padding and checks that the probe really fails.

## Decisions where the spec is silent or I deviated

1. **`serve` returns through `.Lret_serve`, not `.Lret_main`.** Language
   Spec 8 allows a microservice named `main`, and its label `.Lret_main`
   would collide with part 1's `serve` label, so gcc would reject the file
   (E502). `serve` is a reserved word, so `.Lret_serve` can't collide with
   any microservice. This is a label rename only, so behavior is unchanged
   and no test pinned the old name.
2. **Steps 2 and 3 are one commit.** With calls but no depth limit,
   `p0_runtime_stack_overflow` builds natively and prints `1001` instead of
   overflowing, so step 2 alone can't have a green suite. Landing calls and
   the limit together keeps every commit green. The alternatives were a red
   commit or adding the limit before calls (out of the requested order). I
   chose to keep every commit green.
3. **E501 for more than 64 tracked variables.** 10.7 says "more than that
   is E501" but doesn't say where. I report it on each `git revert` /
   `git log` statement whose target is the 65th tracked variable or later,
   using the existing `` `git revert` `` / `` `git log` `` construct text.
   Every tracked variable is the target of at least one such statement,
   so there is always something to point at. The first 64 by checker order
   still get history.
4. **The division-by-zero handler moved** from the end of `main` to after
   every function, so microservices can jump to it. It is still emitted
   only when a `/` or `%` exists.
5. **The depth counter only runs in microservices.** `main` never touches
   `btw_depth`, since `serve` is depth 0 (Language Spec 8).
6. **Under `--annotate`, a microservice's header comment goes before its
   label** (`# line 2: microservice f(n) O(1)`, then `btw_fn_f:`), while
   `serve`'s comment stays after `main`'s prologue as in part 1. The
   instruction notes `one call deeper`, `past 1,000 nested calls?`,
   `history of x` and `print as LGTM/404?` appear only with `--annotate`.
7. `rdi` is set with `mov rdi, ID`, as 10.5 writes it, not the shorter
   `mov edi, ID`.

## What doesn't work / unsure

- **Pipes** can't be built natively because they don't parse yet. They
  desugar into `Call` and `Print`, both of which codegen handles, so they
  should work once the parser card lands. The alignment probe will pick up
  `p2_pipes` automatically, and so will `test_golden`. I couldn't verify
  this.
- **Deep recursion and the real stack.** 1,000 frames of a few dozen bytes
  is far below the 8 MB default stack, so the counter always fires first.
  I didn't test with a lowered `ulimit -s`.
- **Minimum divided by -1** still traps (SIGFPE) natively while the
  interpreter wraps. That's documented as undefined (Language Spec 10) and
  unchanged from part 1.
- **Test names.** `test_every_checked_golden_generates_or_reports_e501`
  keeps its part 1 name. Every checked golden now generates, but the E501
  branch is still reachable through the 65-variable case.
- **NOTES-codegen.md** still says part 2 is "not started", and its table
  lists microservices and calls as E501. I didn't edit part 1's notes
  file. This file supersedes those sections.

## Branch

I developed on `claude/modest-albattani-5u12ll`, the branch this session
was assigned, not on a `feature/NAME` branch as CLAUDE.md asks. I didn't
merge into `main` or open a pull request.
