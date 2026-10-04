# Changelog

All notable changes to btw are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-04

### Added

- `curl` reads one number from stdin. At the end of input it's
  `curl: (52) Empty reply from server.` with exit code 52, and on anything
  that isn't a 64-bit integer `curl: (8) Weird server reply.` with exit
  code 8. In a global initializer it's E405: postinstall scripts can't make
  network calls. `curl` is now a reserved word.
- The playground has a stdin box and a `curl` example.
- `git blame x` prints x's history newest first with the line of each
  commit, as `* 3 (line 7)`. A revert records its own line. Same rules as
  `git log`: E405 on microservice locals, and no `sudo` needed for constants.
- The playground has a `git blame` example.
- The playground has a Two Sum tab: write `twoSum(n, target)` and run it
  against six fixed tests. btw has no arrays, so each test's array is a
  generated microservice, `nums(i)`.
- Golden tests can have a `.in` file for stdin.

### Fixed

- The playground could run a new page on the previous deploy's wheel for up
  to 10 minutes after a deploy, because GitHub Pages lets browsers cache files
  that long and a reload only refetches the page. With the curl release that
  made every `curl` an E404. Every file the page loads now carries a hash of
  the build in its URL.
- Piping btw into `head` or `less` no longer reports E500 with a traceback
  when the reader exits early. btw exits quietly with code 141, like a native
  binary killed by SIGPIPE.

## [0.2.0] - 2026-10-03

### Added

- `btw loadtest FILE NAME`: runs a microservice for n = 8 to 1024 in the
  interpreter, fits the measured Big O and compares it with the static one
  and the SLA. The PM is notified when the SLA is broken.
- Smarter Big O: loops to a fixed bound are O(1), halving or doubling loops
  are O(log n), and log and exponential SLAs are checked.
- W226 for unused variables.
- LSP completion and go to definition.
- The Add --force, Delete it and Remove sudo quick fixes.
- Variable hovers show the commit count.
- The pretty-mode summary line after `btw check`, `run` and `build`:
  `build failed: 2 errors, 1 warning. Skill issue.`
- The browser playground at [btw.sebastianyeo.dev](https://btw.sebastianyeo.dev),
  running btw on Pyodide.
- `demo/`: `fizzbuzz.btw`, `roast.btw` (every roast that fits in one file),
  `bigo.btw` and `bench.btw`.

### Changed

- Release assets are standalone `btw` and `btw-lsp` ELF executables for Linux
  x86-64 that need no Python, instead of the wheel and sdist.

### Fixed

- The minimum number divided by -1 wraps (`/` gives the minimum, `%` gives 0)
  instead of crashing native builds with SIGFPE.
- A top-level syntax error no longer swallows a `microservice` or `serve` on
  the same line, which cascaded into a spurious E503.

## [0.1.0] - 2026-10-03

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

[Unreleased]: https://github.com/khyeo1011/btw/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/khyeo1011/btw/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/khyeo1011/btw/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/khyeo1011/btw/releases/tag/v0.1.0
