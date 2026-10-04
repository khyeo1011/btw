# Implementation Spec

> How the pieces fit together. Language-neutral where possible; file names assume the recommended Python stack. Markdown export of the Notion Implementation Spec page. The Language Spec (`docs/SPEC.md`) wins on language behavior; `src/btw/span.py`, `diagnostics.py` and `ast.py` are the code form of section 4.

---

# 1. Stack

**Recommendation: Python 3.12+ with pygls 2.x**, unless you're clearly faster in Rust.

- No build step, so agents iterate fastest. The checker, interpreter and codegen are all tree walks and string building.
- pygls handles JSON-RPC, document syncing and position encoding.
- One language for compiler and server, so the language server calls the checker directly.
- The costs: Python integers never overflow (wrap them yourself), and its `//` and `%` round differently from x86 (emulate them). The reference table in Language Spec §5 is the unit test for both.

| Concern                           | Python (default)                                                                                       | Rust (alternative)                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| Environment                       | uv, with `pyproject.toml` declaring two console scripts: `btw = "btw.cli:main"` and `btw-lsp = "btw.lsp:main"` | cargo, two binaries                                                                                                 |
| LSP library                       | pygls 2.x (2.1 is current) with lsprotocol 2025.x                                                      | `tower-lsp-server`, the community fork. The original `tower-lsp` hasn't been maintained since early 2024. Pin the version you test. |
| 64-bit wrapping                   | A helper applied after every arithmetic op                                                             | `wrapping_add`, `wrapping_sub`, `wrapping_mul`                                                                             |
| Truncating division               | A helper, tested against Language Spec §5                                                              | Native `/` and `%`                                                                                                         |
| Deep recursion in the interpreter | `sys.setrecursionlimit(50_000)`. Since 3.11, Python-to-Python calls don't use the C stack.             | Run the interpreter on a thread with a bigger stack                                                                        |
| Tests                             | pytest, parametrized over `tests/golden`                                                               | cargo test, or reuse the Python runner                                                                                     |

**pygls 2 gotchas.** Agents trained on pygls 1 get these wrong, so they belong in `CLAUDE.md` (§14).

- `LanguageServer` is imported from `pygls.lsp.server`, not `pygls.server`.
- Publishing diagnostics: `ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=..., diagnostics=[...]))`. The v1 `publish_diagnostics(uri, diags)` is gone.
- Document text: `ls.workspace.get_text_document(uri).source`.
- Renamed methods: `show_message` is now `window_show_message`, `apply_edit` is now `workspace_apply_edit`, and `send_notification` is now `protocol.notify`.
- lsprotocol 2025 renamed many types. Read the installed package instead of guessing names.

**VS Code client:** `vscode-languageclient`. Pin 9.0.1 and write the client in plain JavaScript, with no TypeScript build. Version 10.x also works, but needs `engines.vscode` of at least 1.91 and, in TypeScript, Node16 module resolution, because 10.x only exposes `vscode-languageclient/node` through package exports.

**Neovim:** 0.11 or newer, for `vim.lsp.config` and `vim.lsp.enable`.

**Toolchain:** any recent gcc and binutils on Linux x86-64.

# 2. Repo layout

```
btw-lang/
├── CLAUDE.md                     agent rules, written at hour 0 (topics in §14)
├── README.md                     written Sunday morning
├── pyproject.toml                scripts: btw = btw.cli:main, btw-lsp = btw.lsp:main
├── docs/SPEC.md                  Markdown export of the Notion spec pages
├── src/btw/
│   ├── __main__.py               so python -m btw works
│   ├── span.py                   Pos, Span                            ← you, hour 0
│   ├── diagnostics.py            Severity, Diagnostic, Fix             ← you, hour 0
│   ├── ast.py                    AST node classes                      ← you, hour 0
│   ├── tokens.py                 TokenKind, Token, Comment
│   ├── lexer.py
│   ├── parser.py
│   ├── checker.py                structure, names, scopes, types, sudo, comments
│   ├── bigo.py                   Big O inference and diagnostics
│   ├── suppress.py               works on my machine (P2)
│   ├── interp.py
│   ├── codegen.py
│   ├── driver.py                 check, run and build pipelines; gcc
│   ├── printing.py               short and pretty diagnostic output
│   ├── cli.py
│   ├── lsp.py
│   └── hovers.py                 keyword hover text
├── runtime/btw_rt.c              linked into every native binary
├── tests/
│   ├── golden/                   programs plus .diag .out .err .exit sidecars, written at the event
│   ├── test_golden.py            check, interpreter and native run per program
│   └── test_*.py                 unit tests per component
├── editors/
│   ├── vscode/                   package.json, extension.js, language-configuration.json, syntaxes/
│   └── nvim/                     btw.lua, syntax/btw.vim
└── demo/                         roast.btw, bigo.btw, fizzbuzz.btw (written Sunday morning)
```

