import base64
import mimetypes
from pathlib import Path

from config import (
    DEFAULT_EXTRA_MODALITY_LIMITS,
    DEFAULT_FILE_INLINE_CHARS,
    DEFAULT_MULTIMODAL_LIMIT,
    parse_extra_modalities_config,
    parse_file_inline_chars,
    parse_multimodal_limit,
)
from references import resolve_references, reference_path_key


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
MEBIBYTE = 1024 * 1024


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


def _read_external_file_reference(
    path_text,
    base_dir=None,
    file_inline_chars=DEFAULT_FILE_INLINE_CHARS,
):
    path = _resolve_external_file_reference(path_text, base_dir)
    inline_chars = parse_file_inline_chars(file_inline_chars)

    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            content = source.read(inline_chars + 1)
    except OSError as error:
        raise ValueError(f"Failed to read referenced file: {path}") from error

    if len(content) > inline_chars:
        return path, None
    return path, content


def _read_external_media_reference(
    path_text,
    encoded_bytes_before=0,
    base_dir=None,
    extra_modalities=None,
    multimodal_limit=DEFAULT_MULTIMODAL_LIMIT,
):
    path = _resolve_external_file_reference(path_text, base_dir)
    kind, mime_type = _detect_reference_media_type(path)
    if kind not in {"audio", "image", "video"}:
        return None

    modality_limits = parse_extra_modalities_config(extra_modalities)
    size = path.stat().st_size
    limit_mb = modality_limits.get(kind, DEFAULT_EXTRA_MODALITY_LIMITS[kind])
    max_bytes = limit_mb * MEBIBYTE
    if size > max_bytes:
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
    total_limit = (
        DEFAULT_MULTIMODAL_LIMIT
        if multimodal_limit is None
        else parse_multimodal_limit(multimodal_limit)
    )
    request_max_bytes = total_limit * MEBIBYTE
    if total_encoded > request_max_bytes:
        raise ValueError(
            f"Referenced media files exceed multimodal request body budget "
            f"({total_encoded} encoded bytes > {total_limit} MB)."
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


def attach_external_file_references_with_media(
    user_input,
    base_dir=None,
    extra_modalities=None,
    multimodal_limit=DEFAULT_MULTIMODAL_LIMIT,
    file_inline_chars=DEFAULT_FILE_INLINE_CHARS,
):
    parsed = resolve_references(user_input, base_dir)
    references = []
    files = {}
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
            return user_input, [], {}, {}
        folder_lines = "\n".join(f"- {name}" for name in folders)
        return (
            f"{user_input}\n\n[Referenced folders]\n{folder_lines}\n"
            "These folders are available lazily through read-only file tools for this request.",
            [],
            files,
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
            extra_modalities,
            multimodal_limit,
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

        path, content = _read_external_file_reference(
            path_text, base_dir, file_inline_chars
        )
        files[reference.display] = path
        if content is None:
            blocks.append(
                f"--- File: {path} ---\n"
                "Not embedded because it exceeds the configured file inline chars. "
                "It remains attached as a read-only reference and can be read with "
                f"the read_file tool using reference={reference.display!r}.\n"
                f"--- End file: {path} ---"
            )
        else:
            blocks.append(
                f"--- File: {path} ---\n{content}\n--- End file: {path} ---"
            )

    if folders:
        folder_lines = "\n".join(f"- {name}" for name in folders)
        blocks.append(
            "[Referenced folders]\n"
            f"{folder_lines}\n"
            "These folders are available lazily through read-only file tools for this request."
        )
    return f"{user_input}\n\n" + "\n\n".join(blocks), media_references, files, folders


def main():
    from tui.app import AgentTUIApp

    app = AgentTUIApp()
    app.run()


if __name__ == "__main__":
    main()
