# NOTES-harness

There is no Implementation Spec, so the decisions below define the CLI and the
golden test format. Language behavior still comes from `docs/SPEC.md`.

## CLI

```
btw check  FILE      diagnostics to stdout
btw run    FILE      interpret; diagnostics to stderr, only when errors block the run
btw build  FILE [-o OUT]   native binary (default OUT: FILE without .btw); diagnostics to stderr
btw asm    FILE [-o OUT]   assembly to stdout, or to OUT; diagnostics to stderr
btw tokens FILE      one token per line (`str(token)`); diagnostics to stderr
btw parse  FILE      the AST (`str(program)`); diagnostics to stderr
btw lsp              language server on stdio
```

Every command that takes a FILE also takes `--format short|pretty`, which
defaults to `pretty` when the diagnostics stream is a terminal and to `short`
otherwise. Colors are used only in pretty mode, only on a terminal and only
when `NO_COLOR` is unset (set to anything, even empty, turns them off).

`btw run` stays silent about warnings when the program runs, so a program's
stderr is exactly its runtime output. The source is read as UTF-8 and a
leading byte-order mark is dropped before lexing.

Exit codes:

| Code | Meaning                                                                    |
| ---- | -------------------------------------------------------------------------- |
| 0    | success; for `check`, no errors (warnings are fine)                        |
| 1    | hard or soft errors blocked the command                                    |
| N    | `btw run`: the program's own exit code (`ship it`, 1 or 128 at runtime)    |
| 2    | usage error, unreadable file, component not implemented, internal error    |

## Short diagnostic format

One line per diagnostic, sorted as in Language Spec 11:

```
PATH:LINE:COL: SEVERITY CODE: MESSAGE
```

LINE and COL are 1-based and refer to the start of the span. SEVERITY is
`error` for hard and soft errors and `warning` for warnings. Example:

```
tests/golden/p0_e404_undeclared_var.btw:3:17: error E404: Error 404: variable `x` not found. Did you forget to `npm install` it?
```

## Pretty diagnostic format

One block per diagnostic, blocks separated by a blank line. W is the number of
digits in the 1-based line number:

```
error[E403]: Permission denied. Are you root?
 --> demo.btw:4:5
  |
4 |     git push --force LIMIT = 11
  |     ^^^^^^^^^^^^^^^^^^^^^^
  = help: try `sudo git push --force LIMIT = ...`
```

1. `SEVERITY[CODE]: MESSAGE`, with SEVERITY as in the short format.
2. W spaces, then `--> PATH:LINE:COL`.
3. W spaces, then ` |`.
4. The line number, ` | ` and the source line without its line ending. An
   empty source line (or a line past the end of the file) prints as `N |`.
5. W spaces, ` | `, padding up to the start column, then the carets. The
   padding copies each tab before the column and turns every other character
   into a space, so carets line up in a terminal. A span that ends on the same
   line gets one caret per column it covers; a span that continues onto later
   lines gets carets to the end of the line. Always at least one caret, and a
   column past the end of the line pads with spaces.
6. Only with a help text: W spaces, then ` = help: HELP`.

No line has trailing whitespace. With colors on, `SEVERITY[CODE]` and the
carets are bold red (errors) or bold yellow (warnings), the message is bold,
and `-->`, the line number and the `|` gutter are bold blue. Removing the
escape codes gives exactly the uncolored output.

## Component interfaces

`src/btw/driver.py` expects these. A component that differs should update the
driver in the same change.

| Module            | Function                                      | Returns                           |
| ----------------- | --------------------------------------------- | --------------------------------- |
| `btw.lexer`       | `lex(source)`                                 | `(tokens, comments, diagnostics)` |
| `btw.parser`      | `parse(tokens)`                               | `(program, diagnostics)`          |
| `btw.checker`     | `check(program, comments, source)`            | `(symbols, diagnostics)`          |
| `btw.interpreter` | `run(program, symbols, stdout, stderr)`       | the exit code                     |
| `btw.codegen`     | `generate(program, symbols)`                  | `(assembly_text, diagnostics)`    |
| `btw.lsp`         | `serve()`                                     | nothing; serves stdio until exit  |

