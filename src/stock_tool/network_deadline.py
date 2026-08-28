"""Bounded boundary for optional remote metadata calls."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
from typing import Callable, TypeVar

Value = TypeVar("Value")


class RemoteCallTimeout(TimeoutError):
    """Raised when an optional remote call exceeds the caller's total budget."""


def call_with_timeout(operation: Callable[[], Value], *, timeout_seconds: float) -> Value:
    """Return an optional remote result, or fail without blocking the UI.

    Python cannot safely kill arbitrary third-party requests.  The daemon worker
    is therefore allowed to finish in the background while callers immediately
    return a safe offline fallback and discard any late result.
    """

    if timeout_seconds <= 0:
        raise RemoteCallTimeout("Remote-call time budget was exhausted.")
    result: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def _run() -> None:
        try:
            result.put((True, operation()))
        except BaseException as exc:
            result.put((False, exc))

    Thread(target=_run, name="stock-tool-optional-remote", daemon=True).start()
    try:
        succeeded, value = result.get(timeout=timeout_seconds)
    except Empty as exc:
        raise RemoteCallTimeout(
            f"Optional remote call exceeded {timeout_seconds:.1f} seconds."
        ) from exc
    if succeeded:
        return value  # type: ignore[return-value]
    raise value  # type: ignore[misc]
