from __future__ import annotations

import fnmatch
import json
import os
import re
import threading
from functools import wraps
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from persistence import append_jsonl, atomic_write_json, atomic_write_text

from subagents import SubagentRunner

TEAM_STORE_DIR = ".omniagent" / Path("team")

DEFAULT_TEAMMATE_MAX_TURNS = 12
DEFAULT_TEAMMATE_TOOL_CALL_FACTOR = 4
DEFAULT_TEAMMATE_ROLE = "Custom Teammate"
DEFAULT_TEAMMATE_DESCRIPTION = "Custom teammate."
DEFAULT_TEAMMATE_PROMPT = "You are a teammate in OmniAgent's team."

WRITE_TOOL_NAMES = frozenset({
    "write_file",
    "edit_file",
    "apply_patch",
    "apply_unified_patch",
})
TEAMMATE_REPORT_TOOL_NAME = "report_to_lead"
TEAMMATE_REPORT_KINDS = frozenset({"progress", "blocker", "finding", "question"})
MAX_TEAMMATE_REPORTS_PER_TASK = 3
ACTIVE_TEAMMATE_STATUSES = frozenset({"starting", "running", "cancelling"})

FORBIDDEN_TEAM_TOOL_NAMES = {
    "dispatch_subagent",
    "spawn_teammate",
    "update_todo",
    "ask_user",
}

SPAWN_TEAMMATE_TOOL_NAME = "spawn_teammate"
LIST_TEAMMATES_TOOL_NAME = "list_teammates"
SEND_MESSAGE_TOOL_NAME = "send_message"
READ_INBOX_TOOL_NAME = "read_inbox"
BROADCAST_TOOL_NAME = "broadcast"
SHUTDOWN_TEAMMATE_TOOL_NAME = "shutdown_teammate"
TEAM_TOOL_NAMES = {
    SPAWN_TEAMMATE_TOOL_NAME,
    LIST_TEAMMATES_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    READ_INBOX_TOOL_NAME,
    BROADCAST_TOOL_NAME,
    SHUTDOWN_TEAMMATE_TOOL_NAME,
}


@dataclass(frozen=True)
class TeammateSpec:
    name: str
    role: str
    description: str
    system_prompt: str
    tool_names: tuple[str, ...] = field(default_factory=tuple)
    max_turns: int = DEFAULT_TEAMMATE_MAX_TURNS


