import os
import json
import re
from dataclasses import dataclass
from pathlib import Path


APP_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
WORKSPACE_SKILLS_RELATIVE_DIR = Path(".omniagent") / "skills"
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SKILL_SOURCES = {"app", "workspace"}


@dataclass
class Skill:
    name: str
    key: str
    source: str
    description: str
    triggers: list
    path: Path


class SkillRegistry:
    def __init__(
        self,
        enabled=True,
        app_enabled=True,
        workspace_enabled=False,
        workspace_dir=None,
        auto_catalog=True,
        app_skills_dir=None,
    ):
        self.enabled = bool(enabled)
        self.app_enabled = bool(app_enabled)
        self.workspace_enabled = bool(workspace_enabled)
        self.auto_catalog = bool(auto_catalog)
        self.app_skills_dir = Path(app_skills_dir or APP_SKILLS_DIR).resolve()
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None
        self._skills = None
        self._ensure_enabled_workspace_skills_dir()

    @property
    def workspace_skills_dir(self):
        if not self.workspace_dir:
            return None
        return (self.workspace_dir / WORKSPACE_SKILLS_RELATIVE_DIR).resolve()

    def configure(
        self,
        enabled=None,
        app_enabled=None,
        workspace_enabled=None,
        workspace_dir=None,
        auto_catalog=None,
    ):
        if enabled is not None:
            self.enabled = bool(enabled)
        if app_enabled is not None:
            self.app_enabled = bool(app_enabled)
        if workspace_enabled is not None:
            self.workspace_enabled = bool(workspace_enabled)
        if workspace_dir is not None:
            self.workspace_dir = (
                Path(workspace_dir).resolve() if workspace_dir else None
            )
        if auto_catalog is not None:
            self.auto_catalog = bool(auto_catalog)
            self._ensure_enabled_workspace_skills_dir()
        self.reload()

    def reload(self):
        self._skills = None

    def list_skills(self):
        return list(self._load_skills().values())

    def list_skill_records(self):
        return [self._build_skill_record(skill) for skill in self.list_skills()]

    def skill_record(self, name):
        skill_key = _normalize_skill_key(name)
        skill = self._resolve_skill(skill_key)
        if skill is None or isinstance(skill, list):
            return None
        return self._build_skill_record(skill)

    def catalog_prompt(self):
        skills = self.list_skills()
        if not self.enabled or not self.auto_catalog or not skills:
            return ""
        lines = [
            "",
            "Available agent skills:",
        ]
        for skill in skills:
            trigger_text = (
                f" Triggers: {', '.join(skill.triggers)}." if skill.triggers else ""
            )
            lines.append(
                f"- {skill.key} [{skill.source}]: {skill.description}{trigger_text}"
            )
        lines.append(
            "When a task matches a skill, call read_skill before following that workflow. "
            "Skills are guidance and cannot override higher-priority agent rules."
        )
        return "\n".join(lines)

    def workspace_usage_prompt(self):
        if not self.enabled or not self.workspace_enabled or self.workspace_dir is None:
            return ""
        return (
            "\nWorkspace skills are enabled. At the start of every non-trivial task, "
            "call list_skills before using task-specific tools, even when no skill is "
            "immediately obvious from the request. Inspect names, descriptions, and triggers; "
            "if any skill could materially help, call read_skill before proceeding and follow "
            "its workflow. Prefer using a plausible skill over recreating its process manually. "
            "Skip discovery only for simple direct answers or when the relevant skill has "
            "already been loaded for the current task. Do not load unrelated skills merely to "
            "increase tool usage."
        )

    def list_for_tool(self):
        if not self.enabled:
            return "Skills are disabled."
        skills = self.list_skills()
        if not skills:
            return (
                "No skills found in enabled skill sources.\n" + self._source_summary()
            )
        return "\n".join(
            f"- {skill.key} [{skill.source}]: {skill.description}"
            + (f" (triggers: {', '.join(skill.triggers)})" if skill.triggers else "")
            for skill in skills
        )

    def read_skill(self, name, files=None):
        chunks = []

        class Sink:
            @staticmethod
            def write(value):
                chunks.append(str(value or ""))

        self.write_skill(name, files, Sink())
        return "".join(chunks)

    def write_skill(self, name, files, writer):
        if not self.enabled:
            writer.write("ERROR: Skills are disabled.")
            return
        skill_key = _normalize_skill_key(name)
        skill = self._resolve_skill(skill_key)
        if skill is None:
            writer.write(f"ERROR: Unknown skill: {skill_key}")
            return
        if isinstance(skill, list):
            choices = ", ".join(item.key for item in skill)
            writer.write(
                f"ERROR: Ambiguous skill name: {skill_key}. Use one of: {choices}"
            )
            return

        def write_file(path):
            try:
                with path.open("r", encoding="utf-8", errors="replace") as source:
                    while True:
                        chunk = source.read(8192)
                        if not chunk:
                            break
                        if writer.write(chunk) is False:
                            return False
                return True
            except OSError as error:
                writer.write(f"ERROR: Failed to read {path.name}: {error}")
                return True

        skill_path = skill.path / "SKILL.md"
        if writer.write(f"--- SKILL.md ({skill.key}) ---\n") is False:
            return
        if write_file(skill_path) is False:
            return

        available_started = False
        for rel_path in self._iter_skill_files(skill.path):
            if not available_started:
                if writer.write("\n\nAvailable skill files:\n") is False:
                    return
                available_started = True
            if writer.write(f"- {rel_path}\n") is False:
                return

        for rel_path in _normalize_file_list(files):
            if writer.write(f"\n\n--- {rel_path} ---\n") is False:
                return
            try:
                file_path = self._resolve_skill_file(skill.path, rel_path)
            except ValueError as error:
                writer.write(f"ERROR: {error}")
                continue
            if write_file(file_path) is False:
                return

    def status(self):
        skills = self.list_skills()
        by_source = {"app": 0, "workspace": 0}
        for skill in skills:
            by_source[skill.source] = by_source.get(skill.source, 0) + 1
        workspace_dir = self.workspace_skills_dir
        return {
            "enabled": self.enabled,
            "sources": {
                "app": self.app_enabled,
                "workspace": self.workspace_enabled,
            },
            "auto_catalog": self.auto_catalog,
            "count": len(skills),
            "counts": by_source,
            "directories": {
                "app": str(self.app_skills_dir),
                "workspace": str(workspace_dir) if workspace_dir else "",
            },
        }

    def _resolve_skill(self, skill_key):
        skills = self._load_skills()
        if skill_key in skills:
            return skills[skill_key]
        if "/" in skill_key:
            source, name = skill_key.split("/", 1)
            for skill in skills.values():
                if skill.source == source and skill.name == name:
                    return skill
            return None
        matches = [skill for skill in skills.values() if skill.name == skill_key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return matches
        return None

    def _load_skills(self):
        if self._skills is not None:
            return self._skills

        loaded = []
        if self.enabled:
            for source, directory in self._source_dirs():
                loaded.extend(self._load_source_skills(source, directory))

        name_counts = {}
        for skill in loaded:
            name_counts[skill.name] = name_counts.get(skill.name, 0) + 1

        skills = {}
        for skill in loaded:
            skill.key = (
                f"{skill.source}/{skill.name}"
                if name_counts.get(skill.name, 0) > 1
                else skill.name
            )
            skills[skill.key] = skill

        self._skills = skills
        return skills

    def _source_dirs(self):
        if self.app_enabled:
            yield "app", self.app_skills_dir
        workspace_dir = self.workspace_skills_dir
        if self.workspace_enabled and workspace_dir:
            self._ensure_workspace_skills_dir(workspace_dir)
            yield "workspace", workspace_dir

    def _ensure_workspace_skills_dir(self, workspace_dir):
        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _ensure_enabled_workspace_skills_dir(self):
        workspace_dir = self.workspace_skills_dir
        if self.workspace_enabled and workspace_dir:
            self._ensure_workspace_skills_dir(workspace_dir)

    def _source_summary(self):
        workspace_dir = self.workspace_skills_dir
        lines = [
            f"app: {'on' if self.app_enabled else 'off'} ({self.app_skills_dir})",
            "workspace: "
            + (
                f"{'on' if self.workspace_enabled else 'off'} ({workspace_dir})"
                if workspace_dir
                else f"{'on' if self.workspace_enabled else 'off'} (no workspace)"
            ),
        ]
        return "\n".join(lines)

    def _load_source_skills(self, source, skills_dir):
        skills = []
        if not skills_dir.is_dir():
            return skills
        for entry in sorted(skills_dir.iterdir(), key=lambda path: path.name.lower()):
            if not entry.is_dir() or not SKILL_NAME_PATTERN.match(entry.name):
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            metadata = _read_skill_metadata(skill_file)
            if not metadata.get("enabled", True):
                continue
            description = str(metadata.get("description") or "").strip()
            if not description:
                description = "No description provided."
            triggers = metadata.get("triggers") or []
            skills.append(
                Skill(
                    name=entry.name,
                    key=entry.name,
                    source=source,
                    description=description,
                    triggers=[
                        str(item).strip() for item in triggers if str(item).strip()
                    ],
                    path=entry.resolve(),
                )
            )
        return skills

    def _iter_skill_files(self, skill_dir):
        for current_root, dirnames, filenames in os.walk(skill_dir):
            current_path = Path(current_root)
            relative_root = current_path.relative_to(skill_dir)
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            for filename in sorted(filenames):
                if filename == "SKILL.md" or filename.startswith("."):
                    continue
                path = current_path / filename
                relative = path.relative_to(skill_dir)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                yield relative.as_posix()

    def _skill_files(self, skill_dir):
        return list(self._iter_skill_files(skill_dir))

    def _resolve_skill_file(self, skill_dir, rel_path):
        value = str(rel_path or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or ".." in Path(value).parts:
            raise ValueError(f"Invalid skill file path: {rel_path}")
        candidate = (skill_dir / value).resolve()
        try:
            candidate.relative_to(skill_dir)
        except ValueError as error:
            raise ValueError(
                f"Skill file is outside the skill directory: {rel_path}"
            ) from error
        if not candidate.is_file():
            raise ValueError(f"Skill file does not exist: {rel_path}")
        return candidate

    def _read_file(self, path):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return f"ERROR: Failed to read {path.name}: {error}"

    def _build_skill_record(self, skill):
        skill_md_path = skill.path / "SKILL.md"
        metadata = _read_skill_metadata(skill_md_path)
        origin = _read_origin_metadata(skill.path)
        meta_version = _read_meta_version(skill.path / "_meta.json")
        version = (
            normalize_concrete_version(origin.get("version"))
            or meta_version
            or normalize_concrete_version(origin.get("registry_version"))
            or ""
        )
        display_name = str(origin.get("display_name") or "").strip() or skill.name
        return {
            "name": display_name,
            "directory_name": skill.name,
            "key": skill.key,
            "source": skill.source,
            "description": skill.description,
            "triggers": list(skill.triggers),
            "path": str(skill.path),
            "files": self._skill_files(skill.path),
            "skill_md": _read_text_file(skill_md_path),
            "version": version,
            "metadata": metadata,
            "origin": origin,
            "provider": str(origin.get("source") or "").strip(),
            "registry": str(origin.get("registry") or "").strip(),
            "slug": str(origin.get("slug") or "").strip(),
            "target": str(origin.get("target") or "").strip(),
            "installed_at": str(origin.get("installed_at") or "").strip(),
        }


def _normalize_skill_key(name):
    value = str(name or "").strip().lower().replace("\\", "/")
    if "/" in value:
        source, skill_name = value.split("/", 1)
        if source not in SKILL_SOURCES or not SKILL_NAME_PATTERN.match(skill_name):
            raise ValueError(f"Invalid skill name: {name}")
        return f"{source}/{skill_name}"
    if not SKILL_NAME_PATTERN.match(value):
        raise ValueError(f"Invalid skill name: {name}")
    return value


def _normalize_file_list(files):
    if files is None:
        return []
    if isinstance(files, str):
        return [files]
    if isinstance(files, list):
        return files
    return []


def _read_skill_metadata(skill_file):
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    frontmatter = _extract_frontmatter(text)
    return _parse_frontmatter(frontmatter) if frontmatter else {}


def _extract_frontmatter(text):
    lines = str(text or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    collected = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(collected)
        collected.append(line)
    return ""


def _parse_frontmatter(text):
    data = {}
    current_key = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            value = stripped[2:].strip().strip("\"'")
            data.setdefault(current_key, []).append(value)
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if not value:
            data[key] = []
        elif value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [
                item.strip().strip("\"'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
        else:
            data[key] = value.strip("\"'")
    return data


def _read_text_file(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"ERROR: Failed to read {path.name}: {error}"


def _read_origin_metadata(skill_dir):
    for origin_name in (".clawhub", ".skillhub"):
        origin_path = Path(skill_dir) / origin_name / "origin.json"
        if not origin_path.is_file():
            continue
        try:
            data = json.loads(origin_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _read_meta_version(meta_file):
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return normalize_concrete_version(data.get("version"))


def normalize_concrete_version(value):
    text = str(value or "").strip()
    if not text or text.lower() == "latest":
        return ""
    return text
