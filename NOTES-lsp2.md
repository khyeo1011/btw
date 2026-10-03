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