_BUILTIN_TEAMMATES: dict[str, dict[str, Any]] = {
    "architect": {
        "role": "System Architect",
        "description": (
            "Software architecture expert. Best for system design review, "
            "technology stack decisions, API design, data modeling, and "
            "architecture validation."
        ),
        "tool_names": (
            "read_file",
            "list_dir",
            "grep",
            "glob",
            "git_status",
            "git_diff",
            "web_fetch",
            "web_search",
            "list_skills",
            "read_skill",
        ),
        "max_turns": 10,
        "system_prompt": (
            "You are a system architect teammate in OmniAgent's team.\n"
            "- Analyze the codebase and provide architecture insights.\n"
            "- Recommend design patterns, technology choices, and structural improvements.\n"
            "- Identify architectural risks, bottlenecks, and technical debt.\n"
            "- Use read-only tools to inspect the codebase.\n"
            "- Use report_to_lead for important progress, blockers, findings, or questions.\n"
            "- Do not edit files, run mutating commands, or dispatch subagents.\n"
            "- Reply concisely with: analysis, recommendation, risks, and next steps."
        ),
    },
    "reviewer": {
        "role": "Code Reviewer",
        "description": (
            "Code quality reviewer. Best for code review, style checking, "
            "bug detection, security audit, and test coverage analysis."
        ),
        "tool_names": (
            "read_file",
            "list_dir",
            "grep",
            "glob",
            "bash",
            "local_http_check",
            "git_status",
            "git_diff",
            "list_skills",
            "read_skill",
        ),
        "max_turns": 12,
        "system_prompt": (
            "You are a code reviewer teammate in OmniAgent's team.\n"
            "- Review code for correctness, style, security, and performance.\n"
            "- Run safe diagnostic commands (no installs, no file mutations).\n"
            "- Identify bugs, anti-patterns, and improvement opportunities.\n"
            "- Cross-reference changes with existing code conventions.\n"
            "- Use report_to_lead for important progress, blockers, findings, or questions.\n"
            "- Do not edit files, run mutating commands, or dispatch subagents.\n"
            "- Reply concisely with: findings, severity, evidence, and fix suggestions."
        ),
    },
    "implementer": {
        "role": "Implementation Engineer",
        "description": (
            "Application implementation specialist. Best for scoped feature work, "
            "bug fixes, local refactors, tests, and acceptance verification."
        ),
        "tool_names": (
            "read_file",
            "list_dir",
            "grep",
            "glob",
            "bash",
            "local_http_check",
            "git_status",
            "git_diff",
            "list_skills",
            "read_skill",
            "write_file",
            "edit_file",
            "apply_patch",
            "apply_unified_patch",
        ),
        "max_turns": 14,
        "system_prompt": (
            "You are an implementation engineer teammate in OmniAgent's team.\n"
            "- Implement application code, focused bug fixes, local refactors, and tests.\n"
            "- Work only inside the assigned write_scope and do not touch unrelated files.\n"
            "- Read existing code and conventions before editing, then verify the result.\n"
            "- Use report_to_lead for important progress, blockers, findings, or questions.\n"
            "- Do not handle unrelated CI, deployment, or infrastructure work.\n"
            "- Do not dispatch subagents or spawn teammates.\n"
            "- Reply concisely with: changes, evidence, risks, and remaining work."
        ),
    },
    "devops": {
        "role": "DevOps Engineer",
        "description": (
            "DevOps and infrastructure specialist. Best for CI/CD configuration, "
            "Docker/containerization, deployment scripts, environment setup, "
            "and build system optimization."
        ),
        "tool_names": (
            "read_file",
            "list_dir",
            "grep",
            "glob",
            "bash",
            "web_fetch",
            "web_search",
            "git_status",
            "git_diff",
            "list_skills",
            "read_skill",
            "write_file",
            "edit_file",
            "apply_patch",
            "apply_unified_patch",
        ),
        "max_turns": 14,
        "system_prompt": (
            "You are a DevOps teammate in OmniAgent's team.\n"
            "- Handle only CI/CD, Docker, deployment, build, environment, and infrastructure tasks.\n"
            "- Work only inside the assigned write_scope and do not modify unrelated application code.\n"
            "- Read existing configuration before making changes.\n"
            "- Follow security best practices for credentials and secrets.\n"
            "- Write operations require approval unless approve or full mode is enabled.\n"
            "- Use report_to_lead for important progress, blockers, findings, or questions.\n"
            "- Do not dispatch subagents or spawn teammates.\n"
            "- Reply concisely with: actions taken, evidence, risks, and next steps."
        ),
    },
    "debugger": {
        "role": "Debug Specialist",
        "description": (
            "Debugging and troubleshooting expert. Best for error diagnosis, "
            "log analysis, runtime issue investigation, and root cause analysis."
        ),
        "tool_names": (
            "read_file",
            "list_dir",
            "grep",
            "glob",
            "bash",
            "local_http_check",
            "web_fetch",
            "web_search",
            "git_status",
            "git_diff",
            "list_skills",
            "read_skill",
        ),
        "max_turns": 15,
        "system_prompt": (
            "You are a debug specialist teammate in OmniAgent's team.\n"
            "- Analyze errors, logs, and test failures systematically.\n"
            "- Trace issues through the codebase to find root causes.\n"
            "- Run safe diagnostic commands (no installs, no file mutations).\n"
            "- Suggest fixes with reasoning and evidence.\n"
            "- Use report_to_lead for important progress, blockers, findings, or questions.\n"
            "- Do not edit files, run mutating commands, or dispatch subagents.\n"
            "- Reply concisely with: diagnosis, root cause, evidence, fix suggestion."
        ),
    },
}

_TEAMMATE_ALIASES = {
    "arch": "architect",
    "rev": "reviewer",
    "ops": "devops",
    "impl": "implementer",
    "dbg": "debugger",
}


def teammate_report_tool_definition() -> dict[str, Any]:
    return {
        "name": TEAMMATE_REPORT_TOOL_NAME,
        "description": (
            "Send an important progress update, blocker, finding, or question to the Lead. "
            f"Use sparingly; each teammate task may send at most {MAX_TEAMMATE_REPORTS_PER_TASK} reports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": sorted(TEAMMATE_REPORT_KINDS),
                    "description": "The report category.",
                },
                "message": {
                    "type": "string",
                    "description": "Concise report content for the Lead.",
                },
            },
            "required": ["kind", "message"],
        },
    }


