# Suppression notes

Files: `src/btw/suppress.py`, `tests/test_suppress.py`. Specs: Language
Spec 9.5 and 9.6, Implementation Spec 7 (pass 8) and 4.2 (`soft`). The
driver already calls `suppress.apply(program, diagnostics)` after the
checker and Big O passes, so no driver change was needed.

## Interface

| Function                       | Returns                                                         |
| ------------------------------ | --------------------------------------------------------------- |
| `apply(program, diagnostics)`  | the diagnostics after suppression, plus one W200 or W304 each  |
| `w200(count)`                  | the W200 message, "1 problem" or "N problems"                   |

`W304_HARD` and `W304_NOTHING` hold the two W304 messages.

## How it works

- The candidate targets are every item and every statement, nested blocks
  included, sorted by start position. A directive's target is the first one
  that starts at or after the end of the comment, so blank lines and other
  comments are skipped for free. A `skill issue vibe check` is part of its
  if statement, not a target of its own; the statements in its block are.
- A diagnostic is inside the target when its span starts inside the
  target's span. For a microservice, that's the whole function, annotation
  included (E417, W102 on the name).
- It removes the diagnostics with `soft` set (E403, E417 and every warning),
  except E429, which is never suppressed even if something marks it soft
  (Language Spec 9.6).
- Verdict on the directive's own span: W200 with the count when something
  was removed; otherwise W304 "this one doesn't work on any machine" when
  the target still has diagnostics (necessarily hard ones), or W304
  "nothing to suppress" when it has none.
- The W200 and W304 warnings are added after every directive has run, so no
  directive can suppress another directive's verdict ("always leaves exactly
  one warning on the directive itself").

## Questions

Language Spec 9.5 is silent on these; the implementation picks the defaults
below until someone rules on them. Each has a test in `tests/test_suppress.py`.

1. **A directive with nothing after it** (no statement or item starts after
   it, for example just before `:wq`). Default: W304 "304 Not Modified:
   nothing to suppress. It works on every machine." (9.5, "Nothing to
   remove").
2. **A directive on the last line of a block**, just before `}`. Default:
   the literal reading of "the first statement or item that starts after
   it", so it targets the next statement after the block, in the outer
   scope (or the first statement of a following `skill issue` block).
3. **Two directives on the same target**, or an outer directive whose target
   contains an inner directive's target. Default: directives run in source
   order on what the earlier ones left, so the first takes everything and
   the second gets W304 "nothing to suppress". If the shared target also has
   hard errors, the second gets W304 "this one doesn't work on any machine"
   instead, since only hard errors are left for it.

## Other cards

- The runtime half of 9.5, "Suppressed code runs normally: a suppressed E403
  assignment really assigns", belongs to `interp.py` (and the codegen):
  suppression only removes diagnostics and never changes the AST, so a
  suppressed `git push --force LIMIT = 11` must still assign at run time.
- `tests/test_checker.py` still filters W200 and W304 out through
  `OTHER_CARDS`; now that this card has landed they could come out too.
