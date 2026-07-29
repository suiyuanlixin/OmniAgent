import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


TOOL_OUTPUT_MAX_LINES = 2000
TOOL_OUTPUT_MAX_BYTES = 50 * 1024
TOOL_OUTPUT_LONG_LINE_CHARS = 2000
TOOL_OUTPUT_VIEW_SEGMENT_CHARS = 1800
TOOL_OUTPUT_HEAD_RATIO = 0.75
TOOL_OUTPUT_RETENTION_SECONDS = 7 * 24 * 60 * 60
TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS = 60 * 60
TOOL_OUTPUT_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
TOOL_OUTPUT_CACHE_MAX_BYTES = 1024 * 1024 * 1024
TOOL_OUTPUT_MIN_FREE_BYTES = 256 * 1024 * 1024
TOOL_OUTPUT_AUX_MAX_BYTES = 8 * 1024
TOOL_OUTPUT_AUX_MAX_LINES = 200
TOOL_OUTPUT_RECORD_PARSE_MAX_BYTES = 16 * 1024 * 1024


def _user_cache_root():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "OmniAgent" / "Cache"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "omniagent"
    try:
        return Path.home() / ".cache" / "omniagent"
    except Exception:
        return Path(tempfile.gettempdir()) / f"omniagent-{os.getpid()}"


TOOL_OUTPUT_DIR = _user_cache_root() / "tool-output"
TOOL_OUTPUT_URI_SCHEME = "artifact"

_CLEANUP_LOCK = threading.Lock()
_LAST_CLEANUP = 0.0
_CLEANUP_THREAD_STARTED = False


class ToolOutputStorageError(RuntimeError):
    pass


class ToolOutputStorageLimitError(ToolOutputStorageError):
    pass


def _line_count(text):
    value = str(text or "")
    if not value:
        return 0
    breaks = 0
    previous_cr = False
    ends_with_newline = False
    for char in value:
        if char == "\n":
            if not previous_cr:
                breaks += 1
            previous_cr = False
            ends_with_newline = True
        elif char == "\r":
            breaks += 1
            previous_cr = True
            ends_with_newline = True
        else:
            previous_cr = False
            ends_with_newline = False
    return breaks + (0 if ends_with_newline else 1)


def _text_has_long_line(text):
    current = 0
    previous_cr = False
    for char in str(text or ""):
        if char == "\n":
            current = 0
            previous_cr = False
        elif char == "\r":
            current = 0
            previous_cr = True
        else:
            if previous_cr:
                previous_cr = False
            current += 1
            if current > TOOL_OUTPUT_LONG_LINE_CHARS:
                return True
    return False


def _utf8_prefix(text, max_bytes):
    if max_bytes <= 0:
        return ""
    encoded = str(text or "").encode("utf-8")
    if len(encoded) <= max_bytes:
        return str(text or "")
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _utf8_suffix(text, max_bytes):
    if max_bytes <= 0:
        return ""
    encoded = str(text or "").encode("utf-8")
    if len(encoded) <= max_bytes:
        return str(text or "")
    start = len(encoded) - max_bytes
    while start < len(encoded) and (encoded[start] & 0xC0) == 0x80:
        start += 1
    return encoded[start:].decode("utf-8", errors="ignore")


def _fits(text, max_lines=TOOL_OUTPUT_MAX_LINES, max_bytes=TOOL_OUTPUT_MAX_BYTES):
    value = str(text or "")
    return _line_count(value) <= max_lines and len(value.encode("utf-8")) <= max_bytes


def fits_tool_output(text):
    return _fits(text)


