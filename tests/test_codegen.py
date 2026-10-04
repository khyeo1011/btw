import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from btw import codegen, driver
from btw.span import Pos, Span

GOLDEN = Path(__file__).parent / "golden"
needs_gcc = pytest.mark.skipif(shutil.which("gcc") is None, reason="native: gcc not found")


def program(*body: str, top: tuple[str, ...] = ()) -> str:
    lines = ["i use arch btw", *top, "serve localhost:3000 {", *body, "}", ":wq"]
    return "\n".join(lines) + "\n"


def asm(source: str, annotate: bool = False):
    return driver.asm(source, "test.btw", annotate)


def interpret(source: str, stdin: bytes = b"") -> tuple[str, str, int]:
    stdout, stderr = io.StringIO(), io.StringIO()
    diagnostics, code = driver.run(source, "test.btw", stdout, stderr, io.BytesIO(stdin))
    assert code is not None, diagnostics
    return stdout.getvalue(), stderr.getvalue(), code & 0xFF


def native(source: str, tmp_path: Path, stdin: bytes = b"") -> tuple[str, str, int]:
    binary = tmp_path / "prog"
    diagnostics, gcc_stderr = driver.build(source, "test.btw", binary)
    assert gcc_stderr is None, gcc_stderr
    assert not driver.has_errors(diagnostics), diagnostics
    result = subprocess.run([binary], input=stdin, capture_output=True, timeout=5)
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# E501: constructs the native backend doesn't build yet


def e501s(source: str) -> list[tuple[str, Span]]:
    diagnostics, text = asm(source)
    assert text is None
    return [(d.message, d.span) for d in diagnostics if d.code == "E501"]


def too_many_histories() -> str:
    """65 tracked variables: one more than the runtime's history table."""
    return program(
        *[f"    npm install v{k} = {k}" for k in range(65)],
        *[f"    git log v{k}" for k in range(65)],
        "    git revert v64",
        "    git log v0",
        "    git blame v64",
    )


def test_history_past_64_variables_is_e501():
    revert = "Not implemented: `git revert` in native builds. Try `btw run`."
    log = "Not implemented: `git log` in native builds. Try `btw run`."
    blame = "Not implemented: `git blame` in native builds. Try `btw run`."
    assert e501s(too_many_histories()) == [
        (log, Span(Pos(131, 4), Pos(131, 15))),
        (revert, Span(Pos(132, 4), Pos(132, 18))),
        (blame, Span(Pos(134, 4), Pos(134, 17))),
    ]


def test_history_up_to_64_variables_builds():
    source = program(
        *[f"    npm install v{k} = {k}" for k in range(64)],
        *[f"    git log v{k}" for k in range(64)],
    )
    _, text = asm(source)
    assert "        mov     rdi, 63\n" in text and "rdi, 64" not in text


def test_e501_is_build_exit_1_without_running_gcc(tmp_path, capsys):
    from btw import cli

    path = tmp_path / "prog.btw"
    path.write_text(too_many_histories())
    assert cli.main(["build", "--format", "short", str(path)]) == 1
    assert "error[E501]: Not implemented: `git log`" in capsys.readouterr().err
    assert not (tmp_path / "prog").exists()


# The assembly text


def test_escape():
    assert codegen.escape('a\tb\n"c"\\') == '"a\\tb\\n\\"c\\"\\\\"'
    assert codegen.escape("é") == '"\\303\\251"'


def test_layout():
    _, text = asm(program("    console.log PORT", top=("npm install -g PORT = 3000",)))
    assert text.startswith("        .intel_syntax noprefix\n")
    assert "btw_g_PORT: .quad 0\n" in text
    assert "        .globl main\nmain:\n" in text
    assert text.endswith('        .section .note.GNU-stack,"",@progbits\n')
    assert "#" not in text.replace('"",@progbits', "")  # no comments without --annotate


def test_annotate_fizzbuzz():
    source = (GOLDEN / "p0_fizzbuzz.btw").read_text()
    _, text = asm(source, annotate=True)
    for comment in [
        "# line 3: npm install i = 1",
        "# line 4: doomscroll i <= 15",
        "# line 5: vibe check i % 15 == 0",
        '# line 5: console.log "FizzBuzz"',
        "# line 6: skill issue vibe check i % 3 == 0",
        "# line 8: skill issue",
        "# line 9: git push --force i = i + 1",
    ]:
        assert f"        {comment}\n" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_annotate_keeps_condition_parens():
    _, text = asm(program("    vibe check (1 == 1) { console.log 1 }"), annotate=True)
    assert "# line 3: vibe check (1 == 1)\n" in text


