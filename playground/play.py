"""The playground's bridge to btw. Like `btw run`, but the diagnostics always
show, since the roasts are the point, and they come first, so a program the
playground stops for running too long still gets its roast."""

import io
import json

from btw import driver
from btw.printing import format_pretty, format_summary

PATH = "playground.btw"


def check(source: str) -> str:
    """The diagnostics, pretty without color, and the summary line."""
    try:
        _, _, diagnostics = driver.check(source, PATH)
    except Exception:
        diagnostics = [driver.internal_error(source)]
    blocks = [format_pretty(d, PATH, source, False) for d in diagnostics]
    if summary := format_summary(diagnostics):
        blocks.append(summary)
    return "\n\n".join(blocks)


def run(source: str, stdin: str = "") -> str:
    """Return JSON: stdout, stderr and the exit code, which is null when errors
    blocked the run. `stdin` is all of `curl`'s input, given up front, since
    the worker can't stop to wait for typing."""
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        _, exit_code = driver.run(
            source, PATH, stdout, stderr, io.BytesIO(stdin.encode("utf-8"))
        )
    except Exception:
        exit_code = None  # check() already reported E500
    return json.dumps(
        {
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "exit": None if exit_code is None else exit_code & 0xFF,
        }
    )


def asm(source: str) -> str:
    """What `btw asm --annotate` prints, or why there's none. The checker's
    errors already show as diagnostics, but E501, the native backend's, shows
    only here."""
    try:
        diagnostics, text = driver.asm(source, PATH, annotate=True)
    except Exception:
        return "The code generator crashed. `btw asm` shows the real error."
    if text is not None:
        return text
    e501 = [d for d in diagnostics if d.code == "E501"]
    blocks = [format_pretty(d, PATH, source, False) for d in e501]
    return "\n\n".join(blocks) or "Errors blocked the build."
