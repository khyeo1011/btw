"""One test per tests/golden/*.btw, following the runner steps in NOTES-harness.md."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
TIMEOUT = 60


def tier(program: Path) -> int:
    return int(program.name[1])


def pytest_generate_tests(metafunc):
    if "program" not in metafunc.fixturenames:
        return
    max_tier = metafunc.config.getoption("--tier")
    programs = [
        p for p in sorted(GOLDEN.glob("*.btw")) if max_tier is None or tier(p) <= max_tier
    ]
    metafunc.parametrize("program", programs, ids=[p.stem for p in programs])


def btw(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "btw", *args],
        capture_output=True,
        timeout=TIMEOUT,
    )


def expected(program: Path, suffix: str) -> str:
    """The sidecar's contents; a missing sidecar means empty."""
    sidecar = program.with_suffix(suffix)
    return sidecar.read_bytes().decode("utf-8") if sidecar.exists() else ""


def bless(program: Path, suffix: str, actual: str) -> None:
    sidecar = program.with_suffix(suffix)
    if actual:
        sidecar.write_bytes(actual.encode("utf-8"))
    else:
        sidecar.unlink(missing_ok=True)


def require_ran(result: subprocess.CompletedProcess, step: str) -> None:
    """Exit code 2 means btw itself failed (not implemented, crash): show why."""
    if result.returncode == 2:
        pytest.fail(f"{step}: btw exited 2\n{result.stderr.decode('utf-8', 'replace')}")


def compare_run(program: Path, result: subprocess.CompletedProcess, blessing: bool) -> None:
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    if blessing:
        bless(program, ".out", stdout)
        bless(program, ".err", stderr)
        bless(program, ".exit", f"{result.returncode}\n")
        return
    assert stdout == expected(program, ".out")
    assert stderr == expected(program, ".err")
    assert result.returncode == int(expected(program, ".exit"))


def test_golden(program: Path, request, tmp_path: Path):
    blessing = request.config.getoption("--bless")
    path = str(program)

    # Step 1: diagnostics.
    result = btw("check", "--format", "short", path)
    require_ran(result, "btw check")
    diagnostics = result.stdout.decode("utf-8").replace(f"{path}:", "")
    if blessing:
        bless(program, ".diag", diagnostics)
    else:
        want = expected(program, ".diag")
        assert diagnostics == want
        has_error = any(": error " in line for line in want.splitlines())
        assert result.returncode == (1 if has_error else 0)

    # Step 2: check-only programs stop here.
    if not program.with_suffix(".exit").exists():
        return

    # Step 3: the interpreter.
    result = btw("run", path)
    require_ran(result, "btw run")
    compare_run(program, result, blessing)

    # Step 4: the native backend, compared against the same expectations.
    if blessing or shutil.which("gcc") is None:
        return
    binary = tmp_path / program.stem
    result = btw("build", "--format", "short", "-o", str(binary), path)
    if result.returncode == 2 and b"not implemented yet" in result.stderr:
        pytest.skip("native backend not implemented yet")
    if b" E501: " in result.stderr:
        pytest.skip("uses a construct the native backend doesn't support (E501)")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    compare_run(program, subprocess.run([binary], capture_output=True, timeout=TIMEOUT), False)
