# Codegen notes

Files: `src/btw/codegen.py`, `runtime/btw_rt.c`, `tests/test_codegen.py`,
plus one line in `src/btw/driver.py`. Specs: Implementation Spec 10,
Language Spec 5 and 10.

## Interface

- `gen(program, symbols, annotate=False, source=None)` returns
  `(assembly_text, diagnostics)`, as in the NOTES-harness table (question 17
  there). With E501 the text is `""` and the driver writes nothing.
- `source` is new. `btw asm --annotate` needs the source lines for its
  comments and the AST doesn't keep them, so `driver.asm` now passes
  `source=source`. Without it, an annotation is just `# line N`.
- The rest of the build pipeline was already in the driver: a temp
  directory, `gcc -o OUT prog.s runtime/btw_rt.c`, E502 plus gcc's stderr
  (exit 3) when gcc fails, `--keep-asm` writing `OUT.s`.

## Part 1 scope

Native: globals and constants (initializers in source order), `serve`, every
expression, `console.log` of numbers, booleans and strings, `vibe check` /
`skill issue`, `doomscroll`, `touch grass`, `ship it` in `serve` (the exit
code), expression statements, and the division-by-zero check.

E501, reported before any assembly is written:

| Construct                  | Message construct | Span                      |
| -------------------------- | ----------------- | ------------------------- |
| a microservice declaration | `microservice`    | the `microservice` keyword |
| a call                     | `f(...)`          | the call                  |
| `git revert`, `sudo git revert` | `git revert` | the statement             |
| `git log`                  | `git log`         | the statement             |

So every golden with a microservice or git history xfails its native step
("native: not yet (E501)"), as the golden runner expects. That's
`p0_hoisting`, `p0_microservice_args`, `p0_runtime_stack_overflow`,
`p0_w508_recursion`, `p1_w102_no_big_o`, `p2_w200_two_problems` and every
`p2_git_*`/revert golden, including `p2_w100_unnecessary_sudo` (it uses
`sudo git revert`).

## Status

- Every golden with a run sidecar and no microservice or git history passes
  natively, byte for byte against the same `.out`/`.err`/`.exit` the
  interpreter matches: 21 programs, `p0_runtime_modulo_by_zero` (no `.out`)
  included. Full suite: 987 passed, 18 xfailed.
- `tests/test_codegen.py`: E501 messages and spans, E502 through the CLI
  (exit 3, gcc's stderr follows), `--keep-asm`, `.string` escaping, frame
  size, big literals, annotations, the depth invariant, and eight extra
  differential programs (big numbers, nested `&&`/`||`, division signs,
  globals with sudo, `ship it` from a nested loop, non-ASCII strings, a
  short-circuit guarding `% 0`, a runtime error after output), each built and
  compared with the interpreter.
- The runtime is complete for Implementation Spec 10.7, history included.
  The history functions aren't called by any generated code yet; I checked
  them by hand with a small C driver against the Language Spec 9.3 example,
  the 16-commit cap, booleans and the exit-128 error.

## How it works

- `Codegen.depth` counts the temporaries pushed right now. `push` and `pop`
  are the only ways to change it (plus the `add rsp, 8` of an expression
  statement and the short-circuit join). `expr` asserts every expression
  leaves exactly one value, and `stmt` asserts the depth is 0 before and
  after every statement. A failed assertion is an AssertionError, which the
  CLI reports as E500. `test_every_checked_golden_generates_or_reports_e501`
  runs the generator over every checked golden.
- `call` pads with `sub rsp, 8` when the depth is odd (Implementation Spec
  10.6). In part 1 every call is at a statement boundary, so it never pads;
  the padding matters once calls appear inside expressions.
- Slots: `serve`'s locals in `symbols.frames["serve"]` order, written to
  `Symbol.slot`. FRAME is 8 per slot rounded up to 16, and `sub rsp` is
  omitted when there are no slots.
- One label counter shared by every construct (`.Lloop1`, `.Lelse2`,
  `.Lendif2`, `.Lfalse5`, `.Lend5`). One shared `.Ldiv_zero` handler after
  `main`, emitted only when a `/` or `%` exists.
- Strings are deduplicated: identical literals share one `.LstrN`.

## Decisions where the spec is silent

1. **`push IMM` for small literals.** Implementation Spec 10.4 lowers every
   number literal to `mov rax, IMM` plus `push rax`. A literal that fits in
   a signed 32-bit immediate is pushed directly (`push 15`), which is one
   line shorter on the projector and sign-extends to the same value.
   Anything bigger still goes through `mov rax`.
2. **An `if` without `skill issue`** jumps straight to `.LendifN`, so there
   is no empty `.LelseN` label and no `jmp` over nothing.
3. **E501 for calls.** The catalog only shows the `git log` message. I read
   the backticked part as the construct's name, so calls say `` `f(...)` ``,
   the same way E405 writes a call. A program with a microservice gets one
   E501 for the declaration and one per call.
4. **Annotations.** Each statement gets a blank line and
   `# line N: SOURCE`. SOURCE is the statement's own text, so a one-line
   block like `{ console.log "Fizz" }` gets its own comment. `vibe check`
   and `doomscroll` show their header up to the `{`, an else-if shows
   `skill issue vibe check ...`, and an else block gets `# line N: skill
   issue`. Global initializers and the `serve` line are annotated too. With
   `--annotate`, some instructions also get a short trailing note: the
   variable a slot belongs to (`# i`), `404: skip the block`, `keep
   scrolling`, `touch grass`, `ship it`, `dividing by zero?`. Without
   `--annotate` the output has no comments at all.
5. **`btw_depth`** is in `.data` as Implementation Spec 10.2 shows, even
   though part 1 never touches it.

## Part 2 (not started)

- Microservices: `btw_fn_NAME`, parameters copied from `rdi`... into slots
  0 to 5, `.Lret_NAME`, the `btw_depth` check after the prologue and the
  decrement before `leave` (NOTES-interp decision 1: the check runs in the
  callee, after the arguments are evaluated). Then `print` inside them, and
  `ship it` jumping to the function's own return label.
- Calls: pop the arguments into registers in reverse order, then `call`
  with the existing alignment logic.
- History: ids per tracked symbol (64 max, else E501), one `.LstrN` per
  tracked name, `btw_rt_hist_reset` on declaration, `btw_rt_hist_commit` on
  assignment.

## Branch

Developed on `claude/amazing-lovelace-i7qgh8`, the branch the session
assigned, not on a `feature/NAME` branch as CLAUDE.md asks.
