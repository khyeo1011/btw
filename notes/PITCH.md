# btw: pitch plan and demo scripts

The plan for presenting btw: what to show, in what order, the exact words, and
what to watch out for. Every number and every quoted message below was
re-checked against v0.4.0 on 2026-10-04 (1,778 tests passing), and the Two Sum
lines against the live playground. Re-check the timings on the demo laptop.

## The pitch in one line

**btw is a joke programming language with a real compiler.** The jokes are
the surface. Underneath are a type checker, a Big O checker that tests itself,
an interpreter, an x86-64 native backend, a language server and a browser
playground.

## What the judges should remember

1. **It's funny all the way down.** Every keyword, every error, every hover
   and even the generated assembly is a dev meme. Every error code is an HTTP
   status.
2. **It's a real compiler.** It builds a 14 KB native binary from assembly it
   writes itself, more than 1,000 times faster than the interpreter and with
   byte-for-byte identical output.
3. **It's built like serious software.** A 619-line spec with every message
   pinned down character for character, 1,778 tests, two backends tested
   against each other (and fuzzed), CI, releases, and editor support for VS
   Code and Neovim.

Keep coming back to the contrast: **a stupid idea, executed seriously.** That
contrast is the whole joke, and the whole pitch.

## The story: three acts and a twist

The intro promises three things, and the demo pays off each one with a real
feature:

| The intro says         | The demo shows                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------- |
| dependency hell        | Variables are `npm install`, constants are `npm install -g`, and changing one needs `sudo` |
| git panic              | Assignment is `git push --force`, and every variable has `git revert`, `git log` and `git blame` |
| imposter syndrome      | Two Sum: the Big O checker says "Skill issue", then doubts itself and load-tests its own verdict |
| **twist:** "is it even real?" | `btw build`: a native x86-64 binary, 1,000× faster, same bytes                  |

The twist is the moment the room stops laughing at the language and starts
taking the compiler seriously. Don't spend it early: no "native", "x86" or
"LSP" before the twist (VS Code squiggles in the cold open are fine; don't
explain them).

## Wow-factor inventory

Ranked by stage impact. "Laugh" is what gets the reaction; "Depth" is what
earns the points.

