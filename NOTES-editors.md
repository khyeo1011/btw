# NOTES-editors

The editor integration is specified in `docs/IMPL_SPEC.md` section 12. This
file records what the editors card decided where that spec is silent, how it
was verified, and open questions.

## Files

```
editors/vscode/package.json                    manifest; btw.serverPath (default btw-lsp)
editors/vscode/package-lock.json               pins vscode-languageclient 9.0.1
editors/vscode/extension.js                    LanguageClient over stdio, output channel "btw"
editors/vscode/language-configuration.json     // comments, brackets, auto-closing pairs
editors/vscode/syntaxes/btw.tmLanguage.json    TextMate grammar, scopes from 12.2
editors/vscode/.vscode/launch.json             makes F5 open an Extension Development Host
editors/vscode/test/syntax.test.btw            grammar assertions (see Verification)
editors/nvim/btw.lua                           the 12.3 config, verbatim from the parent page
editors/nvim/syntax/btw.vim                    keyword highlighting for Neovim
editors/nvim/README.md                         how to load both
```

## Editor decisions

- **launch.json.** Section 12.1 doesn't list it, but without it F5 asks which
  debugger to use instead of opening an Extension Development Host.
- **node_modules.** The root `.gitignore` is a Python template, so
  `editors/vscode/.gitignore` ignores `node_modules/`. `package-lock.json` is
  committed so every machine gets 9.0.1.
- **serverPath** is read once, in `activate`. After changing it, run
  "Developer: Reload Window".
- **Grammar mirrors the lexer, not just `\b`.** Keywords need an identifier
  boundary at the end (Language Spec 2.3). At the start, the lexer has already
  consumed any identifier greedily, so:
  - `x:wq` colors `:wq` (it lexes as IDENT then WQ), so `:wq` has no leading
    boundary;
  - `404` is matched as `\b404(?![0-9])`: `4040` and `1404` stay numbers, and
    `404x` colors `404`, because an INT stops at the first non-digit.
- **Rule order.** Comments and strings come first, so keywords inside them
  aren't colored. `microservice` is matched by the header rule (which also
  scopes the name and the Big O annotation) before the keyword rules, so it
  isn't listed again under `#keywords`.
- **Big O** is scoped only right after a microservice's parameter list. The
  annotation body is `O(` up to the first `)`, so `O(n²)` and `O(log n)` are
  covered; an annotation with nested parentheses would be cut short.
- **Vim highlight groups.** The 12.2 categories map to the groups section
  12.3 names:

| Category (12.2 scope)                            | Vim group      | Linked to   |
| ------------------------------------------------ | -------------- | ----------- |
| directive: arch line, `serve`, `localhost:`, `:wq` | btwDirective   | Keyword     |
| `vibe check`, `skill issue`                      | btwConditional | Conditional |
| `doomscroll`, `touch grass`                      | btwRepeat      | Repeat      |
| `ship it`                                        | btwReturn      | Statement   |
| `npm install`, `npm install -g`, `microservice`  | btwStorage     | Type        |
| `git push --force`, `git revert`, `git log`, `sudo` | btwOther    | Statement   |
| `console.log`, microservice name                 | btwConsoleLog, btwFuncName | Function |
| `LGTM`, `404`                                    | btwBoolean     | Boolean     |
| other numbers                                    | btwNumber      | Number      |
| Big O annotation                                 | btwBigO        | Type        |
| strings, escapes                                 | btwString, btwEscape | String, SpecialChar |
| comments                                         | btwComment     | Comment     |

  Vim resolves ties the other way from TextMate: among matches starting at
  the same column, the last one defined wins. So `btw.vim` defines
  `npm install` before `npm install -g`, and numbers before `404`.

## Verification

No VS Code is installed on the machine this was built on, so **F5 itself was
not run**. Each piece it depends on was checked separately:

- **Grammar.** `test/syntax.test.btw` holds 32 lines with hand-written
  positive and negative scope assertions (tabs between words, `doomscrolling`,
  `shipit`, `vibe_check`, `4040`, `npm install -gx`, keywords inside strings
  and comments, the microservice header). Run it with
  `npx vscode-tmgrammar-test 'test/*.test.btw'` from `editors/vscode`. The
  tool picks up the grammar from `package.json` there. It isn't a dependency,
  because of the no-new-dependencies rule. Excluded scopes match exactly, so a
  negative assertion has to list full scope names. All pass, and a
  deliberately sloppy grammar fails them.
- **Golden corpus.** All 81 `tests/golden/*.btw` were tokenized with
  vscode-textmate and vscode-oniguruma, the engine VS Code uses. Every keyword
  kind that appears (19) gets its 12.2 scope, and no keyword-like word outside
  a string or comment is left plain, except the one below.
- **extension.js** was loaded with stubbed `vscode` and
  `vscode-languageclient` modules: it reads `btw.serverPath` (default
  `btw-lsp`), uses stdio, selects `file` documents of language `btw`, creates
  an output channel named `btw`, starts on activate and stops on deactivate.
  The real `vscode-languageclient/node` resolves after `npm install`.
- **Neovim 0.12, headless.** A `.btw` file gets filetype `btw` and
  `syntax/btw.vim`. The same fixture, mapped to Vim groups, passes 505
  per-column checks, and the golden sweep gives the same result as VS Code.
  The client spawns `btw-lsp`. Since `btw.lsp` doesn't exist yet, it exits
  with code 1 and the `ModuleNotFoundError` lands in the LSP log, which is the
  expected error.

To finish the VS Code check by hand: run `npm install` in `editors/vscode`,
open that folder in VS Code (launched with `code .` from a shell where
`uv run which btw-lsp` works, or set `btw.serverPath` to `.venv/bin/btw-lsp`),
press F5, and open any `tests/golden/*.btw` in the new window. Keywords should
be colored, and the "btw" output channel should show the server failing to
start.

## Spec questions

- **`git push` without `--force`** (GIT_PUSH_NO_FORCE, `p1_e400_git_push_no_force`)
  has no row in 12.2, so it is left uncolored. `invalid.illegal.btw` would
  flag it before the server does, if that's wanted.
- **Second arch line** (`p2_w208_repeated_arch`) is colored as a directive
  like the first. That seems right, since W208 is a warning, not a lexing
  difference.