`btw build` links the assembly with `src/btw/runtime.c` using `gcc`. Diagnostics
are `btw.diagnostics.Diagnostic` objects; the driver sorts and deduplicates
them. The interpreter writes runtime errors to stderr itself (Language Spec 10).

## Golden test format

Every `tests/golden/NAME.btw` can have these sidecar files:

| File         | Contents                                                                    |
| ------------ | --------------------------------------------------------------------------- |
| `NAME.diag`  | expected `btw check --format short` output with the `PATH:` prefix removed  |
| `NAME.exit`  | expected exit code of `btw run`, as one number and a newline                |
| `NAME.out`   | expected stdout of `btw run`                                                |
| `NAME.err`   | expected stderr of `btw run`                                                |

A missing `.diag`, `.out` or `.err` means "expected empty". `.exit` is the
switch for running: without it the test is check-only. Programs with errors
are check-only (errors block `run`), and so are programs that never terminate.

Runner steps, per program:

1. Run `btw check --format short NAME.btw`. Strip the path prefix and compare
   stdout with `NAME.diag`. The exit code must be 1 if `.diag` has an `error`
   line, else 0.
2. If there is no `NAME.exit`, stop.
3. Run `btw run NAME.btw`. Compare stdout with `.out`, stderr with `.err` and
   the exit code with `.exit`.
4. If `gcc` is available, `btw build` the program, run the binary and make the
   same three comparisons. Skipped while the native backend isn't implemented,
   and for programs the native backend rejects with E501.

Exit code 2 from `btw` in steps 1 and 3 fails the test with btw's stderr, so
until the components exist every golden test fails with "not implemented yet".
`--tier N` keeps tiers 0 to N. `--bless` rewrites the sidecars from actual
output (steps 1 and 3 only); it is for humans, never for agents.

The tier is the number in the file name prefix (`p0_`, `p1_`, `p2_`).

## Golden tests

