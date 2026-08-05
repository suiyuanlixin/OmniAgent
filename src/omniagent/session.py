import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .persistence import atomic_write_json, atomic_write_text
from .paths import APP_HOME

from .ui import (
    clean_display_text,
    print_error,
    print_success,
)


BASE_DIR = APP_HOME
SESSIONS_DIR = BASE_DIR / "sessions"
PROJECT_INDEX_FILE = SESSIONS_DIR / "projects.json"
PINNED_INDEX_FILE = SESSIONS_DIR / "pinned.json"
PINNED_PROJECT_INDEX_FILE = SESSIONS_DIR / "pinned_projects.json"
PROJECTS_DIR = SESSIONS_DIR / "projects"
ORPHAN_SESSIONS_DIR = SESSIONS_DIR / "orphan"
SESSION_VERSION = "5.1.0"
SESSION_TITLE_STATE_MANUAL = "manual"
SESSION_TITLE_STATE_TEMPORARY = "temporary"
SESSION_TITLE_STATE_GENERATED = "generated"


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
        atomic_write_text(PROJECT_INDEX_FILE, "[]\n")
    if not PINNED_INDEX_FILE.exists():
        atomic_write_text(PINNED_INDEX_FILE, "[]\n")
    if not PINNED_PROJECT_INDEX_FILE.exists():
        atomic_write_text(PINNED_PROJECT_INDEX_FILE, "[]\n")


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
    atomic_write_json(path, data)


def normalize_session_path(session_path):
    if not session_path:
        return ""
    try:
        path = Path(str(session_path)).resolve(strict=False)
    except OSError:
        return ""
    return str(path)


def is_session_archived(record):
    return bool(str((record or {}).get("archived_at") or "").strip())


def _sort_sessions(sessions):
    sessions.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return sessions


def _load_pinned_index():
    ensure_session_storage()
    rows = _safe_read_json(PINNED_INDEX_FILE, [])
    pinned = []
    for row in rows:
        path = normalize_session_path(row)
        if path:
            pinned.append(path)
    return pinned


def _load_pinned_project_index():
    ensure_session_storage()
    rows = _safe_read_json(PINNED_PROJECT_INDEX_FILE, [])
    slugs = []
    for row in rows:
        slug = _slugify(row)
        if slug:
            slugs.append(slug)
    return slugs


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


def save_pinned_project_slugs(project_slugs):
    ensure_session_storage()
    unique_slugs = []
    seen = set()
    for row in project_slugs or []:
        slug = _slugify(row)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        unique_slugs.append(slug)
    _safe_write_json(PINNED_PROJECT_INDEX_FILE, unique_slugs)


def list_pinned_session_paths():
    pinned = _load_pinned_index()
    cleaned = [path for path in pinned if Path(path).exists()]
    if cleaned != pinned:
        save_pinned_session_paths(cleaned)
    return cleaned


def list_pinned_project_slugs():
    pinned = _load_pinned_project_index()
    valid_slugs = {project.slug for project in load_projects()}
    cleaned = [slug for slug in pinned if slug in valid_slugs]
    if cleaned != pinned:
        save_pinned_project_slugs(cleaned)
    return cleaned


def is_session_pinned(session_path):
    path = normalize_session_path(session_path)
    if not path:
        return False
    return path in set(list_pinned_session_paths())


def is_project_pinned(project_slug):
    slug = _slugify(project_slug)
    if not slug:
        return False
    return slug in set(list_pinned_project_slugs())


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


def pin_project(project_slug):
    slug = _slugify(project_slug)
    if not slug:
        raise ValueError("Project slug is invalid.")
    pinned = list_pinned_project_slugs()
    if slug in pinned:
        return pinned
    pinned.append(slug)
    save_pinned_project_slugs(pinned)
    return pinned


def unpin_session(session_path):
    path = normalize_session_path(session_path)
    pinned = [row for row in list_pinned_session_paths() if row != path]
    save_pinned_session_paths(pinned)
    return pinned


def unpin_project(project_slug):
    slug = _slugify(project_slug)
    pinned = [row for row in list_pinned_project_slugs() if row != slug]
    save_pinned_project_slugs(pinned)
    return pinned


def list_pinned_sessions():
    sessions = []
    missing = False
    for session_path in list_pinned_session_paths():
        record = load_session(session_path)
        if record is None or is_session_archived(record):
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


def list_pinned_projects():
    projects_by_slug = {project.slug: project for project in load_projects()}
    projects = []
    cleaned = []
    for slug in list_pinned_project_slugs():
        project = projects_by_slug.get(slug)
        if project is None:
            continue
        cleaned.append(slug)
        projects.append(project)
    if cleaned != list_pinned_project_slugs():
        save_pinned_project_slugs(cleaned)
    return projects


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


def rename_project(project_slug, new_name):
    ensure_session_storage()
    slug = _slugify(project_slug)
    name = str(new_name or "").strip()
    if not slug:
        raise ValueError("Project slug is invalid.")
    if not name:
        raise ValueError("Project name cannot be empty.")

    projects = load_projects()
    target_index = None
    for index, project in enumerate(projects):
        if project.slug == slug:
            target_index = index
            continue
        if project.name == name:
            raise ValueError("Project name already exists.")

    if target_index is None:
        raise ValueError("Project not found.")

    target = projects[target_index]
    updated = ProjectRecord(
        name=name,
        path=target.path,
        slug=target.slug,
        created_at=target.created_at,
    )
    projects[target_index] = updated
    save_projects(projects)
    _rewrite_project_metadata(updated)
    return updated


