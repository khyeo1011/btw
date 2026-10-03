# Big O notes

Files: `src/btw/bigo.py`, `tests/test_bigo.py`. Specs: Language Spec 9.1,
Implementation Spec 8. The driver already calls `bigo.check_bigo(program)`
after the checker, so no driver change was needed.

## Interface

| Function                        | Returns                                                                 |
| ------------------------------- | ----------------------------------------------------------------------- |
| `infer(program)`                | each microservice name mapped to an int degree, or `UNKNOWN`           |
| `costs(program)`                | each name mapped to a `Cost`: `degree` plus `loop`, the deepest loop    |
| `check_bigo(program)`           | E417, W417, W102, W508 and W203 diagnostics                             |
| `format_complexity(degree, var)` | `O(1)`, `O(n)`, `O(n²)`, `O(n³)`, `O(n^4)`; `O(?)` for `UNKNOWN`         |

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

## Not done

- Quick fixes (P2): "Update SLA", "Add SLA", "Tighten SLA". W102's fix needs
  the position after the closing parenthesis of the parameter list, which
  the AST doesn't keep.

## Other cards

- `p2_w200_two_problems` reports a W102 until `suppress.py` lands: it's the
  only golden whose Big O lines don't match yet, and it's a strict xfail in
  `tests/test_bigo.py` (`WAITING`). Remove it from there when suppression
  lands.
- Checker card: `tests/test_checker.py` filters the Big O codes out through
  `OTHER_CARDS`, so this card causes no unexpected passes there. Those codes
  can come out of `OTHER_CARDS` now.

## Open questions / parser

The parser reports every unclosed `(`, checked in `tests/test_bigo.py`
(`UNCLOSED`, 26 cases): parameter lists with zero, one and many parameters,
on several lines, with a comment inside, with the `)` missing before `{`, a
newline, `O(`, `serve` or the end of file; call arguments; grouping; and
`O(` annotations. Each gets the file-level E400 "Syntax error: expected `)`,
found `:wq`. Even Lisp programmers close their parentheses." (or "found end
of file. ...") and, unless the file ends right there, a local E400 on the
token where the `)` should have been. Nothing in `parser.py` needs fixing
for this card; these are for the parser card:

1. **Missing name or `)`?** `microservice f( {` and `microservice f(a, b, {`
   get "expected a name, found `{`." locally, where `f(n {` gets
   "expected `)`". After `(` the grammar (Language Spec 3) accepts either a
   name or `)`, so both are defensible and the spec doesn't pick. The
   file-level `)` error is there either way.
2. **Cascading E503.** An unclosed `(` in a parameter list or a global
   initializer makes the lexer drop every later newline (Language Spec 2.1),
   so top-level recovery never sees a line that starts with `serve` and the
   program also gets E503 "no server running". That's three diagnostics for
   one mistake. NOTES-lexer item 5 already asks the parser card about it.
3. **Catalog text.** The "Even Lisp programmers close their parentheses."
   suffix is the project owner's decision (NOTES-parser), not in the
   Language Spec 11 catalog yet. The catalog should get the row.