def test_frame_rounds_up_to_16():
    _, text = asm(program(*[f"    npm install v{k} = {k}" for k in range(3)]))
    assert "sub     rsp, 32" in text
    _, text = asm(program("    console.log 1"))
    assert "sub     rsp" not in text


def test_big_literals_use_mov():
    _, text = asm(program("    console.log 2147483648", "    console.log -2147483648"))
    assert "mov     rax, 2147483648" in text
    assert "push    2147483647" not in text


def microservices(*items: str, body: tuple[str, ...] = ("    console.log 1",)) -> str:
    lines = ["i use arch btw", *items, "serve localhost:3000 {", *body, "}", ":wq"]
    return "\n".join(lines) + "\n"


def test_microservice_prologue_and_epilogue():
    source = microservices(
        "microservice sum6(a, b, c, d, e, f) O(1) {",
        "    npm install g = a + b + c + d + e + f",
        "    ship it g",
        "}",
        "microservice nothing() O(1) {",
        "}",
    )
    _, text = asm(source)
    assert (
        "btw_fn_sum6:\n"
        "        push    rbp\n"
        "        mov     rbp, rsp\n"
        "        sub     rsp, 64\n"
        "        inc     qword ptr [rip + btw_depth]\n"
        "        cmp     qword ptr [rip + btw_depth], 1000\n"
        "        jg      .Lstack_overflow\n"
        "        mov     qword ptr [rbp - 8], rdi\n"
        "        mov     qword ptr [rbp - 16], rsi\n"
        "        mov     qword ptr [rbp - 24], rdx\n"
        "        mov     qword ptr [rbp - 32], rcx\n"
        "        mov     qword ptr [rbp - 40], r8\n"
        "        mov     qword ptr [rbp - 48], r9\n"
    ) in text
    assert "        jmp     .Lret_sum6\n" in text
    assert (
        "btw_fn_nothing:\n"
        "        push    rbp\n"
        "        mov     rbp, rsp\n"
        "        inc     qword ptr [rip + btw_depth]\n"
        "        cmp     qword ptr [rip + btw_depth], 1000\n"
        "        jg      .Lstack_overflow\n"
        "\n"
        "        xor     eax, eax\n"
        ".Lret_nothing:\n"
        "        dec     qword ptr [rip + btw_depth]\n"
        "        leave\n"
        "        ret\n"
    ) in text


def test_stack_overflow_handler_only_with_microservices():
    _, text = asm(program("    console.log 1"))
    assert "btw_depth" in text and ".Lstack_overflow" not in text
    _, text = asm(microservices("microservice f() O(1) {", "}"))
    assert (
        ".Lstack_overflow:\n"
        "        and     rsp, -16\n"
        "        call    btw_rt_stack_overflow\n"
    ) in text
    assert "btw_depth" not in text.split("btw_fn_f:")[0].split(".text")[1]  # serve is depth 0


def call_site(text: str, callee: str) -> list[str]:
    """The lines from the argument pops up to the push of the result."""
    lines = text.splitlines()
    end = lines.index(f"        call    {callee}") + 2
    start = end - 2
    while lines[start - 1].startswith(("        pop", "        sub     rsp, 8")):
        start -= 1
    return [line.split()[0] + " " + " ".join(line.split()[1:]) for line in lines[start : end + 1]]


def test_call_pops_arguments_in_reverse_and_aligns():
    items = ("microservice f(a, b) O(1) {", "    ship it a - b", "}")
    _, text = asm(microservices(*items, body=("    console.log f(5, 3)",)))
    assert call_site(text, "btw_fn_f") == [
        "pop rsi",
        "pop rdi",
        "call btw_fn_f",
        "push rax",
        "pop rdi",
    ]
    _, text = asm(microservices(*items, body=("    console.log 1 + f(5, 3)",)))
    assert call_site(text, "btw_fn_f") == [
        "pop rsi",
        "pop rdi",
        "sub rsp, 8",
        "call btw_fn_f",
        "add rsp, 8",
        "push rax",
    ]


def test_six_arguments_use_every_register():
    items = ("microservice f(a, b, c, d, e, g) O(1) {", "    ship it a", "}")
    _, text = asm(microservices(*items, body=("    f(1, 2, 3, 4, 5, 6)",)))
    pops = call_site(text, "btw_fn_f")[:6]
    assert pops == ["pop r9", "pop r8", "pop rcx", "pop rdx", "pop rsi", "pop rdi"]


