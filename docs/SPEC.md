<aside>
📌

**Source of truth for the language.** Where this page and the parent page disagree, this page wins. Planning only: rules, grammar and exact messages, no implementation code. Runnable examples with expected output live in the Test Corpus page.

**Tiers:** P0 = must have for the demo · P1 = should have · P2 = stretch. Untagged means P0.

**Implementation Spec:** this file is the Language Spec. "Implementation Spec section N" refers to `docs/IMPL_SPEC.md`.

</aside>

---

# 0. Decisions log

These are the calls the parent page left open. Flip any of them before Oct 3, not during the event.

| No. | Decision              | Choice                                                                                                                                        | Why                                                                                                                                                      |
| --- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Types                 | Three static types: number (signed 64-bit), boolean, string. Strings exist only as literals passed straight to `console.log`.                 | Codegen has to know whether to print `42` or `LGTM`. No heap, no string runtime.                                                                         |
| 2   | Function signatures   | Every parameter is a number and every `microservice` returns a number. Falling off the end returns 0.                                         | No type inference across calls. Booleans cross function boundaries as 1 and 0.                                                                           |
| 3   | Integer math          | Wrapping two's complement. `/` truncates toward zero. `%` takes the sign of the left operand.                                                 | Matches x86 `idiv`, so the interpreter and the native binary agree. Python's `//` and `%` don't match: emulate them.                                     |
| 4   | The 404 rule          | The literal `404` is always false. The number 404 can't be written directly (`403 + 1` works).                                                | It's the joke. Documented in its hover.                                                                                                                  |
| 5   | Printing              | Numbers print in decimal, booleans as `LGTM` or `404`, strings verbatim. Each `console.log` adds a newline.                                   | Funnier output. Relies on decision 1.                                                                                                                    |
| 6   | Statement ends        | A newline ends a statement, and so does a closing `}`. No semicolons.                                                                         | FizzBuzz uses one-line blocks.                                                                                                                           |
| 7   | Condition parentheses | Optional. `vibe check (x == 1) { }` and `vibe check x == 1 { }` both parse; the parens are ordinary grouping.                                 | Fewer syntax errors while typing.                                                                                                                        |
| 8   | Else placement        | `skill issue` may start on the line after the closing `}`.                                                                                    | The FizzBuzz example does exactly this.                                                                                                                  |
| 9   | sudo                  | `sudo` is its own token and can prefix `git push --force` or `git revert`. Anything that changes a constant needs it, including `git revert`. | One rule, easy to explain. **This changes the parent page's all-features example**, which reverts `LIMIT` without sudo.                                  |
| 10  | Globals               | `npm install -g` is allowed only at top level. A top-level `npm install` (a mutable global) is also allowed.                                  | It's a global install.                                                                                                                                   |
| 11  | Global initializers   | Run in source order before the `serve` body. They can use literals, operators and earlier globals, but can't call microservices.              | No initialization-order bugs, plus a free npm postinstall joke.                                                                                          |
| 12  | Scope                 | Block scope. No shadowing of any visible name: globals, microservices, parameters, outer locals.                                              | One "already installed" error, and every declaration gets its own stack slot.                                                                            |
| 13  | Hoisting              | Microservices and globals are visible everywhere, so `serve` can call a microservice defined below it.                                        | Top-level order doesn't matter.                                                                                                                          |
| 14  | Parameters            | 0 to 6 per microservice.                                                                                                                      | System V passes 6 arguments in registers. Seven is a monolith.                                                                                           |
| 15  | Recursion             | Allowed. The Big O checker reports `O(?)`. Both backends stop at a call depth of 1,000 with the same runtime error.                           | Identical behavior interpreted and native.                                                                                                               |
| 16  | Comments              | Only `// TODO ...` and the `// works on my machine` directive. Any other `//` comment is an error.                                            | "Comments: TODO only", made real.                                                                                                                        |
| 17  | Suppression           | `// works on my machine` silences soft errors (sudo, Big O) and warnings in the next statement or item. Hard errors can't be silenced.        | Suppressed code still means something well defined.                                                                                                      |
| 18  | History               | Every variable keeps its last 16 values. `git revert x` restores the previous value and records that as a new commit, like real git.          | Reverting twice toggles, same as `git revert HEAD` twice.                                                                                                |
| 19  | Error codes           | HTTP status codes: E404 not found, E403 needs sudo, E418 type errors, and so on.                                                              | A free extra joke, and stable IDs for golden tests.                                                                                                      |
| 20  | Determinism           | No randomness anywhere: messages, hovers and output are fixed.                                                                                | Golden tests.                                                                                                                                            |
| 21  | Native target         | Linux x86-64, System V ABI, ELF. GNU assembler in Intel syntax, linked by gcc together with a small C runtime file.                           | Intel syntax reads better on a projector and matches Compiler Explorer's default. The C runtime keeps printing and history out of hand-written assembly. |

---

# 1. Program shape

```
i use arch btw                        ← first token of the file
                                      ← then any number of top-level items, in any order:
npm install -g NAME = expr            ←   constants
npm install name = expr               ←   mutable globals
microservice name(a, b) O(n) { }      ←   functions
serve localhost:3000 { }              ←   exactly one main block
:wq                                   ← last token of the file
```

