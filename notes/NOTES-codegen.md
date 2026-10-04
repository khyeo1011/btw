# Codegen notes

Files: `src/btw/codegen.py`, `runtime/btw_rt.c`, `tests/test_codegen.py`,
plus one line in `src/btw/driver.py`. Specs: Implementation Spec 10,
Language Spec 5, 8, 9.3 and 10. This file merges the part 1 and part 2 notes.

## Interface

- `gen(program, symbols, annotate=False, source=None)` returns
  `(assembly_text, diagnostics)`, as in the NOTES-harness table (question 17
  there). With E501 the text is `""` and the driver writes nothing.
- `source` is for `btw asm --annotate`, which needs the source lines for its
  comments; the AST doesn't keep them, so `driver.asm` passes
  `source=source`. Without it, an annotation is just `# line N`.
- The rest of the build pipeline is in the driver: a temp directory,
  `gcc -o OUT prog.s runtime/btw_rt.c`, E502 plus gcc's stderr (exit 3) when
  gcc fails, `--keep-asm` writing `OUT.s`.

## What works

Every construct in the language builds natively: globals and constants
(initializers in source order), `serve`, every expression, `console.log` of
numbers, booleans and strings, `vibe check` / `skill issue`, `doomscroll`,
`touch grass`, `ship it`, expression statements, microservices and calls,
the division-by-zero check, the 1,000-call depth limit, git history and
pipes (which the parser desugars into calls and prints). Every golden with a
run sidecar passes natively, byte for byte against the same
`.out`/`.err`/`.exit` files the interpreter matches.

The only E501 left is more than 64 tracked variables (decision 9).

## How it works

- `Codegen.depth` counts the temporaries pushed right now. `push` and `pop`
  are the only ways to change it (plus the `add rsp, 8` of an expression
  statement and the short-circuit join). `expr` asserts every expression
  leaves exactly one value, and `stmt` asserts the depth is 0 before and
  after every statement. A failed assertion is an AssertionError, which the
  CLI reports as E500.
- **Microservices.** `btw_fn_NAME` uses the frame shape from 10.3, and
  parameters are copied from `rdi`, `rsi`, `rdx`, `rcx`, `r8`, `r9` into
  slots 0 to 5. `ship it` jumps to `.Lret_NAME`, and falling off the end
  returns 0. `main` and the microservices share `prologue`/`epilogue`.
- **Calls.** Arguments are evaluated left to right, popped into the
  registers in reverse order, and `call` pads `rsp` by 8 when the static
  depth is odd (Implementation Spec 10.6). Nothing stays in a register
  across a call.
- **Depth limit.** After each microservice's prologue:
  `inc`/`cmp 1000`/`jg .Lstack_overflow`. Before its `leave`: `dec`. The
  handler does `and rsp, -16` and calls `btw_rt_stack_overflow`. Like the
  interpreter (NOTES-interp decision 1), the check runs in the callee after
  the arguments are evaluated.
- **Git history.** Tracked symbols get ids 0 to 63 in `symbols.all` order.
  Declarations (global initializers included) call `btw_rt_hist_reset`, and
  assignments call `btw_rt_hist_commit`, including assignments to a tracked
  global from inside a microservice. All three pass the statement's 1-based
  start line in `rdx`, for `git blame`. `git revert` calls
  `btw_rt_hist_revert` and stores `rax`. `git log` passes `rdx = 1` and
  `git blame` passes `rsi = 1` for booleans. Each tracked name is a
  `.LstrN` string; `git blame` needs none, since it prints no HEAD.
- Slots: each function's symbols in `symbols.frames` order, written to
  `Symbol.slot`. FRAME is 8 per slot rounded up to 16, and `sub rsp` is
  omitted when there are no slots.
- One label counter shared by every construct (`.Lloop1`, `.Lelse2`,
  `.Lendif2`, `.Lfalse5`, `.Lend5`). Strings are deduplicated: identical
  literals share one `.LstrN`.

## Decisions where the spec is silent

1. **`push IMM` for small literals.** Implementation Spec 10.4 lowers every
   number literal to `mov rax, IMM` plus `push rax`. A literal that fits in
   a signed 32-bit immediate is pushed directly (`push 15`), which is one
   line shorter on the projector and sign-extends to the same value.
   Anything bigger still goes through `mov rax`.
2. **An `if` without `skill issue`** jumps straight to `.LendifN`, so there
   is no empty `.LelseN` label and no `jmp` over nothing.
3. **Annotations.** Each statement gets a blank line and
   `# line N: SOURCE`. SOURCE is the statement's own text, so a one-line
   block like `{ console.log "Fizz" }` gets its own comment. `vibe check`
   and `doomscroll` show their header up to the `{`, an else-if shows
   `skill issue vibe check ...`, and an else block gets `# line N: skill
   issue`. Global initializers and the `serve` line are annotated too. With
   `--annotate`, some instructions also get a short trailing note (the
   variable a slot belongs to, `404: skip the block`, `one call deeper`,
   `history of x`, and so on). Without `--annotate` the output has no
   comments at all.
4. **A microservice's header comment goes before its label**
   (`# line 2: microservice f(n) O(1)`, then `btw_fn_f:`), while `serve`'s
   comment stays after `main`'s prologue.
5. **`serve` returns through `.Lret_serve`, not `.Lret_main`.** Language
   Spec 8 allows a microservice named `main`, whose label `.Lret_main` would
   collide. `serve` is a reserved word, so `.Lret_serve` can't.
6. **The division-by-zero handler** is emitted once, after every function,
   and only when a `/` or `%` exists.
7. **The depth counter only runs in microservices.** `main` never touches
   `btw_depth`, since `serve` is depth 0 (Language Spec 8).
8. `rdi` is set with `mov rdi, ID`, as 10.5 writes it, not `mov edi, ID`.
9. **E501 for more than 64 tracked variables.** 10.7 says "more than that
   is E501" but not where. It goes on each `git revert` / `git log`
   statement whose target is the 65th tracked variable or later, with the
   `` `git revert` `` / `` `git log` `` construct text. The first 64 by
   checker order still get history.

## Tests

`tests/test_codegen.py`:

- E501 and E502 (exit 3, gcc's stderr follows), `--keep-asm`, `.string`
  escaping, frame size, big literals, annotations, the depth invariant, and
  the 64/65 tracked-variable boundary.
- Assembly shape: prologue/epilogue with six parameters, argument pops in
  reverse order, padding at odd depth and none at even depth, labels for a
  microservice named `main`, history call sequences.
- Differential programs, each built and compared with the interpreter: big
  numbers, nested `&&`/`||`, division signs, libc names (`main`, `printf`,
  `exit`), nested calls in arguments, recursion up to and past 1,000,
  arguments evaluated before the depth check, division by zero inside a
  call, history changed from microservices and in loops, the 16-commit cap,
  revert toggling, and the exit-128 error.
- **Alignment probe.** A test runtime `#include`s `runtime/btw_rt.c` with
  every function renamed and wraps each one with a check: at `-O0` with a
  frame pointer, `rbp` is 16-aligned exactly when the caller's `rsp` was
  aligned at the call. A misaligned call exits 99. The probe runs over every
  differential program and every golden with a run sidecar, and
  `test_alignment_probe_catches_a_missing_pad` checks that it really fails.

## Open items

- **Deep recursion and the real stack.** 1,000 frames is far below the 8 MB
  default stack, so the counter always fires first. Not tested with a
  lowered `ulimit -s`.
- `test_every_checked_golden_generates_or_reports_e501` keeps its part 1
  name. Every checked golden now generates.
