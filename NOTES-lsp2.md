# NOTES-lsp2

Language server polish, the P2 rows of Implementation Spec 11: code actions,
relatedInformation, semantic tokens and inlay hints. NOTES-lsp.md covers the
first lsp card (diagnostics, hover, position encodings); this file records
what this card decided where the specs are silent and what was verified in
Neovim.

## Files

```
src/btw/lsp.py       code actions, semantic tokens, inlay hints
src/btw/checker.py   fixes for E426 and E403; related information for E409
src/btw/parser.py    the fix for E408 (see "E408 lives in the parser" below)
tests/test_lsp.py    every feature over the stdio protocol
```

## 1. Code actions

- **Which fixes.** The five in the task: Install Arch (E426), Exit Vim
  (E408), Run with sudo (E403), Update SLA (E417) and Add SLA (W102).
  `bigo.py` already filled E417, W417 and W102. The checker now fills E426
  and E403, and the parser E408. The other P2 fixes in the catalog (Add
  --force, Delete it, Remove sudo) are not done; Tighten SLA (W417) works
  because `bigo.py` already had it.
- **E408 lives in the parser.** The task said to add the missing fixes in the
  checker or `bigo.py`, but E408 is reported by the parser (NOTES-harness
  question 4: `Program` keeps no span for the last token), so its fix was
  added there, in `missing_wq`, and nothing else in the parser changed.
- **The edits.**
  - Install Arch inserts `i use arch btw` and a newline at the very start.
  - Run with sudo inserts `sudo ` at the start of the E403 span (the
    `git push --force` or `git revert` keyword), giving the statement the
    help line suggests.
  - Exit Vim puts `:wq` on a line of its own after the line of the E408
    token: it inserts `\n:wq` at the NEWLINE that ends that line, so a
    trailing `// TODO` stays before `:wq`. Without a final newline (the last
    token runs into end of file) it inserts `\n:wq\n` at the end; when the
    end of file is at column 0 (inside an unclosed `(`, where newlines aren't
    tokens, or an empty file) it inserts `:wq\n`.
- **Range matching.** The server reruns the pipeline on the document and
  returns one quickfix action per fix of every diagnostic whose span touches
  the requested range. An empty range is a cursor: it touches the character
  under it, so the column just past a span doesn't count. An empty span (the
  E408 of an empty file) is touched by a range that contains its position.
  `context.diagnostics` from the client is ignored, since the server can
  recompute the real diagnostics, fixes included, from the document text.
- **The action** carries the title from the catalog, kind `quickfix`, the
  diagnostic it fixes, and a WorkspaceEdit with `changes` for the document.
  The server advertises `codeActionProvider` with kind `quickfix`.

### Verified in Neovim

Neovim 0.11.4 (the official Linux release tarball, unpacked in the session
scratchpad, outside the repo) in a tmux session with keystrokes sent one at a
time and the screen captured after each. Started as in NOTES-lsp.md, with
`.venv/bin` on PATH so `btw-lsp` is this checkout:

```
nvim --clean --cmd "set rtp+=editors/nvim" --cmd "luafile editors/nvim/btw.lua" FILE
```

1. **Install Arch.** The E426 program from NOTES-lsp.md. `:lua
   vim.lsp.buf.code_action()` on line 1 shows

   ```
   Code actions:
   1: Install Arch
   ```

   `1` Enter inserts `i use arch btw` as line 1 and
   `#vim.diagnostic.get(0)` drops to 0.
2. **The other four, in one file.** A program with an under-claimed
   `total(n) O(1)`, an unannotated `twice(n)`, `git push --force LIMIT = 11`
   on a constant and no `:wq` opens with four signs (E, W, E, E). With the
   cursor on each diagnostic in turn (`:call cursor(L, C)`, then the code
   action), the menu offered exactly one action each time:
   `Update SLA to O(n)`, `Add SLA O(1)`, `Run with sudo`, `Exit Vim`.
   Choosing each gave

   ```
   microservice total(n) O(n) {
   ...
   microservice twice(n) O(1) {
   ...
     sudo git push --force LIMIT = 11
     console.log total(LIMIT) + twice(2)
   }
   :wq
   ```

   with no signs left. After `:w`, `btw check` printed nothing and `btw run`
   printed `15` and exited 0.