# 3. CLI

| Command                           | What it does                                                                                                                       | Exit code                                                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `btw check FILE`                  | Lex, parse, check, Big O, suppression. Prints diagnostics with `--format pretty` (default) or `--format short` (tests).            | 0 with no errors (warnings are fine), 1 with errors, 2 for usage or file errors |
| `btw run FILE`                    | Check, then interpret if there are no errors. Diagnostics go to stderr.                                                            | The program's exit code, or 1 for compile errors                                |
| `btw build FILE -o OUT`           | Check, generate assembly, assemble and link with gcc. `-o` defaults to the file name without `.btw`. `--keep-asm` also writes `OUT.s`. | 0 ok, 1 compile errors (E501 included), 3 when gcc fails (E502)            |
| `btw asm FILE`                    | Print the generated assembly. `--annotate` adds source-line comments.                                                              | 0 or 1                                                                          |
| `btw lsp`                         | Start the language server on stdio, same as `btw-lsp`                                                                              | none                                                                            |
| `btw tokens FILE`, `btw parse FILE` | Debug dumps for agents: one token per line, or an indented AST with spans                                                        | 0                                                                               |

Short format, one diagnostic per line (golden tests strip the path):

```
tests/golden/p0_e404_undeclared_var.btw:4:17: error[E404]: Error 404: variable `x` not found. Did you forget to `npm install` it?
```

Pretty format, the default and the one in the demo:

```
error[E404]: Error 404: variable `x` not found. Did you forget to `npm install` it?
  --> tests/golden/p0_e404_undeclared_var.btw:4:17
   |
 4 |     console.log x
   |                 ^
```

- Underline the whole span with carets. Print a `help:` line for E403 and E417.
- P2: a summary line from the roast backlog ("build failed: 2 errors, 1 warning. Skill issue.").
- Colors only when stdout is a terminal and `NO_COLOR` isn't set. Never in short format.

# 4. Core types

> These three files (`span.py`, `diagnostics.py`, `ast.py`) are the contract every agent codes against. They're on main; don't edit them.

## 4.1 Positions

| Type | Fields                                                                                        |
| ---- | --------------------------------------------------------------------------------------------- |
| Pos  | `line` (0-based), `col` (0-based, in UTF-16 code units)                                       |
| Span | `start` and `end` positions, end exclusive. Helpers: does it contain a position, and merge two spans. |

## 4.2 Diagnostics

| Field      | Type                           | Notes                                                                                                   |
| ---------- | ------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `code`     | string                         | Like "E404" or "W508"                                                                                   |
| `severity` | ERROR or WARNING               | Soft errors are ERROR with `soft` set                                                                   |
| `message`  | string                         | Exact text from the Language Spec catalog                                                               |
| `span`     | Span                           |                                                                                                         |
| `soft`     | bool                           | True for E403, E417 and every warning, meaning suppressible                                             |
| `related`  | list of span and message pairs | P2, sent as LSP relatedInformation                                                                      |
| `fixes`    | list of Fix                    | P2 quick fixes. A Fix is a `title` plus a list of `edits`, each an Edit: a `span` and its replacement `text`. |
| `help`     | optional string                | Printed by the CLI in pretty mode                                                                       |

## 4.3 Tokens and comments

```
keywords    ARCH SERVE LOCALHOST WQ NPM_INSTALL_G NPM_INSTALL SUDO GIT_PUSH_FORCE
            GIT_PUSH_NO_FORCE GIT_REVERT GIT_LOG CONSOLE_LOG VIBE_CHECK SKILL_ISSUE
            DOOMSCROLL TOUCH_GRASS MICROSERVICE SHIP_IT LGTM NOT_FOUND
values      IDENT INT STRING
operators   PLUS MINUS STAR SLASH PERCENT EQ_EQ BANG_EQ LT LE GT GE
            AND_AND OR_OR BANG EQ PIPE CARET
punctuation LPAREN RPAREN LBRACE RBRACE COMMA
structure   NEWLINE EOF ERROR
```

