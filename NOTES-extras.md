# P2 extras notes

Card: the P2 language features, in order: pipes, works on my machine, git
history, the roast backlog. Specs: Language Spec 9.3 to 9.5 and 13,
Implementation Spec 6.

## 1. Pipes (Language Spec 9.4)

Files: `src/btw/parser.py`, `tests/test_parser.py`; the `WAITING` entries in
`tests/test_checker.py` and `tests/test_golden.py` are gone.

- `expr()` is an expression used as a value. It calls `pipeline()`, the
  Pratt loop, which hands over to `stages()` at a `|` when the minimum level
  allows level 1. Only the statement parser calls `pipeline()` directly.
- Each stage becomes `Call(callee, [piped, *extra])` with the stage's own
  span (`add(10)`, or just `double`). The piped value is the first argument.
- A final `console.log` stage makes a private `_PipePrint` placeholder (a
  subclass of ErrorExpr, so it never reaches the AST): an expression
  statement turns it into `Print(value)`; in any other position `expr()`
  reports E405 on the `console.log` stage and puts an ErrorExpr in its place
  (no type cascade, and the declaration still happens).
- After a stage only another `|` may follow (`pipeline = or { "|" stage }`),
  so `a | f + 1` is "expected end of line, found `+`.", not `(a | f) + 1`.
- A stage that isn't a name or `console.log` is "expected a name".

### Decisions where the spec is silent

1. **`console.log` in the middle** (`5 | console.log | f`): the spec says
   "last stage only" without a message. Feeding it to another stage uses it
   as a value, so it gets the same E405.
2. **E405 doesn't spend the statement's E400 budget**, because it isn't a
   syntax error.
3. **Names in a void pipe aren't checked**: the whole pipeline becomes one
   ErrorExpr, so `npm install y = nope | console.log` reports only the E405.

### For other cards