def test_serve_and_a_microservice_named_main_have_their_own_labels():
    _, text = asm(microservices("microservice main() O(1) {", "    ship it 1", "}"))
    assert "main:\n" in text and "btw_fn_main:\n" in text
    assert text.count(".Lret_serve:\n") == 1
    assert text.count(".Lret_main:\n") == 1


def test_annotate_microservice_header():
    source = microservices("microservice f(n) O(1) {", "    ship it n", "}")
    _, text = asm(source, annotate=True)
    assert "\n\n        # line 2: microservice f(n) O(1)\nbtw_fn_f:\n" in text
    assert "\n\n\n" not in text


def test_history_calls():
    source = program(
        "    npm install x = 1",
        "    npm install untracked = 2",
        "    git push --force x = untracked",
        "    git push --force untracked = 3",
        "    git revert x",
        "    git log x",
        top=("npm install -g ON = LGTM", "microservice f() O(1) {", "    ship it 1", "}"),
    ).replace(
        "    git log x\n",
        "    git log x\n    sudo git push --force ON = 404\n    git log ON\n    git blame ON\n",
    )
    _, text = asm(source)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    assert lines.count("call btw_rt_hist_reset") == 2  # x and the constant ON
    assert lines.count("call btw_rt_hist_commit") == 2  # x and ON, not untracked
    commit = lines.index("call btw_rt_hist_commit")
    assert lines[commit - 1] == "mov rdx, 9"  # the line of `git push --force x = untracked`
    start = lines.index("call btw_rt_hist_revert") - 3
    assert lines[start : start + 5] == [
        "mov rdi, 1",
        "lea rsi, [rip + .Lstr0]",
        "mov rdx, 11",
        "call btw_rt_hist_revert",
        "mov qword ptr [rbp - 8], rax",
    ]
    logs = [k for k, line in enumerate(lines) if line == "call btw_rt_hist_log"]
    assert [lines[k - 3 : k] for k in logs] == [
        ["mov rdi, 1", "lea rsi, [rip + .Lstr0]", "mov rdx, 0"],
        ["mov rdi, 0", "lea rsi, [rip + .Lstr1]", "mov rdx, 1"],
    ]
    blame = lines.index("call btw_rt_hist_blame")
    assert lines[blame - 2 : blame] == ["mov rdi, 0", "mov rsi, 1"]  # no name: no HEAD
    assert '.Lstr0: .string "x"\n' in text and '.Lstr1: .string "ON"\n' in text


# The push-depth invariant


def test_unbalanced_statement_is_caught(monkeypatch):
    monkeypatch.setattr(codegen.Codegen, "pop", lambda self, register: None)
    with pytest.raises(AssertionError):
        asm(program("    console.log 1 + 2"))


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.btw")), ids=lambda p: p.stem)
def test_every_checked_golden_generates_or_reports_e501(path):
    """Generation asserts the depth is 0 at every statement boundary."""
    source = path.read_text()
    _, _, diagnostics = driver.check(source, str(path))
    if driver.has_errors(diagnostics):
        return
    diagnostics, text = asm(source, annotate=True)
    assert text is not None or any(d.code == "E501" for d in diagnostics)


# Differential: the native binary against the interpreter