def teammate_has_write_tools(spec: TeammateSpec) -> bool:
    return bool(WRITE_TOOL_NAMES & set(spec.tool_names))


def _scope_compare_text(value: str) -> str:
    text = str(value or "")
    return text.casefold() if os.name == "nt" else text


def _scope_static_root(scope: str) -> str:
    parts = []
    for part in _scope_compare_text(scope).split("/"):
        if any(char in part for char in "*?["):
            break
        parts.append(part)
    return "/".join(parts).strip("/")


def write_scopes_overlap(left: str, right: str) -> bool:
    left_root = _scope_static_root(left)
    right_root = _scope_static_root(right)
    if not left_root or not right_root:
        return True
    return (
        left_root == right_root
        or left_root.startswith(right_root + "/")
        or right_root.startswith(left_root + "/")
    )


def _glob_parts_match(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    if not pattern_parts:
        return not path_parts
    head = pattern_parts[0]
    if head == "**":
        return any(
            _glob_parts_match(path_parts[index:], pattern_parts[1:])
            for index in range(len(path_parts) + 1)
        )
    if not path_parts or not fnmatch.fnmatchcase(path_parts[0], head):
        return False
    return _glob_parts_match(path_parts[1:], pattern_parts[1:])


def path_matches_write_scope(relative_path: str, scope: str) -> bool:
    path = _scope_compare_text(relative_path).strip("/")
    pattern = _scope_compare_text(scope).strip("/")
    if not path or not pattern:
        return False
    if not any(char in pattern for char in "*?["):
        return path == pattern or path.startswith(pattern + "/")
    return _glob_parts_match(tuple(path.split("/")), tuple(pattern.split("/")))


def display_teammate_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _synchronized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class TeamStore:
    def __init__(
        self,
        workspace_dir: str | Path | None = None,
        templates_dir: str | Path | None = None,
    ):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else None
        self.templates_dir = Path(templates_dir) if templates_dir else None
        self._builtin_names = set(_BUILTIN_TEAMMATES.keys())
        self._lock = threading.RLock()
        self._specs: dict[str, TeammateSpec] = {}
        self.reload_specs()

    @_synchronized
    def reload_specs(self) -> None:
        self._specs = {}
        self._load_builtin_specs()
        self._load_custom_specs()

    @property
    def team_dir(self) -> Path | None:
        if self.workspace_dir is None:
            return None
        return self.workspace_dir / TEAM_STORE_DIR

    @property
    def config_path(self) -> Path | None:
        td = self.team_dir
        return td / "config.json" if td else None

    @property
    def inbox_dir(self) -> Path | None:
        td = self.team_dir
        return td / "inbox" if td else None

    @property
    def threads_dir(self) -> Path | None:
        td = self.team_dir
        return td / "threads" if td else None

    def _load_builtin_specs(self) -> None:
        for name, config in _BUILTIN_TEAMMATES.items():
            tool_names = tuple(config["tool_names"])
            forbidden = sorted(set(tool_names) & FORBIDDEN_TEAM_TOOL_NAMES)
            if forbidden:
                raise ValueError(
                    f"Teammate '{name}' includes forbidden tools: {', '.join(forbidden)}"
                )
            self._specs[name] = TeammateSpec(
                name=display_teammate_name(name),
                role=config["role"],
                description=config["description"],
                system_prompt=self._template_prompt(name, config["system_prompt"]),
                tool_names=tool_names,
                max_turns=int(config["max_turns"]),
            )

    def _load_custom_specs(self) -> None:
        config = self.load_config()
        members = config.get("members", {})
        if not isinstance(members, dict):
            return
        for name, member in members.items():
            member_name = str(name or "").strip().lower()
            if not member_name or not isinstance(member, dict):
                continue
            spec = self._spec_from_data(member_name, member)
            if spec is not None:
                self._specs[member_name] = spec

    def _template_prompt(self, name: str, fallback: str) -> str:
        templates_dir = self.templates_dir
        if templates_dir is None and self.workspace_dir is not None:
            templates_dir = self.workspace_dir / ".omniagent" / "team"
        if templates_dir is None:
            return fallback
        template_path = templates_dir / f"{name}.md"
        if not template_path.is_file():
            return fallback
        try:
            content = template_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return fallback
        content = content.strip()
        return content or fallback

    def resolve_name(self, name: str) -> str:
        key = str(name or "").strip().lower()
        return _TEAMMATE_ALIASES.get(key, key)

    def get_spec(self, name: str) -> TeammateSpec | None:
        self.reload_specs()
        return self._specs.get(self.resolve_name(name))

    def names(self, *, include_aliases: bool = False) -> list[str]:
        self.reload_specs()
        result = set(self._specs.keys())
        if include_aliases:
            result.update(_TEAMMATE_ALIASES.keys())
        return sorted(result)

    def spec_records(self) -> list[dict[str, Any]]:
        self.reload_specs()
        config = self.load_config()
        members = config.get("members", {})
        if not isinstance(members, dict):
            members = {}
        records = []
        for name in sorted(self._specs.keys()):
            spec = self._specs[name]
            source = "builtin"
            if name in members and name in self._builtin_names:
                source = "override"
            elif name in members:
                source = "custom"
            records.append({
                "key": name,
                "name": spec.name,
                "role": spec.role,
                "description": spec.description,
                "system_prompt": spec.system_prompt,
                "tool_names": list(spec.tool_names),
                "max_turns": int(spec.max_turns),
                "source": source,
                "builtin": name in self._builtin_names,
                "customized": name in members,
                "active": self.is_active(name),
            })
        return records

    def get_spec_record(self, name: str) -> dict[str, Any] | None:
        resolved = self.resolve_name(name)
        for record in self.spec_records():
            if str(record.get("key") or "") == resolved:
                return record
        return None

    def describe(self) -> str:
        lines = [
            f"- {spec.name} ({spec.role}): {spec.description}"
            for spec in self._specs.values()
        ]
        if _TEAMMATE_ALIASES:
            aliases = ", ".join(
                f"{a} -> {t}" for a, t in sorted(_TEAMMATE_ALIASES.items())
            )
            lines.append(f"- aliases: {aliases}")
        return "\n".join(lines)

    def ensure_dirs(self) -> None:
        if self.team_dir is None:
            return
        self.team_dir.mkdir(parents=True, exist_ok=True)
        if self.inbox_dir:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
        if self.threads_dir:
            self.threads_dir.mkdir(parents=True, exist_ok=True)

    @_synchronized
    def load_config(self) -> dict[str, Any]:
        cp = self.config_path
        if cp is None or not cp.is_file():
            return {}
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @_synchronized
    def save_config(self, data: dict[str, Any]) -> None:
        cp = self.config_path
        if cp is None:
            return
        atomic_write_json(cp, data)

    def save_spec(
        self,
        name: str,
        *,
        role: str,
        description: str,
        system_prompt: str,
        tool_names: list[str] | tuple[str, ...],
        max_turns: int,
        old_name: str | None = None,
    ) -> str:
        old_key = self.resolve_name(old_name or name)
        new_key = self.resolve_name(name)
        if not new_key:
            raise ValueError("Teammate name cannot be empty.")
        if old_key in self._builtin_names and new_key != old_key:
            raise ValueError("Builtin teammates cannot be renamed.")
        if not role.strip():
            raise ValueError("Role cannot be empty.")
        if not description.strip():
            raise ValueError("Description cannot be empty.")
        if not system_prompt.strip():
            raise ValueError("System prompt cannot be empty.")
        max_turns = max(1, int(max_turns))
        cleaned_tools = self._normalize_tool_names(tool_names)
        forbidden = sorted(set(cleaned_tools) & FORBIDDEN_TEAM_TOOL_NAMES)
        if forbidden:
            raise ValueError(
                "Teammate includes forbidden tools: " + ", ".join(forbidden)
            )

        config = self.load_config()
        members = config.get("members", {})
        if not isinstance(members, dict):
            members = {}
        if new_key != old_key and (new_key in self._specs or new_key in members):
            raise ValueError(f"Teammate already exists: {new_key}")

        if old_key != new_key and old_key in members:
            members.pop(old_key, None)
        members[new_key] = {
            "role": role.strip(),
            "description": description.strip(),
            "system_prompt": system_prompt.strip(),
            "tool_names": cleaned_tools,
            "max_turns": max_turns,
        }
        config["members"] = members

        teammates = config.get("teammates", [])
        if isinstance(teammates, list) and old_key != new_key:
            for teammate in teammates:
                if self.resolve_name(teammate.get("name")) == old_key:
                    teammate["name"] = display_teammate_name(new_key)
                    teammate["role"] = role.strip()
        elif isinstance(teammates, list):
            for teammate in teammates:
                if self.resolve_name(teammate.get("name")) == new_key:
                    teammate["name"] = display_teammate_name(new_key)
                    teammate["role"] = role.strip()

        self.save_config(config)
        if old_key != new_key:
            self._rename_member_files(old_key, new_key)
        self.reload_specs()
        return new_key

    def delete_spec(self, name: str) -> bool:
        resolved = self.resolve_name(name)
        config = self.load_config()
        members = config.get("members", {})
        if not isinstance(members, dict):
            members = {}
        if resolved not in members:
            return False
        members.pop(resolved, None)
        config["members"] = members
        if resolved not in self._builtin_names:
            teammates = config.get("teammates", [])
            if isinstance(teammates, list):
                config["teammates"] = [
                    teammate
                    for teammate in teammates
                    if self.resolve_name(teammate.get("name")) != resolved
                ]
            self._delete_member_files(resolved)
        self.save_config(config)
        self.reload_specs()
        return True

    def create_default_member(self, base_name: str = "member") -> str:
        existing = set(self.names())
        index = 1
        candidate = str(base_name or "member").strip().lower() or "member"
        name = candidate
        while name in existing:
            index += 1
            name = f"{candidate}{index}"
        return self.save_spec(
            name,
            role=DEFAULT_TEAMMATE_ROLE,
            description=DEFAULT_TEAMMATE_DESCRIPTION,
            system_prompt=DEFAULT_TEAMMATE_PROMPT,
            tool_names=["read_file", "list_dir", "grep", "glob"],
            max_turns=DEFAULT_TEAMMATE_MAX_TURNS,
        )

    @_synchronized
    def get_roster(self) -> list[dict[str, Any]]:
        config = self.load_config()
        return config.get("teammates", [])

    @_synchronized
    def reconcile_stale_tasks(self) -> int:
        config = self.load_config()
        teammates = config.get("teammates", [])
        changed = 0
        for teammate in teammates:
            if str(teammate.get("status") or "") not in ACTIVE_TEAMMATE_STATUSES:
                continue
            teammate["status"] = "interrupted"
            teammate["error"] = "The previous OmniAgent session ended before this task completed."
            teammate["write_scope"] = []
            teammate["updated_at"] = _now_iso()
            changed += 1
        if changed:
            self.save_config(config)
        return changed

    def is_active(self, name: str) -> bool:
        roster = self.get_roster()
        resolved = self.resolve_name(name)
        return any(self.resolve_name(t.get("name")) == resolved for t in roster)

    @_synchronized
    def add_teammate(self, name: str) -> dict[str, Any]:
        resolved = self.resolve_name(name)
        spec = self.get_spec(resolved)
        if spec is None:
            raise ValueError(f"Unknown teammate type: {name!r}")
        config = self.load_config()
        teammates = config.get("teammates", [])
        existing = [
            t for t in teammates if self.resolve_name(t.get("name")) == resolved
        ]
        if existing:
            existing[0]["name"] = spec.name
            existing[0]["status"] = "active"
            self.save_config(config)
            return existing[0]
        entry = {
            "name": spec.name,
            "role": spec.role,
            "status": "active",
            "created_at": _now_iso(),
            "task_count": 0,
        }
        teammates.append(entry)
        config["teammates"] = teammates
        self.save_config(config)
        return entry

    @_synchronized
    def remove_teammate(self, name: str) -> bool:
        resolved = self.resolve_name(name)
        config = self.load_config()
        teammates = config.get("teammates", [])
        new_list = [
            t for t in teammates if self.resolve_name(t.get("name")) != resolved
        ]
        if len(new_list) == len(teammates):
            return False
        config["teammates"] = new_list
        self.save_config(config)
        return True

    @_synchronized
    def start_task(
        self,
        name: str,
        *,
        task_id: str,
        task: str,
        write_scope: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_name(name)
        spec = self.get_spec(resolved)
        if spec is None:
            raise ValueError(f"Unknown teammate type: {name!r}")
        scopes = self.normalize_write_scope(write_scope)
        if teammate_has_write_tools(spec) and not scopes:
            raise ValueError(
                f"Teammate '{spec.name}' has file-writing tools and requires a non-empty write_scope."
            )
        config = self.load_config()
        teammates = config.get("teammates", [])
        for teammate in teammates:
            if str(teammate.get("status") or "") not in ACTIVE_TEAMMATE_STATUSES:
                continue
            existing_task_id = str(teammate.get("task_id") or "")
            if self.resolve_name(teammate.get("name")) == resolved and existing_task_id != task_id:
                raise ValueError(f"Teammate '{spec.name}' already has a running task.")
            owned_scopes = tuple(
                str(item) for item in teammate.get("write_scope") or [] if str(item)
            )
            if scopes and any(
                write_scopes_overlap(scope, owned)
                for scope in scopes
                for owned in owned_scopes
            ):
                owner_name = str(teammate.get("name") or "another teammate")
                owner_role = str(teammate.get("role") or "writer")
                raise ValueError(
                    "write_scope overlaps active owner "
                    f"{owner_name} ({owner_role}): {', '.join(owned_scopes)}"
                )
        entry = next(
            (
                teammate
                for teammate in teammates
                if self.resolve_name(teammate.get("name")) == resolved
            ),
            None,
        )
        if entry is None:
            entry = {
                "name": spec.name,
                "role": spec.role,
                "created_at": _now_iso(),
                "task_count": 0,
            }
            teammates.append(entry)
        entry.update({
            "name": spec.name,
            "role": spec.role,
            "status": "running",
            "task_id": str(task_id),
            "task": str(task or ""),
            "write_scope": list(scopes),
            "updated_at": _now_iso(),
        })
        entry.pop("error", None)
        config["teammates"] = teammates
        self.save_config(config)
        return dict(entry)

    @_synchronized
    def update_status(
        self,
        name: str,
        status: str,
        task_count: int = 0,
        *,
        task_id: str | None = None,
        task: str | None = None,
        error: str | None = None,
        write_scope: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        resolved = self.resolve_name(name)
        config = self.load_config()
        teammates = config.get("teammates", [])
        for t in teammates:
            if self.resolve_name(t.get("name")) == resolved:
                t["name"] = display_teammate_name(resolved)
                t["status"] = str(status or "active")
                t["task_count"] = t.get("task_count", 0) + task_count
                t["updated_at"] = _now_iso()
                if task_id is not None:
                    t["task_id"] = str(task_id)
                if task is not None:
                    t["task"] = str(task)
                if write_scope is not None:
                    t["write_scope"] = list(write_scope)
                elif str(status or "") not in ACTIVE_TEAMMATE_STATUSES:
                    t["write_scope"] = []
                if error is not None:
                    t["error"] = str(error)
                elif status not in {"failed", "cancelled"}:
                    t.pop("error", None)
                break
        self.save_config(config)

    def normalize_write_scope(
        self, values: list[str] | tuple[str, ...] | None
    ) -> tuple[str, ...]:
        if values is None:
            return ()
        if not isinstance(values, (list, tuple)):
            raise ValueError("write_scope must be an array of workspace-relative paths or globs.")
        normalized = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("write_scope entries must be strings.")
            text = value.strip().replace("\\", "/")
            if (
                not text
                or text.startswith("/")
                or text.startswith("//")
                or re.match(r"^[A-Za-z]:", text)
            ):
                if not text:
                    raise ValueError("write_scope entries cannot be empty.")
                raise ValueError(f"write_scope must be workspace-relative: {value!r}")
            while text.startswith("./"):
                text = text[2:]
            text = text.rstrip("/")
            if not text:
                raise ValueError("write_scope entries cannot be empty.")
            raw_parts = text.split("/")
            if any(part in {"", ".", ".."} for part in raw_parts):
                raise ValueError(f"Invalid write_scope entry: {value!r}")
            if "\x00" in text or text.count("[") != text.count("]"):
                raise ValueError(f"Invalid write_scope entry: {value!r}")
            normalized_text = PurePosixPath(*raw_parts).as_posix()
            if normalized_text not in normalized:
                normalized.append(normalized_text)
        return tuple(normalized)

    def workspace_relative_path(self, file_path: str | Path) -> str:
        if self.workspace_dir is None:
            raise ValueError("No workspace is configured.")
        root = self.workspace_dir.resolve(strict=False)
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Path is outside the workspace: {file_path}") from error
        return relative.as_posix()

    @_synchronized
    def active_write_owners(self) -> list[dict[str, Any]]:
        owners = []
        for teammate in self.load_config().get("teammates", []):
            if str(teammate.get("status") or "") not in ACTIVE_TEAMMATE_STATUSES:
                continue
            scope = tuple(str(item) for item in teammate.get("write_scope") or [] if str(item))
            if not scope:
                continue
            owners.append({
                "name": str(teammate.get("name") or ""),
                "role": str(teammate.get("role") or ""),
                "task_id": str(teammate.get("task_id") or ""),
                "write_scope": scope,
            })
        return owners

    @_synchronized
    def find_write_scope_conflict(
        self, scopes: list[str] | tuple[str, ...], *, exclude_task_id: str = ""
    ) -> dict[str, Any] | None:
        for owner in self.active_write_owners():
            if exclude_task_id and owner.get("task_id") == exclude_task_id:
                continue
            if any(
                write_scopes_overlap(scope, owned)
                for scope in scopes
                for owned in owner.get("write_scope", ())
            ):
                return owner
        return None

    @_synchronized
    def find_write_owner_for_path(
        self, relative_path: str, *, exclude_task_id: str = ""
    ) -> dict[str, Any] | None:
        for owner in self.active_write_owners():
            if exclude_task_id and owner.get("task_id") == exclude_task_id:
                continue
            if any(
                path_matches_write_scope(relative_path, scope)
                for scope in owner.get("write_scope", ())
            ):
                return owner
        return None

    @_synchronized
    def send_message(
        self,
        from_name: str,
        to_name: str,
        content: str,
        *,
        kind: str = "message",
        task_id: str = "",
        status: str = "",
        report_kind: str = "",
    ) -> str:
        self.ensure_dirs()
        resolved_to = self.resolve_name(to_name)
        inbox_path = self.inbox_dir / f"{resolved_to}.jsonl"
        entry = {
            "from": from_name or "lead",
            "content": content,
            "timestamp": _now_iso(),
            "kind": str(kind or "message"),
        }
        if task_id:
            entry["task_id"] = str(task_id)
        if status:
            entry["status"] = str(status)
        if report_kind:
            entry["report_kind"] = str(report_kind)
        with self._lock:
            append_jsonl(inbox_path, entry)
        target = "lead" if resolved_to == "lead" else display_teammate_name(resolved_to)
        return f"Message sent to '{target}'."

    @_synchronized
    def read_inbox(self, name: str, clear: bool = False) -> list[dict[str, Any]]:
        self.ensure_dirs()
        resolved = self.resolve_name(name) if name else "lead"
        inbox_path = self.inbox_dir / f"{resolved}.jsonl"
        with self._lock:
            if not inbox_path.is_file():
                return []
            try:
                lines = inbox_path.read_text(encoding="utf-8").strip().splitlines()
                messages = [json.loads(line) for line in lines if line.strip()]
            except (json.JSONDecodeError, OSError):
                return []
            if clear and messages:
                atomic_write_text(inbox_path, "")
            return messages

    @_synchronized
    def broadcast(
        self, from_name: str, content: str, teammate_names: list[str] | None = None
    ) -> str:
        config = self.load_config()
        teammates = config.get("teammates", [])
        if teammate_names:
            resolved = {self.resolve_name(n) for n in teammate_names}
            targets = [
                t for t in teammates if self.resolve_name(t.get("name")) in resolved
            ]
        else:
            targets = teammates
        if not targets:
            return "No active teammates to broadcast to."
        sent = []
        for t in targets:
            self.send_message(from_name, t["name"], content)
            sent.append(display_teammate_name(t["name"]))
        return f"Broadcast sent to: {', '.join(sent)}."

    @_synchronized
    def save_thread(self, name: str, messages: list[dict[str, Any]]) -> None:
        self.ensure_dirs()
        resolved = self.resolve_name(name)
        thread_path = self.threads_dir / f"{resolved}.jsonl"
        content = "".join(
            json.dumps(message, ensure_ascii=False) + "\n" for message in messages
        )
        atomic_write_text(thread_path, content)

    @_synchronized
    def load_thread(self, name: str) -> list[dict[str, Any]]:
        resolved = self.resolve_name(name)
        thread_path = self.threads_dir / f"{resolved}.jsonl"
        if not thread_path.is_file():
            return []
        try:
            lines = thread_path.read_text(encoding="utf-8").strip().splitlines()
            return [json.loads(line) for line in lines if line.strip()]
        except (json.JSONDecodeError, OSError):
            return []

    def _spec_from_data(self, name: str, data: dict[str, Any]) -> TeammateSpec | None:
        role = str(data.get("role") or "").strip() or DEFAULT_TEAMMATE_ROLE
        description = (
            str(data.get("description") or "").strip() or DEFAULT_TEAMMATE_DESCRIPTION
        )
        system_prompt = (
            str(data.get("system_prompt") or "").strip() or DEFAULT_TEAMMATE_PROMPT
        )
        tool_names = self._normalize_tool_names(data.get("tool_names") or [])
        forbidden = sorted(set(tool_names) & FORBIDDEN_TEAM_TOOL_NAMES)
        if forbidden:
            raise ValueError(
                f"Teammate '{name}' includes forbidden tools: {', '.join(forbidden)}"
            )
        max_turns = int(data.get("max_turns") or DEFAULT_TEAMMATE_MAX_TURNS)
        max_turns = max(1, max_turns)
        return TeammateSpec(
            name=display_teammate_name(name),
            role=role,
            description=description,
            system_prompt=system_prompt,
            tool_names=tuple(tool_names),
            max_turns=max_turns,
        )

    def _normalize_tool_names(
        self, tool_names: list[str] | tuple[str, ...] | str
    ) -> list[str]:
        if isinstance(tool_names, str):
            parts = tool_names.split(",")
        else:
            parts = list(tool_names or [])
        cleaned = []
        for part in parts:
            name = str(part or "").strip()
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned

    def _rename_member_files(self, old_name: str, new_name: str) -> None:
        for directory in (self.inbox_dir, self.threads_dir):
            if directory is None:
                continue
            old_path = directory / f"{old_name}.jsonl"
            new_path = directory / f"{new_name}.jsonl"
            if not old_path.exists():
                continue
            try:
                if new_path.exists():
                    new_path.unlink()
                old_path.rename(new_path)
            except OSError:
                continue

    def _delete_member_files(self, name: str) -> None:
        for directory in (self.inbox_dir, self.threads_dir):
            if directory is None:
                continue
            path = directory / f"{name}.jsonl"
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                continue


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().isoformat()


class TeamRunner(SubagentRunner):
    """Background teammate runner with live transcript and inbox delivery."""

    def __init__(
        self,
        parent_agent: Any,
        spec: TeammateSpec,
        tool_schemas: list[dict[str, Any]],
        execute_tool: Callable[[str, dict[str, Any]], str],
        team_store: TeamStore | None = None,
        api_type: str = "anthropic",
        max_tool_calls: int | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        stop_event: Any = None,
    ):
        self.team_store = team_store
        self.stop_event = stop_event
        super().__init__(
            parent_agent=parent_agent,
            spec=spec,
            tool_schemas=tool_schemas,
            execute_tool=execute_tool,
            max_tool_calls=max_tool_calls
            or spec.max_turns * DEFAULT_TEAMMATE_TOOL_CALL_FACTOR,
            event_callback=event_callback,
            worker_label=f"Teammate '{spec.name}'",
            before_turn_callback=self._drain_inbox,
            stop_requested=self._stop_requested,
            forbidden_tool_names=set(FORBIDDEN_TEAM_TOOL_NAMES) | set(TEAM_TOOL_NAMES),
        )
        self.allowed_tool_names.add(TEAMMATE_REPORT_TOOL_NAME)

    def _stop_requested(self) -> bool:
        return bool(self.stop_event is not None and self.stop_event.is_set())

    def _drain_inbox(self) -> list[dict[str, Any]]:
        if self.team_store is None:
            return []
        messages = self.team_store.read_inbox(self.spec.name, clear=True)
        result = []
        for message in messages:
            sender = str(message.get("from") or "lead")
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            result.append({
                "content": content,
                "source": sender,
                "team_message": True,
            })
        return result

def compose_teammate_task(
    task: str,
    *,
    expected_output: str | None = None,
    evidence_required: str | None = None,
    scope_limit: str | None = None,
    write_scope: list[str] | tuple[str, ...] | None = None,
) -> str:
    contract = []
    if expected_output:
        contract.append(f"- Expected output: {expected_output}")
    if evidence_required:
        contract.append(f"- Evidence required: {evidence_required}")
    if scope_limit:
        contract.append(f"- Scope limit: {scope_limit}")
    normalized_scope = [str(item) for item in (write_scope or ()) if str(item)]
    if normalized_scope:
        contract.append("- Write scope: " + ", ".join(normalized_scope))
        contract.append(
            "- You may use direct file-writing tools only inside the write scope. "
            "Do not use bash or any other tool to modify files outside it."
        )
    contract.append(
        "- Final reply must include: conclusion, evidence, risks, and suggested next step."
    )
    return f"{str(task or '').rstrip()}\n\nTeammate contract:\n" + "\n".join(contract)
