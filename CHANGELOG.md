# Changelog

All notable changes to btw are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - unreleased

The first release of btw, a joke programming language built from dev memes,
with a real compiler: a type checker, a Big O checker, an interpreter, an
x86-64 native backend and a language server that roasts you in your editor.

```
i use arch btw
serve localhost:3000 {
    console.log "hello, world"
}
:wq
```

### Install

Download the wheel below and install it with
`uv tool install ./btw-0.1.0-py3-none-any.whl` (or `pipx install`). It installs
the `btw` and `btw-lsp` commands with the C runtime included. `btw build` also
needs gcc on Linux x86-64. The sdist carries the specs and the full test suite.

### Added

#### Toolchain

- `btw check`: lexer, parser, semantic checker (names, scopes, types, `sudo`,
  comments) and Big O checker, with pretty and short (`--format short`)
  diagnostic output.
- `btw run`: tree-walking interpreter with signed 64-bit wrapping arithmetic.
- `btw build` and `btw asm`: x86-64 native backend (GNU as, Intel syntax)
  linked by gcc with the bundled C runtime. `--keep-asm` keeps the assembly and
  `btw asm --annotate` interleaves the source lines.
- `btw lsp` / `btw-lsp`: language server with diagnostics on every edit,
  hovers, quick fixes, semantic tokens and inlay hints.
- Editor support for VS Code and Neovim in `editors/`.
- Debug dumps: `btw tokens` and `btw parse`.

#### Language

- Programs open with `i use arch btw`, run inside
  `serve localhost:3000 { }` and end with `:wq`.
- Variables (`npm install`), constants (`npm install -g`), assignment
  (`git push --force`), print (`console.log`), if/else (`vibe check` /
  `skill issue`), loops (`doomscroll` / `touch grass`), functions
  (`microservice` / `ship it`) and booleans (`LGTM` / `404`).
- `// TODO` is the only comment.
- Big O checker: annotate a microservice with `O(1)`, `O(n)`, `O(n^2)` and so
  on, and claiming less than the code does is E417 ("You said O(n), but this
  is O(n²). Skill issue."). Recursion is unknown and annotations it can't
  verify, such as `O(log n)`, get W203.
- `sudo` constants: changing a constant without `sudo` is E403 ("Permission
  denied. Are you root?"), and `sudo` on a plain variable is W100.
- Git history: every variable keeps its last 16 values. `git revert x` undoes
  the last change and `git log x` prints the history.
- Pipes: `3 | double | add(10) | console.log` means
  `console.log add(double(3), 10)`.
- `// works on my machine` suppresses soft errors and warnings on the next
  statement (W200, or W304 when there's nothing it can suppress).
- Technical debt limit: the 6th TODO in a file is E429, and it can't be
  suppressed.

#### Diagnostics and roasts

- Every diagnostic code is an HTTP status: E404 for unknown names, E408 for a
  missing `:wq`, E418 for type errors, E426 for a missing `i use arch btw`,
  W509 for an infinite `doomscroll` and more (Language Spec 11).
- Roasts for `===`, `;`, `++`, leading zeros, chained comparisons,
  `serve localhost:8080` and `git push` without `--force`.
- Roasts for foreign keywords such as `if`, `else`, `while`, `for`, `return`,
  `let`, `const`, `function`, `print`, `true` and `null`, most with a quick fix
  in the editor.
- Runtime errors: division by zero ("Have you tried turning it off and on
  again?") and more than 1,000 nested calls ("Stack overflow. Please search
  stackoverflow.com.").

[Unreleased]: https://github.com/khyeo1011/btw/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/khyeo1011/btw/releases/tag/v0.1.0
