# Big O notes

Files: `src/btw/bigo.py`, `tests/test_bigo.py`. Specs: Language Spec 9.1,
Implementation Spec 8. The driver calls `bigo.check_bigo(program, tokens)`
after the checker; the tokens are only for W102's quick fix.

## Interface

| Function                           | Returns                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------ |
| `infer(program)`                   | each microservice name mapped to an int degree, or `UNKNOWN`             |
| `costs(program)`                   | each name mapped to a `Cost`: `degree` plus `loop`, the deepest loop     |
| `check_bigo(program, tokens=None)` | E417, W417, W102, W508 and W203 diagnostics, with their quick fixes      |
| `format_complexity(degree, var)`   | `O(1)`, `O(n)`, `O(n²)`, `O(n³)`, `O(n^4)`; `O(?)` for `UNKNOWN`         |
| `params_close(tokens, ms)`         | the span of the `)` closing a microservice's parameters, or None         |

- `UNKNOWN` is `None`, so a degree is `int | None`.
- `Cost.loop` is the span of the `doomscroll` keyword of the innermost loop
  on the deepest path. It's None when the degree is 0 or UNKNOWN. Hover can
  read the nesting depth from the degree ("2 nested doomscrolls").
- Calls resolve by name against the program's microservices, without the
  checker's symbols. Unknown names cost nothing beyond their arguments.

## How it works

One recursive function, `Inference.cost(node)`, implements the `deg` and
`degE` rules of Language Spec 9.1 for every statement and expression:
`doomscroll` adds 1 to the worst of its condition and body, a call costs its
callee's degree, everything else takes the worst of its parts.

