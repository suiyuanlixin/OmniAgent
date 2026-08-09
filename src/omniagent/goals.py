from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

GOAL_VERSION = 1
GOAL_UPDATE_TOOL_NAME = "update_goal"
GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_PAUSED = "paused"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_BLOCKED = "blocked"
GOAL_STATUS_FAILED = "failed"
GOAL_STATUS_CANCELLED = "cancelled"
GOAL_STATUSES = frozenset({GOAL_STATUS_ACTIVE, GOAL_STATUS_PAUSED, GOAL_STATUS_COMPLETED, GOAL_STATUS_BLOCKED, GOAL_STATUS_FAILED, GOAL_STATUS_CANCELLED})
GOAL_PHASE_PLANNING = "planning"
GOAL_PHASE_BUILDING = "building"
GOAL_PHASE_VERIFYING = "verifying"
GOAL_PHASES = frozenset({GOAL_PHASE_PLANNING, GOAL_PHASE_BUILDING, GOAL_PHASE_VERIFYING})
_TERMINAL_STATUSES = frozenset({GOAL_STATUS_COMPLETED, GOAL_STATUS_FAILED, GOAL_STATUS_CANCELLED})
_STATUS_MARKER = re.compile(r"<!--\s*omniagent-goal\s*(\{.*?\})\s*-->", re.IGNORECASE | re.DOTALL)

GOAL_UPDATE_TOOL_DEFINITION = {
    "name": GOAL_UPDATE_TOOL_NAME,
    "description": (
        "Update the active persistent Goal checkpoint. Call this before ending each Goal turn. "
        "Use active while work should continue automatically, blocked when user input or an "
        "external condition is required, failed for an unrecoverable failure, and completed only "
        "after the Goal success criteria have been verified."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": [
                    GOAL_STATUS_ACTIVE,
                    GOAL_STATUS_COMPLETED,
                    GOAL_STATUS_BLOCKED,
                    GOAL_STATUS_FAILED,
                ],
            },
            "progress": {"type": "string"},
            "current_step": {"type": "string"},
            "reason": {"type": "string"},
            "success_criteria": {"type": "string"},
            "verification_report": {"type": "string"},
        },
        "required": ["status", "progress", "current_step"],
        "additionalProperties": False,
    },
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _text(value: Any, limit: int = 4000) -> str:
    return ("" if value is None else str(value)).strip()[:limit]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result >= 0.0 else default


def _new_id() -> str:
    return f"goal-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass
class Goal:
    id: str
    description: str
    success_criteria: str = ""
    status: str = GOAL_STATUS_ACTIVE
    phase: str = GOAL_PHASE_PLANNING
    session_id: str = ""
    workspace_dir: str = ""
    iteration: int = 0
    current_step: str = ""
    progress: str = ""
    last_error: str = ""
    plan: str = ""
    verification_report: str = ""
    elapsed_seconds: float = 0.0
    run_started_at: str = field(default_factory=_now)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def create(cls, description: str, success_criteria: str = "", *, session_id: str = "", workspace_dir: str = "") -> "Goal":
        description = _text(description)
        if not description:
            raise ValueError("Goal description cannot be empty.")
        return cls(id=_new_id(), description=description, success_criteria=_text(success_criteria), session_id=_text(session_id, 256), workspace_dir=_text(workspace_dir, 2000))

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Goal | None":
        if not isinstance(data, dict):
            return None
        version = _safe_int(data.get("version", GOAL_VERSION), GOAL_VERSION)
        if version > GOAL_VERSION:
            return None
        description = _text(data.get("description") or data.get("goal"))
        if not description:
            return None
        status = str(data.get("status") or GOAL_STATUS_ACTIVE).strip().lower()
        phase = str(data.get("phase") or GOAL_PHASE_PLANNING).strip().lower()
        if status not in GOAL_STATUSES:
            status = GOAL_STATUS_ACTIVE
        if phase not in GOAL_PHASES:
            phase = GOAL_PHASE_PLANNING
        created_at = _text(data.get("created_at"), 64) or _now()
        run_started_at = _text(data.get("run_started_at"), 64)
        if status == GOAL_STATUS_ACTIVE and not run_started_at:
            run_started_at = created_at
        return cls(
            id=_text(data.get("id"), 256) or _new_id(),
            description=description,
            success_criteria=_text(data.get("success_criteria")),
            status=status,
            phase=phase,
            session_id=_text(data.get("session_id"), 256),
            workspace_dir=_text(data.get("workspace_dir"), 2000),
            iteration=max(0, _safe_int(data.get("iteration"))),
            current_step=_text(data.get("current_step"), 1000),
            progress=_text(data.get("progress"), 2000),
            last_error=_text(data.get("last_error"), 2000),
            plan=_text(data.get("plan"), 12000),
            verification_report=_text(data.get("verification_report"), 12000),
            elapsed_seconds=_safe_float(data.get("elapsed_seconds")),
            run_started_at=run_started_at,
            created_at=created_at,
            updated_at=_text(data.get("updated_at"), 64) or _now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"version": GOAL_VERSION, "id": self.id, "description": self.description, "success_criteria": self.success_criteria, "status": self.status, "phase": self.phase, "session_id": self.session_id, "workspace_dir": self.workspace_dir, "iteration": self.iteration, "current_step": self.current_step, "progress": self.progress, "last_error": self.last_error, "plan": self.plan, "verification_report": self.verification_report, "elapsed_seconds": self.elapsed_seconds, "run_started_at": self.run_started_at, "created_at": self.created_at, "updated_at": self.updated_at}

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def update(self, **changes) -> "Goal":
        next_status = str(changes.get("status") or self.status).strip().lower()
        if next_status in GOAL_STATUSES and next_status != self.status:
            if self.status == GOAL_STATUS_ACTIVE and self.run_started_at:
                try:
                    started = datetime.fromisoformat(self.run_started_at)
                    self.elapsed_seconds += max(
                        0.0, (datetime.now() - started).total_seconds()
                    )
                except (TypeError, ValueError):
                    pass
                self.run_started_at = ""
            if next_status == GOAL_STATUS_ACTIVE:
                self.run_started_at = _now()
        for key, value in changes.items():
            if key == "status":
                value = str(value or "").strip().lower()
                if value not in GOAL_STATUSES:
                    raise ValueError(f"Unknown Goal status: {value}")
            elif key == "phase":
                value = str(value or "").strip().lower()
                if value not in GOAL_PHASES:
                    raise ValueError(f"Unknown Goal phase: {value}")
            elif key in {"description", "success_criteria", "current_step", "progress", "last_error", "plan", "verification_report"}:
                value = _text(value)
            elif key == "iteration":
                value = max(0, int(value or 0))
            elif key in {"session_id", "workspace_dir"}:
                value = _text(value, 2000)
            if not hasattr(self, key):
                raise ValueError(f"Unknown Goal field: {key}")
            setattr(self, key, value)
        self.updated_at = _now()
        return self

    def current_elapsed_seconds(self) -> float:
        elapsed = max(0.0, float(self.elapsed_seconds or 0.0))
        if self.status == GOAL_STATUS_ACTIVE and self.run_started_at:
            try:
                started = datetime.fromisoformat(self.run_started_at)
                elapsed += max(0.0, (datetime.now() - started).total_seconds())
            except (TypeError, ValueError):
                pass
        return elapsed