- Source files are UTF-8 with the `.btw` extension. A leading byte-order mark is skipped. `\r\n` counts as one newline.
- Positions are 0-based line and column internally (that's what LSP uses) and printed 1-based by the CLI. Columns count UTF-16 code units, which equals characters for ASCII. Only strings and comments can contain non-ASCII text.

# 2. Lexical structure

## 2.1 Whitespace and newlines

- Spaces and tabs separate tokens. A tab counts as one column.
- A newline is a token (`NEWLINE`) because it ends statements. Blank lines are allowed anywhere.
- Newlines inside parentheses are ignored (the lexer tracks paren depth), so long argument lists can wrap.

## 2.2 Comments

A comment runs from `//` to the end of the line, either on its own line or after code. Comments aren't tokens: the lexer returns them in a separate list, classified by the text after `//` and optional spaces.

| Comment                                                                     | Kind | Effect                                               | Tier |
| --------------------------------------------------------------------------- | ---- | ---------------------------------------------------- | ---- |
| `// TODO` plus anything (`//TODO` also works; `TODO` must be uppercase)     | TODO | Counts toward the technical debt limit of 5 per file | P1   |
| `// works on my machine` (case-insensitive; extra text after it is ignored) | WOMM | Suppression directive for the next statement or item | P2   |
| Anything else, including `// todo`                                          | BAD  | E406                                                 | P1   |

Block comments don't exist: `/*` lexes as `/` then `*` and becomes a syntax error.

## 2.3 Keywords

- A multi-word keyword is one token. Between its words, any run of spaces or tabs is allowed, never a newline.
- A keyword only matches if the next character isn't an identifier character, so `doomscrolling` and `shipit` are identifiers.
- Longest match first: try `npm install -g` before `npm install`, `git push --force` before `git push`, and `i use arch btw` before the identifier `i`.

| Token             | Text                                                                | Means                        | Tier |
| ----------------- | ------------------------------------------------------------------- | ---------------------------- | ---- |
| ARCH              | `i use arch btw`                                                    | file header                  | P0   |
| SERVE             | `serve`                                                             | main block                   | P0   |
| `LOCALHOST`       | `localhost:` followed by digits, as one token that carries the port | address after `serve`        | P0   |
| WQ                | `:wq`                                                               | end of program               | P0   |
| NPM_INSTALL_G     | `npm install -g`                                                    | constant declaration         | P0   |
| NPM_INSTALL       | `npm install`                                                       | variable declaration         | P0   |
| GIT_PUSH_FORCE    | `git push --force`                                                  | assignment                   | P0   |
| SUDO              | `sudo`                                                              | permission prefix            | P0   |
| CONSOLE_LOG       | `console.log`                                                       | print                        | P0   |
| VIBE_CHECK        | `vibe check`                                                        | if                           | P0   |
| SKILL_ISSUE       | `skill issue`                                                       | else                         | P0   |
| DOOMSCROLL        | `doomscroll`                                                        | while                        | P0   |
| TOUCH_GRASS       | `touch grass`                                                       | break                        | P0   |
| MICROSERVICE      | `microservice`                                                      | function                     | P0   |
| SHIP_IT           | `ship it`                                                           | return                       | P0   |
| LGTM              | `LGTM`                                                              | true                         | P0   |
| NOT_FOUND         | `404`, exactly those three digits                                   | false                        | P0   |
| GIT_REVERT        | `git revert`                                                        | undo                         | P2   |
| GIT_LOG           | `git log`                                                           | print history                | P2   |
| GIT_PUSH_NO_FORCE | `git push` without `--force`                                        | error token, roasted as E400 | P1   |

Reserved words, which can't name a variable or microservice: `serve`, `sudo`, `doomscroll`, `microservice`, `LGTM`. The first words of multi-word keywords (`npm`, `git`, `vibe`, `skill`, `touch`, `ship`, `console`, `i`) are not reserved, so `i` stays usable as a loop variable. A reserved word used as a name is E400: "Syntax error: expected a name, found `sudo`."

## 2.4 Identifiers

`[A-Za-z_][A-Za-z0-9_]*`, ASCII only, case-sensitive. Convention only, not enforced: constants in `SCREAMING_CASE`, everything else camelCase. The letter `O` is an ordinary identifier, except right after a microservice's parameter list, where `O(` starts a Big O annotation.

## 2.5 Literals

- **Numbers:** decimal digits, either `0` or starting with 1 to 9. Leading zeros are E400 (P2 roast). Anything above 9223372036854775807 is E413. Negative numbers are unary minus applied to a literal.
- **The 404 rule:** the exact digit sequence `404` is the boolean false, never a number. `4040` and `1404` are ordinary numbers.
- **Booleans:** `LGTM` and `404`.
- **Strings:** double quotes, single line. Escapes: `\n`, `\t`, `\"`, `\\`. Any other escape is E400. A string that reaches a newline or the end of the file before its closing quote is E400 "Unterminated string. Like your side projects." The lexer still emits the string token (content up to the end of the line) so parsing carries on normally.

## 2.6 Operators and punctuation

```
+  -  *  /  %        arithmetic      number, number → number
==  !=               equality        same type on both sides → boolean
<  <=  >  >=         comparison      number, number → boolean
&&  ||  !            logic           boolean → boolean, short-circuit
=                    binding         only in declarations and assignments
|                    pipe (P2)       value | microservice
(  )  {  }  ,        grouping, blocks, argument lists
^                    only inside Big O annotations, as in O(n^2)
```

Longest match first: `||` before `|`, `==` before `=`, `<=` before `<`, `!=` before `!`. Any other character is E400 "Unexpected character `@`." The P2 roast tokens are in section 13.

# 3. Grammar

```
program        = NL* ARCH NL* { item NL* } WQ NL* EOF
item           = global_decl | microservice | serve

global_decl    = ( NPM_INSTALL_G | NPM_INSTALL ) IDENT "=" expr
microservice   = MICROSERVICE IDENT "(" [ IDENT { "," IDENT } ] ")" [ big_o ] block
big_o          = "O" "(" big_o_body ")"          "O" is an IDENT whose text is O
big_o_body     = "1" | IDENT | IDENT "^" INT
               | any other tokens up to the matching ")"   → unverifiable
serve          = SERVE LOCALHOST block

block          = "{" NL* [ stmt { NL+ stmt } ] NL* "}"
stmt           = var_decl | assign | if | while | break | return
               | print | revert | log | expr_stmt
var_decl       = ( NPM_INSTALL | NPM_INSTALL_G ) IDENT "=" expr     -g here is E405
assign         = [ SUDO ] GIT_PUSH_FORCE IDENT "=" expr
if             = VIBE_CHECK expr block [ NL* SKILL_ISSUE ( if | block ) ]
while          = DOOMSCROLL expr block
break          = TOUCH_GRASS
return         = SHIP_IT [ expr ]           no expr when the next token is NL or "}"
print          = CONSOLE_LOG expr
revert         = [ SUDO ] GIT_REVERT IDENT
log            = GIT_LOG IDENT
expr_stmt      = expr                       a call or a pipeline; anything else is W204

expr           = pipeline
pipeline       = or { "|" stage }                                   P2
stage          = IDENT [ "(" [ args ] ")" ] | CONSOLE_LOG
or             = and { "||" and }
and            = equality { "&&" equality }
equality       = comparison [ ( "==" | "!=" ) comparison ]          non-associative
comparison     = additive [ ( "<" | "<=" | ">" | ">=" ) additive ]  non-associative
additive       = multiplicative { ( "+" | "-" ) multiplicative }
multiplicative = unary { ( "*" | "/" | "%" ) unary }
unary          = ( "!" | "-" ) unary | postfix
postfix        = IDENT "(" [ args ] ")" | primary
primary        = INT | STRING | LGTM | NOT_FOUND | IDENT | "(" expr ")"
args           = expr { "," expr }
```

- **Else lookahead:** after an if's block, the parser peeks past newlines. If the next token is `skill issue`, it consumes the newlines and parses the else branch. Otherwise it leaves them alone.
- A closing `}` ends the last statement of a block, so `{ console.log "Fizz" }` needs no newline.
- Grouping parentheses don't create an AST node. The inner expression keeps its own span, so diagnostics point inside the parens.

## 3.1 Precedence

```
lowest   1   |                pipe             left    (P2)
         2   ||               or               left
         3   &&               and              left
         4   ==  !=           equality         non-associative
         5   <  <=  >  >=     comparison       non-associative
         6   +  -             additive         left
         7   *  /  %          multiplicative   left
         8   !  -             prefix unary     right
highest  9   f(args)  ( )     call, grouping
```

# 4. Structure rules

| Rule                                           | Diagnostic                                                                    | Tier |
| ---------------------------------------------- | ----------------------------------------------------------------------------- | ---- |
| The first token must be `i use arch btw`       | E426, spanning line 1                                                         | P0   |
| A second `i use arch btw` anywhere             | W208                                                                          | P2   |
| The last token must be `:wq`                   | E408, on the last token in the file                                           | P0   |
| Anything after `:wq`                           | E410, one diagnostic from there to the end of the file                        | P1   |
| No `serve` block                               | E503, on `:wq` (or the end of the file)                                       | P0   |
| More than one `serve` block                    | E409 on each extra one                                                        | P1   |
| A statement such as `console.log` at top level | E400: expected `microservice`, `serve` or `npm install`, found `console.log`. | P0   |
| A port other than 3000                         | Accepted in P0. P2 roast in section 13.                                       | P2   |

The parser never reports E426, E408 or E410 itself. It records whether the arch line was first, where `:wq` is, and what follows it, and the checker reports them. That keeps the parser simple and avoids duplicate errors.

# 5. Types and expressions

| Expression                                                   | Operands                      | Result  | Notes                                                                                                                 |
| ------------------------------------------------------------ | ----------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------- |
| `a + b`, `a - b`, `a * b`                                    | number, number                | number  | Wraps on overflow                                                                                                     |
| `a / b`                                                      | number, number                | number  | Truncates toward zero. Dividing by zero is a runtime error.                                                           |
| `a % b`                                                      | number, number                | number  | Takes the sign of `a`. Modulo by zero is a runtime error.                                                             |
| `-a`                                                         | number                        | number  | Negating the minimum value wraps to itself                                                                            |
| `a == b`, `a != b`                                           | both numbers or both booleans | boolean | Mixing types is E418                                                                                                  |
| Comparisons (less, less-or-equal, greater, greater-or-equal) | number, number                | boolean | Can't be chained                                                                                                      |
| `a && b`, `a                                                 |                               | b`      | boolean, boolean                                                                                                      | boolean | The right side isn't evaluated when the left side decides |
| `!a`                                                         | boolean                       | boolean |                                                                                                                       |
| `f(x, y)`                                                    | numbers                       | number  | Arity must match (E422)                                                                                               |
| `"text"`                                                     | none                          | string  | Only as the direct operand of `console.log`, or the head of a pipe that ends in `console.log`. Anywhere else is E415. |

- Evaluation order is left to right everywhere: operands, arguments, pipe stages.
- An expression whose type is unknown (because of an earlier error) never causes another type error. One mistake, one squiggle.

**Reference values.** Use these as unit tests for the interpreter's arithmetic helpers.

```
 7 /  2 =  3       7 %  2 =  1
-7 /  2 = -3      -7 %  2 = -1      Python's // and % disagree on these two rows
 7 / -2 = -3       7 % -2 =  1      (Python gives -4 1 and -4 -1)
-7 / -2 =  3      -7 % -2 = -1

 9223372036854775807 + 1   = -9223372036854775808
-9223372036854775807 - 2   =  9223372036854775807
 3037000500 * 3037000500   = -9223372036709301616
```

# 6. Statements

| Statement                             | Meaning                                                                                 | Errors                                                                                             | Tier                   |
| ------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------- |
| `npm install x = e`                   | Declare x in the current block with e's type and value. Records history commit 1.       | E409 if the name is already visible. E415 for a string value.                                      | P0                     |
| `npm install -g X = e`                | Declare a constant. Top level only.                                                     | E405 inside a block                                                                                | P0                     |
| `git push --force x = e`              | Assign. Records a history commit.                                                       | E404 unknown name. E418 if the type differs from the declaration. E403 on a constant without sudo. | P0                     |
| `sudo git push --force X = e`         | Assign, allowed on constants                                                            | W100 if the target isn't a constant                                                                | P0 (W100 is P2)        |
| `vibe check c { } skill issue { }`    | If, else-if chains, else                                                                | E418 if c isn't a boolean                                                                          | P0                     |
| `doomscroll c { }`                    | While                                                                                   | E418 if c isn't a boolean. W509 for an obvious infinite loop (rule below).                         | P0 (W509 is P1)        |
| `touch grass`                         | Break out of the innermost doomscroll in the same microservice                          | E405 outside a doomscroll                                                                          | P0                     |
| `ship it` or `ship it e`              | In a microservice: return e, or 0. In `serve`: exit the program with exit code e, or 0. | E418 if e is a boolean. W410 for statements after it in the same block.                            | P0 (W410 is P2)        |
| `console.log e`                       | Print e and a newline                                                                   | E405 if e is a bare microservice name                                                              | P0                     |
| `git revert x` or `sudo git revert x` | Restore the previous value (section 9.3)                                                | E403 on a constant without sudo. E405 on microservice parameters and locals.                       | P2                     |
| `git log x`                           | Print x's history (section 9.3)                                                         | E405 on microservice parameters and locals                                                         | P2                     |
| `f(a, b)` on its own line             | Call and discard the result                                                             | E404, E422                                                                                         | P0                     |
| `a                                    | f                                                                                       | console.log`                                                                                       | Pipeline (section 9.4) | E405 if it ends in `console.log` and is used as a value | P2  |

**W509 rule:** the condition is the literal `LGTM`, and the body contains no `ship it` and no `touch grass` outside nested doomscrolls. A `touch grass` inside a nested `vibe check` still counts as a way out.

# 7. Names and scope

- Three levels: global (constants, globals, microservices), microservice (parameters) and block (every pair of braces).
- Globals and microservices are visible everywhere, including above their definition. The one exception: a global initializer only sees globals declared above it.
- No shadowing. Declaring a name that's already visible (global, microservice, parameter or outer local) is E409. Sibling blocks can each declare their own `i`.
- A variable is visible from its declaration to the end of its block. Using it before the declaration or after the block ends is E404.
- Variables and microservices share one namespace. Using a microservice as a value is E405 ("`total` is a microservice. Call it: `total(...)`."). Calling a variable is E405 ("`x` is a variable, not a microservice.").
- Parameters behave like local variables and can be reassigned with `git push --force`.

# 8. Microservices

- `microservice name(a, b) O(n) { ... }` with 0 to 6 parameters. Seven or more is E413. A repeated parameter name is E409.
- Arguments must be numbers (E418). The wrong number of arguments is E422. Falling off the end returns 0.
- Maximum call depth is 1,000: the 1,001st nested call is a runtime error. `serve` itself is depth 0.
- The Big O annotation is optional. Leaving it out is W102 (section 9.1).
- Names like `main`, `printf` and `exit` are fine, because the codegen prefixes every user symbol.

# 9. Feature specs

## 9.1 Big O checker (P0, the headline)

**Annotations**

| You write                                                  | Means                                                                        | Checked  |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------- | -------- |
| `O(1)`                                                     | degree 0                                                                     | yes      |
| `O(n)`, with any single name inside                        | degree 1                                                                     | yes      |
| `O(n^2)`, `O(n^3)` and so on                               | degree k                                                                     | yes      |
| `O(n²)`, `O(n³)`                                           | degree 2 or 3 (P2: the lexer accepts superscripts only inside an annotation) | yes      |
| `O(log n)`, `O(n log n)`, `O(2^n)`, `O(n!)`, anything else | unverifiable                                                                 | no, W203 |

**Inference** (the degree of each microservice)

```
deg(block)                  = max over its statements, or 0 if it's empty
deg(doomscroll c { B })     = 1 + max(degE(c), deg(B))       the condition runs on every iteration
deg(vibe check c T else E)  = max(degE(c), deg(T), deg(E))
deg(any other statement)    = max over its expressions
degE(f(args))               = max(degFn(f), degE(args))      P1. In P0 a call costs 0.
degE(anything else)         = max over sub-expressions; literals and names are 0
degFn(f)                    = deg(body of f), computed once and memoized
recursion                   = f is on a cycle in the call graph (calling itself counts) → UNKNOWN
UNKNOWN is contagious       : max(UNKNOWN, x) = UNKNOWN and 1 + UNKNOWN = UNKNOWN
```

P0 only detects direct self-calls. P1 builds the call graph and finds cycles (Tarjan's SCC, or a depth-first search with an "in progress" mark).

**Verdicts** (k = annotated degree, d = inferred degree)

| Situation               | Diagnostic                                                                                        | Span           |
| ----------------------- | ------------------------------------------------------------------------------------------------- | -------------- |
| k equals d              | None. The hover shows a ✓.                                                                        |                |
| k is less than d        | E417, soft error: You said O(n), but this is O(n²). Skill issue.                                  | the annotation |
| k is greater than d     | W417: Technically correct, but this is O(1). Sandbagging your estimates?                          | the annotation |
| No annotation, d known  | W102: microservice `f` has no SLA. Inferred: O(n).                                                | the name       |
| d is UNKNOWN            | W508: Complexity: O(?). The halting problem is a skill issue. This replaces the three rows above. | the name       |
| Unverifiable annotation | W203: I can't verify O(log n). I'll take your word for it.                                        | the annotation |

- **Formatting:** degree 0 is `O(1)`, 1 is `O(n)`, 2 is `O(n²)`, 3 is `O(n³)`, 4 and up is `O(n^4)`. Use the annotation's variable name when there is one, `n` otherwise. W203 echoes the annotation's exact source text.
- **P2 extra:** E417 carries related information pointing at the innermost doomscroll of the deepest nest ("nested doomscroll #2 starts here").
- **Known limits, say them in Q&A:** every loop counts as n iterations, so `doomscroll (i < 10)` is counted as O(n) and a halving loop is overestimated. It's a teaching heuristic, not a proof.

## 9.2 sudo constants (P0)

| Statement                     | On a constant                                      | On a variable                                           |
| ----------------------------- | -------------------------------------------------- | ------------------------------------------------------- |
| `git push --force X = e`      | E403, soft error: Permission denied. Are you root? | fine                                                    |
| `sudo git push --force X = e` | fine                                               | W100 (P2): You didn't need sudo for that. Who hurt you? |
| `git revert X`                | E403, soft error                                   | fine                                                    |
| `sudo git revert X`           | fine                                               | W100 (P2)                                               |
| `git log X`                   | fine, reading doesn't need root                    | fine                                                    |

- `sudo` in front of anything else is E400: "`sudo` only works with `git push --force` and `git revert`."
- E403 has a help line (CLI pretty mode, and the P2 quick fix): try `sudo git push --force X = ...`.
- When E403 is suppressed by `// works on my machine`, the assignment runs as if sudo were there.

## 9.3 Git history (P2)

- Every variable has a history: its committed values, oldest first, keeping only the 16 most recent.
- The declaration is commit 1. Each `git push --force` and each `git revert` adds a commit. A declaration that runs again (inside a loop) starts a fresh history.
- `git revert x`: if x has fewer than 2 commits, it's a runtime error, `fatal: bad revision 'x~1'` on stderr with exit code 128 (git's own fatal exit code). Otherwise x becomes the value of the second-newest commit, and that value is appended as a new commit.
- `git log x` prints one line per commit, newest first, as `* VALUE`, with `(HEAD -> x)` appended to the first line. Booleans print as `LGTM` and `404`.
- Restriction, in both backends, to keep codegen simple: history only works on globals, constants and variables declared in `serve`. On microservice parameters and locals it's E405: "History only works on globals and variables in `serve`. Microservice locals are in detached HEAD state."

```
npm install x = 1          history: 1
git push --force x = 2     history: 1 2
git push --force x = 3     history: 1 2 3
git revert x               x = 2, history: 1 2 3 2
git revert x               x = 3, history: 1 2 3 2 3
git log x                  prints:
                             * 3 (HEAD -> x)
                             * 2
                             * 3
                             * 2
                             * 1
```

## 9.4 Pipes (P2)

- `a | f | g(y) | console.log` desugars in the parser to `console.log g(f(a), y)`. The piped value becomes the first argument of each stage.
- A stage is a microservice name, a microservice call with extra arguments, or `console.log` (last stage only).
- Pipes have the lowest precedence, so `a + 1 | f` means `f(a + 1)`.
- A pipeline ending in `console.log` is a statement. Using one as a value is E405: "`console.log` returns nothing. It's void, like my weekend plans."
- `"text" | console.log` is allowed, since the string is still the direct operand of `console.log`.
- Each desugared call keeps the span of its stage, so errors point at the right stage.

## 9.5 Works on my machine (P2)

- `// works on my machine` targets the first statement or item that starts after it, skipping blank lines and other comments.
- It removes soft errors (E403, E417) and warnings whose span starts inside that statement or item. For a microservice, that's the whole function.
- Hard errors stay.
- It always leaves exactly one warning on the directive itself:

| What happened                   | Diagnostic on the directive                                                  |
| ------------------------------- | ---------------------------------------------------------------------------- |
| Removed 1 or more diagnostics   | W200: 200 OK (on my machine): 1 problem suppressed. ("2 problems" and so on) |
| The target only has hard errors | W304: 304 Not Modified: this one doesn't work on any machine.                |
| Nothing to remove               | W304: 304 Not Modified: nothing to suppress. It works on every machine.      |

- Suppressed code runs normally: a suppressed E403 assignment really assigns.

## 9.6 Technical debt limit (P1)

- Up to 5 TODO comments per file is fine. The 6th and every later one gets E429: "Error: technical debt limit exceeded (6/5 TODOs). Finish something." The count in the message is the file's total.
- E429 can't be suppressed. Technical debt can only be refinanced.
- Hovering any TODO shows "Technical debt: 3/5 TODOs used."

# 10. Runtime behavior

- Order: global initializers in source order, then the `serve` body. The exit code is the value of `ship it` in `serve`, or 0. The OS keeps only the low 8 bits, so tests stay within 0 to 255.
- `console.log` and `git log` write to stdout. Runtime errors flush stdout first, then write to stderr.

| Runtime error                              | stderr, exactly                                                                | Exit code |
| ------------------------------------------ | ------------------------------------------------------------------------------ | --------- |
| Division or modulo by zero                 | `Runtime error: division by zero. Have you tried turning it off and on again?` | 1         |
| More than 1,000 nested microservice calls  | `Stack overflow. Please search stackoverflow.com.`                             | 1         |
| `git revert` on a variable with one commit | `fatal: bad revision 'x~1'`                                                    | 128       |

Undefined and never tested: the minimum number divided by -1 (x86 traps; the interpreter would wrap).

# 11. Diagnostics catalog

Messages contain literal backticks around code, exactly as they appear in the Test Corpus expected output. Hard and soft errors block `btw run` and `btw build`; warnings never do. Only soft errors and warnings can be suppressed. One exception to the backtick rule: in E503, `localhost:3000` is shown as code only to stop Notion from turning it into a link, and the real message has no backticks there (see p0_e503_no_serve in the Test Corpus). The codes are HTTP statuses picked to fit: 426 Upgrade Required (install Arch), 408 Request Timeout (never exited), 417 Expectation Failed (Big O), 418 I'm a teapot (types), 429 Too Many Requests (TODOs), 508 Loop Detected (recursion), 509 Bandwidth Limit Exceeded (doomscrolling).

| Code | Severity   | Tier | Trigger                                          | Exact message                                                                                                                                                                                                    | Span                                                         | Quick fix (P2)      |
| ---- | ---------- | ---- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------- |
| E400 | error      | P0   | syntax error                                     | Syntax error: expected WHAT, found WHAT. WHAT is a keyword or symbol in backticks, or one of: an expression, a name, a statement, end of line, end of file.                                                      | the unexpected token                                         |                     |
| E400 | error      | P1   | `git push` without `--force`                     | Updates were rejected because the tip of your current branch is behind. Use `git push --force`.                                                                                                                  | `git push`                                                   | Add --force         |
| E400 | error      | P1   | unterminated string                              | Unterminated string. Like your side projects.                                                                                                                                                                    | from the opening quote                                       |                     |
| E403 | soft error | P0   | constant changed without sudo                    | Permission denied. Are you root?                                                                                                                                                                                 | from the keyword through the name                            | Run with sudo       |
| E404 | error      | P0   | unknown variable                                 | Error 404: variable `x` not found. Did you forget to `npm install` it?                                                                                                                                           | the name                                                     |                     |
| E404 | error      | P0   | unknown microservice                             | Error 404: microservice `f` not found. Did you forget to deploy it?                                                                                                                                              | the callee name                                              |                     |
| E405 | error      | P0   | `touch grass` outside a loop                     | Error: `touch grass` outside a `doomscroll`. You were never scrolling.                                                                                                                                           | `touch grass`                                                |                     |
| E405 | error      | P1   | `npm install -g` inside a block                  | npm ERR! `-g` installs go at the top level.                                                                                                                                                                      | the keyword                                                  |                     |
| E405 | error      | P1   | global initializer calls a microservice          | npm ERR! postinstall scripts are disabled. Globals can't call microservices.                                                                                                                                     | the call                                                     |                     |
| E405 | error      | P1   | microservice used as a value                     | `f` is a microservice. Call it: `f(...)`.                                                                                                                                                                        | the name                                                     |                     |
| E405 | error      | P1   | variable called like a microservice              | `x` is a variable, not a microservice.                                                                                                                                                                           | the name                                                     |                     |
| E405 | error      | P2   | history on a microservice local                  | History only works on globals and variables in `serve`. Microservice locals are in detached HEAD state.                                                                                                          | the statement                                                |                     |
| E405 | error      | P2   | pipe into `console.log` used as a value          | `console.log` returns nothing. It's void, like my weekend plans.                                                                                                                                                 | `console.log`                                                |                     |
| E406 | error      | P1   | comment that isn't a TODO                        | Error: comments must be `// TODO`. Documentation is a TODO.                                                                                                                                                      | the comment                                                  |                     |
| E408 | error      | P0   | missing `:wq`                                    | Error: program never exited. Classic Vim user.                                                                                                                                                                   | the last token                                               | Exit Vim            |
| E409 | error      | P0   | name already visible                             | npm ERR! `x` is already installed. Use `git push --force` to update it.                                                                                                                                          | the new name                                                 |                     |
| E409 | error      | P1   | duplicate microservice                           | Error: microservice `f` is already deployed.                                                                                                                                                                     | the second name                                              |                     |
| E409 | error      | P1   | second `serve` block                             | Error: port 3000 is already in use.                                                                                                                                                                              | the extra `serve`                                            |                     |
| E410 | error      | P1   | code after `:wq`                                 | Error: code after `:wq`. You already left Vim.                                                                                                                                                                   | everything after `:wq`                                       | Delete it           |
| E413 | error      | P1   | 7 or more parameters                             | Error: `f` takes 7 parameters. That's not a microservice, that's a monolith.                                                                                                                                     | the name                                                     |                     |
| E413 | error      | P1   | number literal too large                         | Error: number too large. This isn't JavaScript, there's no BigInt here.                                                                                                                                          | the literal                                                  |                     |
| E415 | error      | P0   | string outside `console.log`                     | Error: strings are for `console.log` only. Everything else is a number.                                                                                                                                          | the string                                                   |                     |
| E417 | soft error | P0   | Big O under-claim                                | You said O(n), but this is O(n²). Skill issue.                                                                                                                                                                   | the annotation                                               | Update SLA to O(n²) |
| E418 | error      | P0   | condition isn't a boolean                        | I'm a teapot: `vibe check` needs LGTM or 404, got a number. (Same with `doomscroll`.)                                                                                                                            | the condition                                                |                     |
| E418 | error      | P0   | assignment changes the type                      | I'm a teapot: `x` was installed as a number, you pushed a boolean. Dependency conflict. (And the reverse.)                                                                                                       | the value                                                    |                     |
| E418 | error      | P1   | operator on the wrong type                       | One of: I'm a teapot: can't apply `+` to a boolean. / I'm a teapot: can't compare a number with a boolean. / I'm a teapot: `!` needs a boolean, got a number. / I'm a teapot: `-` needs a number, got a boolean. | the offending operand (the whole expression for comparisons) |                     |
| E418 | error      | P1   | boolean returned from a microservice             | I'm a teapot: microservices ship numbers, got a boolean. Ship 1 or 0 like it's 1972.                                                                                                                             | the value                                                    |                     |
| E418 | error      | P1   | boolean argument                                 | I'm a teapot: microservices take numbers, got a boolean.                                                                                                                                                         | the argument                                                 |                     |
| E422 | error      | P0   | wrong number of arguments                        | Error: microservice `f` expects 2 arguments, got 1. Breaking API change? ("1 argument" when 1 is expected)                                                                                                       | the call                                                     |                     |
| E426 | error      | P0   | missing `i use arch btw`                         | Fatal: `i use arch btw` not found. Are you on Windows?                                                                                                                                                           | line 1                                                       | Install Arch        |
| E429 | error      | P1   | more than 5 TODOs                                | Error: technical debt limit exceeded (6/5 TODOs). Finish something.                                                                                                                                              | each TODO past the 5th                                       |                     |
| E500 | error      | P0   | internal compiler error                          | It works on my machine. Unfortunately, this is not my machine.                                                                                                                                                   | line 1                                                       |                     |
| E501 | error      | P1   | construct the native backend doesn't support yet | Not implemented: `git log` in native builds. Try `btw run`.                                                                                                                                                      | the construct                                                |                     |
| E502 | error      | P1   | gcc rejected the generated assembly              | Bad gateway: gcc rejected the generated assembly. That's a compiler bug, not a skill issue.                                                                                                                      | line 1                                                       |                     |
| E503 | error      | P0   | no `serve` block                                 | Error: no server running. Nothing is listening on `localhost:3000`.                                                                                                                                              | `:wq`                                                        |                     |
| W100 | warning    | P2   | unnecessary sudo                                 | You didn't need sudo for that. Who hurt you?                                                                                                                                                                     | `sudo`                                                       | Remove sudo         |
| W102 | warning    | P1   | no Big O annotation                              | microservice `f` has no SLA. Inferred: O(n).                                                                                                                                                                     | the name                                                     | Add SLA O(n)        |
| W200 | warning    | P2   | suppression removed something                    | 200 OK (on my machine): 1 problem suppressed.                                                                                                                                                                    | the directive                                                |                     |
| W203 | warning    | P1   | unverifiable annotation                          | I can't verify O(log n). I'll take your word for it.                                                                                                                                                             | the annotation                                               |                     |
| W204 | warning    | P2   | expression statement that does nothing           | This expression does nothing. Like a standup meeting.                                                                                                                                                            | the expression                                               |                     |
| W208 | warning    | P2   | repeated arch line                               | 208 Already Reported: we know you use Arch.                                                                                                                                                                      | the repeat                                                   |                     |
| W304 | warning    | P2   | suppression removed nothing                      | 304 Not Modified: nothing to suppress. It works on every machine. / 304 Not Modified: this one doesn't work on any machine.                                                                                      | the directive                                                |                     |
| W410 | warning    | P2   | code after `ship it`                             | This code never reaches prod.                                                                                                                                                                                    | the first unreachable statement                              |                     |
| W417 | warning    | P1   | Big O over-claim                                 | Technically correct, but this is O(1). Sandbagging your estimates?                                                                                                                                               | the annotation                                               | Tighten SLA         |
| W508 | warning    | P0   | recursion                                        | Complexity: O(?). The halting problem is a skill issue.                                                                                                                                                          | the name                                                     |                     |
| W509 | warning    | P1   | `doomscroll` on LGTM with no way out             | Infinite doomscroll detected. Go touch grass.                                                                                                                                                                    | `doomscroll`                                                 |                     |

Diagnostics are sorted by line, then column, then code, and exact duplicates (same code and span) are dropped. The parser reports at most one E400 per statement.

# 12. Hover text (P1)

| Hover on                 | Shows                                                                                                          |
| ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `i use arch btw`         | **Required first line.** Proves you're worthy. Without it the compiler assumes you're on Windows.              |
| `serve localhost:3000`   | **main().** Every program is secretly a dev server. Nobody knows what else is running on port 3000.            |
| `:wq`                    | **End of program.** The only known way out.                                                                    |
| `npm install`            | **let.** Declares a variable. node_modules just got 200 MB heavier.                                            |
| `npm install -g`         | **const.** A global install. Changing it needs sudo, like everything else on your machine.                     |
| `git push --force`       | **Assignment.** Overwrites the old value without asking. Your teammates love this.                             |
| `sudo`                   | **Permission override.** Lets you modify constants. With great power comes no code review.                     |
| `git revert`             | **Undo.** Restores the previous value as a new commit. History is forever.                                     |
| `git log`                | **Print history.** Every value this variable ever had. Most of them were mistakes.                             |
| `console.log`            | **print.** Real debugging, in a compiled language.                                                             |
| `vibe check`             | **if.** Runs the block when the vibes are LGTM.                                                                |
| `skill issue`            | **else.** For when the vibe check fails.                                                                       |
| `doomscroll`             | **while.** Keeps going while the condition holds. Or forever. Mostly forever.                                  |
| `touch grass`            | **break.** The only healthy way out of a doomscroll.                                                           |
| `microservice`           | **function.** Independently deployable. Called from exactly one place.                                         |
| `ship it`                | **return.** Straight to prod. Tests are a TODO.                                                                |
| `LGTM`                   | **true.** Approved without reading.                                                                            |
| `404`                    | **false.** Truth not found. Also the one number you can't type.                                                |
| a TODO comment           | **Comment.** The only kind allowed. Technical debt: 3/5 TODOs used.                                            |
| `// works on my machine` | **Suppression.** Silences soft errors on the next statement and ships the bug to everyone else.                |
| a Big O annotation       | **SLA.** Checked by counting nested doomscrolls. Verdict: ✓ verified, ✗ actually O(n²), or O(?) for recursion. |
| a variable               | `npm install x` · number · declared on line 4 (P2 adds: 3 commits)                                             |
| a constant               | `npm install -g LIMIT` · number · global install, modifying it needs `sudo`                                    |
| a parameter              | parameter `n` of `total` · number                                                                              |
| a microservice name      | `microservice total(n)` · SLA O(n) · inferred O(n) ✓ (or ✗ with the inferred value, or O(?) when recursive)    |

# 13. Roast backlog (P2, only if you're ahead)

| Input                         | Code | Message                                                                             |
| ----------------------------- | ---- | ----------------------------------------------------------------------------------- |
| `===`                         | E400 | This isn't JavaScript. Use `==`.                                                    |
| `;`                           | E400 | Semicolons are deprecated. This is a modern language.                               |
| `++`                          | E400 | We don't do that here. Use `git push --force i = i + 1`.                            |
| `007`                         | E400 | Leading zeros? This isn't octal, James Bond.                                        |
| a chained comparison          | E400 | Chained comparisons aren't a thing here. This isn't Python.                         |
| `serve localhost:8080`        | E409 | Error: port 8080 is already in use by a Spring Boot app you forgot about. Use 3000. |
| CLI summary line, pretty mode | none | build failed: 2 errors, 1 warning. Skill issue. / 1 warning. LGTM anyway.           |
