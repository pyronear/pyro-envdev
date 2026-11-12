# ruff: noqa: E501
from __future__ import annotations

import time
from typing import Any, Callable, Optional


class WaitError(AssertionError):
    pass


def wait_until(
    fn: Callable[[], Any],
    timeout: float,
    interval: float,
    what: str,
    diagnose: Callable[[], str] = lambda: "",
    abort: Optional[Callable[[float], Optional[str]]] = None,
):
    """Poll fn until it returns something truthy and return it.

    On timeout, raise a WaitError saying what was awaited, the elapsed seconds, the last value fn returned and diagnose().
    abort(elapsed) may return a message to fail early, with the same details.
    """
    start = time.monotonic()
    last = None
    while True:
        last = fn()
        if last:
            return last
        elapsed = time.monotonic() - start
        reason = abort(elapsed) if abort else None
        if reason or elapsed >= timeout:
            head = reason or f"timed out waiting for {what}"
            raise WaitError(
                f"{head} (awaited: {what}; elapsed {elapsed:.0f} s of {timeout:.0f} s; last value: {last!r})\n{diagnose()}"
            )
        time.sleep(interval)
