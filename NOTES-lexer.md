# Lexer notes

Files: `src/btw/tokens.py`, `src/btw/lexer.py`, `tests/test_lexer.py`.
Specs: Language Spec 1 and 2, Implementation Spec 4.3 and 5.

## Interface

- `lex(source) -> (tokens, comments, diagnostics)`. Tokens always end in EOF.
  It never raises: a bug inside the lexer becomes E500 plus an EOF token where
  lexing stopped.
- `format_tokens(tokens) -> str`: one token per line, `KIND "text" LINE:COL`,
  1-based. `btw tokens` prints exactly this.
- `match_keyword(src, i)` and `scan_string(src, i)` work on string indices
  only; `_Lexer.pos_at` is the one place that converts to UTF-16 columns.

## Token details the parser relies on

- `Token.value`: the int for INT (also for too-large and leading-zero
  literals, which carry a diagnostic), the port for LOCALHOST, the unescaped
  text for STRING, and None for everything else, including NOT_FOUND.
- `GIT_PUSH_NO_FORCE` comes with its E400 from the lexer. The parser should
  treat it like `GIT_PUSH_FORCE` and not report it again.
- An ERROR token comes with its E400 ("Unexpected character"). The parser
  reports at most one E400 per statement; the driver drops exact duplicates
  and keeps the lexer's (NOTES-harness, question 8).
- NEWLINE text is `\n` or `\r\n`, and its span sits at the end of its line.
  EOF has a zero-width span at the end of the file.
- `O`, `localhost` (without `:` and digits) and the first words of multi-word
  keywords (`i`, `npm`, `git`, ...) are plain IDENT tokens.
- Comments: `text` runs from `//` to the end of the line. Their kind is
  TODO, WOMM or BAD; E406 and E429 are the checker's job (Implementation
  Spec 7), so the lexer reports nothing for comments.

## Decisions where the spec is silent

1. **Bad escape message (2.5).** The spec says E400 but gives no text. Used
   ``Syntax error: unknown escape `\q`.``, spanning the backslash and the
   next character. The string token is still emitted, with the bad escape
   left out of `value`. No golden test covers it (NOTES-harness, question 15).
2. **Leading zeros (2.5, 13).** Used the section 13 roast as the E400
   message: "Leading zeros? This isn't octal, James Bond." `0404` is an INT
   with that error, not NOT_FOUND.
3. **A backslash right before the end of the line** inside a string is kept
   literally; the string is just unterminated (one E400, not two).
4. **A lone `\r`** counts as a newline, as in LSP, so positions agree with
   editors. Only `\r\n` is mentioned in the spec.
5. **Unclosed `(`** suppresses every later NEWLINE, as section 2.1 says. That
   can make parser recovery worse after an unbalanced paren (everything after
   it is one "line"). Resetting the depth at `{` or `}` would fix it but isn't
   in the spec. Question for the parser card.
6. **Non-ASCII outside strings and comments** is an ERROR token per code
   point; an emoji's ERROR token is 2 columns wide.
7. **`:wq` and `localhost:N`** have no word-boundary check after them:
   `:wqx` lexes as WQ then IDENT. `git push --forced` lexes as
   GIT_PUSH_NO_FORCE, `-`, `-`, `forced`, since the boundary check fails for
   `--force`.
8. **The byte-order mark** is skipped and takes no column.

## Tests

- `uv run pytest tests/test_lexer.py`: unit tests for every case on the card,
  plus, for each `tests/golden/*.btw`, ERROR tokens only where the `.diag`
  expects E400, and every lexer diagnostic present verbatim in the `.diag`.
  The corpus has four lexer diagnostics (unexpected `@`, `git push`,
  unterminated string, number too large), all matching.
- `tests/test_golden.py` still fails everywhere with "parser is not
  implemented yet".