DIFFERENTIAL = {
    "big_numbers": program(
        "    console.log 9223372036854775807",
        "    console.log -9223372036854775807 - 1",
        "    console.log 4294967296 * 4294967296 + 2147483648",
        "    console.log -(-9223372036854775807 - 1)",
    ),
    "nested_logic": program(
        "    npm install a = 3",
        "    npm install b = 404",
        "    console.log (a > 2 && !b) || (a == 1 && LGTM)",
        "    console.log !(a < 2 || b) && a != 4",
        "    console.log (a == 3) == (b == 404)",
        "    console.log 1 + (2 * (3 - (4 / (5 % 3))))",
    ),
    "division_signs": program(
        "    console.log -7 / 2",
        "    console.log -7 % 2",
        "    console.log 7 / -2",
        "    console.log 7 % -2",
        "    console.log -7 / -2",
        "    console.log -7 % -2",
    ),
    "globals": program(
        "    console.log B",
        "    git push --force c = c + B",
        "    sudo git push --force B = 1",
        "    console.log c - B",
        top=("npm install -g A = 20", "npm install -g B = A * 2 + 1", "npm install c = B / 2"),
    ),
    "ship_it_from_nested_loop": program(
        "    npm install i = 0",
        "    doomscroll LGTM {",
        "        npm install j = 0",
        "        doomscroll j < 3 {",
        "            vibe check i * j == 4 { ship it i * 10 + j }",
        "            git push --force j = j + 1",
        "        }",
        "        git push --force i = i + 1",
        "    }",
    ),
    "unicode_string": program('    console.log "héllo → wörld 🚀"', "    ship it -1"),
    "division_by_zero_after_output": program(
        "    console.log 1",
        "    npm install z = 404",
        "    console.log z || 5 % 0 == 1",
    ),
    "expression_statement": program("    npm install x = 2", "    x * 2 + 1", "    console.log x"),
    "libc_names": microservices(
        "microservice main(a) O(1) {",
        "    ship it a / 0",
        "}",
        "microservice printf() O(1) {",
        "}",
        "microservice exit(x) O(n) {",
        "    doomscroll LGTM { ship it x }",
        "}",
        body=("    console.log 1", "    ship it 7"),
    ),
    "nested_calls": microservices(
        "microservice add(a, b) O(1) {",
        "    ship it a + b",
        "}",
        "microservice pick(a, b, c, d, e, f) O(1) {",
        "    ship it a * 100000 + b * 10000 + c * 1000 + d * 100 + e * 10 + f",
        "}",
        "microservice id(x) O(1) {",
        "    console.log x",
        "    ship it x",
        "}",
        body=(
            "    console.log pick(id(1), id(2), add(id(3), 0), 4, add(2, add(1, 2)), id(6))",
            "    console.log 1 + (2 * (3 + add(4, 5 * add(6, 7))))",
            "    console.log add(1, 2) == 3 && add(2, 2) != 5",
            "    console.log -add(1, 2) / add(0, 2) % add(1, 1)",
            "    console.log 7 - add(7, 0) + add(add(add(1, 1), 1), 1)",
            "    add(1, id(9))",
        ),
    ),
    "short_circuit_skips_calls": microservices(
        "microservice say(x) O(1) {",
        "    console.log x",
        "    ship it x",
        "}",
        body=(
            "    console.log say(1) == 2 && say(3) == 3",
            "    console.log say(4) == 4 || say(5) == 5",
            "    console.log say(6) == 6 && (say(7) == 0 || say(8) == 8)",
            "    vibe check say(9) > 0 { console.log say(10) }",
        ),
    ),
    "microservice_statements": microservices(
        "npm install total = 0",
        "npm install -g STEP = 3",
        "microservice count(n) O(n) {",
        "    npm install i = 0",
        "    npm install hits = 0",
        "    doomscroll LGTM {",
        "        vibe check i >= n { touch grass }",
        "        vibe check i % STEP == 0 {",
        "            git push --force hits = hits + 1",
        "        } skill issue vibe check i == 7 {",
        "            ship it -1",
        "        }",
        "        git push --force i = i + 1",
        "    }",
        "    git push --force total = total + hits",
        "    console.log i > 3",
        "    ship it hits",
        "}",
        "microservice bump(n) O(1) {",
        "    git push --force n = n + 1",
        "    ship it n",
        "}",
        body=(
            "    console.log count(5)",
            "    console.log count(7)",
            "    console.log count(20)",
            "    console.log total",
            "    npm install x = 41",
            "    console.log bump(x)",
            "    console.log x",
            "    ship it count(3) + 40",
        ),
    ),
    "recursion": microservices(
        "microservice fib(n) O(n) {",
        "    vibe check n < 2 { ship it n }",
        "    ship it fib(n - 1) + fib(n - 2)",
        "}",
        "microservice down(n) O(n) {",
        "    vibe check n == 0 { ship it 0 }",
        "    ship it 1 + (2 * down(n - 1)) / 2",
        "}",
        body=("    console.log fib(20)", "    console.log down(999)", "    console.log down(1000)"),
    ),
    "arguments_run_before_the_depth_check": microservices(
        "microservice say(x) O(1) {",
        "    console.log x",
        "    ship it x",
        "}",
        "microservice down(n, z) O(n) {",
        "    vibe check n == 0 { ship it say(1 / z) }",
        "    ship it down(n - 1, z)",
        "}",
        body=("    console.log down(998, 1)", "    console.log down(999, 0)"),
    ),
    "overflow_with_odd_depth": microservices(
        "microservice down(n) O(n) {",
        "    ship it 1 + 2 * (3 + down(n + 1))",
        "}",
        body=("    console.log 1", "    console.log 5 + down(0)"),
    ),
    "history_from_microservices": microservices(
        "npm install total = 0",
        "npm install -g FLAG = LGTM",
        "microservice add(n) O(1) {",
        "    git push --force total = total + n",
        "    sudo git push --force FLAG = !FLAG",
        "    ship it total",
        "}",
        body=(
            "    console.log add(add(1) + add(2))",
            "    git revert total",
            "    sudo git revert FLAG",
            "    git log total",
            "    git log FLAG",
            "    npm install i = 0",
            "    doomscroll i < 3 {",
            "        npm install seen = i * 10",
            "        git push --force seen = add(seen)",
            "        git log seen",
            "        git push --force i = i + 1",
            "    }",
            "    git log i",
            "    ship it total",
        ),
    ),
    "history_cap_and_toggle": program(
        "    npm install n = 0",
        "    doomscroll n < 40 { git push --force n = n + 1 }",
        "    git revert n",
        "    git revert n",
        "    git revert n",
        "    git log n",
        "    npm install b = 404",
        "    git push --force b = 1 == 1",
        "    git revert b",
        "    console.log b",
        "    git log b",
        "    npm install once = 1",
        "    git revert once",
    ),
    "division_by_zero_in_a_call": microservices(
        "microservice div(a, b) O(1) {",
        "    ship it a / b",
        "}",
        body=("    console.log div(7, 2)", "    console.log 1 + div(1, div(1, 2))"),
    ),
}