## 2. relatedInformation

- **E417** already carried one related pair from `bigo.py`: the `doomscroll`
  keyword of the innermost loop on the deepest path, with the message
  `nested doomscroll #2 starts here` (the number is the inferred degree).
  The server already mapped `related` to relatedInformation, so nothing
  changed for E417 beyond tests.
- **E409** now points at the first declaration, from the checker. The spec
  doesn't give the text, so:
  - `` `x` was first installed here `` when the earlier name is a variable,
    constant or parameter, and `` `f` was first deployed here `` when it is a
    microservice. The verb follows the first declaration, not the E409
    message: a global named like an earlier microservice gets "already
    installed" (the catalog's message) with "first deployed here".
  - The location is the earlier symbol's `decl_span` (its name). For a local
    shadowing a constant that is the global constant's name; for a repeated
    parameter, the first parameter.
  - The second `serve` points at the first `serve` keyword with
    `port 3000 was first taken here`.
- Related locations are in the same document and use the negotiated
  position encoding like everything else.

### Verified in Neovim

Neovim 0.11's `vim.diagnostic.open_float()` doesn't render
relatedInformation (it shows only the message and code), so it was checked
through the diagnostic's `user_data.lsp.relatedInformation`, which is what a
plugin or a newer Neovim reads.

1. **E417.** The E417 golden, copied to the scratchpad.
   `:lua print(vim.inspect(vim.diagnostic.get(0)[1].user_data.lsp.relatedInformation))`
   prints one location, the file's URI, line 5 characters 8 to 18 (0-based),
   message `nested doomscroll #2 starts here`. Jumping to it with
   `vim.lsp.util.show_document(r.location, "utf-8", {focus = true})` puts
   the cursor at 6,9 on `        doomscroll j < n {`, the inner loop.
2. **E409.** The E409 golden, copied. Printing code, line, related line and
   column (1-based) and message for each diagnostic:

   ```
   E409 5 4 17 `x` was first installed here
   E409 6 2 16 `LIMIT` was first installed here
   ```

   Line 4 column 17 is the first `x`; line 2 column 16 is the constant
   `LIMIT`.

## 3. Semantic tokens

- **Legend**, in this order (the order is the token type index):
  `keyword, variable, function, parameter, number, string, comment,
  operator`, and one modifier, `readonly`. Only `full` is offered: no delta
  and no range requests, since every change rechecks the whole file anyway.
- **What each token gets.** The spec gives only the legend, so:

  | Source                                                     | Type        |
  | ---------------------------------------------------------- | ----------- |
  | every keyword token, `LGTM`, `404`, `localhost:3000`, `:wq` | keyword     |
  | `console.log`                                              | function (like `support.function` in the TextMate grammar and `Function` in `syntax/btw.vim`) |
  | a microservice name, at its declaration and at calls       | function    |
  | a parameter                                                | parameter   |
  | a local or global variable                                 | variable    |
  | a constant (`npm install -g`)                              | variable + readonly |
  | a name the checker couldn't resolve (E404)                 | variable    |
  | `O` and `log` inside a Big O annotation                    | function    |
  | any other name inside a Big O annotation (its size variable) | parameter |
  | other numbers                                              | number      |
  | strings (quotes included)                                  | string      |
  | comments, every kind                                       | comment     |
  | operators, `=` and `\|` included                           | operator    |

  Punctuation, newlines and ERROR tokens get nothing.
- **Names** come from the checked AST, like hover: every Ident and Var the
  checker gave a symbol, matched to the IDENT token by span. So a name keeps
  its kind even when the file has errors elsewhere.
- **Encoding.** Positions and lengths are converted to the negotiated
  position encoding, like diagnostics (Neovim negotiates UTF-8). A token
  that spans lines would be left out, but nothing in btw does.

### Verified in Neovim

Started without `editors/nvim` on the runtimepath, so `syntax/btw.vim`
can't load: only `luafile editors/nvim/btw.lua` (filetype detection and the
LSP config). `:lua print(vim.bo.filetype, vim.b.current_syntax,
#vim.api.nvim_get_runtime_file("syntax/btw.vim", true))` prints `btw nil 0`.

