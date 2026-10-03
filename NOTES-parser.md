# Parser notes

Files: `src/btw/parser.py`, `tests/test_parser.py`, plus `cmd_parse` in
`src/btw/cli.py`. Specs: Language Spec 3 and 4, Implementation Spec 4.4
and 6.

## Interface

- `parse(tokens, comments=None) -> (program, diagnostics)`. The driver calls
  it with both arguments (NOTES-harness); `comments` go straight into
  `Program.comments`. It never raises: an internal error, or input nested
  deeper than Python's recursion limit (a few hundred parentheses), returns
  the items parsed so far plus E500.
- `format_ast(program) -> str`: one node per line, indented two spaces per
  level, as `label: Kind LINE:COL-LINE:COL field=value ...` (1-based, end
  exclusive). `ty` and `sym` only show once the checker has set them.
  `btw parse` prints it now, the same way `btw tokens` prints
  `lexer.format_tokens`. `cli.dump` is unused but stays, because
  `tests/test_driver.py` tests it. The harness owner can delete both.
- The parser builds only the `ast.py` classes and reports E400, E408, W208
  and E500.

## How it works

- Recursive descent for items and statements, and a Pratt loop for binary
  operators (`INFIX` maps each operator to its Language Spec 3.1 level).
  Unary operands are parsed at level 8, so `-x * 2` is `(-x) * 2`.
- **One E400 per statement.** `errored` is saved and reset for each
  statement and each item, and restored afterwards, so a broken statement
  inside a block doesn't use up the E400 of the statement around it. A
  token can't carry two parser E400s either, even from different
  statements (`reported`).
- **Lexer errors count.** An ERROR token (unexpected character) or
  `git push` already has the lexer's E400, so the parser marks the statement
  as errored without reporting anything. `git push x = 2` still becomes an
  Assign.
- **W208** (decided by the project owner): the parser reports it, like
  E408, because `Program` has no field for repeated arch lines. Every
  `i use arch btw` token after the first one in the file gets W208 on its
  own span, at top level or inside a block, as a soft warning. A single arch
  line that isn't first gets nothing from the parser: `has_arch` is false
  and the checker reports E426. An arch line after `:wq` is only part of the
  trailing span (E410). Implementation Spec 7 still lists W208 in the
  checker's structure pass, so the checker card must not report it again.
- **Unclosed `(`** (decided by the project owner): when the program ends
  (at `:wq`, or at the end of the file without one) with a `(` still open,
  the parser reports "Syntax error: expected `)`, found `:wq`. Even Lisp
  programmers close their parentheses." (or "found end of file. Even Lisp
  ...") on that token. The joke is the owner's request, and Language Spec 11
  has the row. It counts parens the way the lexer does: a
  `)` with nothing open is ignored. This report is file-level, so it sits
  outside the one-E400-per-statement budget and replaces any other E400 on
  the same token, such as the outermost block's missing `}`. The lexer drops
  every newline after an unclosed `(`, so this names the real cause even
  when the parser already reported something along the way (usually
  "expected `)`, found `}`"). A `(` after `:wq` is only trailing (E410).
- **Spans:** a statement runs from its first token (including `sudo`) to the
  last token it consumed. A binary expression starts at the first token of
  its left operand, so `(1 + 2) * 3` starts at the `(` while the grouped
  `1 + 2` keeps its own span. A missing `}` ends the block at its last
  token.

## Decisions where the spec is silent

1. **ErrorExpr span.** It's zero-width, at the start of the token where the
   expression should have started: 3:20-3:20 in `p0_e400_missing_expression`.
2. **A missing name drops the statement.** `VarDecl`, `GlobalDecl`,
   `Assign`, `Revert`, `Log` and `Microservice` can't exist without a name, so
   `npm install sudo = 1` and `git push --force = 5` produce no node. A
   missing `=` or value keeps the declaration, with an ErrorExpr value
   (Implementation Spec 6).
3. **Chained comparisons** use the section 13 roast, "Chained comparisons
   aren't a thing here. This isn't Python.", on the second operator. It
   covers both non-associative levels (`a < b < c` and `a == b == c`), since
   Python chains both. The whole chain becomes one ErrorExpr, so the checker
   doesn't add an E418 for `(a < b) < c`.
4. **Misused `sudo`.** The E400 sits on the token after `sudo` (NOTES-harness
   question 7). Then the parser parses the rest as a normal statement, so
   `sudo console.log x` still checks `x`.