@needs_gcc
@pytest.mark.parametrize("name", DIFFERENTIAL)
def test_native_matches_interpreter(name, tmp_path):
    source = DIFFERENTIAL[name]
    assert native(source, tmp_path) == interpret(source)


CURL_INPUTS = [
    b"",
    b" \t\r\n\v\f",
    b"1 2 3",
    b"1\t2\r\n3",
    b"1\v2\f3 \t\n",
    b"-0 007 -00",
    b"9223372036854775807 -9223372036854775808 0",
    b"9223372036854775808",
    b"-9223372036854775809",
    b"18446744073709551616",
    b"99999999999999999999999",
    b"00000000000000000000000000000001 2 3",
    b"+5",
    b"-",
    b"--5",
    b"5-",
    b"1.5",
    b"1\x002 3",
    b"\xc2\xa05",
    b"\xd9\xa5",
    b"1 2",
]


@needs_gcc
@pytest.mark.parametrize("stdin", CURL_INPUTS, ids=repr)
def test_native_curl_matches_interpreter(stdin, tmp_path):
    source = program("    console.log curl", "    console.log curl", "    console.log curl")
    assert native(source, tmp_path, stdin) == interpret(source, stdin)


# Stack alignment: every runtime function checks rsp on entry

ALIGNMENT_PROBE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#define btw_rt_print_int real_print_int
#define btw_rt_print_bool real_print_bool
#define btw_rt_print_str real_print_str
#define btw_rt_div_zero real_div_zero
#define btw_rt_stack_overflow real_stack_overflow
#define btw_rt_hist_reset real_hist_reset
#define btw_rt_hist_commit real_hist_commit
#define btw_rt_hist_revert real_hist_revert
#define btw_rt_hist_log real_hist_log
#define btw_rt_hist_blame real_hist_blame
#define btw_rt_curl real_curl
#include "RUNTIME"
#undef btw_rt_print_int
#undef btw_rt_print_bool
#undef btw_rt_print_str
#undef btw_rt_div_zero
#undef btw_rt_stack_overflow
#undef btw_rt_hist_reset
#undef btw_rt_hist_commit
#undef btw_rt_hist_revert
#undef btw_rt_hist_log
#undef btw_rt_hist_blame
#undef btw_rt_curl

/* At -O0 with a frame pointer, rbp is 16-byte aligned exactly when the
 * caller's rsp was aligned at the call. */
#define CHECK do { if ((unsigned long)__builtin_frame_address(0) % 16) { \
    fputs("misaligned call\n", stderr); _exit(99); } } while (0)

