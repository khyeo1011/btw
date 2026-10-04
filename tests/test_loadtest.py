"""`btw loadtest`: Language Spec 9.7."""

import math
import statistics
from pathlib import Path

import pytest

from btw import cli, driver
from btw.driver import BtwError
from btw.bigo import UNKNOWN
from btw.loadtest import SIZES, measure, slope, verdict

GOLDEN = Path(__file__).parent / "golden"

CONSTANT = """microservice konst(n) O(1) {
    ship it n + 1
}"""

LINEAR = """microservice walk(n) O(n) {
    npm install i = 0
    doomscroll i < n {
        git push --force i = i + 1
    }
    ship it i
}"""

HALVING = """microservice halve(n) O(n) {
    doomscroll n > 1 {
        git push --force n = n / 2
    }
    ship it n
}"""

SQUARE_BOUND = """microservice square(n) O(n) {
    npm install i = 0
    doomscroll i < n * n {
        git push --force i = i + 1
    }
    ship it i
}"""

BINARY_SEARCH = """microservice search(n) O(log n) {
    npm install lo = 0
    npm install hi = n
    doomscroll lo < hi {
        npm install mid = (lo + hi) / 2
        vibe check mid > 0 {
            git push --force hi = mid
        } skill issue {
            git push --force lo = mid + 1
        }
    }
    ship it lo
}"""

N_LOG_N = """microservice sort(n) O(n log n) {
    npm install i = 0
    doomscroll i < n {
        npm install j = n
        doomscroll j > 1 {
            git push --force j = j / 2
        }
        git push --force i = i + 1
    }
    ship it i
}"""

RECURSIVE = """microservice down(n) {
    vibe check n == 0 {
        ship it 0
    }
    ship it down(n - 1)
}"""


def program(*services, top=""):
    return "i use arch btw\n" + top + "\n".join(services) + "\nserve localhost:3000 {\n}\n:wq\n"


def loadtest(source, name, args="n"):
    diagnostics, text = driver.loadtest(source, "test.btw", name, args)
    assert text is not None, diagnostics
    return text.splitlines()


def steps(lines):
    """The step counts of the size lines that finished."""
    finished = [line for line in lines if line.endswith(("step", "steps"))]
    return [int(line.split(": ")[1].split()[0]) for line in finished]


def expected_slope(counts):
    xs = [math.log(n) for n in SIZES[: len(counts)]]
    return statistics.linear_regression(xs, [math.log(c) for c in counts]).slope


# The fit


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_slope_of_exact_power_laws(k):
    assert slope([(n, n**k) for n in SIZES]) == pytest.approx(k)


# Step counts and verdicts, derived by hand from each program's shape


def test_constant_takes_one_step():
    lines = loadtest(program(CONSTANT), "konst")
    assert lines[0] == "n = 8: 1 step"
    assert steps(lines) == [1] * len(SIZES)
    assert lines[-2:] == ["static O(1).", "measured O(n^0.00). Your SLA says O(1). LGTM."]


def test_linear():
    lines = loadtest(program(LINEAR), "walk")
    counts = [n + 1 for n in SIZES]  # n iterations plus the call
    assert steps(lines) == counts
    s = expected_slope(counts)
    assert round(s) == 1
    assert lines[-2:] == ["static O(n).", f"measured O(n^{s:.2f}). Your SLA says O(n). LGTM."]


def test_e417_is_measured_and_the_pm_is_notified():
    """The spec's example: E417 is a soft error, so it doesn't block the load test."""
    source = (GOLDEN / "p0_e417_big_o_underclaim.btw").read_text()
    diagnostics, text = driver.loadtest(source, "test.btw", "pairs")
    assert [d.code for d in diagnostics] == ["E417"]
    lines = text.splitlines()
    counts = [n * n + n + 1 for n in SIZES]
    assert steps(lines) == counts
    assert f"{expected_slope(counts):.2f}" == "1.98"
    assert lines[0] == "n = 8: 73 steps"
    assert lines[7] == "n = 1024: 1049601 steps"
    assert lines[8:] == [
        "static O(n²).",
        "measured O(n^1.98). Your SLA says O(n). The PM has been notified.",
    ]


def test_halving_loop_sandbagged_sla():
    lines = loadtest(program(HALVING), "halve")
    assert steps(lines) == [int(math.log2(n)) + 1 for n in SIZES]
    assert lines[-2:] == [
        "static O(log n).",
        "measured O(n^0.20). Your SLA says O(n). Sandbagging your estimates?",
    ]


def test_binary_search_static_checker_is_pessimistic():
    """Statically E417 (a counter changed inside a vibe check runs n times),
    empirically fine."""
    diagnostics, text = driver.loadtest(program(BINARY_SEARCH), "test.btw", "search")
    assert [d.code for d in diagnostics] == ["E417"]
    lines = text.splitlines()
    assert steps(lines) == [int(math.log2(n)) + 2 for n in SIZES]  # hi halves to 1, then lo moves
    assert lines[-2:] == [
        "static O(n). The static checker was being pessimistic.",
        "measured O(n^0.18). Your SLA says O(log n). LGTM.",
    ]


def test_log_factors_are_not_compared():
    lines = loadtest(program(N_LOG_N), "sort")
    assert steps(lines) == [n * int(math.log2(n)) + n + 1 for n in SIZES]
    assert lines[-2:] == [
        "static O(n log n).",
        "measured O(n^1.20). Your SLA says O(n log n). LGTM.",
    ]


