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


def interpret(source: str) -> tuple[str, str, int]:
    stdout, stderr = io.StringIO(), io.StringIO()
    diagnostics, code = driver.run(source, "test.btw", stdout, stderr)
    assert code is not None, diagnostics
    return stdout.getvalue(), stderr.getvalue(), code & 0xFF


def native(source: str, tmp_path: Path) -> tuple[str, str, int]:
    binary = tmp_path / "prog"
    diagnostics, gcc_stderr = driver.build(source, "test.btw", binary)
    assert gcc_stderr is None, gcc_stderr
    assert not driver.has_errors(diagnostics), diagnostics
    result = subprocess.run([binary], capture_output=True, timeout=5)
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# E501: constructs the native backend doesn't build yet


def e501s(source: str) -> list[tuple[str, Span]]:
    diagnostics, text = asm(source)
    assert text is None
    return [(d.message, d.span) for d in diagnostics if d.code == "E501"]


def test_microservice_and_call_are_e501():
    source = (
        "i use arch btw\n"
        "microservice f(n) O(1) {\n"
        "    ship it n\n"
        "}\n"
        "serve localhost:3000 {\n"
        "    console.log f(1)\n"
        "}\n"
        ":wq\n"
    )
    assert e501s(source) == [
        (
            "Not implemented: `microservice` in native builds. Try `btw run`.",
            Span(Pos(1, 0), Pos(1, 12)),
        ),
        (
            "Not implemented: `f(...)` in native builds. Try `btw run`.",
            Span(Pos(5, 16), Pos(5, 20)),
        ),
    ]


def test_git_revert_and_git_log_are_e501():
    source = program(
        "    npm install x = 1",
        "    git push --force x = 2",
        "    git revert x",
        "    sudo git revert x",
        "    git log x",
    )
    revert = "Not implemented: `git revert` in native builds. Try `btw run`."
    log = "Not implemented: `git log` in native builds. Try `btw run`."
    assert e501s(source) == [
        (revert, Span(Pos(4, 4), Pos(4, 16))),
        (revert, Span(Pos(5, 4), Pos(5, 21))),
        (log, Span(Pos(6, 4), Pos(6, 13))),
    ]


def test_e501_is_build_exit_1_without_running_gcc(tmp_path, capsys):
    from btw import cli

    path = tmp_path / "prog.btw"
    path.write_text(program("    npm install x = 1", "    git log x"))
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
}


@needs_gcc
@pytest.mark.parametrize("name", DIFFERENTIAL)
def test_native_matches_interpreter(name, tmp_path):
    source = DIFFERENTIAL[name]
    assert native(source, tmp_path) == interpret(source)


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