The file was the program from `test_semantic_tokens`. A Lua script walked
every character with `vim.lsp.semantic_tokens.get_at_pos` and wrote each
token Neovim applied, with the group `@lsp.type.TYPE` links to. Excerpt:

```
2:1 npm install -g     keyword              -> @keyword
2:16 LIMIT              variable   readonly  -> @variable
3:14 total              function             -> @function
3:20 n                  parameter            -> @variable.parameter
3:23 O                  function             -> @function
4:21 // TODO faster     comment              -> @comment
9:15 "sum"              string               -> @string
10:15 total              function             -> @function
11:23 404                keyword              -> @keyword
11:41 nope               variable             -> @variable
13:1 :wq                keyword              -> @keyword
```

All 42 tokens matched the test's expectation. On screen with
`termguicolors` (the default colorscheme), keywords are bold, `total`, `O`
and `console.log` cyan, `"sum"` green and the TODO comment grey; without
`termguicolors` in tmux's 16 colors the comment stays uncolored because the
default scheme's `Comment` only sets a GUI color, which is a colorscheme
matter, not the server's. `vim.inspect_pos(0, 3, 22)` names the comment's
group `@lsp.type.comment.btw`.

## 4. Inlay hints

- **Where.** One hint per microservice without an annotation, at the end of
  the `)` that closes its parameter list, found with `bigo.params_close` (the
  same scan W102's Add SLA fix uses, so it handles a parameter list split
  over lines). A microservice whose `)` is missing gets no hint, as W102 gets
  no fix. Annotated microservices get nothing, even unverifiable ones.
- **Label.** The inferred complexity in W102's spelling: `O(1)`, `O(n)`,
  `O(n²)`, always with `n` like W102's message. A recursive microservice
  shows `O(?)`: it has no SLA either, and the hint is the honest answer.
- **Details.** Kind Type, `paddingLeft` so it reads `pairs(n) O(n²) {`, and a
  tooltip, "Inferred by the Big O checker. Write it down as an SLA." Every
  hint but `O(?)` carries a textEdit that inserts the SLA in source form
  (` O(n^2)`, since the lexer rejects `²`), exactly what Add SLA inserts, so
  an editor that accepts hints writes a valid annotation. `O(?)` has no edit
  because it isn't valid syntax.
- **Range.** Only hints whose position is inside the requested range
  (inclusive) are returned.
- `editors/nvim/btw.lua` doesn't turn inlay hints on (Neovim leaves them off
  by default) and belongs to the editors card, so it wasn't changed; enable
  them with `:lua vim.lsp.inlay_hint.enable(true)`.

### Verified in Neovim

The program from `test_inlay_hints`: `pairs(n)` with two nested loops,
`twice(a, b) O(1)`, a recursive `fact(n)` and `wait( n ,` / `  m )` with one
loop and its parameter list over two lines. After
`:lua vim.lsp.inlay_hint.enable(true)` the screen shows the hints as virtual
text (the buffer line still reads `microservice pairs(n) {`):

```
W microservice pairs(n) O(n²) {     ■ microservice `pairs` has no SLA. Inferred: O(n²).
  microservice twice(a, b) O(1) {
W microservice fact(n) O(?) {     ■ Complexity: O(?). The halting problem is a skill issue.
W microservice wait( n ,     ■ microservice `wait` has no SLA. Inferred: O(n).
    m ) O(n) {
```

(`twice`'s `O(1)` is its real annotation.) Changing `fact`'s body to
`ship it n` turned its hint into `O(1)` right away;
`vim.lsp.inlay_hint.get` listed `{1, 21, "O(n²)"}, {12, 20, "O(1)"},
{16, 5, "O(n)"}`. In a fresh session, a Lua script applied every hint's
textEdits with `vim.lsp.util.apply_text_edits` (3 hints, edits on all but
`O(?)`): the buffer got `pairs(n) O(n^2) {` and `m ) O(n) {`, both W102s
disappeared, one hint (`O(?)`) and one diagnostic (W508) were left, and
after `:w` `btw check` reported only the W508.

The Neovim log had nothing from the server; no `lsp.log` was written at
all, so the server never wrote to stderr.
