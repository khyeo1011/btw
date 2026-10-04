import io
import sys

import pytest

from btw import driver
from btw.interp import (
    DIVISION_BY_ZERO,
    EMPTY_REPLY,
    MAX_DEPTH,
    STACK_OVERFLOW,
    WEIRD_REPLY,
    RuntimeFault,
    div,
    format_value,
    read_number,
    rem,
    wrap,
)

MIN = -(2**63)
MAX = 2**63 - 1


# Arithmetic helpers: the reference table of Language Spec 5


@pytest.mark.parametrize(
    "a, b, quotient, remainder",
    [
        (7, 2, 3, 1),
        (-7, 2, -3, -1),
        (7, -2, -3, 1),
        (-7, -2, 3, -1),
    ],
)
def test_division_reference(a, b, quotient, remainder):
    assert div(a, b) == quotient
    assert rem(a, b) == remainder


def test_overflow_reference():
    assert wrap(9223372036854775807 + 1) == -9223372036854775808
    assert wrap(-9223372036854775807 - 2) == 9223372036854775807
    assert wrap(3037000500 * 3037000500) == -9223372036709301616


@pytest.mark.parametrize("n", [0, 1, -1, MIN, MAX, 12345, -12345])
def test_wrap_keeps_in_range_values(n):
    assert wrap(n) == n


def test_wrap_edges():
    assert wrap(MAX + 1) == MIN
    assert wrap(MIN - 1) == MAX
    assert wrap(-MIN) == MIN  # negating the minimum wraps to itself
    assert wrap(2**64) == 0
    assert wrap(2**64 + 5) == 5


def test_division_exact_and_small():
    assert div(6, 3) == 2
    assert rem(6, 3) == 0
    assert div(1, 2) == 0
    assert div(-1, 2) == 0
    assert rem(-1, 2) == -1
    assert div(MIN, 1) == MIN
    assert rem(MIN, -1) == 0
    assert div(MIN, -1) == MIN  # undefined in the spec; the interpreter wraps


def test_format_value():
    assert format_value(True) == "LGTM"
    assert format_value(False) == "404"
    assert format_value(0) == "0"
    assert format_value(-42) == "-42"


# Whole programs


def program(body, top=""):
    return f"i use arch btw\n{top}serve localhost:3000 {{\n{body}\n}}\n:wq\n"


class Recorder(io.StringIO):
    """A stream that logs its writes and flushes into a shared event list."""

    def __init__(self, name, events):
        super().__init__()
        self.name = name
        self.events = events

    def write(self, text):
        self.events.append((self.name, "write", text))
        return super().write(text)

    def flush(self):
        self.events.append((self.name, "flush", None))
        super().flush()


def execute(source):
    stdout, stderr = io.StringIO(), io.StringIO()
    diagnostics, code = driver.run(source, "test.btw", stdout, stderr)
    assert not driver.has_errors(diagnostics), diagnostics
    return stdout.getvalue(), stderr.getvalue(), code


def test_hello():
    assert execute(program('    console.log "hi"')) == ("hi\n", "", 0)


def test_operators():
    out, _, _ = execute(
        program(
            "    console.log 1 + 2 * 3\n"
            "    console.log -7 / 2\n"
            "    console.log -7 % 2\n"
            "    console.log 3 <= 3\n"
            "    console.log 3 != 3\n"
            "    console.log !404\n"
            "    console.log 404 == 404\n"
            "    console.log 403 + 1"
        )
    )
    assert out == "7\n-3\n-1\nLGTM\n404\nLGTM\nLGTM\n404\n"


def test_overflow_in_programs():
    out, _, _ = execute(
        program(
            "    console.log 9223372036854775807 + 1\n"
            "    npm install m = 0 - 9223372036854775807 - 1\n"
            "    console.log -m\n"
            "    console.log m - 1\n"
            "    console.log 3037000500 * 3037000500"
        )
    )
    assert out == (
        "-9223372036854775808\n-9223372036854775808\n9223372036854775807\n-9223372036709301616\n"
    )