- `p0_arith_overflow.btw`: the 3 overflow reference rows, negating the minimum, min - 1 wraps to max
- `p0_arithmetic.btw`: precedence, left associativity, unary minus, all 8 division/modulo reference rows
- `p0_booleans.btw`: LGTM/404 printing, comparisons, ==/!= on booleans, !, && and ||, 404 literal is false, 403 + 1 prints 404, 4040 and 1404 are numbers
- `p0_condition_parens.btw`: conditions with and without parentheses, for vibe check and doomscroll
- `p0_e400_recovery.btw`: E400 then an unrelated E404 on the next line: statement-level parser recovery
- `p0_e400_reserved_word_name.btw`: E400 reserved word `sudo` used as a variable name
- `p0_e400_sudo_misuse.btw`: E400 `sudo` in front of `console.log`
- `p0_e400_syntax_error.btw`: generic E400, expected an expression, found end of line
- `p0_e400_top_level_statement.btw`: E400 for `console.log` at top level
- `p0_e400_unexpected_char.btw`: E400 unexpected character `@`
- `p0_e403_constant_no_sudo.btw`: E403 git push --force on a constant without sudo
- `p0_e404_global_init_order.btw`: E404 global initializer using a global declared below it
- `p0_e404_out_of_scope.btw`: E404 local used after its block ends
- `p0_e404_undeclared_var.btw`: E404 unknown variable (the NOTES example)
- `p0_e404_unknown_microservice.btw`: E404 unknown microservice
- `p0_e405_touch_grass_outside_loop.btw`: E405 touch grass outside a doomscroll
- `p0_e408_missing_wq.btw`: E408 missing `:wq` (see spec question 4)
- `p0_e409_already_installed.btw`: E409 local redeclared, and a local shadowing a constant
- `p0_e409_duplicate_param.btw`: E409 repeated parameter name
- `p0_e415_string_variable.btw`: E415 string as a variable value
- `p0_e417_big_o_underclaim.btw`: E417 O(n) annotation on an O(n²) microservice
- `p0_e418_assignment_type.btw`: E418 pushing a boolean into a number and a number into a boolean
- `p0_e418_condition.btw`: E418 number as vibe check and doomscroll condition
- `p0_e422_wrong_arg_count.btw`: E422 too few arguments (plural) and too many (singular "1 argument")
- `p0_e426_missing_arch.btw`: E426 missing arch line, otherwise valid program
- `p0_e503_no_serve.btw`: E503 no serve block, message without backticks
- `p0_else_if_chain.btw`: vibe check / skill issue vibe check / skill issue chain, else on the line after `}`, all branches taken
- `p0_fizzbuzz.btw`: FizzBuzz 1..15 with one-line blocks and skill issue after `}`
- `p0_hello.btw`: hello world
- `p0_hoisting.btw`: serve calls a microservice defined below it
- `p0_microservice_args.btw`: arguments, nested calls, 6 parameters, reassigning a parameter, falling off the end returns 0
- `p0_runtime_division_by_zero.btw`: runtime division by zero after output: flush stdout, stderr message, exit 1
- `p0_runtime_modulo_by_zero.btw`: runtime modulo by zero, exit 1
- `p0_runtime_stack_overflow.btw`: depth 1,000 succeeds, 1,001 overflows, exit 1; W508
- `p0_ship_it_exit_code.btw`: ship it from serve inside a vibe check sets exit code 21
- `p0_short_circuit.btw`: && and || skip the right side (which would divide by zero)
- `p0_sibling_scopes.btw`: sibling blocks and a later outer declaration reuse the same name
- `p0_string_escapes.btw`: `\t`, `\"`, `\\` and `\n` escapes (the .out contains a real tab)
- `p0_sudo_constant.btw`: sudo git push --force on a constant
- `p0_touch_grass.btw`: touch grass from a nested vibe check, and from an inner doomscroll only
- `p0_variables_constants.btw`: npm install -g, top-level npm install, initializers using earlier globals, globals in serve
- `p0_w508_recursion.btw`: recursive factorial runs; W508 with an O(n) annotation
- `p1_e400_git_push_no_force.btw`: E400 `git push` without --force
- `p1_e400_unterminated_string.btw`: E400 unterminated string
- `p1_e405_global_flag_in_block.btw`: E405 npm install -g inside serve
- `p1_e405_global_init_call.btw`: E405 global initializer calls a microservice
- `p1_e405_microservice_as_value.btw`: E405 microservice used as a value
- `p1_e405_variable_called.btw`: E405 variable called like a microservice
- `p1_e406_bad_comment.btw`: E406 for a plain comment and for a lowercase `// todo` after code
- `p1_e409_duplicate_microservice.btw`: E409 microservice deployed twice
- `p1_e409_second_serve.btw`: E409 second serve block
- `p1_e410_code_after_wq.btw`: E410 code after `:wq`
- `p1_e413_number_too_large.btw`: E413 literal 9223372036854775808
- `p1_e413_too_many_params.btw`: E413 microservice with 7 parameters
- `p1_e418_boolean_argument.btw`: E418 boolean argument
- `p1_e418_operators.btw`: E418, all four operator messages
- `p1_e418_return_boolean.btw`: E418 microservice ships a boolean
- `p1_e429_technical_debt.btw`: E429 on the 6th and 7th TODO, count 7/5
- `p1_todo_comments.btw`: 5 TODO comments (incl. `//TODO` and trailing ones) are fine
- `p1_w102_no_big_o.btw`: W102 missing annotation, program still runs
- `p1_w203_unverifiable.btw`: W203 O(log n)
- `p1_w417_overclaim.btw`: W417 O(n) annotation on an O(1) microservice
- `p1_w509_infinite_doomscroll.btw`: W509 doomscroll LGTM with no way out (check-only)
- `p2_e403_revert_constant.btw`: E403 git revert on a constant without sudo
- `p2_e405_history_on_local.btw`: E405 git revert on a microservice local and git log on a parameter
- `p2_e405_pipe_console_log_value.btw`: E405 pipe into console.log used as a value
- `p2_git_history.btw`: the git log example from 9.3
- `p2_git_log_fresh_history.btw`: a declaration in a loop starts a fresh history; booleans in git log
- `p2_git_log_limit.btw`: history keeps only the 16 newest commits
- `p2_git_revert_constant.btw`: sudo git push --force and sudo git revert on a constant, git log on it
- `p2_pipes.btw`: pipe with an extra-argument stage ending in console.log, pipe precedence, string piped to console.log
- `p2_runtime_revert_one_commit.btw`: git revert with one commit: fatal message with the real name, exit 128
- `p2_w100_unnecessary_sudo.btw`: W100 sudo on a variable for push and revert, still runs
- `p2_w200_two_problems.btw`: W200 "2 problems" on a microservice (W102 + W204 suppressed), runs
- `p2_w200_works_on_my_machine.btw`: W200 suppressing E403; the assignment really happens
- `p2_w204_expression_statement.btw`: W204 expression statement, still runs
- `p2_w208_repeated_arch.btw`: W208 second arch line, still runs
- `p2_w304_hard_error_only.btw`: W304 "doesn't work on any machine" before an E404
- `p2_w304_nothing_to_suppress.btw`: W304 "nothing to suppress"
- `p2_w410_unreachable.btw`: W410 statement after ship it in serve; exit 3