void btw_rt_print_int(long v) { CHECK; real_print_int(v); }
void btw_rt_print_bool(long v) { CHECK; real_print_bool(v); }
void btw_rt_print_str(const char *s) { CHECK; real_print_str(s); }
void btw_rt_div_zero(void) { CHECK; real_div_zero(); }
void btw_rt_stack_overflow(void) { CHECK; real_stack_overflow(); }
void btw_rt_hist_reset(long id, long v, long line) { CHECK; real_hist_reset(id, v, line); }
void btw_rt_hist_commit(long id, long v, long line) { CHECK; real_hist_commit(id, v, line); }
long btw_rt_hist_revert(long id, const char *name, long line) {
    CHECK; return real_hist_revert(id, name, line);
}
void btw_rt_hist_log(long id, const char *name, long is_bool) {
    CHECK; real_hist_log(id, name, is_bool);
}
void btw_rt_hist_blame(long id, long is_bool) { CHECK; real_hist_blame(id, is_bool); }
long btw_rt_curl(void) { CHECK; return real_curl(); }
"""


@pytest.fixture(scope="module")
def probe_runtime(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("probe")
    source = directory / "probe.c"
    source.write_text(ALIGNMENT_PROBE.replace("RUNTIME", str(driver.RUNTIME)))
    obj = directory / "probe.o"
    subprocess.run(
        ["gcc", "-O0", "-fno-omit-frame-pointer", "-c", "-o", str(obj), str(source)], check=True
    )
    return obj


ALIGNMENT_PROGRAMS = {
    **{f"differential_{name}": source for name, source in DIFFERENTIAL.items()},
    **{
        f"golden_{path.stem}": path.read_text()
        for path in sorted(GOLDEN.glob("*.btw"))
        if any(path.with_suffix(suffix).exists() for suffix in (".out", ".err", ".exit"))
    },
}

ALIGNMENT_STDIN = {
    f"golden_{path.stem}": path.with_suffix(".in").read_bytes()
    for path in sorted(GOLDEN.glob("*.btw"))
    if path.with_suffix(".in").exists()
}


@needs_gcc
@pytest.mark.parametrize("name", ALIGNMENT_PROGRAMS)
def test_every_runtime_call_is_aligned(name, probe_runtime, tmp_path):
    source = ALIGNMENT_PROGRAMS[name]
    diagnostics, text = asm(source)
    if text is None:
        pytest.skip("doesn't build: " + ", ".join(sorted({d.code for d in diagnostics})))
    assembly = tmp_path / "prog.s"
    assembly.write_text(text)
    binary = tmp_path / "prog"
    subprocess.run(["gcc", "-o", str(binary), str(assembly), str(probe_runtime)], check=True)
    stdin = ALIGNMENT_STDIN.get(name, b"")
    result = subprocess.run([binary], input=stdin, capture_output=True, timeout=5)
    stdout, stderr = result.stdout.decode(), result.stderr.decode()
    assert (stdout, stderr, result.returncode) == interpret(source, stdin)


@needs_gcc
def test_alignment_probe_catches_a_missing_pad(monkeypatch, probe_runtime, tmp_path):
    """The probe really fails when the padding is left out."""
    monkeypatch.setattr(codegen.Codegen, "call", lambda self, function: self.emit("call", function))
    source = DIFFERENTIAL["nested_calls"]
    _, text = asm(source)
    assembly = tmp_path / "prog.s"
    assembly.write_text(text)
    binary = tmp_path / "prog"
    subprocess.run(["gcc", "-o", str(binary), str(assembly), str(probe_runtime)], check=True)
    result = subprocess.run([binary], capture_output=True, timeout=5)
    assert result.returncode == 99 and result.stderr == b"misaligned call\n"


# E502: gcc rejects the assembly


@needs_gcc
def test_gcc_failure_is_e502(monkeypatch, tmp_path, capsys):
    from btw import cli

    monkeypatch.setattr(codegen, "gen", lambda *args, **kwargs: ("bogus instruction\n", []))
    path = tmp_path / "prog.btw"
    path.write_text(program("    console.log 1"))
    assert cli.main(["build", "--format", "short", str(path)]) == 3
    err = capsys.readouterr().err
    assert (
        "1:1: error[E502]: Bad gateway: gcc rejected the generated assembly. "
        "That's a compiler bug, not a skill issue." in err
    )
    assert "bogus" in err  # gcc's own stderr follows


@needs_gcc
def test_keep_asm(tmp_path):
    binary = tmp_path / "prog"
    driver.build(program("    console.log 1"), "test.btw", binary, keep_asm=True)
    assert (tmp_path / "prog.s").read_text().startswith("        .intel_syntax noprefix")
    assert subprocess.run([binary], capture_output=True).stdout == b"1\n"


def test_python_runs_the_cli():
    """`python -m btw asm` works, as the golden runner calls it."""
    result = subprocess.run(
        [sys.executable, "-m", "btw", "asm", "--annotate", str(GOLDEN / "p0_hello.btw")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "call    btw_rt_print_str" in result.stdout
