import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ui import (
    clean_display_text,
    print_error,
    print_success,
)


BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
PROJECT_INDEX_FILE = SESSIONS_DIR / "projects.json"
PINNED_INDEX_FILE = SESSIONS_DIR / "pinned.json"
PROJECTS_DIR = SESSIONS_DIR / "projects"
ORPHAN_SESSIONS_DIR = SESSIONS_DIR / "orphan"
LEGACY_HISTORY_FILE = BASE_DIR / "memory" / "history.jsonl"
LEGACY_HISTORY_MIGRATED_FILE = BASE_DIR / "memory" / "history.migrated.jsonl"
SESSION_VERSION = "4.0.0"
_legacy_migration_running = False


@dataclass
class ProjectRecord:
    name: str
    path: str
    slug: str
    created_at: str

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "slug": self.slug,
            "created_at": self.created_at,
        }


def ensure_session_storage():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    ORPHAN_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not PROJECT_INDEX_FILE.exists():
        PROJECT_INDEX_FILE.write_text("[]\n", encoding="utf-8")
    if not PINNED_INDEX_FILE.exists():
        PINNED_INDEX_FILE.write_text("[]\n", encoding="utf-8")
    if not _legacy_migration_running:
        _migrate_legacy_history()


def normalize_project_path(path_text):
    try:
        path = Path(str(path_text or "").strip()).expanduser().resolve()
    except OSError:
        return ""
    return str(path)


def _slugify(value):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "project"


def _session_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def _safe_read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def normalize_session_path(session_path):
    if not session_path:
        return ""
    try:
        path = Path(str(session_path)).resolve(strict=False)
    except OSError:
        return ""
    return str(path)


def _load_pinned_index():
    ensure_session_storage()
    rows = _safe_read_json(PINNED_INDEX_FILE, [])
    pinned = []
    for row in rows:
        path = normalize_session_path(row)
        if path:
            pinned.append(path)
    return pinned


def save_pinned_session_paths(session_paths):
    ensure_session_storage()
    unique_paths = []
    seen = set()
    for row in session_paths or []:
        path = normalize_session_path(row)
        if not path or path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    _safe_write_json(PINNED_INDEX_FILE, unique_paths)


def list_pinned_session_paths():
    pinned = _load_pinned_index()
    cleaned = [path for path in pinned if Path(path).exists()]
    if cleaned != pinned:
        save_pinned_session_paths(cleaned)
    return cleaned


def is_session_pinned(session_path):
    path = normalize_session_path(session_path)
    if not path:
        return False
    return path in set(list_pinned_session_paths())


def pin_session(session_path):
    path = normalize_session_path(session_path)
    if not path:
        raise ValueError("Session path is invalid.")
    pinned = list_pinned_session_paths()
    if path in pinned:
        return pinned
    pinned.append(path)
    save_pinned_session_paths(pinned)
    return pinned


def unpin_session(session_path):
    path = normalize_session_path(session_path)
    pinned = [row for row in list_pinned_session_paths() if row != path]
    save_pinned_session_paths(pinned)
    return pinned


def list_pinned_sessions():
    sessions = []
    missing = False
    for session_path in list_pinned_session_paths():
        record = load_session(session_path)
        if record is None:
            missing = True
            continue
        sessions.append(record)
    if missing:
        save_pinned_session_paths([
            record.get("session_path")
            for record in sessions
            if record.get("session_path")
        ])
    return sessions


def load_projects():
    ensure_session_storage()
    rows = _safe_read_json(PROJECT_INDEX_FILE, [])
    projects = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        path = normalize_project_path(row.get("path"))
        slug = _slugify(row.get("slug") or name)
        created_at = str(
            row.get("created_at") or datetime.now().isoformat(timespec="seconds")
        )
        if not name or not path:
            continue
        projects.append(
            ProjectRecord(name=name, path=path, slug=slug, created_at=created_at)
        )
    return projects


def save_projects(projects):
    ensure_session_storage()
    _safe_write_json(PROJECT_INDEX_FILE, [project.to_dict() for project in projects])


def add_project(name, path_text):
    ensure_session_storage()
    name = str(name or "").strip()
    path = normalize_project_path(path_text)
    if not name:
        raise ValueError("Project name cannot be empty.")
    if not path:
        raise ValueError("Project path is invalid.")

    projects = load_projects()
    now = datetime.now().isoformat(timespec="seconds")
    for index, project in enumerate(projects):
        if project.name == name:
            updated = ProjectRecord(
                name=name, path=path, slug=project.slug, created_at=project.created_at
            )
            projects[index] = updated
            save_projects(projects)
            return updated

    existing_slugs = {project.slug for project in projects}
    base_slug = _slugify(name)
    slug = base_slug
    counter = 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1

    project = ProjectRecord(name=name, path=path, slug=slug, created_at=now)
    projects.append(project)
    save_projects(projects)
    return project


def get_project_by_name(name):
    name = str(name or "").strip()
    for project in load_projects():
        if project.name == name:
            return project
    return None


def _project_sessions_dir(project):
    if project is None:
        return ORPHAN_SESSIONS_DIR
    return PROJECTS_DIR / project.slug