def test_short_circuit_skips_the_right_side():
    out, err, code = execute(
        program(
            "    npm install zero = 0\n"
            "    console.log 404 && 1 / zero == 0\n"
            "    console.log LGTM || 1 / zero == 0"
        )
    )
    assert (out, err, code) == ("404\nLGTM\n", "", 0)


def test_short_circuit_evaluates_the_right_side_when_needed():
    _, err, code = execute(
        program("    npm install zero = 0\n    console.log LGTM && 1 / zero == 0")
    )
    assert (err, code) == (DIVISION_BY_ZERO + "\n", 1)


def test_evaluation_order_is_left_to_right():
    top = "microservice show(x) O(1) {\n    console.log x\n    ship it x\n}\n"
    out, _, _ = execute(program("    console.log show(1) - show(2) * show(3)", top))
    assert out == "1\n2\n3\n-5\n"


@pytest.mark.parametrize("op", ["/", "%"])
def test_division_by_zero_flushes_stdout_first(op):
    events = []
    stdout, stderr = Recorder("out", events), Recorder("err", events)
    source = program(
        f'    console.log "before"\n    console.log 1 {op} 0\n    console.log "after"'
    )
    diagnostics, code = driver.run(source, "test.btw", stdout, stderr)
    assert not driver.has_errors(diagnostics)
    assert code == 1
    assert stdout.getvalue() == "before\n"
    assert stderr.getvalue() == DIVISION_BY_ZERO + "\n"
    first_error = events.index(("err", "write", DIVISION_BY_ZERO + "\n"))
    assert ("out", "flush", None) in events[:first_error]


DEPTH = (
    "microservice depth(n) O(n) {\n"
    "    vibe check n == 1 {\n"
    "        ship it 1\n"
    "    }\n"
    "    ship it 1 + depth(n - 1)\n"
    "}\n"
)


def test_call_depth_limit():
    out, err, code = execute(program(f"    console.log depth({MAX_DEPTH})", DEPTH))
    assert (out, err, code) == (f"{MAX_DEPTH}\n", "", 0)
    out, err, code = execute(program(f"    console.log depth({MAX_DEPTH + 1})", DEPTH))
    assert (out, err, code) == ("", STACK_OVERFLOW + "\n", 1)


def test_depth_recovers_after_returns():
    body = f"    console.log depth({MAX_DEPTH})\n    console.log depth({MAX_DEPTH})"
    assert execute(program(body, DEPTH))[0] == f"{MAX_DEPTH}\n{MAX_DEPTH}\n"


def test_microservice_falls_off_the_end():
    top = "microservice nothing() O(1) {\n    npm install x = 1\n}\n"
    assert execute(program("    console.log nothing()", top))[0] == "0\n"


def test_frames_are_per_call():
    top = (
        "microservice f(n) O(n) {\n"
        "    npm install local = n\n"
        "    vibe check n > 0 {\n"
        "        f(n - 1)\n"
        "    }\n"
        "    ship it local\n"
        "}\n"
    )
    assert execute(program("    console.log f(3)", top))[0] == "3\n"


def test_ship_it_in_serve_exits_from_a_loop():
    body = (
        "    npm install i = 0\n"
        "    doomscroll LGTM {\n"
        "        git push --force i = i + 1\n"
        "        vibe check i == 7 {\n"
        "            ship it i\n"
        "        }\n"
        "    }\n"
        '    console.log "unreachable"'
    )
    assert execute(program(body)) == ("", "", 7)


def test_bare_ship_it_in_serve_exits_0():
    assert execute(program('    ship it\n    console.log "no"')) == ("", "", 0)


def test_touch_grass_breaks_the_innermost_loop():
    body = (
        "    npm install i = 0\n"
        "    doomscroll i < 3 {\n"
        "        npm install j = 0\n"
        "        doomscroll LGTM {\n"
        "            vibe check j == 2 {\n"
        "                touch grass\n"
        "            }\n"
        "            git push --force j = j + 1\n"
        "        }\n"
        "        console.log i * 10 + j\n"
        "        git push --force i = i + 1\n"
        "    }"
    )
    assert execute(program(body))[0] == "2\n12\n22\n"


