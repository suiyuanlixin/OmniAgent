import base64
import mimetypes
from pathlib import Path

from references import resolve_references, reference_path_key
from tools import MAX_READ_CHARS


IMAGE_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
AUDIO_MEDIA_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/ogg",
    "audio/webm",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
}
VIDEO_MEDIA_TYPES = {
    "video/mp4",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-matroska",
}
IMAGE_FILE_MAX_BYTES = 10 * 1024 * 1024
AUDIO_FILE_MAX_BYTES = 50 * 1024 * 1024
VIDEO_FILE_MAX_BYTES = 50 * 1024 * 1024
MULTIMODAL_REQUEST_MAX_BYTES = 64 * 1024 * 1024


def _resolve_external_file_reference(path_text, base_dir=None):
    try:
        source = Path(path_text).expanduser()
        path = source if source.is_absolute() else Path(base_dir or Path.cwd()) / source
        path = path.resolve(strict=True)
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
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
    ):
        return "audio", "audio/mpeg"
    if header.startswith(b"fLaC"):
        return "audio", "audio/flac"
    if header.startswith(b"OggS"):
        return "audio", "audio/ogg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "video", "video/x-msvideo"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        suffix = path.suffix.lower()
        if suffix == ".webm":
            return "audio", "audio/webm"
        return "video", "video/x-matroska"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        suffix = path.suffix.lower()
        if suffix in {".m4a", ".aac"}:
            return "audio", "audio/mp4" if suffix == ".m4a" else "audio/aac"
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
    if mime_type in AUDIO_MEDIA_TYPES:
        return "audio", mime_type
    if mime_type in VIDEO_MEDIA_TYPES:
        return "video", mime_type
    return "text", ""


def _read_external_file_reference(path_text, base_dir=None):
    path = _resolve_external_file_reference(path_text, base_dir)

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


def _read_external_media_reference(path_text, encoded_bytes_before=0, base_dir=None):
    path = _resolve_external_file_reference(path_text, base_dir)
    kind, mime_type = _detect_reference_media_type(path)
    if kind not in {"audio", "image", "video"}:
        return None

    size = path.stat().st_size
    if kind == "image":
        max_bytes = IMAGE_FILE_MAX_BYTES
    elif kind == "audio":
        max_bytes = AUDIO_FILE_MAX_BYTES
    else:
        max_bytes = VIDEO_FILE_MAX_BYTES
    if size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(
            f"Referenced {kind} file is too large for multimodal base64 input "
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
            f"Referenced media files exceed multimodal request body budget "
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


def attach_external_file_references_with_media(user_input, base_dir=None):
    parsed = resolve_references(user_input, base_dir)
    references = []
    folders = {}
    seen = set()
    for reference in parsed:
        key = (reference.kind, reference_path_key(reference.path))
        if key in seen:
            continue
        seen.add(key)
        if reference.kind == "folder":
            folders[reference.display] = reference.path
        else:
            references.append(reference)
    if not references:
        if not folders:
            return user_input, [], {}
        folder_lines = "\n".join(f"- {name}" for name in folders)
        return (
            f"{user_input}\n\n[Referenced folders]\n{folder_lines}\n"
            "These folders are available lazily through read-only file tools for this request.",
            [],
            folders,
        )

    blocks = [
        (
            "[Referenced external files]\n"
            "The user explicitly attached these read-only file contents. "
            "They do not grant access to directories or other external files."
        )
    ]
    media_references = []
    encoded_media_bytes = 0
    for reference in references:
        path_text = reference.source
        media_reference = _read_external_media_reference(
            path_text,
            encoded_media_bytes,
            base_dir,
        )
        if media_reference:
            media_references.append(media_reference)
            encoded_media_bytes += media_reference["encoded_bytes"]
            blocks.append(
                f"--- {media_reference['kind'].title()}: "
                f"{media_reference['path']} "
                f"({media_reference['mime_type']}, "
                f"{media_reference['bytes']} bytes) ---\n"
                "Attached as multimodal input when the current model supports "
                "this modality.\n"
                f"--- End {media_reference['kind']}: "
                f"{media_reference['path']} ---"
            )
            continue

        path, content = _read_external_file_reference(path_text, base_dir)
        blocks.append(f"--- File: {path} ---\n{content}\n--- End file: {path} ---")

    if folders:
        folder_lines = "\n".join(f"- {name}" for name in folders)
        blocks.append(
            "[Referenced folders]\n"
            f"{folder_lines}\n"
            "These folders are available lazily through read-only file tools for this request."
        )
    return f"{user_input}\n\n" + "\n\n".join(blocks), media_references, folders


def main():
    from tui.app import AgentTUIApp

    app = AgentTUIApp()
    app.run()


if __name__ == "__main__":
    main()
