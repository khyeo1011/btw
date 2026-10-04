"""The playground's API, playground/play.py.

Each call runs in a fresh interpreter with pygls blocked, as in the browser,
where the worker unpacks the wheel without its dependencies. In this process,
earlier tests have already imported btw, so blocking pygls here would miss a
new import of the language server; the driver also imports components lazily,
so the block has to hold while play's functions run, not just while play loads.
"""

import json
import subprocess
import sys
from pathlib import Path

PLAYGROUND = Path(__file__).parent.parent / "playground"

SCRIPT = """\
import json, sys
sys.modules["pygls"] = None
sys.modules["lsprotocol"] = None
sys.path.insert(0, {playground!r})
import play
if {crash!r}:
    from btw import driver
    def crash(*args):
        raise RuntimeError("crash")
    driver.check = crash
name, args = json.load(sys.stdin)
sys.stdout.buffer.write(getattr(play, name)(*args).encode("utf-8"))
"""


def call(name: str, *args: str, crash: bool = False) -> str:
    """play.NAME(*args), with driver.check raising if `crash`."""
    script = SCRIPT.format(playground=str(PLAYGROUND), crash=crash)
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps([name, args]),
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def program(*lines: str) -> str:
    return "\n".join(["i use arch btw", *lines, ":wq", ""])


CLEAN = program(
    "serve localhost:3000 {",
    "    console.log curl + curl",
    "    ship it 300",
    "}",
)
UNKNOWN = program(
    "serve localhost:3000 {",
    "    console.log x",
    "}",
)
TOTAL = program(
    "microservice total(n) O(n) {",
    "    npm install x = 0",
    "    doomscroll x < n { git push --force x = x + 1 }",
    "    ship it x",
    "}",
    "serve localhost:3000 {",
    "    console.log total(3)",
    "}",
)


def test_pygls_is_blocked():
    # The block the other tests rely on: the language server can't load.
    script = SCRIPT.format(playground=str(PLAYGROUND), crash=False)
    script = script.split("import play")[0] + "import btw.lsp\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "halted; None in sys.modules" in result.stderr


# check


def test_check_clean():
    assert call("check", CLEAN) == ""


def test_check_error():
    assert call("check", UNKNOWN) == (
        "error[E404]: Error 404: variable `x` not found."
        " Did you forget to `npm install` it?\n"
        "  --> playground.btw:3:17\n"
        "   |\n"
        " 3 |     console.log x\n"
        "   |                 ^\n"
        "\n"
        "build failed: 1 error. Skill issue."
    )


def test_check_warning():
    text = call("check", program("npm install unused = 1", "serve localhost:3000 {", "}"))
    assert text.startswith("warning[W226]: ")
    assert text.endswith("\n\n1 warning. LGTM anyway.")


def test_check_crash():
    text = call("check", UNKNOWN, crash=True)
    assert text.startswith("error[E500]: It works on my machine.")
    assert "--> playground.btw:1:1" in text


# run


def test_run():
    # curl reads the stdin given up front; the exit code keeps its low 8 bits.
    assert json.loads(call("run", CLEAN, "4 5")) == {"stdout": "9\n", "stderr": "", "exit": 44}


def test_run_blocked():
    assert json.loads(call("run", UNKNOWN)) == {"stdout": "", "stderr": "", "exit": None}


def test_run_crash():
    assert json.loads(call("run", CLEAN, crash=True))["exit"] is None


# asm


def test_asm():
    assert "btw_fn_total:" in call("asm", TOTAL)


def test_asm_blocked():
    assert call("asm", UNKNOWN) == "Errors blocked the build."


def test_asm_e501():
    # The runtime keeps 64 histories; E501 shows only here, not in check().
    source = program(
        "serve localhost:3000 {",
        *[f"    npm install v{k} = {k}" for k in range(65)],
        *[f"    git log v{k}" for k in range(65)],
        "}",
    )
    assert "E501" not in call("check", source)
    assert call("asm", source).startswith("error[E501]: Not implemented: `git log`")


def test_asm_crash():
    assert call("asm", CLEAN, crash=True) == (
        "The code generator crashed. `btw asm` shows the real error."
    )


# runtime


def test_runtime():
    assert json.loads(call("runtime", TOTAL, "total")) == {"degree": [1, 0], "text": "O(n)"}


def test_runtime_missing():
    assert call("runtime", TOTAL, "nope") == "null"
    assert call("runtime", TOTAL, "total", crash=True) == "null"