def test_globals_initialize_in_order_and_are_shared():
    top = (
        "npm install -g BASE = 10\n"
        "npm install count = BASE + 1\n"
        "microservice bump() O(1) {\n"
        "    git push --force count = count + 1\n"
        "}\n"
    )
    assert (
        execute(program("    bump()\n    bump()\n    console.log count", top))[0]
        == "13\n"
    )


def test_git_history():
    body = (
        "    npm install x = 1\n"
        "    git push --force x = 2\n"
        "    git revert x\n"
        "    git log x"
    )
    assert execute(program(body))[0] == "* 1 (HEAD -> x)\n* 2\n* 1\n"


def test_git_history_keeps_16_commits():
    body = (
        "    npm install x = 0\n"
        "    doomscroll x < 20 {\n"
        "        git push --force x = x + 1\n"
        "    }\n"
        "    git log x"
    )
    out = execute(program(body))[0]
    assert out.splitlines() == [
        "* 20 (HEAD -> x)",
        *[f"* {n}" for n in range(19, 4, -1)],
    ]


def test_git_revert_one_commit():
    out, err, code = execute(
        program('    npm install count = 1\n    console.log "a"\n    git revert count')
    )
    assert (out, err, code) == ("a\n", "fatal: bad revision 'count~1'\n", 128)


def test_recursion_limit_is_restored():
    before = sys.getrecursionlimit()
    execute(program(f"    console.log depth({MAX_DEPTH})", DEPTH))
    assert sys.getrecursionlimit() == before


# curl: Language Spec 10


@pytest.mark.parametrize(
    "stdin, value",
    [
        (b"42", 42),
        (b"  \t\r\n\v\f-17\n", -17),
        (b"007", 7),
        (b"-0", 0),
        (b"9223372036854775807", MAX),
        (b"-9223372036854775808", MIN),
        (b"0000000000000000000000000000001", 1),
    ],
)
def test_curl_reads_a_number(stdin, value):
    assert read_number(io.BytesIO(stdin)) == value


@pytest.mark.parametrize("stdin", [b"", b" \n\t\r\v\f"])
def test_curl_at_the_end_of_input(stdin):
    with pytest.raises(RuntimeFault) as fault:
        read_number(io.BytesIO(stdin))
    assert (fault.value.message, fault.value.exit_code) == (EMPTY_REPLY, 52)


@pytest.mark.parametrize(
    "stdin",
    [
        b"+5",
        b"-",
        b"--5",
        b"5-",
        b"12abc",
        b"1.5",
        b"9223372036854775808",
        b"-9223372036854775809",
        b"\xc2\xa05",  # a no-break space isn't ASCII whitespace
        b"\xd9\xa5",  # nor is an Arabic-Indic digit a digit
    ],
)
def test_curl_weird_reply(stdin):
    with pytest.raises(RuntimeFault) as fault:
        read_number(io.BytesIO(stdin))
    assert (fault.value.message, fault.value.exit_code) == (WEIRD_REPLY, 8)


def test_curl_reads_one_whitespace_character_past_the_number():
    """So an interactive run never waits for input it doesn't need."""
    stdin = io.BytesIO(b"1\n\n2")
    assert read_number(stdin) == 1
    assert stdin.tell() == 2


def test_curl_in_a_program():
    source = program("    console.log curl + curl")
    stdout, stderr = io.StringIO(), io.StringIO()
    _, code = driver.run(source, "test.btw", stdout, stderr, io.BytesIO(b"40 2"))
    assert (stdout.getvalue(), stderr.getvalue(), code) == ("42\n", "", 0)


def test_run_without_stdin_reads_nothing():
    """driver.run's stdin defaults to empty input, never the process's own."""
    assert execute(program("    console.log curl")) == ("", EMPTY_REPLY + "\n", 52)
