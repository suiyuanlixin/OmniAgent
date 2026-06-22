import base64
import mimetypes
import re
from pathlib import Path

from ui import clean_display_text
from tools import MAX_READ_CHARS


FILE_REFERENCE_PATTERN = re.compile(r"\[([^\[\]\r\n]+)\]")
IMAGE_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
VIDEO_MEDIA_TYPES = {
    "video/mp4",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-matroska",
}
IMAGE_FILE_MAX_BYTES = 10 * 1024 * 1024
VIDEO_FILE_MAX_BYTES = 50 * 1024 * 1024
MULTIMODAL_REQUEST_MAX_BYTES = 64 * 1024 * 1024


def _is_file_reference_path(path_text):
    value = str(path_text or "").strip()
    if not value:
        return False
    if value.startswith(("/", "\\", "~")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    return value.startswith(("./", ".\\", "../", "..\\"))


def _external_file_references(user_input):
    references = []
    seen = set()
    for match in FILE_REFERENCE_PATTERN.finditer(user_input):
        path_text = match.group(1).strip()
        if not _is_file_reference_path(path_text):
            continue
        if path_text in seen:
            continue
        seen.add(path_text)
        references.append(path_text)
    return references


def _resolve_external_file_reference(path_text):
    try:
        path = Path(path_text).expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError(f"Referenced file does not exist: {path_text}") from error

    if not path.is_file():
        raise ValueError(f"Referenced path is not a file: {path}")
    return path


def _guess_media_type_from_header(path):
    try:
        with path.open("rb") as file:
            header = file.read(32)
    except OSError:
        return None, None

    if header.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image", "image/webp"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "video", "video/x-msvideo"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/x-matroska"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        suffix = path.suffix.lower()
        if suffix == ".mov":
            return "video", "video/quicktime"
        return "video", "video/mp4"
    return None, None


def _detect_reference_media_type(path):
    kind, mime_type = _guess_media_type_from_header(path)
    if kind and mime_type:
        return kind, mime_type

    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type in IMAGE_MEDIA_TYPES:
        return "image", mime_type
    if mime_type in VIDEO_MEDIA_TYPES:
        return "video", mime_type
    return "text", ""


def _read_external_file_reference(path_text):
    path = _resolve_external_file_reference(path_text)

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ValueError(f"Failed to read referenced file: {path}") from error

    truncated = content[:MAX_READ_CHARS]
    if len(content) > MAX_READ_CHARS:
        truncated += (
            f"\n\n[referenced file truncated after {MAX_READ_CHARS} characters]"
        )
    return path, truncated


def _read_external_media_reference(path_text, encoded_bytes_before=0):
    path = _resolve_external_file_reference(path_text)
    kind, mime_type = _detect_reference_media_type(path)
    if kind not in {"image", "video"}:
        return None

    size = path.stat().st_size
    max_bytes = IMAGE_FILE_MAX_BYTES if kind == "image" else VIDEO_FILE_MAX_BYTES
    if size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(
            f"Referenced {kind} file is too large for MiniMax-M3 base64 input "
            f"({size} bytes > {limit_mb} MB): {path}"
        )

    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as error:
        raise ValueError(f"Failed to read referenced media file: {path}") from error

    encoded_bytes = len(data.encode("ascii"))
    total_encoded = encoded_bytes_before + encoded_bytes
    if total_encoded > MULTIMODAL_REQUEST_MAX_BYTES:
        limit_mb = MULTIMODAL_REQUEST_MAX_BYTES // (1024 * 1024)
        raise ValueError(
            f"Referenced media files exceed MiniMax-M3 request body budget "
            f"({total_encoded} encoded bytes > {limit_mb} MB)."
        )

    return {
        "path": str(path),
        "kind": kind,
        "mime_type": mime_type,
        "data": data,
        "bytes": size,
        "encoded_bytes": encoded_bytes,
        "detail": "default",
    }


def attach_external_file_references_with_media(user_input):
    references = _external_file_references(user_input)
    if not references:
        return user_input, []

    blocks = [
        (
            "[Referenced external files]\n"
            "The user explicitly attached these read-only file contents. "
            "They do not grant access to directories or other external files."
        )
    ]
    media_references = []
    encoded_media_bytes = 0
    for path_text in references:
        media_reference = _read_external_media_reference(
            path_text,
            encoded_media_bytes,
        )
        if media_reference:
            media_references.append(media_reference)
            encoded_media_bytes += media_reference["encoded_bytes"]
            blocks.append(
                f"--- {media_reference['kind'].title()}: "
                f"{media_reference['path']} "
                f"({media_reference['mime_type']}, "
                f"{media_reference['bytes']} bytes) ---\n"
                "Attached as multimodal input for MiniMax-M3-capable APIs.\n"
                f"--- End {media_reference['kind']}: "
                f"{media_reference['path']} ---"
            )
            continue

        path, content = _read_external_file_reference(path_text)
        blocks.append(f"--- File: {path} ---\n{content}\n--- End file: {path} ---")

    return f"{user_input}\n\n" + "\n\n".join(blocks), media_references


def main():
    from tui.app import AgentTUIApp

    app = AgentTUIApp()
    app.run()


if __name__ == "__main__":
    main()