def _ensure_tool_output_dir():
    root = TOOL_OUTPUT_DIR
    if root.exists() and root.is_symlink():
        raise ToolOutputStorageError("Tool output directory cannot be a symlink.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir():
        raise ToolOutputStorageError("Tool output path is not a directory.")
    if os.name != "nt":
        try:
            root.chmod(0o700)
        except OSError as error:
            raise ToolOutputStorageError(
                "Failed to secure the tool output directory."
            ) from error
    return root.resolve(strict=False)


def _cache_usage_bytes():
    total = 0
    root = _ensure_tool_output_dir()
    for path in root.glob("tool_*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _trim_cache_to_budget(required_bytes):
    required = max(0, int(required_bytes or 0))
    root = _ensure_tool_output_dir()
    usage = _cache_usage_bytes()
    if usage + required <= TOOL_OUTPUT_CACHE_MAX_BYTES:
        return
    candidates = []
    for path in root.glob("tool_*"):
        try:
            if path.is_file() and not path.name.endswith(".part"):
                stat = path.stat()
                candidates.append((stat.st_mtime, path, stat.st_size))
        except OSError:
            continue
    recent_cutoff = time.time() - 5 * 60
    for _mtime, path, size in sorted(candidates):
        if _mtime >= recent_cutoff:
            continue
        try:
            path.unlink()
            usage = max(0, usage - size)
        except OSError:
            continue
        if usage + required <= TOOL_OUTPUT_CACHE_MAX_BYTES:
            return


def _check_storage_capacity(expected_bytes=0):
    expected = max(0, int(expected_bytes or 0))
    if expected > TOOL_OUTPUT_MAX_ARTIFACT_BYTES:
        raise ToolOutputStorageLimitError(
            f"Artifact exceeds internal safety limit of {TOOL_OUTPUT_MAX_ARTIFACT_BYTES} bytes."
        )
    root = _ensure_tool_output_dir()
    try:
        free = shutil.disk_usage(root).free
    except OSError as error:
        raise ToolOutputStorageError("Unable to inspect artifact storage capacity.") from error
    if free - expected < TOOL_OUTPUT_MIN_FREE_BYTES:
        raise ToolOutputStorageLimitError(
            "Artifact storage stopped to preserve minimum free disk space."
        )
    if _cache_usage_bytes() + expected > TOOL_OUTPUT_CACHE_MAX_BYTES:
        cleanup_tool_outputs(force=True)
        _trim_cache_to_budget(expected)
        if _cache_usage_bytes() + expected > TOOL_OUTPUT_CACHE_MAX_BYTES:
            raise ToolOutputStorageLimitError(
                f"Artifact cache exceeds internal safety limit of {TOOL_OUTPUT_CACHE_MAX_BYTES} bytes."
            )


def cleanup_tool_outputs(force=False):
    global _LAST_CLEANUP
    now = time.time()
    with _CLEANUP_LOCK:
        if not force and now - _LAST_CLEANUP < TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS:
            return
        _LAST_CLEANUP = now
        try:
            root = _ensure_tool_output_dir()
            cutoff = now - TOOL_OUTPUT_RETENTION_SECONDS
            for path in root.glob("tool_*"):
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue
        except OSError:
            return


def ensure_cleanup_thread():
    global _CLEANUP_THREAD_STARTED
    with _CLEANUP_LOCK:
        if _CLEANUP_THREAD_STARTED:
            return
        _CLEANUP_THREAD_STARTED = True

    def cleanup_loop():
        while True:
            time.sleep(TOOL_OUTPUT_CLEANUP_INTERVAL_SECONDS)
            cleanup_tool_outputs(force=True)

    threading.Thread(
        target=cleanup_loop,
        name="omni-tool-output-cleanup",
        daemon=True,
    ).start()


def new_tool_output_path(suffix=".txt"):
    cleanup_tool_outputs()
    root = _ensure_tool_output_dir()
    return (
        root / f"tool_{int(time.time() * 1000)}_{uuid.uuid4().hex}{suffix}"
    ).resolve(strict=False)


def artifact_uri(path):
    resolved = Path(path).resolve(strict=False)
    if not is_tool_output_path(resolved):
        raise ToolOutputStorageError(f"Not a managed artifact path: {resolved}")
    return f"{TOOL_OUTPUT_URI_SCHEME}://{resolved.name}"


def resolve_artifact_uri(value):
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() != TOOL_OUTPUT_URI_SCHEME:
        return None
    if parsed.params or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ToolOutputStorageError(f"Invalid artifact URI: {text}")
    name = parsed.netloc
    if not re.fullmatch(r"tool_[A-Za-z0-9_.-]+", name or ""):
        raise ToolOutputStorageError(f"Invalid artifact identifier: {name!r}")
    path = (_ensure_tool_output_dir() / name).resolve(strict=False)
    if not is_tool_output_path(path):
        raise ToolOutputStorageError(f"Artifact is outside the managed directory: {text}")
    return path


def is_tool_output_path(path):
    resolved = Path(path).resolve(strict=False)
    root = _ensure_tool_output_dir()
    try:
        return os.path.commonpath(
            [os.path.normcase(str(root)), os.path.normcase(str(resolved))]
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _exclusive_open(path, mode="wb", encoding=None):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    return os.fdopen(fd, mode, encoding=encoding) if "b" not in mode else os.fdopen(fd, mode)


class _LimitedTextSink:
    def __init__(self, sink, max_bytes=TOOL_OUTPUT_MAX_ARTIFACT_BYTES):
        self.sink = sink
        self.max_bytes = int(max_bytes)
        self.written_bytes = 0

    def write(self, value):
        text = str(value or "")
        size = len(text.encode("utf-8"))
        if self.written_bytes + size > self.max_bytes:
            raise ToolOutputStorageLimitError(
                "Wrapped view exceeds the internal artifact size safety limit."
            )
        self.sink.write(text)
        self.written_bytes += size


def write_tool_output(text):
    value = str(text or "")
    encoded = value.encode("utf-8")
    _check_storage_capacity(len(encoded))
    final_path = new_tool_output_path()
    part_path = final_path.with_suffix(final_path.suffix + ".part")
    try:
        with _exclusive_open(part_path, "wb") as sink:
            sink.write(encoded)
            sink.flush()
        os.replace(part_path, final_path)
        if os.name != "nt":
            final_path.chmod(0o600)
    finally:
        try:
            if part_path.exists():
                part_path.unlink()
        except OSError:
            pass
    return final_path


def _scan_text_file(path):
    total_chars = 0
    newline_count = 0
    current_line_chars = 0
    has_long_line = False
    ends_with_newline = False
    with Path(path).open("r", encoding="utf-8", errors="replace", newline=None) as source:
        while True:
            chunk = source.read(8192)
            if not chunk:
                break
            total_chars += len(chunk)
            ends_with_newline = chunk.endswith("\n")
            start = 0
            while True:
                newline = chunk.find("\n", start)
                if newline < 0:
                    current_line_chars += len(chunk) - start
                    if current_line_chars > TOOL_OUTPUT_LONG_LINE_CHARS:
                        has_long_line = True
                    break
                current_line_chars += newline - start
                if current_line_chars > TOOL_OUTPUT_LONG_LINE_CHARS:
                    has_long_line = True
                newline_count += 1
                current_line_chars = 0
                start = newline + 1
    total_lines = 0
    if total_chars:
        total_lines = newline_count + (0 if ends_with_newline else 1)
    return total_lines, has_long_line


def _write_view_segment(sink, source_line, segment_index, char_start, text):
    char_end = char_start + len(text) - 1
    if not text:
        char_end = char_start - 1
    sink.write(
        f"[source line {source_line}, segment {segment_index}, "
        f"chars {char_start}-{char_end}] {text}\n"
    )


def _write_view_line_end(sink, source_line, newline_kind):
    sink.write(f"[source line {source_line}, end, newline {newline_kind}]\n")


def _create_wrapped_view(source_path):
    source_size = Path(source_path).stat().st_size
    _check_storage_capacity(min(source_size * 2 + 4096, TOOL_OUTPUT_MAX_ARTIFACT_BYTES))
    view_path = new_tool_output_path(suffix=".view.txt")
    part_path = view_path.with_suffix(view_path.suffix + ".part")
    source_line = 1
    segment_index = 1
    char_start = 1
    segment = ""
    saw_content = False
    line_has_content = False
    pending_cr = False

    def feed_content(value, sink):
        nonlocal segment_index, char_start, segment, saw_content, line_has_content
        if not value:
            return
        saw_content = True
        line_has_content = True
        position = 0
        while position < len(value):
            room = TOOL_OUTPUT_VIEW_SEGMENT_CHARS - len(segment)
            take = value[position : position + room]
            segment += take
            position += len(take)
            if len(segment) >= TOOL_OUTPUT_VIEW_SEGMENT_CHARS:
                _write_view_segment(
                    sink, source_line, segment_index, char_start, segment
                )
                char_start += len(segment)
                segment_index += 1
                segment = ""

    def finish_line(newline_kind, sink):
        nonlocal source_line, segment_index, char_start, segment, line_has_content
        if segment or segment_index == 1:
            _write_view_segment(
                sink, source_line, segment_index, char_start, segment
            )
        _write_view_line_end(sink, source_line, newline_kind)
        source_line += 1
        segment_index = 1
        char_start = 1
        segment = ""
        line_has_content = False

    try:
        with Path(source_path).open(
            "r", encoding="utf-8", errors="replace", newline=""
        ) as source, _exclusive_open(
            part_path, "w", encoding="utf-8"
        ) as raw_sink:
            sink = _LimitedTextSink(raw_sink)
            while True:
                chunk = source.read(8192)
                if not chunk:
                    break
                saw_content = True
                position = 0
                if pending_cr:
                    if chunk.startswith("\n"):
                        finish_line("CRLF", sink)
                        position = 1
                    else:
                        finish_line("CR", sink)
                    pending_cr = False
                while position < len(chunk):
                    match = re.search(r"[\r\n]", chunk[position:])
                    if match is None:
                        feed_content(chunk[position:], sink)
                        break
                    newline = position + match.start()
                    feed_content(chunk[position:newline], sink)
                    if chunk[newline] == "\n":
                        finish_line("LF", sink)
                        position = newline + 1
                        continue
                    if newline + 1 < len(chunk):
                        if chunk[newline + 1] == "\n":
                            finish_line("CRLF", sink)
                            position = newline + 2
                        else:
                            finish_line("CR", sink)
                            position = newline + 1
                        continue
                    pending_cr = True
                    position = len(chunk)
            if pending_cr:
                finish_line("CR", sink)
            elif line_has_content:
                if segment or segment_index == 1:
                    _write_view_segment(
                        sink, source_line, segment_index, char_start, segment
                    )
                _write_view_line_end(sink, source_line, "NONE")
            elif not saw_content:
                _write_view_segment(sink, 1, 1, 1, "")
                _write_view_line_end(sink, 1, "NONE")
        os.replace(part_path, view_path)
        if os.name != "nt":
            view_path.chmod(0o600)
        return view_path
    finally:
        try:
            if part_path.exists():
                part_path.unlink()
        except OSError:
            pass

def ensure_wrapped_view(source_path, cache=None, has_long_line=None):
    source_path = Path(source_path).resolve(strict=False)
    try:
        stat = source_path.stat()
    except OSError:
        return None
    cache_key = (str(source_path), stat.st_size, stat.st_mtime_ns)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached and Path(cached).is_file():
            move_to_end = getattr(cache, "move_to_end", None)
            if callable(move_to_end):
                move_to_end(cache_key)
            return Path(cached)
    if has_long_line is None:
        _total_lines, has_long_line = _scan_text_file(source_path)
    if not has_long_line:
        return None
    try:
        view_path = _create_wrapped_view(source_path)
    except (OSError, ToolOutputStorageError):
        return None
    if cache is not None:
        stale = [key for key in cache if key[0] == str(source_path) and key != cache_key]
        for key in stale:
            cache.pop(key, None)
        cache[cache_key] = view_path
        popitem = getattr(cache, "popitem", None)
        while len(cache) > 128 and callable(popitem):
            try:
                popitem(last=False)
            except TypeError:
                break
    return view_path


def _bounded_line_windows(text, max_lines, max_bytes, strategy="head_tail"):
    value = str(text or "")
    if max_lines <= 0 or max_bytes <= 0 or not value:
        return "", 0, 0
    lines = value.splitlines()
    if not lines:
        return "", 0, 0

    if strategy == "tail":
        selected = deque()
        used = 0
        for line in reversed(lines):
            line_bytes = len(line.encode("utf-8"))
            separator = 1 if selected else 0
            if len(selected) >= max_lines or used + separator + line_bytes > max_bytes:
                if not selected:
                    partial = _utf8_suffix(line, max_bytes)
                    if partial:
                        selected.appendleft(partial)
                        used = len(partial.encode("utf-8"))
                break
            selected.appendleft(line)
            used += separator + line_bytes
        result = "\n".join(selected)
        return result, len(selected), len(result.encode("utf-8"))

    head_lines = max(1, int(max_lines * TOOL_OUTPUT_HEAD_RATIO))
    tail_lines = max(0, max_lines - head_lines - 1)
    head_bytes = max(1, int(max_bytes * TOOL_OUTPUT_HEAD_RATIO))
    marker = "... omitted from preview ..."
    marker_bytes = len(marker.encode("utf-8")) + 2
    tail_bytes = max(0, max_bytes - head_bytes - marker_bytes)

    head = []
    used = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8"))
        separator = 1 if head else 0
        if len(head) >= head_lines or used + separator + line_bytes > head_bytes:
            if not head:
                partial = _utf8_prefix(line, head_bytes)
                if partial:
                    head.append(partial)
            break
        head.append(line)
        used += separator + line_bytes

    tail = deque()
    used = 0
    for line in reversed(lines[len(head):]):
        line_bytes = len(line.encode("utf-8"))
        separator = 1 if tail else 0
        if len(tail) >= tail_lines or used + separator + line_bytes > tail_bytes:
            if not tail and tail_bytes > 0:
                partial = _utf8_suffix(line, tail_bytes)
                if partial:
                    tail.appendleft(partial)
            break
        tail.appendleft(line)
        used += separator + line_bytes

    parts = []
    if head:
        parts.append("\n".join(head))
    if len(head) + len(tail) < len(lines):
        parts.append(marker)
    if tail:
        parts.append("\n".join(tail))
    result = "\n".join(parts)
    return result, len(head) + len(tail), len(result.encode("utf-8"))



def _bounded_path_windows(path, max_lines, max_bytes, strategy="head_tail"):
    if max_lines <= 0 or max_bytes <= 0:
        return "", 0, 0
    source_path = Path(path)
    if strategy == "tail":
        selected = deque()
        used = 0
        with source_path.open(
            "r", encoding="utf-8", errors="replace", newline=None
        ) as source:
            for raw_line in source:
                line = raw_line.rstrip("\r\n")
                line_bytes = len(line.encode("utf-8"))
                selected.append((line, line_bytes))
                used += line_bytes + (1 if len(selected) > 1 else 0)
                while selected and (
                    len(selected) > max_lines or used > max_bytes
                ):
                    removed, removed_bytes = selected.popleft()
                    used -= removed_bytes
                    if selected:
                        used -= 1
        if not selected:
            return "", 0, 0
        result = "\n".join(line for line, _ in selected)
        if len(result.encode("utf-8")) > max_bytes:
            result = _utf8_suffix(result, max_bytes)
        return result, _line_count(result), len(result.encode("utf-8"))

    head_lines = max(1, int(max_lines * TOOL_OUTPUT_HEAD_RATIO))
    tail_lines = max(0, max_lines - head_lines - 1)
    marker = "... omitted from preview ..."
    marker_cost = len(marker.encode("utf-8")) + 2
    head_bytes = max(1, int(max_bytes * TOOL_OUTPUT_HEAD_RATIO))
    tail_bytes = max(0, max_bytes - head_bytes - marker_cost)
    head = []
    head_used = 0
    tail = deque()
    tail_used = 0
    head_complete = False
    with source_path.open(
        "r", encoding="utf-8", errors="replace", newline=None
    ) as source:
        for raw_line in source:
            line = raw_line.rstrip("\r\n")
            line_bytes = len(line.encode("utf-8"))
            if not head_complete:
                separator = 1 if head else 0
                if (
                    len(head) < head_lines
                    and head_used + separator + line_bytes <= head_bytes
                ):
                    head.append(line)
                    head_used += separator + line_bytes
                    continue
                if not head:
                    partial = _utf8_prefix(line, head_bytes)
                    if partial:
                        head.append(partial)
                head_complete = True
            if tail_lines <= 0 or tail_bytes <= 0:
                continue
            tail.append((line, line_bytes))
            tail_used += line_bytes + (1 if len(tail) > 1 else 0)
            while tail and (
                len(tail) > tail_lines or tail_used > tail_bytes
            ):
                _removed, removed_bytes = tail.popleft()
                tail_used -= removed_bytes
                if tail:
                    tail_used -= 1
    parts = []
    if head:
        parts.append("\n".join(head))
    if tail:
        parts.append(marker)
        parts.append("\n".join(line for line, _ in tail))
    result = "\n".join(parts)
    return result, _line_count(result), len(result.encode("utf-8"))

def _bounded_record_path_windows(path, max_lines, max_bytes, mode):
    source_path = Path(path)
    try:
        size = source_path.stat().st_size
    except OSError:
        return "", 0, 0
    if size > TOOL_OUTPUT_RECORD_PARSE_MAX_BYTES:
        return _bounded_path_windows(
            source_path, max_lines, max_bytes, "head_tail"
        )
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", 0, 0
    return _bounded_record_windows(text, max_lines, max_bytes, mode)


def _split_records(text, mode):
    value = str(text or "")
    if mode == "diff":
        matches = list(re.finditer(r"(?m)^diff --git ", value))
        if not matches:
            return []
        records = []
        if matches[0].start() > 0:
            records.append(value[: matches[0].start()].rstrip("\n"))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            records.append(value[match.start():end].rstrip("\n"))
        return [item for item in records if item]
    return []


def _bounded_record_windows(text, max_lines, max_bytes, mode):
    records = _split_records(text, mode)
    if not records:
        return _bounded_line_windows(text, max_lines, max_bytes, "head_tail")
    return _bounded_records_list(records, max_lines, max_bytes)


def _bounded_records_list(records, max_lines, max_bytes):
    values = [str(record or "") for record in list(records or []) if str(record or "")]
    if not values or max_lines <= 0 or max_bytes <= 0:
        return "", 0, 0
    if len(values) == 1:
        return _bounded_line_windows(values[0], max_lines, max_bytes, "head_tail")

    marker = "... records omitted from preview ..."
    marker_bytes = len(marker.encode("utf-8"))
    content_lines = max(0, max_lines - 3)
    content_bytes = max(0, max_bytes - marker_bytes - 4)
    head_line_budget = max(1, int(content_lines * TOOL_OUTPUT_HEAD_RATIO))
    tail_line_budget = max(0, content_lines - head_line_budget)
    head_byte_budget = max(1, int(content_bytes * TOOL_OUTPUT_HEAD_RATIO))
    tail_byte_budget = max(0, content_bytes - head_byte_budget)

    def collect(indices, line_budget, byte_budget, append_left=False):
        selected = deque() if append_left else []
        used_lines = 0
        used_bytes = 0
        selected_indices = []
        for index in indices:
            record = values[index]
            separator_lines = 1 if selected else 0
            separator_bytes = 2 if selected else 0
            available_lines = line_budget - used_lines - separator_lines
            available_bytes = byte_budget - used_bytes - separator_bytes
            if available_lines <= 0 or available_bytes <= 0:
                break
            record_lines = _line_count(record)
            record_bytes = len(record.encode("utf-8"))
            if record_lines <= available_lines and record_bytes <= available_bytes:
                piece = record
            else:
                piece, _, _ = _bounded_line_windows(
                    record, available_lines, available_bytes, "head_tail"
                )
            if not piece:
                break
            if append_left:
                selected.appendleft(piece)
                selected_indices.insert(0, index)
            else:
                selected.append(piece)
                selected_indices.append(index)
            used_lines += separator_lines + _line_count(piece)
            used_bytes += separator_bytes + len(piece.encode("utf-8"))
            if piece != record:
                break
        return list(selected), selected_indices

    head, head_indices = collect(
        range(len(values)), head_line_budget, head_byte_budget
    )
    tail, tail_indices = collect(
        range(len(values) - 1, -1, -1),
        tail_line_budget,
        tail_byte_budget,
        append_left=True,
    )
    head_set = set(head_indices)
    filtered_tail = [
        piece for piece, index in zip(tail, tail_indices) if index not in head_set
    ]
    tail_indices = [index for index in tail_indices if index not in head_set]

    parts = []
    if head:
        parts.append("\n\n".join(head))
    covered = head_set | set(tail_indices)
    if len(covered) < len(values):
        parts.append(marker)
    if filtered_tail:
        parts.append("\n\n".join(filtered_tail))
    result = "\n\n".join(parts)
    if not _fits(result, max_lines=max_lines, max_bytes=max_bytes):
        result, _, _ = _bounded_line_windows(
            result,
            max_lines,
            max_bytes,
            "head_tail",
        )
    return result, _line_count(result), len(result.encode("utf-8"))


@dataclass
class ToolOutputValue:
    text: str
    records: tuple[str, ...] = ()
    record_mode: str = ""


@dataclass
class ToolOutputArtifact:
    raw_path: Path
    total_lines: int
    total_bytes: int
    strategy: str = "head_tail"
    record_mode: str = ""
    view_path: Path | None = None
    source_text: str | None = None
    records: tuple[str, ...] = ()
    preview_text: str | None = None
    complete: bool = True
    captured_bytes: int | None = None

    @classmethod
    def from_text(
        cls,
        text,
        strategy="head_tail",
        record_mode="",
        records=None,
        view_cache=None,
    ):
        value = str(text or "")
        total_bytes = len(value.encode("utf-8"))
        complete = total_bytes <= TOOL_OUTPUT_MAX_ARTIFACT_BYTES
        captured = value if complete else _utf8_prefix(value, TOOL_OUTPUT_MAX_ARTIFACT_BYTES)
        raw_path = write_tool_output(captured)
        view_path = ensure_wrapped_view(
            raw_path,
            cache=view_cache,
            has_long_line=_text_has_long_line(captured),
        )
        return cls(
            raw_path=raw_path,
            total_lines=_line_count(value),
            total_bytes=total_bytes,
            strategy=strategy,
            record_mode=record_mode,
            view_path=view_path,
            source_text=value if complete else None,
            records=tuple(str(item or "") for item in list(records or [])),
            complete=complete,
            captured_bytes=len(captured.encode("utf-8")),
        )

    @classmethod
    def from_path(
        cls,
        path,
        strategy="tail",
        record_mode="",
        records=None,
        view_cache=None,
        total_lines=None,
        total_bytes=None,
        has_long_line=None,
        preview_text=None,
        complete=True,
    ):
        raw_path = Path(path).resolve(strict=False)
        if total_lines is None or has_long_line is None:
            scanned_lines, scanned_long_line = _scan_text_file(raw_path)
            if total_lines is None:
                total_lines = scanned_lines
            if has_long_line is None:
                has_long_line = scanned_long_line
        view_path = ensure_wrapped_view(
            raw_path,
            cache=view_cache,
            has_long_line=has_long_line,
        )
        captured = raw_path.stat().st_size
        return cls(
            raw_path=raw_path,
            total_lines=int(total_lines or 0),
            total_bytes=int(total_bytes if total_bytes is not None else captured),
            strategy=strategy,
            record_mode=record_mode,
            view_path=view_path,
            source_text=None,
            records=tuple(str(item or "") for item in list(records or [])),
            preview_text=preview_text,
            complete=bool(complete),
            captured_bytes=captured,
        )

    def _preview_source(self):
        if self.preview_text is not None:
            return self.preview_text
        if self.source_text is not None and (
            self.view_path is None or self.record_mode or self.records
        ):
            return self.source_text
        return None

    def _preview_path(self):
        return self.view_path or self.raw_path

    @staticmethod
    def _prepare_aux(label, value):
        text = str(value or "")
        if not text:
            return ""
        if _fits(
            text,
            max_lines=TOOL_OUTPUT_AUX_MAX_LINES,
            max_bytes=TOOL_OUTPUT_AUX_MAX_BYTES,
        ):
            return text
        try:
            path = write_tool_output(text)
        except ToolOutputStorageError as error:
            return f"\n[{label} could not be preserved: {error}]\n"
        preview, _, _ = _bounded_line_windows(
            text,
            TOOL_OUTPUT_AUX_MAX_LINES,
            TOOL_OUTPUT_AUX_MAX_BYTES - 512,
            "head_tail",
        )
        return (
            f"\n[{label} preview limited; full content: {artifact_uri(path)}]\n"
            f"{preview}"
        )

    def render(self, allow_subagent_hint=True, prefix="", suffix=""):
        policy_label = {
            "tail": "tail",
            "head_tail": "75% head + 25% tail",
        }.get(self.strategy, self.strategy)
        hint = (
            "Use dispatch_subagent with a reader, grep, or read_file(offset, limit) "
            "to inspect the preserved output."
            if allow_subagent_hint
            else "Use grep or read_file(offset, limit) to inspect the preserved output."
        )
        raw_label = "Full output" if self.complete else "Captured output"
        completeness = (
            "[Tool output preview limited; full content preserved]"
            if self.complete
            else "[Tool output capture stopped at an internal storage safety limit]"
        )
        capture_line = ""
        if not self.complete:
            capture_line = (
                f"Captured: {int(self.captured_bytes or 0)} UTF-8 bytes; "
                "the producer was stopped and this artifact is incomplete.\n"
            )
        view_line = (
            f"Readable wrapped view: {artifact_uri(self.view_path)}\n"
            if self.view_path is not None
            else ""
        )
        total_label = "Total" if self.complete else "Total observed before safety stop"
        base = (
            f"{completeness}\n"
            f"{total_label}: {self.total_lines} lines, "
            f"{self.total_bytes} UTF-8 bytes\n"
            f"{capture_line}"
            f"Preview policy: {policy_label}\n"
            f"{raw_label}: {artifact_uri(self.raw_path)}\n"
            f"{view_line}"
            f"{hint}"
        )
        prefix_text = self._prepare_aux("prefix", prefix)
        suffix_text = self._prepare_aux("suffix", suffix)
        separator = "\n\n--- preview ---\n"
        preview = ""
        shown_lines = 0
        shown_bytes = 0
        source = self._preview_source()
        for _ in range(3):
            metadata = (
                f"\nPreview payload: {shown_lines} lines, {shown_bytes} UTF-8 bytes"
                if preview
                else ""
            )
            fixed = prefix_text + base + metadata + separator + suffix_text
            remaining_lines = max(0, TOOL_OUTPUT_MAX_LINES - _line_count(fixed))
            remaining_bytes = max(
                0, TOOL_OUTPUT_MAX_BYTES - len(fixed.encode("utf-8"))
            )
            if self.records:
                preview, shown_lines, shown_bytes = _bounded_records_list(
                    self.records, remaining_lines, remaining_bytes
                )
            elif source is None and self.record_mode:
                preview, shown_lines, shown_bytes = _bounded_record_path_windows(
                    self.raw_path,
                    remaining_lines,
                    remaining_bytes,
                    self.record_mode,
                )
            elif source is None:
                preview, shown_lines, shown_bytes = _bounded_path_windows(
                    self._preview_path(),
                    remaining_lines,
                    remaining_bytes,
                    self.strategy,
                )
            elif self.record_mode:
                preview, shown_lines, shown_bytes = _bounded_record_windows(
                    source, remaining_lines, remaining_bytes, self.record_mode
                )
            else:
                preview, shown_lines, shown_bytes = _bounded_line_windows(
                    source, remaining_lines, remaining_bytes, self.strategy
                )
            shown_lines = _line_count(preview)
            shown_bytes = len(preview.encode("utf-8"))

        result = prefix_text + base
        if preview:
            result += (
                f"\nPreview payload: {shown_lines} lines, {shown_bytes} UTF-8 bytes"
                + separator
                + preview
            )
        result += suffix_text
        if not _fits(result):
            minimal = (
                f"{completeness}\n"
                f"{raw_label}: {artifact_uri(self.raw_path)}\n"
                f"{view_line}"
                f"{hint}"
            )
            result = minimal
        if not _fits(result):
            raise ToolOutputStorageError(
                "Internal error: tool output envelope exceeds its fixed safety budget."
            )
        return result


class ToolOutputWriter:
    def __init__(self):
        self._buffer = []
        self._buffer_bytes = 0
        self._line_breaks = 0
        self._has_text = False
        self._ends_with_newline = False
        self._previous_cr = False
        self._current_line_chars = 0
        self._has_long_line = False
        self._path = None
        self._part_path = None
        self._sink = None
        self._captured_bytes = 0
        self._attempted_bytes = 0
        self._storage_limited = False
        self._next_capacity_check = 16 * 1024 * 1024
        self._head = []
        self._head_bytes = 0
        self._tail = deque()
        self._tail_bytes = 0

    @property
    def storage_limited(self):
        return self._storage_limited

    def abort(self):
        if self._sink is not None:
            try:
                self._sink.close()
            except Exception:
                pass
            self._sink = None
        if self._part_path is not None:
            try:
                if self._part_path.exists():
                    self._part_path.unlink()
            except OSError:
                pass
            self._part_path = None

    def __del__(self):
        self.abort()

    def _track_text(self, value):
        if not value:
            return
        self._has_text = True
        for char in value:
            if char == "\n":
                if not self._previous_cr:
                    self._line_breaks += 1
                self._previous_cr = False
                self._ends_with_newline = True
                self._current_line_chars = 0
            elif char == "\r":
                self._line_breaks += 1
                self._previous_cr = True
                self._ends_with_newline = True
                self._current_line_chars = 0
            else:
                self._previous_cr = False
                self._ends_with_newline = False
                self._current_line_chars += 1
                if self._current_line_chars > TOOL_OUTPUT_LONG_LINE_CHARS:
                    self._has_long_line = True

    def _update_tail(self, value):
        if not value:
            return
        if self._head_bytes < TOOL_OUTPUT_MAX_BYTES:
            remaining = TOOL_OUTPUT_MAX_BYTES - self._head_bytes
            head_piece = _utf8_prefix(value, remaining)
            if head_piece:
                self._head.append(head_piece)
                self._head_bytes += len(head_piece.encode("utf-8"))
        value_bytes = len(value.encode("utf-8"))
        if value_bytes >= TOOL_OUTPUT_MAX_BYTES:
            tail_piece = _utf8_suffix(value, TOOL_OUTPUT_MAX_BYTES)
            self._tail.clear()
            self._tail_bytes = len(tail_piece.encode("utf-8"))
            if tail_piece:
                self._tail.append(tail_piece)
            return
        self._tail.append(value)
        self._tail_bytes += value_bytes
        while self._tail and self._tail_bytes > TOOL_OUTPUT_MAX_BYTES:
            removed = self._tail.popleft()
            self._tail_bytes -= len(removed.encode("utf-8"))

    def _start_stream_file(self):
        _check_storage_capacity(0)
        self._path = new_tool_output_path()
        self._part_path = self._path.with_suffix(self._path.suffix + ".part")
        self._sink = _exclusive_open(self._part_path, "wb")
        initial = "".join(self._buffer).encode("utf-8")
        if initial:
            self._sink.write(initial)
            self._captured_bytes += len(initial)
        self._sink.flush()
        self._buffer.clear()

    def write(self, text):
        if self._storage_limited:
            return False
        value = str(text or "")
        if not value:
            return True
        encoded = value.encode("utf-8")
        self._attempted_bytes += len(encoded)
        self._track_text(value)
        self._update_tail(value)
        if self._sink is None:
            self._buffer.append(value)
            self._buffer_bytes += len(encoded)
            logical_lines = self._line_breaks + (
                0 if self._ends_with_newline else (1 if self._has_text else 0)
            )
            if (
                self._buffer_bytes > TOOL_OUTPUT_MAX_BYTES
                or logical_lines > TOOL_OUTPUT_MAX_LINES
            ):
                self._start_stream_file()
            return True

        if self._captured_bytes + len(encoded) >= self._next_capacity_check:
            try:
                _check_storage_capacity(len(encoded))
            except ToolOutputStorageLimitError:
                self._storage_limited = True
                return False
            self._next_capacity_check = self._captured_bytes + len(encoded) + 16 * 1024 * 1024
        remaining = TOOL_OUTPUT_MAX_ARTIFACT_BYTES - self._captured_bytes
        if len(encoded) > remaining:
            if remaining > 0:
                prefix = encoded[:remaining].decode("utf-8", errors="ignore").encode("utf-8")
                self._sink.write(prefix)
                self._captured_bytes += len(prefix)
            self._sink.flush()
            self._storage_limited = True
            return False
        self._sink.write(encoded)
        self._captured_bytes += len(encoded)
        return True

    def _logical_lines(self):
        return self._line_breaks + (
            0 if self._ends_with_newline else (1 if self._has_text else 0)
        )

    def _close_stream_file(self):
        if self._sink is not None:
            self._sink.flush()
            self._sink.close()
            self._sink = None
        if self._part_path is not None and self._path is not None:
            os.replace(self._part_path, self._path)
            if os.name != "nt":
                self._path.chmod(0o600)
            self._part_path = None

    def finalize(
        self,
        strategy="tail",
        record_mode="",
        records=None,
        allow_subagent_hint=True,
        view_cache=None,
        prefix="",
        suffix="",
    ):
        if self._sink is None and self._path is None:
            value = "".join(self._buffer)
            combined = str(prefix or "") + value + str(suffix or "")
            if _fits(combined):
                return combined
            artifact = ToolOutputArtifact.from_text(
                value,
                strategy=strategy,
                record_mode=record_mode,
                records=records,
                view_cache=view_cache,
            )
            return artifact.render(
                allow_subagent_hint=allow_subagent_hint,
                prefix=prefix,
                suffix=suffix,
            )

        self._close_stream_file()
        tail_text = "".join(self._tail)
        tail_preview, _, _ = _bounded_line_windows(
            tail_text,
            TOOL_OUTPUT_MAX_LINES,
            TOOL_OUTPUT_MAX_BYTES,
            "tail",
        )
        if record_mode:
            preview_text = None
        elif strategy == "tail":
            preview_text = tail_preview
        else:
            head_text = "".join(self._head)
            combined_window_bytes = len(head_text.encode("utf-8")) + len(
                tail_preview.encode("utf-8")
            )
            if self._attempted_bytes <= combined_window_bytes:
                preview_text = None
            else:
                preview_text = (
                    head_text
                    + "\n... omitted from preview ...\n"
                    + tail_preview
                )
        artifact = ToolOutputArtifact.from_path(
            self._path,
            strategy=strategy,
            record_mode=record_mode,
            records=records,
            view_cache=view_cache,
            total_lines=self._logical_lines(),
            total_bytes=self._attempted_bytes,
            has_long_line=self._has_long_line,
            preview_text=preview_text,
            complete=not self._storage_limited,
        )
        return artifact.render(
            allow_subagent_hint=allow_subagent_hint,
            prefix=prefix,
            suffix=suffix,
        )


def finalize_tool_output(
    text,
    *,
    strategy="head_tail",
    record_mode="",
    records=None,
    allow_subagent_hint=True,
    view_cache=None,
):
    if isinstance(text, ToolOutputValue):
        value = str(text.text or "")
        records = tuple(text.records or records or ())
        record_mode = text.record_mode or record_mode
    else:
        value = str(text or "")
    if _fits(value):
        return value
    artifact = ToolOutputArtifact.from_text(
        value,
        strategy=strategy,
        record_mode=record_mode,
        records=records,
        view_cache=view_cache,
    )
    return artifact.render(allow_subagent_hint=allow_subagent_hint)