## Spec questions

Ambiguities found while writing the tests. Golden tests avoid depending on an
open question where they can. Where they can't (questions 4, 5, 7, 8, 9, 11
and 14), the entry names the test and the assumption it makes.

1. **W508 "replaces the three rows above" (9.1).** Does it replace E417, W417
   and W102, or the k = d, E417 and W417 rows? Tests: recursive microservices
   (`p0_w508_recursion`, `p0_runtime_stack_overflow`) carry an `O(n)`
   annotation, so both readings give W508 alone.
2. **Call cost in P0 vs P1 (9.1).** A call costs 0 in P0 and degFn in P1.
   Tests: no non-recursive microservice calls another one.
3. **E400 "found WHAT" for identifiers, numbers and strings (11).** The format
   isn't given. Tests: only symbols, keywords and end of line are "found".
4. **E408 "the last token" (4, 11).** Does the final NEWLINE or EOF count?
   Every golden file ends with a newline, so this can't be avoided.
   `p0_e408_missing_wq` assumes the last real token (the `}` at 4:1).
5. **E410 and E408 together (4).** With code after `:wq`, `:wq` isn't the last
   token. `p1_e410_code_after_wq` assumes only E410, since the E408 trigger is
   "missing `:wq`".
6. **Other checks with E426 or E503 (4).** Do the remaining checks run?
   Tests: `p0_e426_missing_arch` and `p0_e503_no_serve` contain nothing else
   to report.
7. **Span of the `sudo` misuse E400 (9.2).** `sudo` itself, or the token after
   it? `p0_e400_sudo_misuse` assumes the token after `sudo` (3:10), following
   the catalog's E400 span "the unexpected token". Can't be avoided.
8. **Unexpected character and the parser (2.6).** Does the lexer drop the
   character, or emit a token the parser also reports? `p0_e400_unexpected_char`
   puts `@` at the end of a complete statement and expects exactly one E400.
9. **Top-level statement message (4).** Section 4 gives it without the
   "Syntax error: " prefix. `p0_e400_top_level_statement` assumes the generic
   E400 form: "Syntax error: expected `microservice`, `serve` or
   `npm install`, found `console.log`."
10. **E418 comparison message with a boolean on the left (11).** "can't compare
    a number with a boolean" might flip. Tests: the number is on the left.
11. **E409 for a repeated parameter (8).** The catalog has no row for it.
    `p0_e409_duplicate_param` assumes the "already installed" message.
12. **`ship it` of a boolean in `serve` (6).** E418, but which message? Not
    tested.
13. **`&&`, `||` with numbers and `<` with booleans (5, 11).** No message given.
    Not tested.
14. **History on variables in nested blocks of `serve` (9.3).**
    `p2_git_log_fresh_history` assumes a variable declared in a doomscroll
    inside `serve` counts as "declared in `serve`" (9.3 itself describes
    declarations re-running in loops).
15. **Section 13 roasts and other E400 texts (2.5, 13).** Leading zeros, bad
    escapes and the roast messages are P2 and some have no exact text. Not
    tested.
16. **E500, E501, E502 (11).** Internal error, native backend gaps and gcc
    failures can't be produced by `btw check` on a source file. Not golden
    testable.