class GoalRunner:
    """Durable state coordinator around OmniAgent's existing model/tool loop."""

    def __init__(
        self,
        goal: Goal,
        *,
        on_change: Callable[[Goal], None] | None = None,
        completion_validator: Callable[[Goal, dict[str, Any]], str] | None = None,
    ):
        self.goal = goal
        self.on_change = on_change
        self.completion_validator = completion_validator

    def _changed(self, **changes) -> Goal:
        self.goal.update(**changes)
        if callable(self.on_change):
            self.on_change(self.goal)
        return self.goal

    def prompt_context(self) -> str:
        criteria = self.goal.success_criteria or "No explicit success criteria have been recorded yet."
        plan = self.goal.plan or "No durable plan has been recorded yet."
        progress = self.goal.progress or "No progress has been recorded yet."
        return (
            "\n\nPERSISTENT GOAL CONTEXT\n"
            f"Goal ID: {self.goal.id}\n"
            f"Goal: {self.goal.description}\n"
            f"Success criteria: {criteria}\n"
            f"Current phase: {self.goal.phase}\n"
            f"Current step: {self.goal.current_step or '(not selected)'}\n"
            f"Recorded plan: {plan}\n"
            f"Latest progress: {progress}\n"
            "This Goal persists across turns and coordinates the existing Plan and Build modes. "
            "Continue from the recorded state and do not repeat verified work. Before ending this "
            "Goal turn, call update_goal with a durable checkpoint. Use active while work should "
            "continue automatically; use blocked when user input, permission, or an external "
            "condition is required; use failed only for an unrecoverable failure; use completed "
            "only after the success criteria have been verified."
        )

    def begin_turn(self, *, phase: str | None = None) -> Goal:
        if self.goal.status != GOAL_STATUS_ACTIVE:
            return self.goal
        changes = {"iteration": self.goal.iteration + 1}
        if phase:
            changes["phase"] = phase
        return self._changed(**changes)

    def pause_for_error(self, error: Any) -> Goal:
        if self.goal.status != GOAL_STATUS_ACTIVE:
            return self.goal
        message = _text(error, 2000) or "Goal request failed."
        return self._changed(
            status=GOAL_STATUS_PAUSED,
            progress="Paused after a request error.",
            last_error=message,
        )

    def apply_tool_update(self, tool_input: dict[str, Any], *, phase: str) -> Goal:
        if self.goal.status != GOAL_STATUS_ACTIVE:
            raise ValueError("Goal is not active.")
        if not isinstance(tool_input, dict):
            raise ValueError("Goal update input must be an object.")
        status = str(tool_input.get("status") or "").strip().lower()
        if status not in {
            GOAL_STATUS_ACTIVE,
            GOAL_STATUS_COMPLETED,
            GOAL_STATUS_BLOCKED,
            GOAL_STATUS_FAILED,
        }:
            raise ValueError(f"Unknown Goal status: {status}")
        reason = _text(tool_input.get("reason"), 2000)
        if status in {GOAL_STATUS_BLOCKED, GOAL_STATUS_FAILED} and not reason:
            raise ValueError(f"Goal status '{status}' requires a reason.")
        if status == GOAL_STATUS_COMPLETED and callable(self.completion_validator):
            validation_error = _text(
                self.completion_validator(self.goal, tool_input), 2000
            )
            if validation_error:
                raise ValueError(validation_error)
        changes = {
            "status": status,
            "phase": phase,
            "progress": _text(tool_input.get("progress"), 2000),
            "current_step": _text(tool_input.get("current_step"), 1000),
            "last_error": reason,
        }
        if "success_criteria" in tool_input:
            changes["success_criteria"] = _text(
                tool_input.get("success_criteria"), 4000
            )
        if "verification_report" in tool_input:
            changes["verification_report"] = _text(
                tool_input.get("verification_report"), 12000
            )
        if status not in {GOAL_STATUS_BLOCKED, GOAL_STATUS_FAILED}:
            changes["last_error"] = ""
        return self._changed(**changes)

    def observe_response(self, response: dict[str, Any] | None, *, agent=None) -> Goal:
        if self.goal.status != GOAL_STATUS_ACTIVE:
            return self.goal
        response = response if isinstance(response, dict) else {}
        if response.get("agent_stopped"):
            return self._changed(status=GOAL_STATUS_PAUSED, progress="Paused by user.")

        phase = self.goal.phase
        if agent is not None:
            try:
                status = agent.get_agent_status()
                if status.get("plan_mode"):
                    phase = GOAL_PHASE_PLANNING
                elif getattr(agent, "agent_final_check_done", False):
                    phase = GOAL_PHASE_VERIFYING
                else:
                    phase = GOAL_PHASE_BUILDING
                plan = status.get("plan") or {}
                active_items = plan.get("active_items") or []
                if active_items:
                    self.goal.plan = _text(
                        "\n".join(
                            f"- [{item.get('status', 'pending')}] {item.get('content', '')}"
                            for item in active_items
                            if isinstance(item, dict)
                        ),
                        12000,
                    )
                current = next(
                    (
                        item
                        for item in active_items
                        if str(item.get("status")) == "in_progress"
                    ),
                    None,
                )
                if current:
                    self.goal.current_step = _text(current.get("content"), 1000)
            except Exception:
                pass

        marker = self.parse_marker(response.get("response", ""))
        if marker:
            marker_input = {
                "status": marker.get("status") or GOAL_STATUS_ACTIVE,
                "progress": marker.get("progress") or response.get("response") or "",
                "current_step": marker.get("current_step") or self.goal.current_step,
            }
            for key in ("reason", "success_criteria", "verification_report"):
                if key in marker:
                    marker_input[key] = marker.get(key)
            if (
                marker_input["status"] == GOAL_STATUS_COMPLETED
                and "verification_report" not in marker_input
            ):
                marker_input["verification_report"] = marker.get("progress") or ""
            try:
                updated = self.apply_tool_update(marker_input, phase=phase)
            except ValueError as error:
                return self._changed(
                    status=GOAL_STATUS_ACTIVE,
                    phase=phase,
                    progress=_text(response.get("response"), 2000),
                    last_error=_text(error, 2000),
                )
            if marker.get("plan"):
                return self._changed(plan=_text(marker.get("plan"), 12000))
            return updated

        return self._changed(
            status=GOAL_STATUS_ACTIVE,
            phase=phase,
            progress=_text(response.get("response"), 2000),
        )

    @staticmethod
    def parse_marker(text: Any) -> dict[str, Any]:
        match = _STATUS_MARKER.search(str(text or ""))
        if not match:
            return {}
        try:
            data = json.loads(match.group(1))
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def strip_marker(text: Any) -> str:
        return _STATUS_MARKER.sub("", str(text or "")).strip()


def goal_from_record(record: dict[str, Any] | None) -> Goal | None:
    return Goal.from_dict((record or {}).get("goal"))


def set_goal_on_record(record: dict[str, Any], goal: Goal | None) -> dict[str, Any]:
    updated = dict(record or {})
    if goal is None:
        updated.pop("goal", None)
    else:
        updated["goal"] = goal.to_dict()
    return updated


def goal_status_label(status: str) -> str:
    return str(status or GOAL_STATUS_ACTIVE).replace("_", " ").title()


def goal_phase_label(phase: str) -> str:
    return str(phase or GOAL_PHASE_PLANNING).replace("_", " ").title()