def get_project_by_name(name):
    name = str(name or "").strip()
    for project in load_projects():
        if project.name == name:
            return project
    return None


def get_project_by_slug(project_slug):
    slug = _slugify(project_slug)
    for project in load_projects():
        if project.slug == slug:
            return project
    return None


def _project_sessions_dir(project):
    if project is None:
        return ORPHAN_SESSIONS_DIR
    return PROJECTS_DIR / project.slug


def _rewrite_project_metadata(project):
    if project is None:
        return
    for record in list_sessions(project):
        record["project"] = project.to_dict()
        session_path = Path(str(record.get("session_path") or ""))
        if session_path:
            _safe_write_json(session_path, record)


def _session_paths(session_id, project=None):
    directory = _project_sessions_dir(project)
    return {
        "dir": directory,
        "session": directory / f"{session_id}.json",
        "history": directory / f"{session_id}.history.jsonl",
    }


def session_todo_dir(session_path):
    value = str(session_path or "").strip()
    if not value:
        return None
    path = Path(value)
    return path.parent / f"{path.stem}.todos"


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
        "archived_at": "",
        "project": project.to_dict() if isinstance(project, ProjectRecord) else None,
        "conversation": [],
        "usage_history": [],
        "history_path": str(paths["history"]),
        "session_path": str(paths["session"]),
    }
    _safe_write_json(paths["session"], record)
    if not paths["history"].exists():
        atomic_write_text(paths["history"], "")
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
    record["version"] = SESSION_VERSION
    record["updated_at"] = datetime.now().isoformat(timespec="seconds")
    record["session_path"] = str(paths["session"])
    record["history_path"] = str(paths["history"])
    _safe_write_json(paths["session"], record)
    if not paths["history"].exists():
        atomic_write_text(paths["history"], "")
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


def list_sessions(project=None, include_archived=False):
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
        if (not include_archived) and is_session_archived(data):
            continue
        sessions.append(data)

    return _sort_sessions(sessions)


def list_archived_sessions():
    sessions = []
    for project in load_projects():
        sessions.extend(
            session
            for session in list_sessions(project, include_archived=True)
            if is_session_archived(session)
        )
    sessions.extend(
        session
        for session in list_sessions(None, include_archived=True)
        if is_session_archived(session)
    )
    return _sort_sessions(sessions)


def load_session(session_path):
    path = Path(str(session_path))
    data = _safe_read_json(path, {})
    if not isinstance(data, dict):
        return None
    data["session_path"] = str(path)
    data["history_path"] = str(path.with_suffix(".history.jsonl"))
    return data


def rename_session(session_path, new_title):
    path = Path(str(session_path))
    record = load_session(path)
    if not record:
        raise ValueError("Session not found.")
    title = str(new_title or "").strip()
    if not title:
        raise ValueError("Chat title cannot be empty.")
    record["title"] = title
    record["title_state"] = SESSION_TITLE_STATE_MANUAL
    record.pop("title_seed_text", None)
    record["title_summary_pending"] = False
    _safe_write_json(path, record)
    return record


def archive_session(session_path):
    path = Path(str(session_path))
    record = load_session(path)
    if not record:
        raise ValueError("Session not found.")
    if is_session_archived(record):
        return record
    record["archived_at"] = datetime.now().isoformat(timespec="seconds")
    normalized = normalize_session_path(path)
    if normalized:
        unpin_session(normalized)
    _safe_write_json(path, record)
    return record


def unarchive_session(session_path):
    path = Path(str(session_path))
    record = load_session(path)
    if not record:
        raise ValueError("Session not found.")
    record["archived_at"] = ""
    _safe_write_json(path, record)
    return record


def archive_project_sessions(project_slug):
    project = get_project_by_slug(project_slug)
    if project is None:
        raise ValueError("Project not found.")
    archived = 0
    for record in list_sessions(project):
        archive_session(str(record.get("session_path") or ""))
        archived += 1
    return archived


def delete_session(session_path):
    path = Path(str(session_path))
    normalized = normalize_session_path(path)
    history_path = path.with_suffix(".history.jsonl")
    todo_dir = session_todo_dir(path)
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
    if todo_dir is not None and todo_dir.exists():
        expected_parent = path.parent.resolve(strict=False)
        resolved_todo_dir = todo_dir.resolve(strict=False)
        if (
            resolved_todo_dir.parent != expected_parent
            or resolved_todo_dir.name != f"{path.stem}.todos"
        ):
            raise ValueError("Session todo path is invalid.")
        try:
            shutil.rmtree(resolved_todo_dir)
        except OSError as error:
            raise ValueError(f"Failed to delete session todos: {error}") from error
    if normalized:
        unpin_session(normalized)
    return True


def remove_project(project_slug):
    slug = _slugify(project_slug)
    if not slug:
        raise ValueError("Project slug is invalid.")
    project = get_project_by_slug(slug)
    if project is None:
        raise ValueError("Project not found.")

    for record in list_sessions(project, include_archived=True):
        delete_session(str(record.get("session_path") or ""))
    unpin_project(slug)

    projects = [row for row in load_projects() if row.slug != slug]
    save_projects(projects)

    project_dir = _project_sessions_dir(project)
    if project_dir.exists():
        try:
            shutil.rmtree(project_dir)
        except OSError as error:
            raise ValueError(f"Failed to remove project directory: {error}") from error
    return project
