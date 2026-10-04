# Changelog

All notable changes to btw are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - unreleased

The first release.

### Added

- `btw check`: lexer, parser, semantic checker (names, scopes, types, `sudo`,
  comments), Big O checker and `works on my machine` suppression, with pretty
  and short diagnostic output.
- `btw run`: tree-walking interpreter with 64-bit wrapping arithmetic,
  microservices, pipes, roasts and git-style variable history.
- `btw build` and `btw asm`: x86-64 native backend (GNU as, Intel syntax)
  linked by gcc with the bundled C runtime.
- `btw lsp` / `btw-lsp`: language server with diagnostics, hovers, code
  actions, semantic tokens and inlay hints.
- Editor support for VS Code and Neovim in `editors/`.
- Debug dumps: `btw tokens` and `btw parse`.
- Release assets: standalone `btw` and `btw-lsp` ELF executables for Linux
  x86-64 that need no Python.

[Unreleased]: https://github.com/khyeo1011/btw/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/khyeo1011/btw/releases/tag/v0.1.0