| #  | Moment                         | How to show it                                         | Laugh                                                                                     | Depth                                                                                                                                  |
| -- | ------------------------------ | ------------------------------------------------------ | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | Load test catches the checker  | `btw loadtest demo/bigo.btw grid 2>/dev/null`          | "The static checker was being optimistic. ... The PM has been notified."                  | Static inference plus measurement: counts steps for n = 8 to 1024 and fits ln(steps) against ln(n) by least squares. Deterministic.     |
| 2  | Native build                   | `btw build demo/fizzbuzz.btw -o fizzbuzz`, `ls -lh`    | "So it's a joke language. Surely it's interpreted?"                                       | Its own x86-64 codegen (no LLVM), System V calls, 16-byte stack alignment, a 160-line C runtime. 14 KB binary.                          |
| 3  | Same bytes, 1,000× faster      | `diff <(btw run X) <(./X) && echo identical`, `time ./bench` | "14 seconds. 12 milliseconds."                                                      | Differential testing: the 53 golden programs that run, plus 100 fuzzed ones per CI run, must match stdout, stderr and exit code on both backends. 3,000 fuzzed programs matched in the last check. |
| 4  | Big O roast                    | `btw check demo/bigo.btw`                              | "You said O(n), but this is O(n²). Skill issue." / "tell the PM it was always the plan" | Degree inference O(n^k log^j n) through calls, call-graph cycle detection for recursion, O(log n) detection for halving loops.          |
| 5  | The Two Sum challenge          | Playground Two Sum tab: pass 6/6, then claim `O(n)`    | "6/6 passed. LGTM, ship it. Accepted. Runtime: O(n²). Beats 0% of hash maps." then "You said O(n), but this is O(n²). Skill issue." and "Errors blocked the run." | No arrays or hash maps in btw, so O(n) can't be written, and the checker sees through the nested loops. The way out: admit O(n²), or `// works on my machine`. |
| 6  | Quick fix "Exit Vim"           | VS Code: delete `:wq`, then the light bulb             | "Error: program never exited. Classic Vim user."                                          | A real LSP server: diagnostics on every keystroke, hovers, quick fixes, completion, go to definition, semantic tokens, inlay hints.     |
| 7  | Assembly with jokes            | Playground: FizzBuzz, then **x86-64** above Output (CLI: `btw asm demo/fizzbuzz.btw --annotate`) | `jz .Lloop1_end  # 404: stop scrolling`                                     | Readable codegen: each source line above its instructions. The playground runs the real codegen on Pyodide, so judges need nothing installed. |
| 8  | `git blame` on a variable      | `btw run tests/golden/p2_git_blame.btw`                | Hover: "Find out which line made each commit. It was you."                                | Per-variable history (16 commits in a ring buffer), in the interpreter and in native code.                                             |
| 9  | 83 roasts in one file          | `btw check demo/roast.btw`, scroll                     | "Infinite doomscroll detected. Go touch grass." and 82 more                               | 51 exact messages under 31 codes. Parser error recovery, so one mistake gets one squiggle.                                             |
| 10 | Foreign keywords               | Type `if` in VS Code                                   | "`if` is a boomer conditional. Use `vibe check`." (and a quick fix)                       | 22 words from other languages caught without changing the meaning of any valid program.                                                |
| 11 | Runtime errors are real errors | `p0_runtime_stack_overflow`, `curl` at end of input    | "Stack overflow. Please search stackoverflow.com."                                        | The exit codes are the real ones: 128 like git, 52 and 8 like curl.                                                                     |
| 12 | Seven parameters               | Any microservice with 7 parameters                     | "That's not a microservice, that's a monolith."                                           | The joke is the ABI: System V passes six arguments in registers.                                                                        |
| 13 | Browser playground             | btw.sebastianyeo.dev, run the infinite doomscroll      | "Still running after 5 s, so the playground stopped it."                                  | The real compiler on Pyodide, in a Web Worker so an endless loop can't freeze the tab.                                                  |

Numbers to drop in passing: **1,778** tests, **109** golden programs, **83**
roasts in 148 lines, **51** error messages, **22** foreign keywords roasted,
**5** TODOs allowed per file, **1** runtime dependency.

## Comedy rules

- **Let the compiler tell the jokes.** Read the error message out loud,
  deadpan, word for word, then stop talking. The pause is where the laugh
  lands. Don't explain a joke.
- **Threes.** Dependency hell, git panic, imposter syndrome. Install Arch,
  Exit Vim, touch grass.
- **Callback at the end.** The first rule of btw is `i use arch btw`, so the
  last line of the pitch is "I use arch, btw."
- **Laugh first, then the fact.** Every joke is followed by one sentence of
  real engineering. The laugh buys attention; the sentence earns the score.
- **Make fun of yourself, never the audience.** "Skill issue" is aimed at
  you.

## Intro options

**A. The one you wrote (recommended for in person):**

> "While other teams spent 24 hours building corporate dashboards, I decided
> to build something that reflects the true essence of modern software
> engineering: dependency hell, git panic, and crushing imposter syndrome."

Bridge straight into the product: *"So I made it a programming language. It's
called btw."*

**B. Shorter, for a 1-minute slot or a booth:**

> "Most compilers tell you what's wrong with your code. Mine tells you what's
> wrong with you."

**C. Cold open, for the video:** a black terminal, `btw run hello.btw`, and
the only output is `Fatal: 'i use arch btw' not found. Are you on Windows?`
Hold one beat, cut to the title.

## In-person demo script (3 minutes)

