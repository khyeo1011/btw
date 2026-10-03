"""One test per tests/golden/*.btw, following the runner in Implementation Spec 13."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
TIMEOUT = 5
RUN_SIDECARS = (".out", ".err", ".exit")

# Goldens whose diagnostics can't match until another card lands. Step 1 is an
# expected failure while it differs, and a hard failure once it matches, so
# the entry gets removed as soon as the other card is done.
WAITING: dict[str, str] = {}


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


def btw(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "btw", *args], capture_output=True, timeout=timeout
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
    assert result.returncode == int(expected(program, ".exit") or "0")


def test_golden(program: Path, request, tmp_path: Path):
    blessing = request.config.getoption("--bless")
    path = str(program)

    # 1. Diagnostics, with the path prefix stripped.
    result = btw("check", "--format", "short", path)
    require_ran(result, "btw check")
    diagnostics = result.stdout.decode("utf-8").replace(f"{path}:", "")
    want = expected(program, ".diag")
    if blessing:
        bless(program, ".diag", diagnostics)
    elif program.stem in WAITING:
        if diagnostics != want:
            pytest.xfail(f"waiting on {WAITING[program.stem]}")
        pytest.fail(f"{program.stem} matches now: remove it from WAITING")
    else:
        assert diagnostics == want
    has_error = any(": error[" in line for line in want.splitlines())
    if not blessing:
        assert result.returncode == (1 if has_error else 0)

    # 2. Expected errors, or a check-only program: stop here.
    if has_error or not any(program.with_suffix(s).exists() for s in RUN_SIDECARS):
        return

    # 3. The interpreter.
    result = btw("run", path, timeout=TIMEOUT)
    require_ran(result, "btw run")
    compare_run(program, result, blessing)

    # 4. The native binary, compared against the same expectations.
    if blessing:
        return
    if shutil.which("gcc") is None:
        pytest.skip("native: gcc not found")
    binary = tmp_path / program.stem
    result = btw("build", "--format", "short", "-o", str(binary), path)
    stderr = result.stderr.decode("utf-8", "replace")
    if result.returncode == 2 and "not implemented yet" in stderr:
        pytest.xfail("native: not yet (backend not implemented)")
    if "[E501]: " in stderr:
        pytest.xfail("native: not yet (E501)")
    assert result.returncode == 0, stderr
    compare_run(program, subprocess.run([binary], capture_output=True, timeout=TIMEOUT), False)
