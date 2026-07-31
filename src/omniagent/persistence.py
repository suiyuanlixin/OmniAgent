from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_APPEND_LOCKS_GUARD = threading.Lock()
_APPEND_LOCKS: dict[str, threading.Lock] = {}


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> Path:
    """Replace a text file without exposing a partially written destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(str(content))
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None and os.name != "nt":
            temporary.chmod(mode)
        os.replace(temporary, destination)
        if mode is not None and os.name != "nt":
            destination.chmod(mode)
        return destination
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    trailing_newline: bool = True,
    mode: int | None = None,
) -> Path:
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if trailing_newline:
        text += "\n"
    return atomic_write_text(path, text, mode=mode)


def append_jsonl(path: str | Path, record: Any, *, mode: int | None = None) -> Path:
    """Append one complete JSON record under an in-process per-path lock."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.normcase(str(destination.resolve(strict=False)))
    with _APPEND_LOCKS_GUARD:
        lock = _APPEND_LOCKS.setdefault(key, threading.Lock())
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with lock:
        with destination.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
        if mode is not None and os.name != "nt":
            destination.chmod(mode)
    return destination