**Stage layout:** VS Code (Extension Development Host) with
`demo/fizzbuzz.btw` open, and a terminal at 20 pt or larger in the repo with
the venv active. Every command is already in the shell history, so you only
press Up and Enter. Lines marked ✂ are the cut for a 2-minute slot.

**Timing:** the spoken lines below are about 505 words: 3:20 at 150 words a
minute before laughs, typing and app switches, so a full run is closer to
3:45, and Act 3 alone is 155 words for a 35-second slot. Rehearse with a timer.
For a hard 3:00, cut in this order: Act 2 (48 words), the `fizzbuzz.s` aside
in the twist (11), the help-line read in Act 3 (11), and the list at the start
of the close, keeping the playground and the QR code (15). That leaves about
420 words, so keep the pace up and let the screen carry the reads.

### 0:00 to 0:20 · Hook

**Say:** "While other teams spent 24 hours building corporate dashboards, I
decided to build something that reflects the true essence of modern software
engineering: dependency hell, git panic, and crushing imposter syndrome.
*(beat)* So I made it a programming language. It's called btw."

### 0:20 to 0:45 · The rules (VS Code)

**Do:** delete line 1 (`i use arch btw`) and hover the squiggle.

**Say:** "Rule one: every program starts with `i use arch btw`. If you forget:
*(read)* 'Fatal: i use arch btw not found. Are you on Windows?'"

**Do:** light bulb, **Install Arch**. Then delete `:wq` and hover.

**Say:** "Rule two: the only way out is `:wq`. *(read)* 'Error: program never
exited. Classic Vim user.' *(click **Exit Vim**)* Yes, there is a quick fix
called Exit Vim. Most requested feature in computing history."

### 0:45 to 1:10 · Act 1, dependency hell

**Do:** point at the FizzBuzz code, then run `btw run demo/fizzbuzz.btw`.

**Say:** "Variables are `npm install`, because every variable is a dependency.
Constants are `npm install -g`, and changing one needs `sudo`. If is
`vibe check`, else is `skill issue`, and loops are `doomscroll`. The only way
out of a doomscroll is `touch grass`. *(run)* And it runs. FizzBuzz, in
production, on localhost:3000."

### 1:10 to 1:30 · Act 2, git panic ✂

**Do:** `btw run tests/golden/p2_git_blame.btw`

**Say:** "Assignment is `git push --force`, because nobody has ever asked
before overwriting something. And because it's git, every variable has
history. `git revert` undoes a change as a new commit, and `git blame` tells
you which line made every value. The hover text ends with: 'It was you.'"

### 1:30 to 2:05 · Act 3, imposter syndrome

**Do:** switch to the playground's **Two Sum** tab. Your nested-loop solution
is already in it, with no SLA. Press Ctrl+Enter.

**Say:** "Nothing says imposter syndrome like a technical interview. So: Two
Sum. *(tests go green; read)* '6/6 passed. LGTM, ship it. Accepted. Runtime:
O(n²). Beats 0% of hash maps.' *(beat)* Everyone knows the interview answer is
O(n) with a hash map. btw doesn't have hash maps. Or arrays. But in btw you
write down the Big O of every function, so I'll just... claim O(n)."

**Do:** type `O(n)` after `twoSum(n, target)` and press Ctrl+Enter.

**Say:** "*(read)* 'You said O(n), but this is O(n²). Skill issue.' *(read the
help line)* 'try O(n²), then tell the PM it was always the plan.' And it won't
even run my tests. *(read)* 'Errors blocked the run.'"

**If the Wi-Fi is bad:** `btw check demo/bigo.btw` in the terminal gives the
same E417 on `pairs`. Skip the green tests and keep the lines from "In btw
you write down the Big O".

**Do:** `btw loadtest demo/bigo.btw grid 2>/dev/null`

**Say:** "But static analysis can be wrong, and my compiler knows it. It has
imposter syndrome too. So it load-tests itself: it runs the function from 8 to
1,024, counts every loop iteration and fits the curve. On this one, my checker
said O(n).
*(read)* 'The static checker was being optimistic. The PM has been notified.'
It's the only compiler I know that snitches on itself."