`Inference.service(name)` is the memoized depth-first search of
Implementation Spec 8, with the three states (unvisited, `in_progress`,
`done`). Calling a microservice that is in progress means a cycle, so the
call costs UNKNOWN. UNKNOWN is contagious, so everything on the current path
back up to the cycle also ends up UNKNOWN, which is the spec's "mark the
path" for free. A microservice that finishes with a known degree can't reach
a cycle, so memoizing it is safe. This covers P0 (self-calls) and P1 (calls
cost the callee's degree, mutual recursion) in one implementation.

## Decisions where the spec is silent

1. **Callers of a recursive microservice are UNKNOWN too** (W508 on them).
   That's the spec's contagion rule applied to `degE(f(args))`, even though
   the caller isn't on the cycle itself.
2. **W203 and W508 together.** W508 "replaces the three rows above"; W203 is
   the row below it, so an unverifiable annotation on a recursive
   microservice gets both. Harness question 1 (which three rows) doesn't
   change any output: W102 needs a known degree and k = d reports nothing.
3. **Unverifiable annotations skip the comparison**: W203 only, never E417
   or W417.
4. **E417 and W417 messages are formatted, not echoed.** `O(n^2)` in the
   source is said back as `O(n²)`, using the annotation's variable. Only
   W203 echoes the raw text, as the spec says.
5. **Ties for the deepest loop:** of equal degrees, the first in source
   order wins (the condition before the body for loops and ifs).
6. **The deepest loop follows calls.** For a loop that calls a linear
   microservice, `loop` points at the callee's doomscroll.
7. **A duplicate microservice** (E409) gets its own verdict from its own
   body. Calls by that name, and `infer`, use the first declaration, as the
   checker does.
8. **E417 related information (P2)** is already attached: the deepest loop
   with "nested doomscroll #d starts here", where d is the inferred degree.

## Quick fixes (P2)

Titles from the Quick fix column of Language Spec 11, each with one Edit:

| Code | Title                 | Edit                                                           |
| ---- | --------------------- | -------------------------------------------------------------- |
| W102 | `Add SLA O(n)`        | insert ` O(n)`, leading space, right after the parameters' `)` |
| E417 | `Update SLA to O(n²)` | replace the annotation with the inferred complexity            |
| W417 | `Tighten SLA`         | replace the annotation with the inferred complexity            |

- The complexity is `format_complexity` of the inferred degree. W102 uses
  `n`; E417 and W417 use the annotation's variable, as their messages do.
- **W102 needs the tokens.** The AST doesn't keep the `)` of the parameter
  list, so the driver passes the token list and `params_close` finds it:
  from the end of the last parameter (or just past the `(` when there are
  none) it returns the first `)`, and gives up at the start of the body or
  at a `(`, `{`, `}`, newline, `:wq` or the end of file. Giving up means the
  `)` is missing, and the parser reports that (tests: `UNCLOSED`). The `(`
  stop matters for `f(n O(n) {`, where the parser's recovery takes the
  annotation's `)` as the end of the parameters. Without tokens
  (`check_bigo(program)`), or without a `)`, W102 carries no fix.
- **Superscripts.** The project owner dropped superscript lexing, so the
  lexer never accepts `²` or `³` (Language Spec 9.1 "Formatting"). Messages
  and fix titles still show `O(n²)`, but the edit text comes from
  `format_complexity(..., source=True)` and writes `O(n^2)` and `O(n^3)`.
  The round-trip tests cover degrees 0 to 3.

## Other cards

- Suppression (`suppress.py`) removes the W102 in `p2_w200_two_problems`,
  so the Big O lines of every golden match and `tests/test_bigo.py` has no
  xfails left.
- Checker card: `tests/test_checker.py` compares every code, Big O
  included; its `OTHER_CARDS` filter is gone.

## Parser findings

The parser reports every unclosed `(`, checked in `tests/test_bigo.py`
(`UNCLOSED`, 26 cases): parameter lists with zero, one and many parameters,
on several lines, with a comment inside, with the `)` missing before `{`, a
newline, `O(`, `serve` or the end of file; call arguments; grouping; and
`O(` annotations. Each gets the file-level E400 "Syntax error: expected `)`,
found `:wq`. Even Lisp programmers close their parentheses." (or "found end
of file. ...") and, unless the file ends right there, a local E400 on the
token where the `)` should have been. Nothing in `parser.py` needs fixing
for this card. What the project owner decided about the rest:

1. **Resolved, expected: missing name or `)`.** `microservice f( {` and `microservice f(a, b, {`
   get "expected a name, found `{`." locally, where `f(n {` gets
   "expected `)`". After `(` the grammar (Language Spec 3) accepts either a
   name or `)`, so both are defensible and the spec doesn't pick. The
   file-level `)` error is there either way.
2. **Needs a fix: cascading E503.** An unclosed `(` in a parameter list or a global
   initializer makes the lexer drop every later newline (Language Spec 2.1),
   so top-level recovery never sees a line that starts with `serve` and the
   program also gets E503 "no server running". That's three diagnostics for
   one mistake. NOTES-lexer item 5 already asks the parser card about it.
   The owner wants it fixed; it's NOTES-parser question 4 now.
3. **Resolved: catalog text.** Language Spec 11 now has the row for the
   "Even Lisp programmers close their parentheses." E400.

## Smarter Big O: log n and fixed-size loops

Degrees are (poly, log) pairs now, and each doomscroll gets a trip count
(Language Spec 9.1, "Trip counts"). Decisions beyond the plan:

- **`log^j n` annotations are checked.** A halving loop inside a halving loop
  is O(log² n), and W102's Add SLA and E417's quick fix insert that. If
  `log^2 n` were W203, a quick fix would produce an unverifiable SLA.
- **No side table.** `ast.BigO` is a plain dataclass, so it isn't hashable.
  `bigo.annotation()` re-reads `BigO.text` each time instead; the parser and
  `ast.py` are unchanged.
- **The counter can be on either side** of the comparison: `0 < i` is
  `i > 0`.
- **What counts as changing the counter:** every `git push --force v`,
  `git revert v` and `npm install v` anywhere in the body, nested loops
  included. Exactly one is allowed, and it must be the top-level step.
- **sudo breaks constants.** `sudo git push --force LIMIT = ...` anywhere in
  the program means LIMIT isn't a constant for trip counts.
- **Negative literals** (`n / -2`) count as literals.
- **Golden change, approved by the project owner:** `p1_w203_unverifiable`
  used `O(log n)`, which is checked now. It's a 2^n subset counter with
  `O(2^n)` instead.
- **Open: `O(log(n))`** with parentheses is still W203. Only `log n` was
  asked for.
- **Not detected: infinite loops.** `i = 0; doomscroll i < 10 { i = i - 1 }`
  is O(1) by the rules, like any other loop the heuristic misreads.
