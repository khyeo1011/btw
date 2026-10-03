# Checker notes

Files: `src/btw/checker.py`, `tests/test_checker.py`, plus `check` in
`src/btw/driver.py`. Specs: Language Spec 4 to 11, Implementation Spec 4.5
and 7.

## Interface

- `check(program, comments=None) -> (symbols, diagnostics)`. `comments`
  defaults to `program.comments`; the driver passes `program.comments`.
- It fills `ty` on every expression and `sym` on every Var, Call (and its
  callee Ident) and declaration Ident (globals, constants, microservices,
  parameters, locals). A name that doesn't resolve gets `sym = None`.
- `Symbol` (Implementation Spec 4.5) has `name`, `kind` (`SymbolKind`: LOCAL,
  PARAM, GLOBAL, CONST, MICROSERVICE), `ty`, `decl_span`, `owner` (the
  microservice name, `"serve"` or `"global"`), `arity`, `tracked` and
  `slot`. It uses identity for `==` and hashing, so the interpreter and the
  codegen can key dicts by Symbol.
- `Symbols` has three fields:
  - `globals`: every top-level name (global, constant, microservice) mapped to
    its symbol. When a name is declared twice, the first declaration wins.
  - `frames`: `"serve"` and each microservice name mapped to its parameters
    and then its locals, in declaration order. Use that order for codegen
    slots. Every declaration gets its own symbol, so sibling `i`s are two
    entries.
  - `all`: every symbol, in the order the checker created it.
- A StrLit always has `ty = STRING`. Its parent sees UNKNOWN when the string
  is an E415, so `Print.value.ty is Type.STRING` is how the codegen spots a
  string print.

## Passes

1. Structure: E426, E410, E503, and E409 for each extra `serve`. W208 belongs
   to the parser (NOTES-parser), so the checker doesn't report it.
2. Hoisting: globals, constants and microservices go into `globals`. E409 for
   a duplicate name, E413 for 7 or more parameters.
3. Global initializers: run in source order. Only globals declared above are
   visible, plus microservice names, so that `npm install A = f` gets the E405
   "is a microservice" message. Any call is E405 (postinstall).
4. Bodies: a scope stack for each microservice and for `serve`. This pass
   covers names, types, sudo (E403, W100), `touch grass`, W509, W204 and W410.
5. History: the targets of `git revert` and `git log` that belong to globals
   or `serve` get `tracked`. A microservice parameter or local as the target
   is E405 on the whole statement.
7. Comments: E406 on every BAD comment, and E429 on every TODO after the
   fifth, with the file's total count in the message.
9. Finish: sort and drop duplicates, the same way `driver.sort_diagnostics`
   does. The driver sorts again after Big O and suppression.

## Decisions where the spec is silent

1. **E426 span.** The checker never sees the source text, so it can't
   measure line 1. Instead, the span runs from 1:1 to the start of line 2.
   The pretty printer shows that as carets to the end of line 1, and LSP
   shows it as the whole line.
2. **Keyword spans** (`npm install -g` for E405, `doomscroll` for W509,
   `serve` for the extra-serve E409, `sudo` for W100) start at the statement
   and are as long as the keyword written with single spaces. The AST
   doesn't keep keyword tokens, so a keyword like `npm  install -g` with
   extra spaces gets a span that stops short.
3. **E503 without `:wq`** sits zero-width at the end of the file, at
   `program.span.end`.
4. **Name clashes at top level.** The message is "already deployed" only
   when a microservice repeats a microservice name. Every other clash (a
   global after a global, a microservice after a global, a global after a
   microservice) gets "already installed" on the later name.
5. **Shadowing by a parameter** (a parameter named like a global or a
   microservice) is E409 "already installed", the same as a repeated
   parameter name.
6. **A rejected declaration** (E409) still gets a fresh symbol on its Ident,
   which hover can use, but it isn't bound. The visible earlier symbol
   stays, so later uses don't cascade.
7. **`npm install -g` in a block** is E405, and then it declares a constant
   local of that function. So it needs `sudo` like any other constant.
8. **Assigning, reverting or logging a microservice name** is the E405
   "is a microservice. Call it" message on the name.
9. **Calls in a global initializer** get only the postinstall E405, with no
   E404, E405 or E422 for the callee. The arguments are still checked.
10. **The result type of an operator is fixed by the operator,** even when an
    operand is wrong or unknown. Arithmetic and unary minus give NUMBER;
    comparisons, logic and `!` give BOOLEAN. For example, `x + LGTM == 1`
    reports only the `+`. An unknown callee, a called variable and an
    ErrorExpr are UNKNOWN.
11. **Every offending operand gets its own E418.** `LGTM * 404` is two
    squiggles, and so is `1 && 2`. Comparisons and equality get one E418 on
    the whole expression.
12. **A string condition, return value, argument or operand** is E415 only,
    never an E418 too. A string as an expression statement is E415 and W204.
13. **W509 reading.** A `ship it` anywhere in the body counts as a way out,
    even inside a nested doomscroll, because it leaves the function. A
    `touch grass` counts only outside nested doomscrolls. Only the literal
    `LGTM` triggers W509: `(LGTM)` counts, because parentheses aren't nodes,
    but `!404` doesn't.
14. **W410** only follows `ship it`, not `touch grass`. Each block gets at
    most one W410, on the first statement after its first `ship it`.
    Nested blocks are judged on their own.
15. **W204** fires for any expression statement that isn't a Call. An
    ErrorExpr doesn't get W204, because the parser already reported it.
16. **History in nested `serve` blocks** counts as "in `serve`" (owner
    `serve`), as NOTES-harness question 14 assumes.
17. **E403 help for `git revert`** is "try `sudo git revert X`". The spec
    only gives the `git push --force` form.

## Status

- Every `tests/golden/*.diag` matches `btw check --format short`, Big O
  and suppression codes included (`bigo.py` and `suppress.py` run in the
  driver).
- The E405 "`console.log` returns nothing" for a pipe used as a value comes
  from the parser, not the checker: the desugared AST has no node for a
  pipeline (NOTES-extras).
- `uv run pytest tests/test_checker.py` passes. The tests include that
  golden comparison, plus unit tests for symbols and types and for every
  message and span the corpus doesn't cover.

## Questions

1. **Two bad operands** (`LGTM + LGTM`): one E418 per operand, or only the
   first? The catalog says "the offending operand", and "One mistake, one
   squiggle" could be read either way. The checker reports both.
2. **W509 and `ship it` in a nested doomscroll** (Language Spec 6): does
   "outside nested doomscrolls" apply only to `touch grass`, or to `ship it`
   too? The checker counts that `ship it` as a way out (decision 13).