### 2:05 to 2:45 · The twist: is it even real?

**Say:** "Now you're thinking: cute, it's a Python script with jokes.
*(beat)* That's what my imposter syndrome said too. So I wrote a native
backend."

**Do:** `btw build demo/fizzbuzz.btw -o fizzbuzz && ls -lh fizzbuzz && ./fizzbuzz`

**Say:** "btw compiles to x86-64 assembly that it writes itself. No LLVM; gcc
just links it. That's a 14-kilobyte binary. ✂ *(show `fizzbuzz.s`)* Even the
assembly has jokes: 'jump if zero: 404, stop scrolling.'"

**Do:** `time ./bench`

**Say:** "On a prime-counting benchmark the interpreter takes 14 seconds. The
binary takes 12 milliseconds. More than a thousand times faster. And it's the
same output, byte for byte: on every pull request, 53 test programs and 100
random ones run through both backends and have to match exactly. 1,778 tests
in all."

### 2:45 to 3:00 · Close

**Do:** put up the QR code (`docs/qr.png`). It opens the playground's Two Sum
tab.

**Say:** "A Big O checker that checks itself, a native compiler, a language
server, and a playground you can try right now at btw.sebastianyeo.dev. Go
solve Two Sum in it. Claim O(n). I dare you. Zero dashboards. It's a joke
language with a real compiler. Thank you. *(walk off, stop, turn back)* Oh,
and I use arch, btw."

### Got 5 minutes? Add these

- **The roast file** (after Act 1): `btw check demo/roast.btw`, scroll fast.
  "148 lines, 83 roasts. Every error code is an HTTP status. Type errors are
  418, I'm a teapot. Six TODOs is 429, Too Many Requests: 'technical debt
  limit exceeded. Finish something.'"
- **Foreign keywords** (in VS Code): type `if (x > 0) {`. "'`if` is a boomer
  conditional. Use `vibe check`.' It knows 22 words from other languages."
- **The cheat code** (after Act 3): put `// works on my machine` above the
  dishonest `twoSum`. 6/6 again, with one warning left behind: '200 OK (on my
  machine): 1 problem suppressed.' "Interviewers hate this one trick. Hard
  errors can't be suppressed. Only your conscience."
- **The playground** (before the close): run the infinite doomscroll example.
  "It runs the real compiler in your browser, and it won't let you doomscroll
  forever."
- **The monolith:** a microservice with seven parameters. "'That's not a
  microservice, that's a monolith.' That's not just a joke: x86-64 passes six
  arguments in registers."

## Booth version (30 seconds)

For judges walking past, with `demo/bigo.btw` open in VS Code:

> "btw is a joke programming language with a real compiler. *(hover the E417
> squiggle)* You write the Big O of your function, and it says 'You said O(n),
> but this is O(n²). Skill issue.' *(terminal: `btw build`, run)* And it
> compiles to a native x86-64 binary, a thousand times faster than the
> interpreter. Want to get roasted? Type anything."

Then open the Two Sum challenge in the playground and hand them the keyboard:
"Solve Two Sum. Bonus points if you can get it past the Big O checker."
Getting roasted personally is the best demo there is, and it's the
interview question everyone has trauma about.

## Video demo script (2 minutes)

Record at 1080p with the terminal at 20 pt or more. Cut hard, zoom on every
message being read, and caption every punchline so it works muted. The video
can do two things the stage can't: the speed race and close-ups.