def test_square_bound_static_checker_is_optimistic():
    lines = loadtest(program(SQUARE_BOUND), "square")
    assert steps(lines) == [n * n + 1 for n in SIZES]
    assert lines[-2:] == [
        "static O(n). The static checker was being optimistic.",
        "measured O(n^2.00). Your SLA says O(n). The PM has been notified.",
    ]


def test_recursion_is_measured_until_the_stack_overflows():
    lines = loadtest(program(RECURSIVE), "down")
    assert steps(lines) == [n + 1 for n in SIZES[:-1]]  # down(n) down to down(0)
    assert lines[-3:] == [
        "n = 1024: Stack overflow. Please search stackoverflow.com. Stopped.",
        "static O(?).",
        "measured O(n^0.98). No SLA, so nobody was notified.",
    ]


def test_unverifiable_sla_is_echoed():
    service = HALVING.replace("O(n)", "O(sqrt n)")
    assert loadtest(program(service), "halve")[-1] == (
        "measured O(n^0.20). Your SLA says O(sqrt n). I'll take your word for it."
    )


@pytest.mark.parametrize("sla", ["2^n", "n!"])
def test_superpolynomial_sla_is_echoed(sla):
    """A power-law fit can't measure these. Checked on the verdict alone: an
    exponential microservice would spend the whole budget."""
    prog, _ = driver.parse(program(f"microservice f(n) O({sla}) {{\n}}"))
    assert verdict(prog.items[0], UNKNOWN, 5.57)[-1] == (
        f"measured O(n^5.57). Your SLA says O({sla}). I'll take your word for it."
    )


def test_annotation_variable_is_used():
    service = LINEAR.replace("walk(n) O(n)", "walk(n) O(m)")
    assert loadtest(program(service), "walk")[-2] == "static O(m)."


# The sweep


def test_budget_covers_the_whole_sweep():
    source = program(LINEAR)
    prog, symbols, _ = driver.check(source, "test.btw")
    service = prog.items[0]
    points, lines = measure(prog, symbols, service, [None], budget=100)
    assert points == [(8, 9), (16, 17), (32, 33)]  # 59 steps, and n = 64 needs 65 more
    assert lines[-1] == "n = 64: over budget. Stopped."


def test_args_template():
    service = """microservice add(a, b) O(1) {
    ship it a + b
}"""
    assert steps(loadtest(program(service), "add", "7, n")) == [1] * len(SIZES)


def test_globals_are_fresh_for_every_size():
    top = "npm install total = 0\n"
    service = """microservice grow(n) O(n) {
    git push --force total = total + n
    npm install i = 0
    doomscroll i < total {
        git push --force i = i + 1
    }
}"""
    lines = loadtest(program(service, top=top), "grow")
    assert steps(lines) == [n + 1 for n in SIZES]  # not a running total


def test_output_is_discarded(capsys):
    service = """microservice say(n) O(1) {
    console.log "hello"
}"""
    loadtest(program(service), "say")
    assert capsys.readouterr().out == ""


def test_stdin_is_empty():
    service = """microservice ask(n) O(1) {
    ship it n + curl
}"""
    with pytest.raises(BtwError) as error:
        driver.loadtest(program(service), "t.btw", "ask")
    assert str(error.value) == (
        "need at least 2 sizes to fit a slope. n = 8: curl: (52) Empty reply from server. Stopped."
    )


# Errors


def test_hard_errors_block_it():
    source = program(CONSTANT.replace("n + 1", "nope"))
    diagnostics, text = driver.loadtest(source, "t.btw", "konst")
    assert text is None
    assert [d.code for d in diagnostics] == ["E404"]


@pytest.mark.parametrize(
    "name, args, message",
    [
        ("nope", "n", "no microservice named `nope`"),
        ("konst", "n, 2", "`konst` takes 1 argument, but --args gives 2"),
        ("konst", "x", "--args: `x` is neither a number nor `n`"),
    ],
)
def test_usage_errors(name, args, message):
    with pytest.raises(BtwError, match=f"^{message}$"):
        driver.loadtest(program(CONSTANT), "t.btw", name, args)


def test_needs_two_sizes():
    service = """microservice boom(n) O(1) {
    ship it n / 0
}"""
    with pytest.raises(BtwError) as error:
        driver.loadtest(program(service), "t.btw", "boom")
    assert str(error.value) == (
        "need at least 2 sizes to fit a slope. n = 8: Runtime error: division by zero. "
        "Have you tried turning it off and on again? Stopped."
    )


# CLI


def test_cli_exits_0_whatever_the_verdict(tmp_path, capsys):
    path = tmp_path / "under.btw"
    path.write_text(program(LINEAR.replace("O(n)", "O(1)")))
    assert cli.main(["loadtest", "--format", "short", str(path), "walk"]) == 0
    out, err = capsys.readouterr()
    assert out.endswith("The PM has been notified.\n")
    assert "error[E417]" in err


def test_cli_exits_1_for_hard_errors(tmp_path, capsys):
    path = tmp_path / "bad.btw"
    path.write_text(program(CONSTANT.replace("n + 1", "nope")))
    assert cli.main(["loadtest", "--format", "short", str(path), "konst"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_exits_2_for_usage_errors(capsys):
    path = GOLDEN / "p0_e417_big_o_underclaim.btw"
    assert cli.main(["loadtest", str(path), "nope"]) == 2
    assert capsys.readouterr().err.endswith("btw: no microservice named `nope`\n")
