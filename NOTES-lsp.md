# NOTES-lsp

The language server is specified in `docs/IMPL_SPEC.md` section 11 and its
hover text in `docs/SPEC.md` section 12. This file records what the lsp card
decided where those are silent, how it was verified, and open questions.

## Files

```
src/btw/lsp.py        pygls 2 server: diagnostics on didOpen/didChange/didSave, hover; main()
src/btw/hovers.py     hover(source, pos): keyword table, identifiers, Big O, TODO counter
tests/test_lsp.py     starts the server over stdio with a minimal JSON-RPC client
tests/test_hovers.py  hover text, one test per row kind of Language Spec 12
```

## Server decisions

- **Pipeline.** Every didOpen, didChange and didSave runs `driver.check` on
  the workspace text (`ls.workspace.get_text_document(uri).source`), so the
  server reports exactly what `btw check` reports. Never codegen, no
  debouncing.
- **E500.** `lsp.check` turns any exception from the pipeline into the single
  E500 that `driver.internal_error` builds (line 1). Every handler is also
  wrapped by `guarded`: an exception there logs a traceback to stderr and
  publishes one E500 on that document. For hover that means the request
  answers `null` and the document shows E500 until the next edit.
- **Position encoding.** Spans count UTF-16 code units, but pygls picks the
  client's first preference, and Neovim 0.11 offers `utf-8` first. `lsp.py`
  converts every span to the negotiated encoding and every hover position
  back, using the document's text. A column past the end of a line (the end
  of file, say) is kept as is.
- **Sync.** Full document sync: files are small, and every change rechecks
  the whole file anyway.
- **didClose** publishes an empty list so a closed file's diagnostics don't
  linger. The spec doesn't mention it.
- **stdout.** `main` hands the real stdout to pygls and then points
  `sys.stdout` at stderr, so a stray `print` can't corrupt the protocol.
- **Logging** goes to stderr at WARNING. pygls logs every message at INFO,
  and Neovim files all of a server's stderr under `[ERROR]` in its LSP log, so
  INFO made that log useless.
- **relatedInformation** is sent when a diagnostic has `related` (P2: E417's
  "nested doomscroll" pointer, once the Big O card adds it).

## Hover decisions

- **Lookup order.** A comment under the cursor, then a Big O annotation, then
  the token. Keywords use the table verbatim, as Markdown. `serve` and
  `localhost:3000` both show the `serve localhost:3000` row. Numbers,
  strings, operators, BAD comments and `git push` without `--force` have no
  hover.
- **Identifiers** come from the checked AST: the innermost Ident or Var under
  the cursor that the checker gave a symbol. Declarations and uses show the
  same text. A name the checker couldn't resolve (E404) has no hover.
- **Variables** (locals and mutable globals) use the "a variable" row with the
  1-based declaration line. The P2 "3 commits" part isn't done. Booleans say
  `boolean`, and a name declared from an ErrorExpr says `unknown`.
- **TODO counter** is the file's total TODO count, the same number E429 uses,
  so it can read 7/5.
- **Microservice names** show the parameters, the SLA and the inferred
  complexity in the annotation's variable, as in Language Spec 9.1.

## Spec questions

The hover rows below left some cases open. Entries marked **Resolved** were
settled by the project owner, and Language Spec 12 now says the same.

1. **Microservice name without an annotation.** **Resolved:** taunt the user
   for making the compiler analyze the code, and tell them to write an SLA:
   `` `microservice f(n)` · no SLA · I had to read your code to find out it's
   O(n). Write an SLA. `` A recursive one ends in `O(?)` the same way.
2. **Microservice with an unverifiable annotation.** **Resolved:** not
   checked, so no mark: `` · SLA O(log n) · inferred O(n) ``. The inferred
   value is an upper bound, so a binary search over n items is technically
   O(n) as well.
3. **Recursive microservice.** **Resolved:** recursive microservices aren't
   checked, so no mark: `` · SLA O(n) · inferred O(?) ``.
4. **Big O annotation hover.** **Resolved:** a correct SLA ends
   `Verdict: Correct! Are you an arch user as well?` and a wrong one (an
   under-claim or an over-claim) `Verdict: Go take a DSA course again.`
   Neither recursive nor unverifiable SLAs are checked, so they keep
   `Verdict: O(?).` and `Verdict: can't verify O(log n). Inferred: O(1).`

## Verification

`uv run pytest` passes: 880 passed, 39 xfailed (the xfails are the native
step and the WAITING goldens, as before). `tests/test_lsp.py` starts the
server as a subprocess, sends initialize, initialized and didOpen with the
E426 golden, and checks the one published diagnostic (severity 1, code
`E426`, source `btw`, the exact message, line 1). A second test sends
didChange with the arch line added, gets an empty list, and hovers `serve`.
The client fails if anything that isn't a framed JSON-RPC message reaches
stdout.

### Neovim by hand

Neovim 0.11.4 (the official Linux release tarball, outside the repo), run as
a real terminal session inside tmux, with keystrokes sent one at a time and
the screen captured after each step. The golden file was copied first, so
`tests/golden` was never edited.

```
cp tests/golden/p0_e426_missing_arch.btw /tmp/e426.btw
uv run nvim --clean --cmd "set rtp+=editors/nvim" --cmd "luafile editors/nvim/btw.lua" /tmp/e426.btw
```

1. **Open the file.** Line 1 shows E426 as virtual text:

   ```
   E serve localhost:3000 {     ■ Fatal: `i use arch btw` not found. Are you on Windows?
         console.log "hi"
     }
     :wq
   ```

   `:lua print(vim.inspect(vim.tbl_map(function(d) return {d.lnum, d.col, d.code, d.source, d.severity} end, vim.diagnostic.get(0))))`
   prints `{ { 0, 0, "E426", "btw", 1 } }`. `offset_encoding` is `utf-8`.
2. **Type the arch line.** `O`, then `i use arch btw` typed in place.
   Neovim doesn't redraw diagnostics in insert mode by default, so after Esc
   the E426 is gone and `#vim.diagnostic.get(0)` is 0. With
   `:lua vim.diagnostic.config({update_in_insert = true})` and the line
   retyped a word at a time, the screen showed:

   ```
   E i     ■■ Fatal: `i use arch btw` not found. Are you on Windows?
   E i use     ■■ Fatal: `i use arch btw` not found. Are you on Windows?
   E i use arch     ■■ Fatal: `i use arch btw` not found. Are you on Windows?
   E i use arch b     ■■ Fatal: `i use arch btw` not found. Are you on Windows?
   i use arch btw
   ```

   (The second ■ is an E400 for the half-typed line.) E426 disappears the
   moment `btw` is complete.
3. **Hover `doomscroll`.** The E426 golden has no `doomscroll`, so a line
   `doomscroll 404 { }` was typed inside `serve`. `K` on it opens:

   ```
       doomscroll 404 { }
   }   while. Keeps going while the condition holds. Or forever. Mostly forever.
   ```

   (Neovim renders `**while.**` in bold.) `K` on `404` shows "false. Truth
   not found. Also the one number you can't type."

The LSP log (`~/.local/state/<app>/lsp.log`) had no tracebacks, and after
the logging change it stays empty.