| Time      | Picture                                                                                                       | Voiceover                                                                                                                                                         | On screen                                    |
| --------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| 0:00–0:05 | Black terminal. Type `btw run hello.btw`. Output: E426.                                                       | *(silence, keyboard sounds)*                                                                                                                                      | Zoom on "Are you on Windows?"                |
| 0:05–0:08 | Title card.                                                                                                   | *(none)*                                                                                                                                                          | **btw**, a joke language with a real compiler |
| 0:08–0:20 | Fast montage of roasts scrolling by (`btw check demo/roast.btw`).                                             | "While other teams spent 24 hours building corporate dashboards, I built something about the true essence of software engineering: dependency hell, git panic, and crushing imposter syndrome." | `83 roasts. 148 lines.`                      |
| 0:20–0:35 | FizzBuzz in VS Code. Each keyword gets a label as it's named.                                                 | "Variables are `npm install`. Assignment is `git push --force`. If is `vibe check`, else is `skill issue`, loops are `doomscroll`, and you get out with `touch grass`." | `npm install` = let, `vibe check` = if, ... |
| 0:35–0:50 | Delete `:wq`, hover, light bulb, **Exit Vim**. Then type `if`, hover, **Use vibe check**.                     | "It has a real language server, with quick fixes. This one is called Exit Vim."                                                                                    | Zoom on "Classic Vim user."                  |
| 0:50–1:05 | Playground Two Sum tab: 6/6 green, type `O(n)`, Ctrl+Enter, E417 and "Errors blocked the run." Then `btw loadtest demo/bigo.btw grid 2>/dev/null`. | "Write down your Big O, and it checks you. Even on Two Sum. Then, because it has imposter syndrome too, it load-tests itself, and snitches when its own checker was wrong." | "Skill issue." then "The PM has been notified." |
| 1:05–1:12 | Black screen, white text.                                                                                     | "But is it even a real language?"                                                                                                                                 | *is it even real?*                           |
| 1:12–1:35 | Split screen. Left: `time btw run demo/bench.btw`. Right: `btw build` then `time ./bench`. The right side finishes at once; speed up the left side with a running clock. | "It compiles to x86-64. No LLVM: it writes the assembly itself. The interpreter takes 14 seconds. The binary takes 12 milliseconds."                             | `1,000× faster`                              |
| 1:35–1:45 | `diff <(btw run demo/fizzbuzz.btw) <(./fizzbuzz) && echo identical`, then zoom into `fizzbuzz.s` on `# 404: stop scrolling`. | "Same bytes, every time. Even the assembly has jokes."                                                                                                             | `0 bytes different`                          |
| 1:45–1:53 | Quick cuts: `1778 passed`, the playground in a browser, a Neovim squiggle.                                    | "1,778 tests. Runs in your browser. Works in VS Code and Neovim."                                                                                                 | `btw.sebastianyeo.dev`                       |
| 1:53–2:00 | End card.                                                                                                     | "It's a joke language with a real compiler. I use arch, btw."                                                                                                     | GitHub URL, playground URL, the QR code (`docs/qr.png`), *Try Two Sum. Claim O(n). I dare you.* |

**Capture list:** the E426 cold open, the roast scroll, the VS Code quick
fixes (Install Arch, Exit Vim, Use vibe check, Update SLA), the inlay hint
with the inferred Big O, the load test, both halves of the race, the `diff`,
`fizzbuzz.s`, `pytest` finishing, the playground, and Neovim. Record the
VS Code quick fixes as a GIF too; it's the screenshot the README is missing.

## Q&A prep