- **Token:** `kind`, `text` (the raw lexeme), `span`, and `value` (the number for INT, the port for `LOCALHOST`, the unescaped text for STRING).
- **Comment:** `kind` (TODO, WOMM or BAD), `text`, `span`.
- **Lexer output:** tokens ending in EOF, comments, diagnostics. The lexer never raises.

## 4.4 AST

Every node has a keyword-only `span`, so node fields stay positional: `IntLit(42, span=s)`. The checker fills `ty` on expression nodes and `sym` on Var, Call and Ident nodes.

| Node                   | Fields                                                        | Notes                                                                                     |
| ---------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Program                | `items`, `has_arch`, `wq_span`, `trailing_span`, `comments`   | `trailing_span` covers everything after `:wq`, for E410                                   |
| GlobalDecl             | `name` (Ident), `is_const`, `value`                           |                                                                                           |
| Microservice           | `name`, `params` (list of Ident), `big_o` (or none), `body`   |                                                                                           |
| BigO                   | `degree` (int or none), `var`, `text`                         | `degree` none means unverifiable. `text` is the raw source between the parens.            |
| Serve                  | `port`, `body`                                                |                                                                                           |
| Block                  | `stmts`                                                       |                                                                                           |
| VarDecl                | `name`, `is_const`, `value`                                   | `is_const` inside a block is reported by the checker (E405)                               |
| Assign                 | `name` (Var), `value`, `sudo`                                 | The target is a use, so it's a Var and gets `sym`                                         |
| If                     | `cond`, `then` (Block), `else_` (Block, If, or none)          |                                                                                           |
| While                  | `cond`, `body`                                                |                                                                                           |
| Break                  | none                                                          |                                                                                           |
| Return                 | `value` (or none)                                             |                                                                                           |
| Print                  | `value`                                                       |                                                                                           |
| Revert                 | `name` (Var), `sudo`                                          | P2                                                                                        |
| Log                    | `name` (Var)                                                  | P2                                                                                        |
| ExprStmt               | `expr`                                                        |                                                                                           |
| IntLit, BoolLit, StrLit | `value`                                                      | StrLit is already unescaped                                                               |
| Var                    | `name`                                                        | gets `sym`                                                                                |
| Unary                  | `op`, `operand`                                               |                                                                                           |
| Binary                 | `op`, `left`, `right`                                         | Includes `&&` and `\|\|`                                                                  |
| Call                   | `callee` (Ident), `args`                                      | Pipes desugar into Call and Print. Gets `sym`.                                            |
| ErrorExpr              | none                                                          | Parser placeholder. Its type is UNKNOWN.                                                  |
| Ident                  | `name`                                                        | Names at declaration sites and Call callees. Gets `sym`, so the interpreter can key declarations and parameters by Symbol. |

## 4.5 Symbols and types