5. **`skill issue` followed by neither `vibe check` nor `{`** gives
   "expected `{`".
6. **`serve` without `localhost:N`** gives "expected `localhost:3000`" (it
   names the only port the spec accepts without a P2 roast). The Serve node
   is kept with port 3000, so there's no E503 on top.
7. **`trailing_span`** runs from the first token after `:wq` that isn't a
   newline to the end of the file ("from there to the end of the file",
   Language Spec 4). Newlines after `:wq` don't count, and neither do
   comments, since they aren't tokens.
8. **Items need no newline between them**, as in the grammar's
   `{ item NL* }`. `i use arch btw serve localhost:3000 { } :wq` is a valid
   one-line program.
9. **A statement must end** at a newline, a `}` or the end of the file.
   Anything else gets "expected end of line, found WHAT."
10. **Big O text** is rebuilt from token spans, because the parser never
    sees the source. Spaces come back exactly. A tab inside an annotation
    comes back as a space, and a line break as one space (newlines inside
    parentheses aren't tokens). An unclosed annotation is unverifiable.
    `O(n^k)` takes k from the INT token's value. The lexer doesn't accept
    superscripts (the owner dropped them), so `O(n²)` is an E400.

## Recovery beyond the spec

Implementation Spec 6 says to skip to a NEWLINE or a `}` inside blocks, and
to the next line that starts with an item keyword or `:wq` at top level. On
top of that:

- **Braces opened while skipping are skipped as a pair.** A broken
  `skill issue { }` doesn't close the block around it. Without this, its `}`
  closes the outer block and the real `}` turns into a top-level error.
- **`:wq` always stops a skip**, even in the middle of a line, and a block
  that reaches `:wq` closes with "expected `}`, found `:wq`." That way a
  missing brace never hides `:wq`, which would add a wrong E408.
- **`microservice` or `serve` at the start of a statement** closes the open
  block ("expected `}`, found `serve`.") and goes back to top level. Both
  are reserved words, so they can't start a statement.
- **Before a block's `{`:** a `{` on the next line (Allman style) gets an
  E400 and the block is parsed anyway. Junk before `{` on the same line is
  skipped (`doomscroll x < ) {`).
- **A stray `{ ... }` in a block** gets "expected a statement, found `{`" and
  is parsed and thrown away, so its braces stay balanced.
- **Bad parameter lists** skip to their `)`, so the Big O annotation and the
  body still parse.
- **A missing `}` at the end of the file** gets the E400 once, from the
  innermost block. Every outer block closes silently. An unclosed `(` takes
  that token's E400 instead.

## Questions

1. **Resolved: W208** is reported by the parser (see "How it works").
2. **Resolved: unclosed `(`.** The parser now reports it when the program
   ends (see "How it works"). The lexer still drops every newline after the
   `(` (NOTES-lexer decision 5), so the statements in between still parse as
   one line.
3. **Other lexer E400s** (unterminated string, bad escape, leading zeros)
   don't count as the statement's E400, because the parser only sees a
   normal token. A statement can then end up with a lexer E400 and a parser
   E400. No golden test does this.
4. **Needs a fix (owner decision): cascading E503 after an unclosed `(`.**
   An unclosed `(` in a parameter list or a global initializer makes the
   lexer drop every later newline (Language Spec 2.1, NOTES-lexer decision
   5), so top-level recovery never finds a line starting with `serve` and
   the program also gets E503 "no server running": three diagnostics for
   one mistake. Example: `microservice f(n {` followed by a normal `serve`
   block. The owner wants the E503 gone. Resetting the lexer's paren depth
   at `{` or `}` would do it, but section 2.1 doesn't allow that yet, so the
   fix needs a spec change first (parser and lexer cards). Found by the Big
   O card (NOTES-bigo "Parser findings").

## Pipes

Pipes parse now (P2 extras card, see NOTES-extras): `|` is level 1 in
`expr`, each stage desugars into a Call with the stage's span, and a final
`console.log` makes a Print when the pipeline is the whole statement, E405
anywhere else.

## Status

- `uv run pytest tests/test_parser.py`: 212 pass, plus the 2 pipe xfails.
  The tests cover every case on the card, and for every
  `tests/golden/*.btw` they check that the lexer and parser together give
  exactly the E400, E408 and W208 lines in its `.diag`.
- `tests/test_golden.py` still fails everywhere with "checker is not
  implemented yet".
