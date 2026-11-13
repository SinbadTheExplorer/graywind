"""Small JSON state files that survive crashes and concurrent jobs.

`write_atomic` is the keys.py pattern (temp file in the same directory,
fsync, replace, unlink on error), so a crash leaves the old file or the new
one, never half of either. `locked` serialises read-modify-write between
jobs that run at the same moment (a brief and a watch run, say).
"""
import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data, *, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read(path: Path, default=None):
    """The file's JSON, or `default` if it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


@contextlib.contextmanager
def locked(path: Path):
    """An exclusive lock on `<path>.lock` for the duration of the block."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