| They ask                                   | Answer                                                                                                                                                                                                                       |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Is the Big O checker correct?              | "No, and it says so. It's a heuristic: it counts nested loops and follows calls, and recursion is O(?). That's exactly why `btw loadtest` exists: it measures, and tells you when the static answer was wrong."           |
| How do you know the two backends agree?    | "Differential testing. The interpreter is the reference. Every golden program that runs is also built natively and must match the same expected stdout, stderr and exit code byte for byte. A seeded fuzzer adds random well-typed programs: 100 on every PR, and 3,000 matched in the last check. CI does it on every PR." |
| 1,000× faster than a Python interpreter isn't a fair fight. How does it compare to C? | "Fair. The same benchmark written in C takes 4.0 ms with `gcc -O2` and 5.2 ms at `-O0`; btw's binary takes 12.5 ms. So it's within about 3× of optimized C, from a stack machine with no register allocation." (Measured on the Ryzen, mean of 50 runs.) |
| Why a stack machine, no register allocation? | "Correctness first. Every expression pushes exactly one value; the generator counts pushes, asserts it, and uses the count to keep the stack 16-byte aligned for every call. There's a test that injects a probe into the runtime and fails on any misaligned call, and a test that the probe really catches one. It's still 1,000× faster than the interpreter." |
| Why Python?                                | "Iteration speed. The native backend is where the speed comes from, so the compiler itself doesn't need to be fast. It also lets the same compiler run in the browser on Pyodide."                                           |
| What about strings, arrays, the heap?      | "Strings exist only as literals for `console.log`; everything else is a 64-bit integer. That was a deliberate scope call to get a native backend done in a hackathon. Arrays are a TODO, and you only get five of those." |
| How does integer math match in both?       | "Two's complement wrapping, `/` truncates toward zero, `%` follows the left operand, like x86 `idiv`. Python does neither by default, so the interpreter emulates it. Even the minimum number divided by -1, which crashes `idiv`, wraps in both." |
| Can you solve Two Sum in O(n)?             | "No. No hash maps, no arrays: the input is a microservice. Your options are an honest O(n²), or `// works on my machine`, which lets it run and leaves a W200 so everyone knows what you did."                            |
| How many people? How long?                 | *(Fill in.)* The git history has 49 merged pull requests (#1 to #50) between Oct 3, 12:10 and Oct 4, 08:06.                                                                                                                  |
| Did you use AI?                            | Answer head-on: the repo makes it visible (`CLAUDE.md`, `notes/`, and Claude co-author lines on most commits). If it matches how you worked, the strong version is the process: "I wrote the language spec, with every error message exact, and golden tests by hand. Those were the contract: agents implemented one component each against frozen interface files, and the tests decided what was done." Fill in the README's AI usage section to match. |
| Can I use it for real work?                | "Please don't. But it has a release with standalone binaries, so technically you can."                                                                                                                                       |
| What was the hardest part?                 | *(Your own story.)* Good candidates: matching the interpreter and native output byte for byte, stack alignment, or error recovery that gives one squiggle per mistake instead of a red file.                                 |

## Before you go on stage

**Pre-flight** (in the repo, the day of the demo):

```
uv sync && source .venv/bin/activate      # puts btw on PATH
btw build demo/fizzbuzz.btw -o fizzbuzz   # build ahead of time (don't commit them)
btw build demo/bench.btw -o bench
btw asm demo/fizzbuzz.btw --annotate > fizzbuzz.s
cp tests/golden/p0_e426_missing_arch.btw hello.btw   # the video cold open
time ./bench                              # the "12 milliseconds"
time btw run demo/bench.btw               # once, offstage: the "14 seconds"
uv run pytest -q                          # the "1778 passed" shot
```

**Landmines found while preparing this:**

- **At the booth, steer people to `if`, not `break`.** `if`, `while`, `let`,
  `print` and `return x` all get roasted, but a bare `break` or `return` on
  its own line gets a plain "Error 404: variable `break` not found" (a spec
  gap, in the bug report).
- **Don't paste generated code into the playground.** A sum of 332 or more
  terms, or 200 nested blocks, gives E500 ("It works on my machine...")
  everywhere: CLI, playground and editor (bug 2 in the bug report).
- **The VS Code hover shows two things.** On the E426 squiggle, the popup
  also shows the hover text for what's now on line 1 (`serve`'s "main().
  Every program is secretly a dev server."). Read the top line, the
  diagnostic.
- **The cold open prints a second punchline.** `btw run hello.btw` prints the
  E426 block, then "build failed: 1 error. Skill issue." Zoom on both, or cut
  after the first.
- **Use `2>/dev/null` on the load test.** `btw loadtest demo/bigo.btw grid`
  prints the file's six diagnostics on stderr before the measurements, which
  buries the punchline.
- **`btw check demo/bigo.btw` exits 1** (E417 is on purpose), so `&&` after it
  stops the chain. Use `;`.
- **Time the interpreter on the demo laptop.** The 14.9 s is from a Ryzen 9
  9950X3D desktop (three runs: 14.7 to 15.3 s); a cloud VM took 52 s. If it's over 20 s, never run it
  live: quote the number, run only the binary, and save the race for the
  video.
- **The playground needs the internet** (Pyodide loads from a CDN), and
  Act 3 runs in it. Before you start, open the Two Sum tab, paste your
  nested-loop solution without an SLA, and run the tests once so Pyodide is
  loaded and they're green. Don't reload it. If the Wi-Fi is bad, use the
  offline line in Act 3. Everything else works offline.
- **VS Code has to find `btw-lsp`.** Launch with `uv run code editors/vscode`,
  press F5, open `demo/fizzbuzz.btw` in the new window, and check that a
  squiggle appears before you walk up.
- **Two Sum, checked against the tab's own test harness** (all six tests,
  with a nested-loop `twoSum`): no SLA gives W102 "Inferred: O(n²)" and 6/6;
  `O(n)` gives E417 and "Errors blocked the run."; `O(n^2)` gives 6/6 and
  "LGTM, ship it."; `// works on my machine` above an `O(n)` `twoSum` gives
  W200 and 6/6. The empty starter gives W102 "Inferred: O(1)" and 0/6. Every
  6/6 with the nested loops also prints "Accepted. Runtime: O(n²). Beats 0% of
  hash maps." (all of these re-checked on the live site, about 20 ms a run).