| Symbol field | Meaning                                                               |
| ------------ | --------------------------------------------------------------------- |
| `name`       |                                                                       |
| `kind`       | local, param, global, const or microservice                           |
| `ty`         | NUMBER or BOOLEAN (a microservice's is its return type, always NUMBER) |
| `decl_span`  | For hover, go to definition and related information                   |
| `owner`      | The microservice's name, "serve" or "global"                          |
| `arity`      | Microservices only                                                    |
| `tracked`    | Used by `git revert` or `git log` (P2)                                |
| `slot`       | Frame slot index, filled in by the codegen for locals and params      |

Types: NUMBER, BOOLEAN, STRING, UNKNOWN, defined as `Type` in `ast.py`. UNKNOWN never produces a type error.

# 5. Lexer

- One pass with a cursor, keeping line and column (UTF-16 units) as it goes.
- At each position, try in this order: spaces and tabs (skip); newline (emit NEWLINE unless the paren depth is above 0); a `//` comment (record it, skip to the end of the line); the multi-word keyword table, longest first, with the word-boundary check; `localhost:` plus digits; `:wq`; a number (then the 404 rule, leading zeros and overflow); a string; an identifier (then the single-word keyword and reserved-word check); operators, longest first. Anything else becomes an ERROR token plus E400 "Unexpected character `@`."
- Keyword matching goes word by word and allows any run of spaces or tabs between words. `npm install -g` must be tried before `npm install`, and `git push --force` before plain `git push`.
- It never raises. Bad input becomes ERROR tokens with diagnostics, and lexing continues.

# 6. Parser

- Recursive descent for statements; precedence climbing or Pratt parsing for expressions. matklad's two articles on the parent page are the references.
- It never raises and always returns a Program, however broken the input.
- **Recovery inside blocks:** on an unexpected token, emit one E400, skip tokens up to a NEWLINE or a `}` (without consuming the `}`), and carry on. At top level, skip to the next line that starts with `microservice`, `serve`, `npm install` or `:wq`.
- **Missing expression:** insert an ErrorExpr whose span is where the expression should have been. The declaration still happens, so there's no E404 cascade. This deserves its own golden test.
- **Missing `}` at the end of the file:** E400 "Syntax error: expected `}`, found end of file." Then close every open block.
- At most one E400 per statement.
- Else lookahead, `ship it` without a value, and Big O annotations: as specified in Language Spec §3.
- The arch line, `:wq` and trailing tokens are recorded on Program and reported by the checker. The one exception is E408: with no `:wq` at all, the parser reports it on the last token that isn't NEWLINE or EOF (Language Spec §4).
- Pipes (P2) desugar here, and each desugared call keeps its stage's span.

# 7. Checker passes, in order

1. **Structure:** E426, E410, E503, E409 for extra `serve` blocks, W208 (P2).
2. **Hoisting:** collect globals and microservices. E409 for duplicates and repeated parameter names, E413 for 7 or more parameters.
3. **Global initializers** in source order: only earlier globals are visible, calls are E405 (postinstall), strings are E415.
4. **Bodies:** walk each microservice and the `serve` block with a scope stack. Resolve names (E404, E409, E405), compute types (E418, E415, E422), apply sudo rules (E403, W100), track loop context (E405 for `touch grass`, W509), and flag unreachable code (W410) and useless expressions (W204).
5. **History targets (P2):** mark symbols as tracked; E405 on microservice params and locals.
6. **Big O** (`bigo.py`): E417, W417, W102, W508, W203.
7. **Comments:** E406 for BAD comments, E429 for every TODO past the fifth.
8. **Suppression** (`suppress.py`, P2): apply works-on-my-machine to everything collected so far, then add W200 or W304.
9. **Finish:** sort by line, column and code, and drop exact duplicates.

# 8. Big O implementation notes

- Resolve calls by name straight against the list of microservices, so this module doesn't depend on the checker. Unknown names are ignored.
- Memoized depth-first search with three states per microservice: unvisited, in progress, done. Reaching an in-progress microservice means a cycle: mark everything on the current path from it as UNKNOWN. P0 only needs the self-call check.
- A degree is a pair (poly, log), so plain tuple comparison orders them. The trip count of each doomscroll (Language Spec 9.1) needs the statement before it and the names declared so far, so the walk tracks the parameters and locals in scope instead of asking the checker.
- The parser classifies only `1`, `n` and `n^k` into `BigO.degree`. The log forms leave it none, and `bigo.py` reads them from `BigO.text`.
- While computing degrees, also return the span of the innermost doomscroll on the deepest path. It feeds the related information and the hover ("2 nested doomscrolls").
- Expose `infer(program)` for hover and inlay hints, `check_bigo(program)` for diagnostics, and `format_complexity(degree, var)`.

# 9. Interpreter

- Input is a checked Program with no errors (warnings are fine). It's also the oracle for differential tests, so correctness beats speed.
- Values are Python ints (always wrapped) and bools. Strings only appear in Print.
- The environment is one dict per call frame, keyed by Symbol. Every declaration has its own Symbol, so no scope logic is needed at runtime.
- Break and return are small exception classes (or result flags).
- Arithmetic helpers: a wrap function that maps any integer into the signed 64-bit range; division that truncates toward zero; remainder equal to a minus b times the truncated quotient. Test them against Language Spec §5.
- Depth counter: increment on microservice entry, decrement on exit, runtime error above 1,000. Call `sys.setrecursionlimit(50_000)` at startup.
- Runtime errors: flush stdout, write the exact message to stderr, return the exit code.
- History (P2): a dict from Symbol to a list capped at 16 entries.

# 10. Native codegen

## 10.1 Pipeline

`gen(program, symbols)` returns the text of one `.s` file. The driver writes it to a temp directory, runs `gcc -o OUT prog.s runtime/btw_rt.c`, and reports E502 with gcc's stderr if that fails. Unsupported constructs produce E501 before any assembly is written.

## 10.2 Output layout

```
        .intel_syntax noprefix

        .section .rodata
.Lstr0: .string "FizzBuzz"          one per string literal, and one per tracked variable's name

        .data
btw_g_LIMIT:  .quad 0               one per global or constant
btw_depth:    .quad 0               call depth counter

        .text
        .globl main
main:                               prologue, global initializers, serve body, epilogue
btw_fn_total:                       one function per microservice

        .section .note.GNU-stack,"",@progbits
```

## 10.3 Names, frames and registers

- User microservices are `btw_fn_NAME`, globals and constants are `btw_g_NAME`, labels are `.L` plus a kind plus a counter (`.Lelse3`, `.Lloop4`, `.Lloop4_end`). The prefixes stop user names from colliding with libc's `main`, `printf` or `exit`.
- Frame: `push rbp`, `mov rbp, rsp`, `sub rsp, FRAME`. FRAME is 8 times the number of slots (parameters plus every local declared anywhere in the function), rounded up to a multiple of 16. Slot k lives at `[rbp - 8*(k+1)]`.
- Parameters arrive in `rdi`, `rsi`, `rdx`, `rcx`, `r8`, `r9` and are copied into slots 0 to 5 at entry.
- Epilogue: a `.Lret_NAME` label, then `leave` and `ret`. `main` uses the same frame shape; `xor eax, eax` before its epilogue gives exit code 0.
- Only `rax`, `rcx`, `rdx` and the argument registers are used, and nothing stays in a register across a call. Callee-saved registers are never touched, so nothing needs saving.

## 10.4 Expressions (stack machine)

Every expression leaves exactly one 8-byte value pushed. At every statement boundary the temporary stack is empty.

| Construct                  | Lowering                                                                                                                                                                                                                         |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Number literal             | `mov rax, IMM` then `push rax`                                                                                                                                                                                                   |
| `LGTM`, `404`              | `push 1`, `push 0`                                                                                                                                                                                                               |
| Local or parameter         | `push qword ptr [rbp - OFF]`                                                                                                                                                                                                     |
| Global or constant         | `push qword ptr [rip + btw_g_NAME]`                                                                                                                                                                                              |
| `a + b`, `a - b`, `a * b`  | Evaluate a, evaluate b, `pop rcx`, `pop rax`, then `add rax, rcx`, `sub rax, rcx` or `imul rax, rcx`, then `push rax`                                                                                                            |
| `a / b`, `a % b`           | Evaluate a and b, `pop rcx`, `pop rax`, `test rcx, rcx`, `jz` to the zero handler, `cmp rcx, -1`: if equal `neg rax` (`/`) or `xor eax, eax` (`%`), else `cqo`, `idiv rcx` (`%` adds `mov rax, rdx`), then `push rax`            |
| Comparisons                | `pop rcx`, `pop rax`, `cmp rax, rcx`, then `setl`, `setle`, `setg`, `setge`, `sete` or `setne` into `al`, `movzx eax, al`, `push rax`                                                                                            |
| `-a`                       | `pop rax`, `neg rax`, `push rax`                                                                                                                                                                                                 |
| `!a`                       | `pop rax`, `xor rax, 1`, `push rax`                                                                                                                                                                                              |
| `a && b`                   | Evaluate a, `pop rax`, `test rax, rax`, `jz .LfalseN`, evaluate b, `jmp .LendN`, then `.LfalseN:` with `push 0`, then `.LendN:`. Reset the static depth counter at the false label so both paths end with exactly one value pushed. |
| `a \|\| b`                 | The mirror image, with `jnz .LtrueN` and `push 1`                                                                                                                                                                                |
| `f(a, b)`                  | Evaluate the arguments left to right (each pushes), pop them into the argument registers in reverse order, align (10.6), `call btw_fn_f`, undo the alignment, `push rax`                                                         |

## 10.5 Statements

| Statement                   | Lowering                                                                                                                                                                         |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| VarDecl, Assign             | Evaluate, `pop rax`, `mov` it into the slot or into `[rip + btw_g_NAME]`. Tracked variables (P2) also call the history runtime: reset on declaration, commit on assignment.      |
| Print a number              | Evaluate, `pop rdi`, `call btw_rt_print_int`                                                                                                                                     |
| Print a boolean             | Evaluate, `pop rdi`, `call btw_rt_print_bool`                                                                                                                                    |
| Print a string              | `lea rdi, [rip + .LstrN]`, `call btw_rt_print_str`                                                                                                                               |
| If                          | Evaluate the condition, `pop rax`, `test rax, rax`, `jz .LelseN`, then-block, `jmp .LendifN`, `.LelseN:` with the else-block, `.LendifN:`                                        |
| While                       | `.LloopN:`, condition, `pop rax`, `test rax, rax`, `jz .LloopN_end`, body, `jmp .LloopN`, `.LloopN_end:`                                                                         |
| Break                       | `jmp` to the innermost loop's end label. Safe because the temporary stack is empty at every statement boundary.                                                                  |
| Return                      | Evaluate into `rax` (or `xor eax, eax`), then `jmp .Lret_NAME`                                                                                                                   |
| ExprStmt                    | Evaluate, then `add rsp, 8` to drop the value                                                                                                                                    |
| Revert (P2)                 | `mov rdi, ID`, `lea rsi, [rip + NAME_STRING]`, call `btw_rt_hist_revert`, store `rax` into the variable                                                                          |
| Log (P2)                    | `mov rdi, ID`, `lea rsi, [rip + NAME_STRING]`, `mov rdx` to 1 for a boolean or 0 for a number, call `btw_rt_hist_log`                                                            |
| Microservice entry and exit | After the prologue: `inc qword ptr [rip + btw_depth]`, `cmp qword ptr [rip + btw_depth], 1000`, `jg` to the overflow handler. Before `leave`: `dec qword ptr [rip + btw_depth]`. No call, so `rax` survives. |

## 10.6 Stack alignment

At every function entry, `rsp` is 8 more than a multiple of 16 (the call pushed the return address). After `push rbp` it's aligned, and FRAME is a multiple of 16, so it's still aligned after the prologue. Each pushed temporary moves it by 8. The codegen tracks `depth`, the number of temporaries pushed right now, at compile time. Before every `call`: if `depth` is odd, emit `sub rsp, 8` before the call and `add rsp, 8` after it. Count `depth` after popping the arguments into registers. The two error handlers that never return (division by zero and stack overflow) simply do `and rsp, -16` before their call.

## 10.7 Runtime library (`runtime/btw_rt.c`)

| Function                                                | Behavior                                                                                                                            |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `void btw_rt_print_int(long v)`                         | printf with `%ld` and a newline                                                                                                     |
| `void btw_rt_print_bool(long v)`                        | puts `LGTM` or `404`                                                                                                                |
| `void btw_rt_print_str(const char *s)`                  | puts                                                                                                                                |
| `void btw_rt_div_zero(void)`                            | Flush stdout, print the exact division message to stderr, exit 1                                                                    |
| `void btw_rt_stack_overflow(void)`                      | Flush stdout, print the exact stack overflow message to stderr, exit 1                                                              |
| `void btw_rt_hist_reset(long id, long v)`               | The history becomes just v (P2)                                                                                                     |
| `void btw_rt_hist_commit(long id, long v)`              | Append v, dropping the oldest past 16 (P2)                                                                                          |
| `long btw_rt_hist_revert(long id, const char *name)`    | With fewer than 2 commits: flush stdout, print `fatal: bad revision 'NAME~1'`, exit 128. Otherwise append the previous value and return it (P2). |
| `void btw_rt_hist_log(long id, const char *name, long is_bool)` | Print the history newest first, in the Language Spec §9.3 format (P2)                                                       |

Up to 64 tracked variables, with ids assigned by the codegen. More than that is E501.

## 10.8 Gotchas

- `push` only takes a 32-bit sign-extended immediate. Load big numbers with `mov rax, IMM` (GNU as picks the 64-bit form) and push `rax`.
- `idiv` needs `cqo` first, and dividing by zero raises SIGFPE, hence the explicit check. The minimum number divided by -1 also traps, so a divisor of -1 skips `idiv`: `x / -1` is `neg` (which wraps the minimum to itself) and `x % -1` is 0 (Language Spec 10).
- `setcc` writes a single byte, so always `movzx eax, al` afterwards.
- Memory operands without a register to imply a size need `qword ptr`, as in `push qword ptr [rbp - 8]` and `inc qword ptr [rip + btw_depth]`.
- All data access is RIP-relative (`[rip + label]`, `lea rdi, [rip + .Lstr0]`). gcc links position-independent executables by default, and absolute addresses won't link.
- End every file with `.section .note.GNU-stack,"",@progbits`, or newer linkers warn about an executable stack.
- `rcx` and `rdx` get clobbered by calls and by `idiv`. The stack machine never keeps values in registers across either.
- In `.string` literals, escape backslash, double quote, newline and tab, and write any byte outside printable ASCII as a three-digit octal escape.
- Booleans are always exactly 0 or 1, which is what makes `xor rax, 1` correct for `!`.

## 10.9 Demo view

`btw asm --annotate` puts a comment such as `# line 6: vibe check (i % 15 == 0)` before each statement's code. In the demo, run it in a split terminal next to the source.

# 11. Language server

- Stdio transport. Entry point `btw-lsp` (and `btw lsp`).
- On didOpen, didChange and didSave: run lex, parse, check, Big O and suppression on the document text (never codegen) and publish diagnostics. The files are small, so no debouncing.
- Wrap every handler so an exception becomes a single E500 diagnostic instead of killing the server.
- Mapping: ERROR is severity 1 and WARNING is 2; `code` is "E404"; `source` is "btw"; the range comes from the span. `related` becomes relatedInformation (P2).
- **Hover (P1):** find the token or comment under the cursor. Keywords use the Language Spec §12 table, identifiers show symbol info, a microservice name shows its Big O verdict, and a TODO shows the debt counter. Return Markdown.
- **Code actions (P2):** for diagnostics in the requested range that carry fixes, return quickfix code actions with a workspace edit.
- **Completion (P2):** keyword snippets (for example, `doomscroll` expands to a loop with the cursor in the condition) and the names in scope.
- **Go to definition (P2):** the symbol's `decl_span`.
- **Semantic tokens (P2):** legend keyword, variable, function, parameter, number, string, comment, operator, plus a readonly modifier for constants. This gives Neovim highlighting without a syntax file.
- **Inlay hints (P2):** after the parameter list of an unannotated microservice, show the inferred O().
- **Never write to stdout.** It's the protocol channel, and one stray print corrupts the stream. Log to stderr.

# 12. Editors

## 12.1 VS Code extension

Lives in `editors/vscode`, runs with F5 (Extension Development Host), never gets published.

- `package.json`: a name such as `btw-lang`; `main` pointing at `extension.js`; `contributes.languages` with id `btw`, extension `.btw`, alias `btw` and the language configuration file; `contributes.grammars` for language `btw` with scope name `source.btw`; a `btw.serverPath` setting that defaults to `btw-lsp`. Recent VS Code activates on contributed languages automatically, and adding `onLanguage:btw` doesn't hurt.
- `extension.js`: create a LanguageClient whose server options run the configured command over stdio, with a document selector for `file` documents of language `btw`. Start it in activate, stop it in deactivate. Name its output channel "btw" so server stderr is easy to find.
- `language-configuration.json`: line comment `//`, bracket pairs for braces and parentheses, and auto-closing pairs for braces, parentheses and double quotes.
- Run `npm install` once in `editors/vscode` on each machine (needs Node).
- If VS Code can't find `btw-lsp` (apps launched from a dock don't always inherit your shell's PATH), start it with `code .` from a terminal or set `btw.serverPath` to an absolute path.

## 12.2 TextMate scopes

| Matches                                                       | Scope                                                                   |
| ------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `i use arch btw`, `serve`, `localhost:3000`, `:wq`            | keyword.control.directive.btw                                           |
| `vibe check`, `skill issue`, `doomscroll`, `touch grass`, `ship it` | keyword.control.btw                                               |
| `npm install -g`, `npm install`, `microservice`               | storage.type.btw                                                        |
| `git push --force`, `git revert`, `git log`, `sudo`           | keyword.other.btw                                                       |
| `console.log`                                                 | support.function.btw                                                    |
| `LGTM`, `404`                                                 | constant.language.btw                                                   |
| Other numbers                                                 | constant.numeric.btw                                                    |
| Strings                                                       | string.quoted.double.btw, with escapes as constant.character.escape.btw |
| Comments                                                      | comment.line.double-slash.btw                                           |
| The name after `microservice`                                 | `entity.name.function.btw`                                              |
| A Big O annotation after the parameter list                   | `entity.name.type.btw`                                                  |

Put the multi-word patterns first, allow any whitespace run between words, use word boundaries at both ends, and match `404` before generic numbers. These standard scopes pick up colors from VS Code's default themes.

## 12.3 Neovim

- Config: the snippet on the parent page (0.11+), saved as `editors/nvim/btw.lua`.
- Fallback highlighting: `syntax/btw.vim`, with keyword and match groups for the same categories linked to standard highlight groups (Conditional, Repeat, Keyword, Type, Statement, Function, Boolean, Number, String, Comment). About 15 minutes of work, and it covers highlighting until semantic tokens (P2) exist.
- Debugging: `:checkhealth vim.lsp` shows attached clients and the log path; `:lua =vim.lsp.get_clients()` lists running clients.

# 13. Testing

- **Golden tests are written at the event, not before.** Card A1 writes them from the Language Spec starting at 12:30, working out every expected output by hand. A human reviews every expected file before other agents rely on it: a wrong expectation gets copied into every component.
- **Layout:** one program per `tests/golden/NAME.btw`, plus sidecar files. Names start with the tier (`p0_`, `p1_`, `p2_`), and failing tests include the code they expect, like `p0_e404_undeclared_var`.

| File                   | Meaning                                                                                                                                                  |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NAME.btw`             | The program                                                                                                                                              |
| `NAME.diag`            | Expected `btw check --format short` output with the path stripped: `LINE:COL: severity[CODE]: message`, 1-based, sorted by position. Missing means no diagnostics. |
| `NAME.out`             | Expected stdout. The interpreter and the native binary must both match it byte for byte.                                                                 |
| `NAME.err`             | Expected stderr (runtime errors)                                                                                                                         |
| `NAME.exit`            | Expected exit code. Missing means 0.                                                                                                                     |
| None of out, err, exit | Check-only: the program is never executed (for example the infinite doomscroll)                                                                          |

- **Runner, per program:**
  1. Run `btw check --format short`, strip the path prefix, and compare with `.diag` (empty when missing).
  2. If the expected diagnostics contain any error, stop there.
  3. If `.out`, `.err` or `.exit` exists, run the interpreter with a 5-second timeout and compare stdout, stderr and the exit code.
  4. Native: build and run with a 5-second timeout and compare the same three. If the build reports E501, mark the case as an expected failure ("native: not yet") rather than a failure.
- **Options:** `--tier N` runs only tests whose prefix is pN or lower. `--bless` rewrites expectation files from the current output. Only a human runs `--bless`, after reading the diff.
- **Unit tests per component:** tricky lexer inputs, parser shapes (else on the next line, one-line blocks, precedence, recovery), Big O verdicts, the arithmetic helpers.
- **Differential testing is the codegen's safety net:** the interpreter is the reference, and every golden program with output must match it byte for byte.

# 14. What `CLAUDE.md` should cover

- **Source of truth:** `docs/SPEC.md`. When the spec is ambiguous or disagrees with a test, stop and ask instead of inventing behavior. Diagnostic messages must match the spec character for character.
- **Commands:** `uv sync`, the full test suite, a single golden test, the `--tier` option, and each `btw` subcommand from §3.
- **Hard rules:** don't edit the three contract files (`span.py`, `diagnostics.py`, `ast.py`); never edit expected-output files to make a test pass, and never run `--bless`; only touch the files your card owns; no randomness, network calls or new dependencies; commit small and run the tests before every commit; when blocked, write the question in a NOTES file and move on.
- **Python:** 3.12, dataclasses, match statements, type hints; 64-bit wrapping and truncating division (Language Spec §5).
- **pygls 2:** the gotchas from §1, and never writing to stdout.
- **Codegen:** the target from §10, the push-depth invariant, 16-byte alignment before every call, the symbol prefixes, and building plus comparing against the interpreter after every change.