def _session_paths(session_id, project=None):
    directory = _project_sessions_dir(project)
    return {
        "dir": directory,
        "session": directory / f"{session_id}.json",
        "history": directory / f"{session_id}.history.jsonl",
    }


def _session_title_from_history(conversation_history):
    for message in conversation_history or []:
        if str(message.get("role") or "") != "user":
            continue
        title = clean_display_text(message.get("content", ""))
        title = " ".join(title.split())
        if title:
            return title[:60]
    return "New Chat"


def create_session(project=None, title="", model_name=""):
    ensure_session_storage()
    now = datetime.now().isoformat(timespec="seconds")
    session_id = _session_id()
    paths = _session_paths(session_id, project)
    record = {
        "version": SESSION_VERSION,
        "id": session_id,
        "title": str(title or "New Chat").strip() or "New Chat",
        "model_name": str(model_name or "").strip(),
        "created_at": now,
        "updated_at": now,
        "project": project.to_dict() if isinstance(project, ProjectRecord) else None,
        "conversation": [],
        "history_path": str(paths["history"]),
        "session_path": str(paths["session"]),
    }
    _safe_write_json(paths["session"], record)
    if not paths["history"].exists():
        paths["history"].write_text("", encoding="utf-8")
    return record


def save_session_record(record):
    ensure_session_storage()
    if not isinstance(record, dict):
        raise ValueError("Session record must be a dictionary.")
    project_data = record.get("project")
    project = None
    if (
        isinstance(project_data, dict)
        and project_data.get("name")
        and project_data.get("path")
    ):
        project = ProjectRecord(
            name=str(project_data["name"]),
            path=normalize_project_path(project_data["path"]),
            slug=_slugify(project_data.get("slug") or project_data["name"]),
            created_at=str(
                project_data.get("created_at")
                or datetime.now().isoformat(timespec="seconds")
            ),
        )
    session_id = str(record.get("id") or "").strip()
    if not session_id:
        raise ValueError("Session record is missing id.")
    paths = _session_paths(session_id, project)
    record["updated_at"] = datetime.now().isoformat(timespec="seconds")
    record["session_path"] = str(paths["session"])
    record["history_path"] = str(paths["history"])
    _safe_write_json(paths["session"], record)
    if not paths["history"].exists():
        paths["history"].write_text("", encoding="utf-8")
    return record


def save_conversation(conversation_history, model_name, session_record=None):
    if not conversation_history:
        print_error("No conversation history to save.")
        return False

    if session_record is None:
        session_record = create_session(
            title=_session_title_from_history(conversation_history),
            model_name=model_name,
        )

    session_record["conversation"] = list(conversation_history or [])
    session_record["model_name"] = str(model_name or "").strip()
    if (
        not str(session_record.get("title") or "").strip()
        or session_record.get("title") == "New Chat"
    ):
        session_record["title"] = _session_title_from_history(conversation_history)
    save_session_record(session_record)
    print_success(f"Conversation saved to {session_record['session_path']}")
    return True


def list_sessions(project=None):
    ensure_session_storage()
    directory = _project_sessions_dir(project)
    if not directory.exists():
        return []

    sessions = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        if path.name.endswith(".history.jsonl"):
            continue
        data = _safe_read_json(path, {})
        if not isinstance(data, dict):
            continue
        data["session_path"] = str(path)
        history_path = path.with_suffix(".history.jsonl")
        data["history_path"] = str(history_path)
        sessions.append(data)

    sessions.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return sessions


def load_session(session_path):
    path = Path(str(session_path))
    data = _safe_read_json(path, {})
    if not isinstance(data, dict):
        return None
    data["session_path"] = str(path)
    data["history_path"] = str(path.with_suffix(".history.jsonl"))
    return data


def delete_session(session_path):
    path = Path(str(session_path))
    normalized = normalize_session_path(path)
    history_path = path.with_suffix(".history.jsonl")
    if path.exists():
        try:
            path.unlink()
        except OSError as error:
            raise ValueError(f"Failed to delete session: {error}") from error
    if history_path.exists():
        try:
            history_path.unlink()
        except OSError as error:
            raise ValueError(f"Failed to delete session history: {error}") from error
    if normalized:
        unpin_session(normalized)
    return True


def _migrate_legacy_history():
    global _legacy_migration_running
    if not LEGACY_HISTORY_FILE.exists() or LEGACY_HISTORY_MIGRATED_FILE.exists():
        return

    try:
        lines = LEGACY_HISTORY_FILE.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return

    conversation = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip()
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        conversation.append({
            "role": role,
            "content": row.get("content", ""),
        })

    _legacy_migration_running = True
    try:
        if conversation:
            record = create_session(
                title="Imported Legacy History",
                model_name="",
            )
            record["conversation"] = conversation
            save_session_record(record)
            history_target = Path(record["history_path"])
            shutil.copyfile(LEGACY_HISTORY_FILE, history_target)

        try:
            LEGACY_HISTORY_MIGRATED_FILE.write_text(
                f"Migrated at {datetime.now().isoformat(timespec='seconds')}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    finally:
        _legacy_migration_running = False
