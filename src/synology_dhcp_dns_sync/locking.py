"""Cross-process locking for sync runs."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import fcntl

from .exceptions import LockHeldError


@contextmanager
def acquire_process_lock(lock_path: Path):
    """Acquire an exclusive non-blocking process lock."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            holder = handle.read().strip()
            detail = f" held by PID {holder}" if holder else ""
            raise LockHeldError(
                f"Another sync process is already running (lock: {lock_path}{detail})."
            ) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()

        yield
    finally:
        try:
            handle.seek(0)
            handle.truncate()
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
