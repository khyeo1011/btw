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