- **LSP / hovers:** hovering the head of a pipe (`x` in `x | f`) shows
  nothing. `hovers.name_at` skips any node whose span doesn't contain the
  position, and a desugared Call has its stage's span (Language Spec 9.4),
  which doesn't cover its first argument. Fix in `hovers.py`: don't prune at
  a Call (or check `args` regardless of the Call's span).

## 2. Works on my machine (Language Spec 9.5)

Already done before this card: `src/btw/suppress.py` (PR #9, see
NOTES-suppress) applies 9.5 to the full diagnostic list (lexer, parser,
checker, Big O), and `driver.check` calls `suppress.apply(program,
diagnostics)` just before the final sort. I checked it against 9.5 line by
line: it targets the first statement or item that starts after the
directive, removes the soft diagnostics that start inside it (never E429),
and leaves exactly one W200 or W304 on the directive. The runtime half
(a suppressed E403 assignment really assigns) works because suppression
never changes the AST. No code change; the four goldens
(`p2_w200_two_problems`, `p2_w200_works_on_my_machine`,
`p2_w304_hard_error_only`, `p2_w304_nothing_to_suppress`) pass. A
pipeline statement is an ordinary target.

## 3. Git history (Language Spec 9.3)

Also already done before this card, by the interpreter and checker cards
(NOTES-interp, NOTES-checker pass 5):

- `interp.py`: history only for symbols the checker marks `tracked`; a
  declaration starts a fresh list, each push and revert appends and keeps
  the 16 newest; `git revert` with fewer than 2 commits is `fatal: bad
  revision 'x~1'` with exit 128; `git log` prints newest first with
  `(HEAD -> x)`, booleans as `LGTM`/`404`.
- `checker.py`: E403 (soft, with the `sudo git revert X` help) on a revert of
  a constant without sudo, W100 on sudo for a variable, and E405 "History
  only works on globals and variables in `serve`. ..." on the whole
  statement when the target is a microservice parameter or local.

No code change. The goldens pass in interpreter mode (and natively):
`p2_git_history`, `p2_git_log_fresh_history`, `p2_git_log_limit`,
`p2_git_revert_constant`, `p2_runtime_revert_one_commit`,
`p2_e403_revert_constant`, `p2_e405_history_on_local`.

## 4. Roast backlog (Language Spec 13)

Files: `src/btw/lexer.py`, `src/btw/parser.py`, `tests/test_lexer.py`,
`tests/test_parser.py`.

| Input                  | Where  | Status                                                    |
| ---------------------- | ------ | --------------------------------------------------------- |
| `===`                  | lexer  | new: ERROR token + E400                                   |
| `;`                    | lexer  | new: ERROR token + E400 (was "Unexpected character `;`.") |
| `++`                   | lexer  | new: ERROR token + E400                                   |
| `007`                  | lexer  | already done (NOTES-lexer decision 2)                     |
| chained comparison     | parser | already done (NOTES-parser decision 3)                    |
| `serve localhost:8080` | parser | new: E409 on the `localhost:8080` token                   |
| CLI summary line       | CLI    | done later, see "CLI summary line" below                  |

- The three roast tokens are tried before the operators, so `===` is one
  token rather than `==` then `=`. None of `===`, `++` or `;` can start a
  valid token sequence, so no program that used to be valid changes
  meaning. Being ERROR tokens, the parser counts them as the statement's
  E400 and doesn't report again (NOTES-lexer "Token details").
- `test_other_port_is_accepted` now uses port 5000, since 8080 is roasted.

### CLI summary line

Files: `src/btw/printing.py` (`format_summary`), `src/btw/cli.py`,
`tests/test_printing.py`. Decided with the project owner:

- `btw check`, `btw run` and `btw build` print it after the diagnostics, on
  the same stream, in pretty mode only (the goldens use `--format short`, so
  they never see it). `tokens`, `parse` and `asm` don't.
- Only when there is at least one diagnostic left after suppression. Soft
  errors count as errors.
- `build failed: 1 error. Skill issue.` leaves out the warning part when there
  are no warnings, and nouns are singular for 1.
- `btw run` reports diagnostics only when they block the run, so a run with
  warnings alone prints neither the warnings nor the summary.

### Questions

1. **Ports other than 3000 and 8080.** Language Spec 4 says "A port other
   than 3000: Accepted in P0. P2 roast in section 13", but section 13's
   message names 8080 and Spring Boot (8080 is Spring Boot's default).
   Should `serve localhost:5000` get the same E409 with its own number
   ("port 5000 is already in use by a Spring Boot app ...")? For now only
   8080 is roasted and every other port is accepted, as in P0.
2. **`++` message.** The spec text says `git push --force i = i + 1`
   whatever the variable is. Kept verbatim (messages must match the spec
   character for character); `count++` still suggests `i`. Should the
   message name the variable in front of `++` when there is one?
3. **Cascade on `i++`.** The parser keeps the expression statement `i`, so
   `i++` also gets W204 "This expression does nothing." on `i`. Dropping
   broken expression statements would also hide a real E404 on `j++` for an
   undeclared `j`, so it stays. The same already happens for `x @`.

## Status

Whole suite, `uv run pytest`:

```
============================ 1129 passed in 28.80s =============================
```

`uv run pytest tests/test_golden.py -k p2`: 17 passed, interpreter and
native steps both (gcc is installed here). No xfails or skips are left in
the suite.

Works:

- Pipes, including E405 for a void pipe used as a value: `p2_pipes`,
  `p2_e405_pipe_console_log_value`.
- Works on my machine (W200, W304) and git history (interpreter, E403 on
  revert, E405 on microservice locals): already in place, every p2 golden
  for them passes.
- Roasts: `===`, `;`, `++`, `007`, chained comparisons, `serve
  localhost:8080`.

Doesn't work, or not done:

- Hovering the head of a pipe shows nothing (see "For other cards" under
  pipes; the fix belongs in `hovers.py`).
- Open questions above: other ports, the `++` variable name, the W204
  cascade on `i++`.