- **Have the video ready** as a fallback if the laptop, the projector or the
  Wi-Fi fails.

**Repo polish judges will see:**

- The README screenshot is in place (`docs/screenshot.png`).
- The README's "AI usage" section is written. Give it a grammar pass ("for
  bulk of the implementation", "AI's were given"): judges will read it.
- The QR code (`docs/qr.png`) opens the playground's Two Sum tab. Put it on
  the closing slide and the video's end card.

## Where the project stands

An honest assessment, to choose what to show and what to be ready for.

**Strengths (show these):**

- **Complete pipeline.** Lexer, recursive-descent and Pratt parser with error
  recovery, semantic checker, Big O inference, tree-walking interpreter,
  x86-64 codegen with a C runtime, load tester, language server, VS Code and
  Neovim support, browser playground, standalone ELF releases. All of it
  works today, and all of it is tested.
- **Spec-driven.** `docs/SPEC.md` pins down every message character for
  character, and the golden tests were derived from it by hand. Each
  component has a notes file recording the decisions where the spec was
  silent. That's unusual rigor for a hackathon, and worth one sentence in
  Q&A.
- **Testing depth.** 1,778 tests, differential testing across both backends
  (golden programs plus a seeded fuzzer; 3,000 random programs matched), and
  a stack-alignment probe that is itself tested.
- **Jokes grounded in real behavior.** git's exit code 128, curl's 52 and 8,
  the six System V argument registers, HTTP status codes. Judges who know
  these will notice.
- **Determinism.** No randomness; the load test counts steps instead of
  timing them, so its verdict is the same on every machine.

**Weak spots (be ready, don't hide them):**

- The Big O checker is a heuristic (documented in the spec as "a teaching
  heuristic, not a proof"). Turn it into the load-test story.
- No optimizations or register allocation in the codegen. Turn it into the
  correctness story.
- Native builds are Linux x86-64 only. Judges on a Mac can use the
  playground.
- End-to-end testing on 2026-10-04 found three bugs, none on the demo path:
  `btw build` can overwrite a source file that has no `.btw` extension, a
  332-term expression or 200 nested blocks give E500, and `===` in a
  condition adds an extra E418. Also one spec gap: a bare `break` misses its
  roast. Details and repros are in the bug report.
