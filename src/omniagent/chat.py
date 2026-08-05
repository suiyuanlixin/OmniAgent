import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ui import (
    add_explored_entry,
    add_tool_error_entry,
    append_subagent_event,
    begin_overflow_replay_scope,
    append_team_event,
    build_tool_error_display,
    clean_and_print_stream_response,
    clean_display_text,
    clean_thinking_text,
    commit_overflow_replay_scope,
    finish_compaction_entry,
    finish_team_entry,
    update_team_entry_status,
    finish_thinking_round,
    print_error,
    print_info,
    print_stream_thinking,
    print_stream_thinking_continue,
    print_stream_response_continue,
    print_stream_response_start,
    print_warn,
    rollback_overflow_replay_scope,
    set_todo_panel,
    set_context_usage,
    start_compaction_entry,
    start_subagent_entry,
    start_team_entry,
    tool_display_is_error,
    tool_result_is_error,
)
from .config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    AUTO_MODEL_SELECTION,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DEFAULT_MAX_AGENT_ROUNDS,
    DEFAULT_MAX_AGENT_TOOL_CALLS,
    GEMINI_OPENAI_BASE_URL,
    SUPPORTED_API_TYPES,
    normalize_api_type,
    normalize_extra_modalities,
    normalize_optional_model_selection,
    normalize_reasoning_effort_for_api,
)
from .memory import MemoryStore, parse_memory_update_response
from .paths import APP_HOME
from .orchestration import NormalToolCoordinator, NormalTurn
from .tools import (
    ASK_USER_TOOL_DEFINITION,
    AgentTools,
    PROGRAM_DOCS_TOOL_DEFINITION,
    PLAN_MODE_ALLOWED_TOOLS,
    PLAN_SUBAGENT_TYPES,
    SUBMIT_PLAN_TOOL_NAME,
    TOOL_DEFINITIONS,
    WEB_FETCH_TOOL_DEFINITION,
    WEB_SEARCH_TOOL_DEFINITION,
    anthropic_tool_schemas,
    glm_tool_schemas,
    ollama_tool_schemas,
    openai_tool_schemas,
)
from .subagents import (
    DISPATCH_SUBAGENT_TOOL_NAME,
    FORBIDDEN_SUBAGENT_TOOL_NAMES,
    MAX_SUBAGENT_TASKS_PER_BATCH,
    MAX_SUBAGENT_WORKERS,
    SubagentSpec,
    SubagentRunner,
    compose_subagent_task,
    format_worker_request_error,
    subagent_has_write_tools,
)
from .team import (
    ACTIVE_TEAMMATE_STATUSES,
    MAX_TEAMMATE_REPORTS_PER_TASK,
    TEAMMATE_REPORT_KINDS,
    TEAMMATE_REPORT_TOOL_NAME,
    WRITE_TOOL_NAMES,
    TeamStore,
    TeamRunner,
    compose_teammate_task,
    path_matches_write_scope,
    teammate_has_write_tools,
    teammate_report_tool_definition,
)


AGENT_CONTEXT_WARN_CHARS = 180000
COMPACTION_MAX_TOKENS = 2048
COMPACTION_TAIL_TURNS = 2
COMPACTION_RECENT_TOKEN_MIN = 2000
COMPACTION_RECENT_TOKEN_MAX = 8000
COMPACTION_TOOL_PROTECT_TOKENS = 40000
COMPACTION_TOOL_PRUNE_MIN_TOKENS = 20000
COMPACTION_TOOL_RESULT_PLACEHOLDER = (
    "[Old tool result pruned to reduce context usage. Re-run the tool if details are needed.]"
)
MEMORY_UPDATE_MAX_TOKENS = 4096
COMPACTION_SUMMARY_PREFIX = "[Compressed conversation summary for continuity]"
USER_PROMPT_FILE = APP_HOME / "prompt.md"
USER_PROMPT_MAX_CHARS = 20000
_EXPLORED_TOOLS = frozenset({
    "read_file",
    "read_program_docs",
    "list_skills",
    "read_skill",
    "grep",
    "glob",
    "list_dir",
})
USER_PROMPT_TEMPLATE = """<!--
在这里写你的自定义提示词、人格、回复风格和偏好。
默认模板内容不会发送给模型；请把真实提示词写在注释外。

示例：
- 默认使用中文回答。
- 回答尽量简洁，优先给出可执行结论。
- 修改代码时保持项目现有风格，避免无关重构。
-->
"""
USER_PROMPT_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
NORMAL_SYSTEM_PROMPT = (
    "You are the built-in assistant for the OmniAgent project, a terminal LLM "
    "agent workbench. Help the user discuss, understand, configure, and improve "
    "this project."
)


AGENT_PROJECT_PROMPT = """You are the built-in local file-editing agent for the OmniAgent project, a terminal LLM agent workbench. Help the user inspect and modify this project safely."""


AGENT_SYSTEM_PROMPT = f"""{AGENT_PROJECT_PROMPT}

Rules:
- Work only inside the configured workspace and use tools for local file facts.
- Explore before editing: list directories, search, and read relevant line ranges first.
- Prefer small, targeted changes. Do not rewrite unrelated code.
- Use read_file with offset/limit pagination when a file is long. Follow the returned next offset instead of requesting the whole file.
- When a tool reports `preview limited` and returns an `artifact://tool_...` URI, the complete output is preserved behind that read-only handle. Inspect it with read_file pagination or grep; do not treat the URI as a filesystem path or pass it to shell, git, write, or edit tools.
- Prefer apply_unified_patch for contextual edits, apply_patch for simple line-range edits, and edit_file for exact small replacements.
- Use git_status and git_diff to understand existing and resulting workspace changes.
- After editing, run a lightweight verification command when it is safe and relevant.
- For local HTTP/static checks, use local_http_check when serving static files; never run a dev/static server as a foreground bash command. If custom server logic is unavoidable, use a bounded script that starts the server, checks the URL, and terminates it before exiting.
- Do not claim the task is complete until you have inspected the resulting diff or verification output.
- In the final summary, distinguish files you edited in this run from pre-existing workspace changes.
- If a tool fails, explain the failure and try a different precise approach instead of repeating the same call.
- Stop when the task is complete and summarize what changed."""


AGENT_TODO_RULES = """
Todo rules:
- For multi-step tasks, create and maintain a task todo list with update_todo before acting.
- Call update_todo with the full current todo item list whenever task status changes.
- Keep existing todo item ids in later update_todo calls until they are completed, blocked, or failed; do not drop or replace active items just to revise the todo list.
- Give each todo item a stable id when dependencies matter. Use depends_on to block later work until prerequisites are completed.
- Use priority p0/p1/p2/p3 to reflect urgency. Prefer p0/p1 tasks when budget is tight.
- Todo updates take effect immediately; do not pause for todo approval before continuing the work.
- Keep at most one todo item in_progress. Mark the active step in_progress before working on it.
- Use structured completion_criteria for tasks that need observable proof. Prefer objects like {"type":"test","target":"pytest path","expected":"exit code 0"}.
- Set verified=true with a verification_note only after tool output proves the criteria.
- Use blocked with a clear reason when progress requires user input or an external change.
- Use failed with a clear reason when verification fails or an attempted approach is invalid; do not mark it completed just to finish.
- Keep the todo list high quality: avoid vague items, avoid too many P0 items, include criteria for P0/P1 work, and keep dependencies explicit.
- Mark completed steps completed, and do not give the final answer while any todo item is pending or in_progress.
- Skip update_todo for simple one-step answers or direct questions that do not need a todo list."""


COMPACTION_SYSTEM_PROMPT = """你负责压缩聊天上下文。
只返回连续性摘要。保留目标、偏好、约束、决定、项目事实、错误、验证、待办和仍有用的旧摘要。
遵循持久记忆，尤其语言偏好。不要编造。简洁。"""


MEMORY_UPDATE_SYSTEM_PROMPT = """你负责更新持久记忆。
只返回 JSON。遵循持久记忆和偏好记忆，尤其语言偏好。事实准确；情景记忆可以有人情味，但不能编造。"""

SESSION_TITLE_SYSTEM_PROMPT = """你负责为新对话生成一个简短标题。
只返回标题文本，不要引号、句号、前缀、编号或解释。
标题要概括用户这句话的核心任务，尽量短，适合显示在侧边栏。"""
SESSION_TITLE_MAX_TOKENS = 64


def _ensure_user_prompt_file():
    prompt_path = Path(USER_PROMPT_FILE)
    if prompt_path.exists():
        return

    try:
        prompt_path.write_text(USER_PROMPT_TEMPLATE, encoding="utf-8")
    except OSError as error:
        print_warn(f"Failed to create {USER_PROMPT_FILE}: {error}")


def _read_user_custom_prompt():
    prompt_path = Path(USER_PROMPT_FILE)
    if not prompt_path.is_file():
        return ""

    try:
        content = prompt_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        print_warn(f"Failed to read {USER_PROMPT_FILE}: {error}")
        return ""

    content = USER_PROMPT_COMMENT_PATTERN.sub("", content).strip()
    if not content:
        return ""
    if len(content) <= USER_PROMPT_MAX_CHARS:
        return content
    return (
        content[:USER_PROMPT_MAX_CHARS]
        + f"\n\n[{USER_PROMPT_FILE} truncated after {USER_PROMPT_MAX_CHARS} characters]"
    )


def _with_user_custom_prompt(base_prompt):
    custom_prompt = _read_user_custom_prompt()
    if not custom_prompt:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        f"User custom instructions from {USER_PROMPT_FILE}:\n"
        f"{custom_prompt}"
    )


def _with_persistent_memory(base_prompt, memory_store):
    if memory_store is None:
        return base_prompt
    try:
        memory_block = memory_store.system_prompt_block()
    except Exception as error:
        print_warn(f"Failed to read persistent memory: {error}")
        return base_prompt
    if not memory_block:
        return base_prompt
    return f"{base_prompt}\n\n{memory_block}"


def _format_stream_error_message(error):
    text = str(error or "").strip()
    if not text:
        return "流式请求失败。"
    if "validation errors for ChatRequest" in text and "think." in text:
        return "流式请求失败：当前 Ollama thinking 强度仅支持 low / medium / high。"
    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()), text
    )
    if len(first_line) > 180:
        first_line = first_line[:177].rstrip() + "..."
    return f"流式请求失败：{first_line}"


class OmniAgent:
    def __init__(
        self,
        model,
        api_key,
        api_type=API_TYPE_GLM,
        base_url="",
        max_tokens=4096,
        context_window_tokens=DEFAULT_CONTEXT_WINDOW_TOKENS,
        temperature=0.7,
        stream_mode=False,
        thinking_mode=False,
        reasoning_effort="",
        extra_modalities=(),
        agent_mode=False,
        workspace_dir=None,
        max_agent_rounds=DEFAULT_MAX_AGENT_ROUNDS,
        max_agent_tool_calls=DEFAULT_MAX_AGENT_TOOL_CALLS,
        agent_approval_mode="confirm",
        skills_enabled=True,
        skills_source_app=True,
        skills_source_workspace=False,
        skills_auto_catalog=True,
        compaction_enable=True,
        compaction_compact_model=AUTO_MODEL_SELECTION,
        memory_model=AUTO_MODEL_SELECTION,
        web_search_enabled=True,
        web_search_provider="tavily",
        web_search_api_key="",
        web_search_max_results=5,
        web_search_depth="basic",
        web_search_topic="general",
        agent_plan_enabled=True,
        agent_team_enable=False,
        current_model_name="",
        history_path=None,
        usage_history_callback=None,
        plan_mode_changed_callback=None,
        todo_dir=None,
    ):
        _ensure_user_prompt_file()
        self.memory_store = MemoryStore(history_path=history_path)
        self.memory_lock = threading.Lock()
        self.session_memory_lock = threading.Lock()
        self.usage_history_lock = threading.Lock()
        self.usage_history_callback = usage_history_callback
        self.plan_mode_changed_callback = plan_mode_changed_callback
        self._agent_tools_execution_lock = threading.RLock()
        self._team_tasks_lock = threading.RLock()
        self._team_tasks = {}
        self._shutdown_lock = threading.Lock()
        self._shutdown = False
        self.session_episodic_heading = ""
        self.session_memory_generation = 0
        self.conversation_history = []
        self.client = None
        self.thinking_mode = thinking_mode
        self.reasoning_effort = normalize_reasoning_effort_for_api(
            api_type, reasoning_effort
        )
        self.extra_modalities = normalize_extra_modalities(extra_modalities)
        self.last_context_input_tokens = 0
        self.last_context_output_tokens = 0
        self.last_context_reasoning_tokens = 0
        self.last_context_cache_read_tokens = 0
        self.last_context_cache_write_tokens = 0
        self.last_context_total_tokens = 0
        self.last_context_usage_source = ""
        self.last_compaction_usage = {}
        self.request_usage_history = []
        self.current_model_name = str(current_model_name or "").strip()
        self.set_context_window_tokens(context_window_tokens)
        self.set_compaction_config(
            compaction_enable,
            compaction_compact_model,
        )
        self.set_memory_model(memory_model)
        self.agent_tools = AgentTools(
            workspace_dir,
            todo_dir=todo_dir,
            approval_mode=agent_approval_mode,
            visible_output_callback=self._before_agent_visible_output,
            web_search_enabled=web_search_enabled,
            web_search_provider=web_search_provider,
            web_search_api_key=web_search_api_key,
            web_search_max_results=web_search_max_results,
            web_search_depth=web_search_depth,
            web_search_topic=web_search_topic,
            todo_update_callback=set_todo_panel,
            todos_enabled=True,
            skills_enabled=skills_enabled,
            skills_app_enabled=skills_source_app,
            skills_workspace_enabled=skills_source_workspace,
            skills_auto_catalog=skills_auto_catalog,
            stop_requested_callback=lambda: self.agent_stop_requested,
            plan_mode=agent_plan_enabled,
        )
        self.agent_mode = bool(agent_mode and self.agent_tools.enabled)
        self.max_agent_rounds = max(1, int(max_agent_rounds))
        self.max_agent_tool_calls = max(1, int(max_agent_tool_calls))
        self.agent_running = False
        self.agent_stop_requested = False
        self.agent_tool_calls = 0
        self.agent_tool_call_limit = self.max_agent_tool_calls
        self.agent_round_index = 0
        self.agent_round_limit = self.max_agent_rounds
        self.agent_plan_rejected = False
        self.agent_final_check_done = False
        self.agent_plan_check_signature = None
        self.agent_plan_check_exit_note = ""
        self.agent_context_warning_sent = False
        self.agent_thinking_streamed = False
        self.agent_thinking_needs_separator = False
        self.agent_response_streamed = False
        self.agent_response_started = False
        self.agent_output_needs_separator = False
        self._last_tool_display = None
        self._subagent_dispatch_display = None
        self.resume_existing_plan = False
        self.configure(
            api_type,
            base_url,
            model,
            api_key,
            max_tokens,
            temperature,
            stream_mode,
            thinking_mode=None,
            reasoning_effort=None,
            extra_modalities=None,
        )
        self.agent_tools.set_subagent_executor(self._dispatch_subagent)
        self.agent_team_enabled = bool(agent_team_enable) and (
            workspace_dir is not None
        )
        if self.agent_team_enabled:
            self.team_store = TeamStore(workspace_dir=workspace_dir)
            self.team_store.reconcile_stale_tasks()
            self.agent_tools.set_team_config(
                team_store=self.team_store,
                team_enabled=True,
            )
            self.agent_tools.set_team_executor(self._execute_teammate)
            self.agent_tools.set_team_shutdown_executor(self._shutdown_teammate_task)
        else:
            self.team_store = None
            self.agent_tools.set_team_config(team_enabled=False)

    def configure(
        self,
        api_type,
        base_url,
        model,
        api_key,
        max_tokens=None,
        temperature=None,
        stream_mode=None,
        thinking_mode=None,
        reasoning_effort=None,
        extra_modalities=None,
    ):
        api_type = normalize_api_type(api_type)
        if api_type not in SUPPORTED_API_TYPES:
            raise ValueError(f"Unsupported API type: {api_type}")

        if api_type == API_TYPE_GLM:
            base_url = ""
        elif api_type == API_TYPE_GEMINI:
            base_url = (base_url or "").strip() or GEMINI_OPENAI_BASE_URL
        else:
            base_url = (base_url or "").strip()
        client = self._create_client(api_type, api_key, base_url)
        previous_client = self.client

        self.api_type = api_type
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.client = client
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if temperature is not None:
            self.temperature = temperature
        if stream_mode is not None:
            self.stream_mode = stream_mode
        if thinking_mode is not None:
            self.thinking_mode = thinking_mode
        if reasoning_effort is not None:
            self.set_reasoning_effort(reasoning_effort)
        if extra_modalities is not None:
            self.set_extra_modalities(extra_modalities)
        if previous_client is not None and previous_client is not client:
            self._close_client(previous_client)

    @staticmethod
    def _close_client(client):
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as error:
            print_warn(f"Failed to close model client: {error}")

    def shutdown(self, timeout=5.0):
        """Stop background work and release provider resources."""
        with self._shutdown_lock:
            self._shutdown = True

        self.request_agent_stop()
        deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
        with self._team_tasks_lock:
            records = list(self._team_tasks.values())
            for record in records:
                stop_event = record.get("stop_event")
                if stop_event is not None:
                    stop_event.set()
                if record.get("status") in ACTIVE_TEAMMATE_STATUSES:
                    record["status"] = "cancelling"

        current_thread = threading.current_thread()
        for record in records:
            worker = record.get("thread")
            if worker is None or worker is current_thread or not worker.is_alive():
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            worker.join(remaining)

        client = self.client
        self.client = None
        if client is not None:
            self._close_client(client)
        return not any(
            record.get("thread") is not None and record["thread"].is_alive()
            for record in records
        )

    def _create_client(self, api_type, api_key, base_url):
        if api_type == API_TYPE_ANTHROPIC:
            try:
                import anthropic
            except ImportError as error:
                raise RuntimeError(
                    "Anthropic SDK is not installed. Run: pip install anthropic"
                ) from error

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return anthropic.Anthropic(**kwargs)

        if api_type in {API_TYPE_OPENAI, API_TYPE_GEMINI}:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError(
                    "OpenAI SDK is not installed. Run: pip install openai"
                ) from error

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return OpenAI(**kwargs)

        if api_type == API_TYPE_OLLAMA:
            try:
                from ollama import Client
            except ImportError as error:
                raise RuntimeError(
                    "Ollama SDK is not installed. Run: pip install ollama"
                ) from error

            kwargs = {}
            if base_url:
                kwargs["host"] = base_url
            if api_key:
                kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
            return Client(**kwargs)

        try:
            from zai import ZhipuAiClient
        except ImportError as error:
            raise RuntimeError(
                "ZhipuAI SDK is not installed. Run: pip install zai-sdk"
            ) from error

        return ZhipuAiClient(api_key=api_key)

    def set_max_tokens(self, max_tokens):
        self.max_tokens = max_tokens

    def set_context_window_tokens(self, context_window_tokens):
        self.context_window_tokens = max(1, int(context_window_tokens))
        set_context_usage(self.last_context_input_tokens, self.context_window_tokens)

    def set_temperature(self, temperature):
        self.temperature = temperature

    def set_stream_mode(self, enabled):
        self.stream_mode = enabled

    def set_thinking_mode(self, enabled):
        self.thinking_mode = enabled

    def set_reasoning_effort(self, effort):
        self.reasoning_effort = normalize_reasoning_effort_for_api(
            self.api_type, effort
        )

    def set_extra_modalities(self, extra_modalities):
        self.extra_modalities = normalize_extra_modalities(extra_modalities)

    def set_agent_limits(self, max_rounds=None, max_tool_calls=None):
        if max_rounds is not None:
            self.max_agent_rounds = max(1, int(max_rounds))
        if max_tool_calls is not None:
            self.max_agent_tool_calls = max(1, int(max_tool_calls))

    def set_agent_approval_mode(self, approval_mode):
        self.agent_tools.set_approval_mode(approval_mode)

    def set_plan_mode(self, enabled, *, notify=False):
        enabled = bool(enabled)
        changed = self.agent_tools.plan_mode != enabled
        self.agent_tools.set_plan_mode(enabled)
        self.agent_final_check_done = False
        if changed and notify and self.plan_mode_changed_callback is not None:
            self.plan_mode_changed_callback(enabled)

    def set_agent_skills(self, enabled):
        self.agent_tools.set_skills_enabled(enabled)

    def set_skills_config(
        self,
        enabled=None,
        app_enabled=None,
        workspace_enabled=None,
        auto_catalog=None,
    ):
        self.agent_tools.set_skills_config(
            enabled=enabled,
            app_enabled=app_enabled,
            workspace_enabled=workspace_enabled,
            auto_catalog=auto_catalog,
        )

    def set_web_search_config(
        self,
        enabled=None,
        provider=None,
        api_key=None,
        max_results=None,
        search_depth=None,
        topic=None,
    ):
        self.agent_tools.set_web_search_config(
            enabled,
            provider,
            api_key,
            max_results,
            search_depth,
            topic,
        )

    def get_web_search_status(self):
        return self.agent_tools.web_search_status()

    def web_search(self, query, **kwargs):
        return self.agent_tools.search_web(query, **kwargs)

    def _normal_web_search_available(self):
        return bool(self.agent_tools.web_search_available)

    def _normal_web_search_tool_limit(self):
        return max(1, int(self.max_agent_tool_calls))

    def _normal_tools_available(self):
        return True

    def set_compaction_config(
        self,
        enabled=None,
        compact_model=None,
    ):
        if enabled is not None:
            self.compaction_enable = bool(enabled)
        if compact_model is not None:
            self.compaction_compact_model = normalize_optional_model_selection(
                compact_model
            )

    def set_memory_model(self, model):
        self.memory_model = normalize_optional_model_selection(model)

    def _memory_model_name(self):
        if self.memory_model == AUTO_MODEL_SELECTION:
            return self.model
        return self.memory_model

    def get_memory_model_status(self):
        return {
            "configured_model": self.memory_model,
            "effective_model": self._memory_model_name(),
        }

    def set_workspace_dir(self, workspace_dir):
        self.agent_tools.set_workspace_dir(workspace_dir)
        if not self.agent_tools.enabled:
            self.agent_mode = False

    def set_agent_mode(self, enabled):
        self.agent_mode = bool(enabled and self.agent_tools.enabled)
        if not self.agent_mode:
            self.request_agent_stop()
        return self.agent_mode

    def request_agent_stop(self):
        was_running = self.agent_running
        self.agent_stop_requested = True
        return was_running

    def get_agent_status(self):
        return {
            "enabled": self.agent_mode,
            "workspace_dir": str(self.agent_tools.workspace_dir)
            if self.agent_tools.enabled
            else None,
            "running": self.agent_running,
            "max_rounds": self.max_agent_rounds,
            "max_tool_calls": self.max_agent_tool_calls,
            "approval_mode": self.agent_tools.approval_mode,
            "plan_enabled": self.agent_tools.plan_mode,
            "plan_mode": self.agent_tools.plan_mode,
            "skills": self.agent_tools.skills_status(),
            "plan": self.agent_tools.todo_status(),
            "team_enabled": self.agent_team_enabled,
        }

    def set_team_mode(self, enabled):
        next_enabled = bool(enabled and self.agent_tools.enabled)
        if self.agent_team_enabled and not next_enabled and self.team_store is not None:
            active_names = {
                str(record.get("display_name") or record.get("teammate_name") or "")
                for record in self._team_tasks.values()
                if record.get("status") in {"starting", "running", "cancelling"}
            }
            for name in active_names:
                if name:
                    self._shutdown_teammate_task(name)
        self.agent_team_enabled = next_enabled
        if self.team_store is None and self.agent_tools.workspace_dir is not None:
            self.team_store = TeamStore(workspace_dir=self.agent_tools.workspace_dir)
            self.team_store.reconcile_stale_tasks()
            self.agent_tools.set_team_executor(self._execute_teammate)
            self.agent_tools.set_team_shutdown_executor(self._shutdown_teammate_task)
        if self.team_store is not None:
            self.team_store.reload_specs()
            self.agent_tools.set_team_config(
                team_store=self.team_store,
                team_enabled=self.agent_team_enabled,
            )
        return self.agent_team_enabled

    def get_team_status(self):
        roster = self.team_store.get_roster() if self.team_store else []
        available_types = self.team_store.names() if self.team_store else []
        return {
            "enabled": self.agent_team_enabled,
            "active_count": len(roster),
            "teammates": roster,
            "available_types": available_types,
        }

    def get_todo_status(self):
        return self.agent_tools.todo_status()

    def clear_todos(self):
        self.agent_tools.clear_todos()
        self.resume_existing_plan = False

    def retry_todo(self, todo_id, reason=""):
        changed = self.agent_tools.retry_todo(todo_id, reason)
        if changed:
            self.agent_final_check_done = False
            self.resume_existing_plan = True
        return changed

    def unblock_todo(self, todo_id, reason=""):
        changed = self.agent_tools.unblock_todo(todo_id, reason)
        if changed:
            self.agent_final_check_done = False
            self.resume_existing_plan = True
        return changed

    def get_todo_quality_report(self):
        return self.agent_tools.todo_quality_report()

    def get_todo_history(self, limit=20):
        return self.agent_tools.todo_history(limit)

    def send_message(
        self,
        user_message,
        stream_callback_thinking=None,
        stream_callback_response=None,
        media_references=None,
        reference_files=None,
        reference_folders=None,
    ):
        self.agent_tools.set_reference_files(reference_files)
        self.agent_tools.set_reference_folders(reference_folders)
        user_content = self._user_message_content(user_message, media_references)
        self.conversation_history.append({"role": "user", "content": user_content})
        self._record_preference_signal(user_message)
        original_history = self._history_snapshot()
        self.agent_stop_requested = False
        self._message_overflow_replayed = False
        if self.agent_mode and not self.agent_tools.enabled:
            self.agent_mode = False
        managed_round_replay = self.agent_mode or self._normal_tools_available()
        whole_turn_replay = not managed_round_replay

        try:
            response = None
            user_message_index = len(self.conversation_history) - 1
            attempts = 2 if whole_turn_replay else 1
            for attempt in range(attempts):
                self._auto_compact_context()
                self._sanitize_orphan_tool_results_in_history()
                user_message_index = len(self.conversation_history) - 1
                request_history = self._history_snapshot()
                if whole_turn_replay:
                    begin_overflow_replay_scope()

                try:
                    response = self._request_current_turn(
                        stream_callback_thinking,
                        stream_callback_response,
                    )
                except Exception as error:
                    self._restore_history(request_history)
                    if whole_turn_replay:
                        rollback_overflow_replay_scope()
                    if (
                        whole_turn_replay
                        and attempt == 0
                        and _is_context_overflow_error(error)
                    ):
                        recovery = self._recover_context_overflow()
                        if recovery.get("recovered"):
                            self._message_overflow_replayed = True
                            print_info(
                                "Context overflow detected. Compacted context and "
                                "replaying the current turn."
                            )
                            continue
                    raise
                else:
                    if whole_turn_replay:
                        if response is None:
                            rollback_overflow_replay_scope()
                        else:
                            commit_overflow_replay_scope()
                    break

            if response and self._message_overflow_replayed:
                response["overflow_replayed"] = True
            if response and not response.get("agent_stopped"):
                self._record_hot_history(user_message_index)
            if response is None:
                if whole_turn_replay:
                    self._restore_history(original_history)
            elif response.get("agent_stopped"):
                self._restore_history(original_history)
            elif self.agent_mode:
                self._compact_agent_history(user_message_index, response)
            if response and not response.get("agent_stopped"):
                self._auto_compact_context()
            return response

        except KeyboardInterrupt:
            if self.agent_running:
                self.request_agent_stop()
                self._restore_history(original_history)
                self._separate_after_agent_thinking()
                self._print_agent_stopped_by_user()
                return {
                    "thinking": "",
                    "response": "Agent stopped by user.",
                    "agent_stopped": True,
                }
            raise
        except Exception as error:
            if whole_turn_replay:
                self._restore_history(original_history)
            if self.agent_running:
                self._separate_after_agent_thinking()
            print_error(f"Request error: {error}")
            return None
        finally:
            self.agent_tools.clear_reference_files()
            self.agent_tools.clear_reference_folders()

    def _request_current_turn(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        if self.agent_mode and not self.agent_tools.enabled:
            self.agent_mode = False

        if self.agent_mode:
            return self._agent_response()
        if self._normal_tools_available():
            return self._normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )
        if self.stream_mode:
            return self._stream_response(
                stream_callback_thinking,
                stream_callback_response,
                self.model,
            )
        if self.api_type == API_TYPE_ANTHROPIC:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self._normal_system_prompt(),
                messages=self._anthropic_messages(),
                **self._anthropic_request_options(),
            )
            return self._parse_anthropic_response(response)
        if self.api_type == API_TYPE_OLLAMA:
            response = self.client.chat(
                **self._ollama_chat_kwargs(messages=self.conversation_history)
            )
            return self._parse_ollama_response(response)

        response = self.client.chat.completions.create(
            **self._chat_completion_kwargs(messages=self.conversation_history)
        )
        return self._parse_response(response)

    def _run_model_turn_with_overflow_recovery(self, turn_callable):
        for attempt in range(2):
            round_history = self._history_snapshot()
            begin_overflow_replay_scope()
            try:
                result = turn_callable()
            except Exception as error:
                self._restore_history(round_history)
                rollback_overflow_replay_scope()
                if attempt == 0 and _is_context_overflow_error(error):
                    recovery = self._recover_context_overflow()
                    if recovery.get("recovered"):
                        self._message_overflow_replayed = True
                        print_info(
                            "Context overflow detected. Compacted context and "
                            "replaying the current model round."
                        )
                        continue
                raise
            commit_overflow_replay_scope()
            return result
        raise RuntimeError("Model round replay exhausted.")

    def _recover_context_overflow(self):
        input_budget_tokens = self._compaction_input_budget()
        before_tokens = self._estimate_current_context_tokens()
        prune_result = self._soft_prune_old_tool_results(input_budget_tokens)
        compact_result = self.compact_context(manual=False)

        after_tokens = self._estimate_current_context_tokens()
        recovered = bool(
            prune_result.get("pruned_tool_results")
            or compact_result.get("compacted")
        ) and after_tokens < before_tokens
        return {
            "recovered": recovered,
            "before_input_tokens": before_tokens,
            "after_input_tokens": after_tokens,
            **prune_result,
            "compaction": compact_result,
        }

    def _agent_response(self):
        self.agent_running = True
        self.agent_stop_requested = False
        self.agent_tool_calls = 0
        self.agent_tool_call_limit = self.max_agent_tool_calls
        self.agent_round_index = 0
        self.agent_round_limit = self.max_agent_rounds
        self.agent_plan_rejected = False
        self.agent_final_check_done = False
        self.agent_plan_check_signature = None
        self.agent_plan_check_exit_note = ""
        self.agent_context_warning_sent = False
        self.agent_thinking_streamed = False
        self.agent_thinking_needs_separator = False
        self.agent_response_streamed = False
        self.agent_response_started = False
        self.agent_output_needs_separator = False
        resume_existing_plan = (
            self.resume_existing_plan or self.agent_tools.has_incomplete_todos()
        )
        self.agent_tools.begin_agent_session(clear_todos=not resume_existing_plan)
        self.resume_existing_plan = False
        self.agent_tools.set_budget_context(
            self.agent_tool_call_limit,
            self.agent_tool_calls,
        )
        try:
            if self.api_type == API_TYPE_ANTHROPIC:
                return self._finalize_agent_response(self._anthropic_agent_response())
            if self.api_type == API_TYPE_OLLAMA:
                return self._finalize_agent_response(self._ollama_agent_response())
            return self._finalize_agent_response(self._chat_completion_agent_response())
        except KeyboardInterrupt:
            self.agent_stop_requested = True
            self._print_agent_stopped_by_user()
            return self._finalize_agent_response({
                "thinking": "",
                "response": "Agent stopped by user.",
                "agent_stopped": True,
            })
        finally:
            self.agent_running = False

    def _finalize_agent_response(self, response):
        if response and self.agent_thinking_streamed:
            response = dict(response)
            response["thinking"] = ""
            response["thinking_streamed"] = True
            response["response_streamed"] = self.agent_response_streamed
            response["thinking_needs_separator"] = (
                self.agent_thinking_needs_separator
                and not response.get("agent_stopped")
            )
        elif response:
            response = dict(response)
            response["response_streamed"] = self.agent_response_streamed
        return response

    def _anthropic_agent_response(self):
        full_thinking = ""
        final_response = ""

        for round_index in range(1, (self.max_agent_rounds * 2) + 1):
            if round_index > self.agent_round_limit:
                break
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)
            self._prepare_agent_model_round(round_index)
            blocks, response_streamed = self._run_model_turn_with_overflow_recovery(
                self._stream_anthropic_agent_turn
            )
            self.conversation_history.append({"role": "assistant", "content": blocks})

            thinking, text, tool_uses = self._parse_anthropic_blocks(blocks)
            full_thinking += thinking
            final_response += text
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)

            if not tool_uses:
                if self._append_agent_final_check_if_needed():
                    final_response = ""
                    continue
                final_response = self._agent_response_with_plan_exit_note(
                    final_response
                )
                if response_streamed:
                    plan_note = self.agent_plan_check_exit_note
                    if plan_note:
                        print_stream_response_continue(f"\n\n{plan_note}")
                else:
                    self._stream_agent_response_text(final_response, pseudo=True)
                return {"thinking": full_thinking, "response": final_response}

            if self._agent_tool_budget_exceeded(tool_uses):
                message = self._agent_tool_budget_message()
                tool_results = []
                for tool_use in tool_uses:
                    error_result = _error_text(message)
                    display = self._tool_display_for_result(
                        tool_use.get("name", ""),
                        tool_use.get("input", {}),
                        error_result,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.get("id", ""),
                        "tool_name": tool_use.get("name", ""),
                        "content": error_result,
                        "is_error": True,
                        "display": display,
                    })
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results,
                })
                self._separate_after_agent_thinking()
                print_error(message)
                return {
                    "thinking": full_thinking,
                    "response": final_response or message,
                }

            tool_results = []
            for tool_use in tool_uses:
                if self._agent_should_stop():
                    return self._agent_stopped_response(full_thinking, final_response)
                tool_result = self._execute_agent_tool(
                    tool_use.get("name", ""),
                    tool_use.get("input", {}),
                )
                display = self._consume_last_tool_display()
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.get("id", ""),
                    "tool_name": tool_use.get("name", ""),
                    "content": tool_result,
                    "is_error": tool_result_is_error(
                        tool_use.get("name", ""), tool_result, display
                    ),
                    "display": display,
                })
            self.conversation_history.append({"role": "user", "content": tool_results})
            finish_thinking_round()

        message = f"Agent loop stopped after {self.agent_round_limit} tool rounds."
        self._separate_after_agent_thinking()
        print_error(message)
        return {"thinking": full_thinking, "response": final_response or message}

    def _stream_chat_completion_agent_turn(self):
        kwargs = self._chat_completion_kwargs(
            messages=self._chat_agent_messages(),
            tools=self._chat_tool_schemas(),
            stream=True,
        )
        kwargs["stream_options"] = {"include_usage": True}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            if not _stream_usage_unsupported(error):
                raise
            kwargs.pop("stream_options", None)
            response = self.client.chat.completions.create(**kwargs)

        field_thinking = ""
        tagged_thinking = ""
        raw_thinking = ""
        full_response = ""
        raw_response = ""
        tool_call_parts = {}
        usage_snapshot = None
        response_streamed = False

        for chunk in response:
            if self._agent_should_stop():
                break
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
            if not getattr(chunk, "choices", None):
                continue

            delta = chunk.choices[0].delta
            reasoning, field_thinking_candidate, raw_thinking = (
                self._stream_reasoning_delta(
                    delta,
                    field_thinking,
                    raw_thinking,
                )
            )
            if reasoning:
                field_thinking = field_thinking_candidate
                self._stream_agent_thinking(reasoning)

            content, full_response, raw_response = self._stream_content_delta(
                self._get_field(delta, "content", "") or "",
                full_response,
                raw_response,
            )
            tagged_reasoning, tagged_thinking = self._stream_tagged_reasoning_delta(
                raw_response,
                tagged_thinking,
            )
            if tagged_reasoning and not response_streamed and self.thinking_mode:
                self._stream_agent_thinking(tagged_reasoning)
            if content:
                if not response_streamed:
                    self._separate_after_agent_thinking()
                    self.agent_output_needs_separator = False
                    print_stream_response_start(self.model)
                    self.agent_response_started = True
                    response_streamed = True
                    self.agent_response_streamed = True
                print_stream_response_continue(content)

            self._update_chat_stream_tool_call_parts(
                tool_call_parts,
                self._get_field(delta, "tool_calls", None) or [],
            )

        self._record_context_usage_snapshot(usage_snapshot)

        full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
        assistant_message = self._chat_stream_assistant_message(
            full_response,
            full_thinking,
        )
        assistant_tool_calls, tool_calls = self._chat_stream_tool_calls(tool_call_parts)
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls

        return (
            assistant_message,
            full_thinking,
            full_response,
            tool_calls,
            response_streamed,
        )

    @staticmethod
    def _combine_stream_reasoning_text(field_thinking, tagged_thinking):
        return _combine_reasoning_text(field_thinking, tagged_thinking)

    @staticmethod
    def _clean_stream_reasoning_text(thinking):
        return _clean_reasoning_text(thinking)

    def _chat_completion_agent_response(self):
        full_thinking = ""
        final_response = ""

        for round_index in range(1, (self.max_agent_rounds * 2) + 1):
            if round_index > self.agent_round_limit:
                break
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)
            self._prepare_agent_model_round(round_index)
            (
                assistant_message,
                thinking_content,
                text,
                tool_calls,
                response_streamed,
            ) = self._run_model_turn_with_overflow_recovery(
                self._stream_chat_completion_agent_turn
            )
            self.conversation_history.append(assistant_message)
            full_thinking += thinking_content
            final_response += text
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)

            if not tool_calls:
                if self._append_agent_final_check_if_needed():
                    final_response = ""
                    continue
                final_response = self._agent_response_with_plan_exit_note(
                    final_response
                )
                if response_streamed:
                    plan_note = self.agent_plan_check_exit_note
                    if plan_note:
                        print_stream_response_continue(f"\n\n{plan_note}")
                else:
                    self._stream_agent_response_text(final_response, pseudo=True)
                return {"thinking": full_thinking, "response": final_response}

            if self._agent_tool_budget_exceeded(tool_calls):
                message = self._agent_tool_budget_message()
                for tool_call in tool_calls:
                    error_result = _error_text(message)
                    display = self._tool_display_for_result(
                        tool_call["name"],
                        tool_call.get("arguments", {}),
                        error_result,
                    )
                    self.conversation_history.append(
                        self._chat_tool_result_message(
                            tool_call["id"],
                            tool_call["name"],
                            error_result,
                            display=display,
                        )
                    )
                self._separate_after_agent_thinking()
                print_error(message)
                return {
                    "thinking": full_thinking,
                    "response": final_response or message,
                }

            for tool_call in tool_calls:
                if self._agent_should_stop():
                    return self._agent_stopped_response(full_thinking, final_response)
                tool_result = self._execute_agent_tool(
                    tool_call["name"], tool_call["arguments"]
                )
                self.conversation_history.append(
                    self._chat_tool_result_message(
                        tool_call["id"],
                        tool_call["name"],
                        tool_result,
                        display=self._consume_last_tool_display(),
                    )
                )
            finish_thinking_round()

        message = f"Agent loop stopped after {self.agent_round_limit} tool rounds."
        self._separate_after_agent_thinking()
        print_error(message)
        return {"thinking": full_thinking, "response": final_response or message}

    def _normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        if self.api_type == API_TYPE_ANTHROPIC:
            return self._anthropic_normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )
        if self.api_type == API_TYPE_OLLAMA:
            return self._ollama_normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )
        return self._chat_completion_normal_web_search_response(
            stream_callback_thinking,
            stream_callback_response,
        )

    def _chat_completion_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        if self.stream_mode:
            return self._stream_chat_completion_normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )

        return self._run_complete_normal_tool_loop(
            self._chat_completion_normal_turn,
            lambda calls: self._append_normal_web_search_tool_results(
                calls, provider="chat"
            ),
            stream_callback_thinking,
            stream_callback_response,
        )

    def _run_complete_normal_tool_loop(
        self,
        run_turn,
        execute_tools,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        coordinator = NormalToolCoordinator(
            max_rounds=self._normal_web_search_tool_limit(),
            run_turn=run_turn,
            append_assistant=self.conversation_history.append,
            execute_tools=execute_tools,
            render_turn=lambda thinking, response: self._render_normal_complete_round(
                thinking,
                response,
                stream_callback_thinking,
                stream_callback_response,
            ),
        )
        result = coordinator.run()
        finalize = (
            self._normal_web_search_round_limit_response
            if result.limit_reached
            else self._finalize_normal_web_search_response
        )
        return finalize(
            result.thinking,
            result.response,
            stream_callback_thinking,
            stream_callback_response,
            thinking_streamed=result.thinking_rendered,
            response_streamed=result.response_rendered,
        )

    def _chat_completion_normal_turn(self):
        response = self._run_model_turn_with_overflow_recovery(
            lambda: self.client.chat.completions.create(
                **self._chat_completion_kwargs(
                    messages=self.conversation_history,
                    tools=self._normal_web_search_tool_schemas(),
                )
            )
        )
        self._record_context_usage(response)
        message = response.choices[0].message
        assistant_message, thinking, text, tool_calls = self._chat_message_parts(message)
        return NormalTurn(assistant_message, thinking, text, tool_calls)

    def _ollama_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        if self.stream_mode:
            return self._stream_ollama_normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )

        return self._run_complete_normal_tool_loop(
            self._ollama_normal_turn,
            lambda calls: self._append_normal_web_search_tool_results(
                calls, provider="ollama"
            ),
            stream_callback_thinking,
            stream_callback_response,
        )

    def _ollama_normal_turn(self):
        response = self._run_model_turn_with_overflow_recovery(
            lambda: self.client.chat(
                **self._ollama_chat_kwargs(
                    messages=self.conversation_history,
                    tools=self._normal_web_search_tool_schemas(),
                )
            )
        )
        self._record_context_usage(response)
        message = self._get_field(response, "message", {})
        assistant_message, thinking, text, tool_calls = self._ollama_message_parts(message)
        return NormalTurn(assistant_message, thinking, text, tool_calls)

    def _execute_anthropic_normal_tool_uses(self, tool_uses):
        tool_results = []
        for tool_use in tool_uses:
            tool_result, display = self._execute_normal_web_search_tool_with_display(
                tool_use.get("name", ""),
                tool_use.get("input", {}),
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.get("id", ""),
                "tool_name": tool_use.get("name", ""),
                "content": tool_result,
                "is_error": tool_result_is_error(
                    tool_use.get("name", ""), tool_result, display
                ),
                "display": display,
            })
        self.conversation_history.append({"role": "user", "content": tool_results})

    def _anthropic_normal_turn(self):
        response = self._run_model_turn_with_overflow_recovery(
            lambda: self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self._normal_system_prompt(),
                messages=self._anthropic_messages(),
                tools=self._normal_web_search_tool_schemas(),
                **self._anthropic_request_options(),
            )
        )
        self._record_context_usage(response)
        blocks = self._anthropic_content_blocks(
            self._get_field(response, "content", [])
        )
        thinking, text, tool_uses = self._parse_anthropic_blocks(blocks)
        return NormalTurn(
            {"role": "assistant", "content": blocks},
            thinking,
            text,
            tool_uses,
        )

    def _anthropic_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        if self.stream_mode:
            return self._stream_anthropic_normal_web_search_response(
                stream_callback_thinking,
                stream_callback_response,
            )
        return self._run_complete_normal_tool_loop(
            self._anthropic_normal_turn,
            self._execute_anthropic_normal_tool_uses,
            stream_callback_thinking,
            stream_callback_response,
        )

    def _append_normal_web_search_tool_results(self, tool_calls, provider):
        for tool_call in tool_calls:
            tool_result, display = (
                self._execute_normal_web_search_tool_with_display(
                    tool_call.get("name", ""),
                    tool_call.get("arguments", {}),
                )
            )
            if provider == "ollama":
                self.conversation_history.append(
                    self._ollama_tool_result_message(
                        tool_call.get("name", ""),
                        tool_result,
                        display=display,
                    )
                )
            else:
                self.conversation_history.append(
                    self._chat_tool_result_message(
                        tool_call.get("id", ""),
                        tool_call.get("name", ""),
                        tool_result,
                        display=display,
                    )
                )

    def _execute_normal_web_search_tool_with_display(self, name, arguments):
        arguments = arguments if isinstance(arguments, dict) else {}
        self.agent_tools.consume_display_payload()
        result = self._execute_normal_web_search_tool(name, arguments)
        tool_display = self.agent_tools.consume_display_payload()
        self.agent_tools.consume_output_separator()
        display = self._tool_display_for_result(
            name,
            arguments,
            result,
            existing_display=tool_display,
        )
        if not tool_result_is_error(name, result, display):
            self._track_explored_tool(name, arguments)
        return result, display

    def _execute_normal_web_search_tool(self, name, arguments):
        arguments = arguments if isinstance(arguments, dict) else {}
        if name in {"read_file", "list_dir", "grep", "glob"}:
            if not str(arguments.get("reference") or "").strip():
                return _error_text(
                    "In normal mode, local file tools require an explicit referenced file or folder label."
                )
            return self.agent_tools.execute(name, arguments)
        if name in {
            "update_todo",
            "ask_user",
            "read_program_docs",
            "web_fetch",
        }:
            return self.agent_tools.execute(name, arguments)
        if name != "web_search":
            return _error_text(f"Tool is not available in normal mode: {name}")
        try:
            return self.agent_tools.execute(name, arguments)
        except Exception as error:
            return _error_text(str(error))

    def _render_normal_complete_round(
        self,
        thinking,
        response,
        callback_thinking=None,
        callback_response=None,
    ):
        thinking_rendered = False
        response_rendered = False
        if thinking and self.thinking_mode and callback_thinking is not None:
            print_stream_thinking("")
            callback_thinking(thinking)
            finish_thinking_round()
            thinking_rendered = True

        display_response = clean_display_text(response)
        if display_response and callback_response is not None:
            print_stream_response_start(self.model)
            callback_response(display_response)
            response_rendered = True
        return thinking_rendered, response_rendered

    @staticmethod
    def _normal_stream_thinking_tracker(callback_thinking):
        state = {"streamed": False}
        if callback_thinking is None:
            return state, None

        def tracked(content):
            if content:
                state["streamed"] = True
            callback_thinking(content)

        return state, tracked

    def _stream_normal_thinking_if_needed(
        self,
        thinking,
        callback_thinking=None,
        thinking_streamed=False,
    ):
        if (
            not thinking
            or not self.thinking_mode
            or thinking_streamed
            or callback_thinking is None
        ):
            return False, bool(thinking_streamed)

        print_stream_thinking("")
        callback_thinking(thinking)
        return True, True

    def _stream_chat_completion_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        try:
            thinking_streamed, tracked_callback_thinking = (
                self._normal_stream_thinking_tracker(stream_callback_thinking)
            )
            full_thinking = ""
            final_response = ""
            response_streamed = False

            for _ in range(self._normal_web_search_tool_limit()):
                (
                    assistant_message,
                    thinking,
                    text,
                    tool_calls,
                    round_response_started,
                ) = self._run_model_turn_with_overflow_recovery(
                    lambda: self._stream_chat_completion_normal_web_search_turn(
                        full_thinking,
                        False,
                        tracked_callback_thinking,
                        stream_callback_response,
                        emit_response=True,
                    )
                )
                full_thinking += thinking
                final_response += text
                response_streamed = response_streamed or round_response_started
                if self._agent_should_stop():
                    return self._agent_stopped_response(full_thinking, final_response)

                if not tool_calls:
                    self.conversation_history.append(assistant_message)
                    return self._stream_normal_tool_first_response(
                        full_thinking,
                        final_response,
                        stream_callback_response,
                        tracked_callback_thinking,
                        thinking_streamed["streamed"],
                        _response_started=response_streamed,
                    )

                self.conversation_history.append(assistant_message)
                if self.thinking_mode:
                    finish_thinking_round()
                self._append_normal_web_search_tool_results(tool_calls, provider="chat")

            return self._stream_normal_web_search_round_limit_response(
                full_thinking,
                final_response,
                response_streamed,
                stream_callback_response,
                tracked_callback_thinking,
                thinking_streamed["streamed"],
            )
        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _stream_chat_completion_normal_web_search_turn(
        self,
        prior_thinking,
        response_started,
        callback_thinking=None,
        callback_response=None,
        emit_response=True,
    ):
        kwargs = self._chat_completion_kwargs(
            messages=self.conversation_history,
            tools=self._normal_web_search_tool_schemas(),
            stream=True,
        )
        kwargs["stream_options"] = {"include_usage": True}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            if not _stream_usage_unsupported(error):
                raise
            kwargs.pop("stream_options", None)
            response = self.client.chat.completions.create(**kwargs)

        field_thinking = ""
        tagged_thinking = ""
        raw_thinking = ""
        full_response = ""
        raw_response = ""
        tool_call_parts = {}
        usage_snapshot = None

        for chunk in response:
            if self._agent_should_stop():
                break
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
            if not getattr(chunk, "choices", None):
                continue

            delta = chunk.choices[0].delta
            reasoning, field_thinking, raw_thinking = self._stream_reasoning_delta(
                delta,
                field_thinking,
                raw_thinking,
            )
            if (
                reasoning
                and not response_started
                and callback_thinking
                and self.thinking_mode
            ):
                callback_thinking(reasoning)

            content, full_response, raw_response = self._stream_content_delta(
                self._get_field(delta, "content", "") or "",
                full_response,
                raw_response,
            )
            tagged_reasoning, tagged_thinking = self._stream_tagged_reasoning_delta(
                raw_response,
                tagged_thinking,
            )
            if (
                tagged_reasoning
                and not response_started
                and callback_thinking
                and self.thinking_mode
            ):
                callback_thinking(tagged_reasoning)
            full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
            if content and emit_response:
                response_started = self._start_normal_stream_response(
                    response_started,
                    prior_thinking + full_thinking,
                )
                if callback_response:
                    callback_response(content)

            self._update_chat_stream_tool_call_parts(
                tool_call_parts,
                self._get_field(delta, "tool_calls", None) or [],
            )

        self._record_context_usage_snapshot(usage_snapshot)

        full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
        assistant_message = self._chat_stream_assistant_message(
            full_response,
            full_thinking,
        )
        assistant_tool_calls, tool_calls = self._chat_stream_tool_calls(tool_call_parts)
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls

        return (
            assistant_message,
            full_thinking,
            full_response,
            tool_calls,
            response_started,
        )

    def _update_chat_stream_tool_call_parts(self, tool_call_parts, tool_call_deltas):
        for fallback_index, call in enumerate(tool_call_deltas or []):
            raw_index = self._get_field(call, "index", fallback_index)
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                index = fallback_index

            part = tool_call_parts.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "name": "",
                    "arguments": "",
                },
            )

            call_id = self._get_field(call, "id", "") or ""
            if call_id:
                part["id"] = call_id
            call_type = self._get_field(call, "type", "") or ""
            if call_type:
                part["type"] = call_type

            function = self._get_field(call, "function", {}) or {}
            name = self._get_field(function, "name", "") or ""
            if name:
                if not part["name"] or name.startswith(part["name"]):
                    part["name"] = name
                elif name != part["name"]:
                    part["name"] += name

            arguments = self._get_field(function, "arguments", None)
            if isinstance(arguments, str):
                part["arguments"] += arguments
            elif arguments:
                serialized = json.dumps(arguments, ensure_ascii=False)
                part["arguments"] = part["arguments"] or serialized

    def _chat_stream_tool_calls(self, tool_call_parts):
        assistant_tool_calls = []
        tool_calls = []
        for index in sorted(tool_call_parts):
            part = tool_call_parts[index]
            arguments = part.get("arguments", "")
            name = part.get("name", "")
            call_id = part.get("id", "")
            assistant_tool_call = {
                "id": call_id,
                "type": part.get("type") or "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
            assistant_tool_calls.append(assistant_tool_call)
            tool_calls.append({
                "id": call_id,
                "name": name,
                "arguments": self._parse_tool_arguments(arguments),
            })
        return assistant_tool_calls, tool_calls

    def _stream_ollama_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        try:
            thinking_streamed, tracked_callback_thinking = (
                self._normal_stream_thinking_tracker(stream_callback_thinking)
            )
            full_thinking = ""
            final_response = ""
            response_streamed = False

            for _ in range(self._normal_web_search_tool_limit()):
                (
                    assistant_message,
                    thinking,
                    text,
                    tool_calls,
                    round_response_started,
                ) = self._run_model_turn_with_overflow_recovery(
                    lambda: self._stream_ollama_normal_web_search_turn(
                        full_thinking,
                        False,
                        tracked_callback_thinking,
                        stream_callback_response,
                        emit_response=True,
                    )
                )
                full_thinking += thinking
                final_response += text
                response_streamed = response_streamed or round_response_started
                if self._agent_should_stop():
                    return self._agent_stopped_response(
                        _clean_reasoning_text(full_thinking),
                        final_response,
                    )

                if not tool_calls:
                    self.conversation_history.append(assistant_message)
                    return self._stream_normal_tool_first_response(
                        _clean_reasoning_text(full_thinking),
                        final_response,
                        stream_callback_response,
                        tracked_callback_thinking,
                        thinking_streamed["streamed"],
                        _response_started=response_streamed,
                    )

                self.conversation_history.append(assistant_message)
                if self.thinking_mode:
                    finish_thinking_round()
                self._append_normal_web_search_tool_results(
                    tool_calls, provider="ollama"
                )

            return self._stream_normal_web_search_round_limit_response(
                _clean_reasoning_text(full_thinking),
                final_response,
                response_streamed,
                stream_callback_response,
                tracked_callback_thinking,
                thinking_streamed["streamed"],
            )
        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _stream_ollama_normal_web_search_turn(
        self,
        prior_thinking,
        response_started,
        callback_thinking=None,
        callback_response=None,
        emit_response=True,
    ):
        response = self.client.chat(
            **self._ollama_chat_kwargs(
                messages=self.conversation_history,
                tools=self._normal_web_search_tool_schemas(),
                stream=True,
            )
        )

        field_thinking = ""
        tagged_thinking = ""
        full_response = ""
        raw_response = ""
        tool_call_parts = {}
        usage_snapshot = None

        for chunk in response:
            if self._agent_should_stop():
                break
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)

            message = self._get_field(chunk, "message", {})
            thinking = self._get_field(message, "thinking", "") or ""
            if thinking:
                field_thinking += thinking
                if callback_thinking and self.thinking_mode and not response_started:
                    callback_thinking(thinking)

            content, full_response, raw_response = self._stream_content_delta(
                self._get_field(message, "content", "") or "",
                full_response,
                raw_response,
            )
            tagged_reasoning, tagged_thinking = self._stream_tagged_reasoning_delta(
                raw_response,
                tagged_thinking,
            )
            if (
                tagged_reasoning
                and not response_started
                and callback_thinking
                and self.thinking_mode
            ):
                callback_thinking(tagged_reasoning)
            full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
            if content and emit_response:
                response_started = self._start_normal_stream_response(
                    response_started,
                    prior_thinking + full_thinking,
                )
                if callback_response:
                    callback_response(content)

            self._update_ollama_stream_tool_call_parts(
                tool_call_parts,
                self._get_field(message, "tool_calls", None) or [],
            )

        self._record_context_usage_snapshot(usage_snapshot)

        assistant_tool_calls, tool_calls = self._ollama_stream_tool_calls(
            tool_call_parts
        )
        full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
        assistant_message = self._ollama_assistant_message(
            full_response,
            _clean_reasoning_text(full_thinking),
            assistant_tool_calls,
        )
        return (
            assistant_message,
            full_thinking,
            full_response,
            tool_calls,
            response_started,
        )

    def _update_ollama_stream_tool_call_parts(self, tool_call_parts, raw_tool_calls):
        for fallback_index, call in enumerate(raw_tool_calls or []):
            function = self._get_field(call, "function", {}) or {}
            raw_index = self._get_field(function, "index", fallback_index)
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                index = fallback_index

            part = tool_call_parts.setdefault(
                index,
                {
                    "type": self._get_field(call, "type", "function") or "function",
                    "name": "",
                    "arguments": "",
                },
            )
            call_type = self._get_field(call, "type", "") or ""
            if call_type:
                part["type"] = call_type

            name = self._get_field(function, "name", "") or ""
            if name:
                if not part["name"] or name.startswith(part["name"]):
                    part["name"] = name
                elif name != part["name"]:
                    part["name"] += name

            arguments = self._get_field(function, "arguments", None)
            if isinstance(arguments, dict):
                part["arguments"] = arguments
            elif isinstance(arguments, str):
                existing = part.get("arguments")
                part["arguments"] = (
                    existing if isinstance(existing, str) else ""
                ) + arguments
            elif arguments:
                part["arguments"] = arguments

    def _ollama_stream_tool_calls(self, tool_call_parts):
        assistant_tool_calls = []
        tool_calls = []
        for index in sorted(tool_call_parts):
            part = tool_call_parts[index]
            parsed_arguments = self._parse_tool_arguments(part.get("arguments", {}))
            function_call = {
                "name": part.get("name", ""),
                "arguments": parsed_arguments,
            }
            if len(tool_call_parts) > 1:
                function_call["index"] = index
            assistant_tool_calls.append({
                "type": part.get("type") or "function",
                "function": function_call,
            })
            tool_calls.append({
                "name": part.get("name", ""),
                "arguments": parsed_arguments,
            })
        return assistant_tool_calls, tool_calls

    def _stream_anthropic_normal_web_search_response(
        self,
        stream_callback_thinking=None,
        stream_callback_response=None,
    ):
        try:
            thinking_streamed, tracked_callback_thinking = (
                self._normal_stream_thinking_tracker(stream_callback_thinking)
            )
            full_thinking = ""
            final_response = ""
            response_streamed = False

            for _ in range(self._normal_web_search_tool_limit()):
                (
                    blocks,
                    thinking,
                    text,
                    tool_uses,
                    round_response_started,
                ) = self._run_model_turn_with_overflow_recovery(
                    lambda: self._stream_anthropic_normal_web_search_turn(
                        full_thinking,
                        False,
                        tracked_callback_thinking,
                        stream_callback_response,
                        emit_response=True,
                    )
                )
                full_thinking += thinking
                final_response += text
                response_streamed = response_streamed or round_response_started
                if self._agent_should_stop():
                    return self._agent_stopped_response(full_thinking, final_response)

                if not tool_uses:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": blocks,
                    })
                    return self._stream_normal_tool_first_response(
                        full_thinking,
                        final_response,
                        stream_callback_response,
                        tracked_callback_thinking,
                        thinking_streamed["streamed"],
                        _response_started=response_streamed,
                    )

                self.conversation_history.append({
                    "role": "assistant",
                    "content": blocks,
                })
                if self.thinking_mode:
                    finish_thinking_round()
                tool_results = []
                for tool_use in tool_uses:
                    if self._agent_should_stop():
                        return self._agent_stopped_response(
                            full_thinking, final_response
                        )
                    tool_result, display = (
                        self._execute_normal_web_search_tool_with_display(
                            tool_use.get("name", ""),
                            tool_use.get("input", {}),
                        )
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.get("id", ""),
                        "tool_name": tool_use.get("name", ""),
                        "content": tool_result,
                        "is_error": tool_result_is_error(
                            tool_use.get("name", ""), tool_result, display
                        ),
                        "display": display,
                    })
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results,
                })

            return self._stream_normal_web_search_round_limit_response(
                full_thinking,
                final_response,
                response_streamed,
                stream_callback_response,
                tracked_callback_thinking,
                thinking_streamed["streamed"],
            )
        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _stream_anthropic_normal_web_search_turn(
        self,
        prior_thinking,
        response_started,
        callback_thinking=None,
        callback_response=None,
        emit_response=True,
    ):
        blocks = []
        active_block_index = None

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=self._normal_system_prompt(),
            messages=self._anthropic_messages(),
            tools=self._normal_web_search_tool_schemas(),
            stream=True,
            **self._anthropic_request_options(),
        )

        field_thinking = ""
        tagged_thinking = ""
        full_response = ""
        raw_response = ""
        usage_snapshot = None
        for chunk in response:
            if self._agent_should_stop():
                break
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
            chunk_type = self._get_field(chunk, "type", "")

            if chunk_type == "content_block_start":
                content_block = self._get_field(chunk, "content_block")
                block_type = self._get_field(content_block, "type", "")
                initial_reasoning = self._anthropic_reasoning_text(content_block, clean=False)
                if block_type == "text":
                    if initial_reasoning:
                        field_thinking += initial_reasoning
                        if (
                            callback_thinking
                            and self.thinking_mode
                            and not response_started
                        ):
                            callback_thinking(initial_reasoning)
                    initial_text = self._get_field(content_block, "text", "") or ""
                    block = {"type": "text", "text": ""}
                    if initial_text:
                        content, full_response, raw_response = (
                            self._stream_content_delta(
                                initial_text,
                                full_response,
                                raw_response,
                            )
                        )
                        block["text"] = block.get("text", "") + content
                        tagged_reasoning, tagged_thinking = (
                            self._stream_tagged_reasoning_delta(
                                raw_response,
                                tagged_thinking,
                            )
                        )
                        if (
                            tagged_reasoning
                            and not response_started
                            and callback_thinking
                            and self.thinking_mode
                        ):
                            callback_thinking(tagged_reasoning)
                        full_thinking = _combine_reasoning_text(
                            field_thinking,
                            tagged_thinking,
                        )
                        if content and emit_response:
                            response_started = self._start_normal_stream_response(
                                response_started,
                                prior_thinking + full_thinking,
                            )
                            if callback_response:
                                callback_response(content)
                elif (
                    self._is_anthropic_reasoning_block_type(block_type)
                    or initial_reasoning
                ):
                    initial_thinking = initial_reasoning
                    block = {"type": "thinking", "thinking": initial_thinking}
                    if initial_thinking:
                        field_thinking += initial_thinking
                        if (
                            callback_thinking
                            and self.thinking_mode
                            and not response_started
                        ):
                            callback_thinking(initial_thinking)
                    signature = self._get_field(content_block, "signature")
                    if signature:
                        block["signature"] = signature
                elif block_type == "tool_use":
                    block = {
                        "type": "tool_use",
                        "id": self._get_field(content_block, "id", "") or "",
                        "name": self._get_field(content_block, "name", "") or "",
                        "input": self._get_field(content_block, "input", {}) or {},
                        "_input_json": "",
                    }
                else:
                    block = {"type": block_type or "unknown"}
                blocks.append(block)
                active_block_index = len(blocks) - 1
                continue

            if chunk_type == "content_block_delta" and active_block_index is not None:
                delta = self._get_field(chunk, "delta")
                delta_type = self._get_field(delta, "type", "")
                block = blocks[active_block_index]

                if delta_type == "text_delta":
                    text_delta = self._get_field(delta, "text", "") or ""
                    if text_delta:
                        content, full_response, raw_response = (
                            self._stream_content_delta(
                                text_delta,
                                full_response,
                                raw_response,
                            )
                        )
                        block["text"] = block.get("text", "") + content
                        tagged_reasoning, tagged_thinking = (
                            self._stream_tagged_reasoning_delta(
                                raw_response,
                                tagged_thinking,
                            )
                        )
                        if (
                            tagged_reasoning
                            and not response_started
                            and callback_thinking
                            and self.thinking_mode
                        ):
                            callback_thinking(tagged_reasoning)
                        full_thinking = _combine_reasoning_text(
                            field_thinking,
                            tagged_thinking,
                        )
                        if content and emit_response:
                            response_started = self._start_normal_stream_response(
                                response_started,
                                prior_thinking + full_thinking,
                            )
                            if callback_response:
                                callback_response(content)
                elif self._is_anthropic_reasoning_delta_type(delta_type):
                    thinking_delta = self._anthropic_delta_reasoning_text(delta)
                    if thinking_delta:
                        field_thinking += thinking_delta
                        block["thinking"] = block.get("thinking", "") + thinking_delta
                        if (
                            callback_thinking
                            and self.thinking_mode
                            and not response_started
                        ):
                            callback_thinking(thinking_delta)
                elif delta_type == "signature_delta":
                    block["signature"] = block.get("signature", "") + (
                        self._get_field(delta, "signature", "") or ""
                    )
                elif delta_type == "input_json_delta":
                    block["_input_json"] = block.get("_input_json", "") + (
                        self._get_field(delta, "partial_json", "") or ""
                    )
                continue

            if chunk_type == "content_block_stop" and active_block_index is not None:
                block = blocks[active_block_index]
                if block.get("type") == "tool_use":
                    raw_input = block.pop("_input_json", "")
                    if raw_input:
                        block["input"] = self._parse_tool_arguments(raw_input)
                active_block_index = None

        for block in blocks:
            block.pop("_input_json", None)
        self._record_context_usage_snapshot(usage_snapshot)

        thinking, text, tool_uses = self._parse_anthropic_blocks(blocks)
        thinking = _combine_reasoning_text(
            _merge_reasoning_text(thinking, field_thinking),
            tagged_thinking,
        )
        return blocks, thinking, text, tool_uses, response_started

    def _pseudo_stream_text(
        self,
        text,
        callback_response=None,
        chunk_size=8,
        delay=0.005,
    ):
        if not text:
            return
        text = clean_display_text(text)
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            chunk = text[i : i + chunk_size]
            if callback_response:
                callback_response(chunk)
            else:
                print_stream_response_continue(chunk)
            if delay:
                time.sleep(delay)

    def _start_normal_stream_response(self, response_started, thinking):
        if response_started:
            return True
        print_stream_response_start(self.model)
        return True

    def _stream_normal_tool_first_response(
        self,
        thinking,
        response,
        callback_response=None,
        callback_thinking=None,
        thinking_streamed=False,
        _response_started=False,
    ):
        thinking_printed_now, thinking_streamed = (
            self._stream_normal_thinking_if_needed(
                thinking,
                callback_thinking,
                thinking_streamed,
            )
        )
        response_started = _response_started
        if response and not _response_started:
            separator_thinking = "" if thinking_printed_now else thinking
            response_started = self._start_normal_stream_response(
                False,
                separator_thinking,
            )
            self._pseudo_stream_text(response, callback_response)
        return {
            "thinking": thinking,
            "response": response,
            "response_streamed": response_started,
            "thinking_streamed": thinking_streamed,
        }

    def _stream_normal_web_search_round_limit_response(
        self,
        thinking,
        response,
        response_started,
        stream_callback_response=None,
        stream_callback_thinking=None,
        thinking_streamed=False,
    ):
        message = (
            "Normal-mode tools stopped after "
            f"{self._normal_web_search_tool_limit()} tool calls."
        )
        _, thinking_streamed = self._stream_normal_thinking_if_needed(
            thinking,
            stream_callback_thinking,
            thinking_streamed,
        )
        print_error(message)
        final_response = response or message
        if not response and stream_callback_response is not None:
            print_stream_response_start(self.model)
            self._pseudo_stream_text(
                message,
                stream_callback_response,
                delay=0,
            )
            response_started = True
        return {
            "thinking": thinking,
            "response": final_response,
            "response_streamed": response_started,
            "thinking_streamed": thinking_streamed,
        }

    def _finalize_normal_web_search_response(
        self,
        thinking,
        response,
        stream_callback_thinking=None,
        stream_callback_response=None,
        *,
        thinking_streamed=False,
        response_streamed=False,
    ):
        if self.stream_mode:
            thinking_streamed = self._stream_normal_web_search_text(
                thinking,
                response,
                stream_callback_thinking,
                stream_callback_response,
            )
            return {
                "thinking": thinking,
                "response": response,
                "response_streamed": True,
                "thinking_streamed": thinking_streamed,
            }
        return {
            "thinking": thinking,
            "response": response,
            "response_streamed": bool(response_streamed),
            "thinking_streamed": bool(thinking_streamed),
        }

    def _stream_normal_web_search_text(
        self,
        thinking,
        response,
        callback_thinking=None,
        callback_response=None,
    ):
        _, thinking_streamed = self._stream_normal_thinking_if_needed(
            thinking,
            callback_thinking,
            False,
        )
        print_stream_response_start(self.model)
        if response:
            self._pseudo_stream_text(response, callback_response)
        return thinking_streamed

    def _normal_web_search_round_limit_response(
        self,
        thinking,
        response,
        stream_callback_thinking=None,
        stream_callback_response=None,
        *,
        thinking_streamed=False,
        response_streamed=False,
    ):
        message = (
            "Normal-mode tools stopped after "
            f"{self._normal_web_search_tool_limit()} tool calls."
        )
        print_error(message)
        if not response:
            return {
                "thinking": thinking,
                "response": message,
                "response_streamed": False,
                "thinking_streamed": bool(thinking_streamed),
            }
        return self._finalize_normal_web_search_response(
            thinking,
            response,
            stream_callback_thinking,
            stream_callback_response,
            thinking_streamed=thinking_streamed,
            response_streamed=response_streamed,
        )

    def _stream_ollama_agent_turn(self):
        response = self.client.chat(
            **self._ollama_chat_kwargs(
                messages=self._ollama_agent_messages(),
                tools=ollama_tool_schemas(
                    self.agent_tools.web_search_available,
                    self.agent_tools.skills_available,
                    self.agent_tools.todos_enabled,
                    extra_definitions=self.agent_tools.plan_tool_definitions()
                    + self.agent_tools.subagent_tool_definitions()
                    + self.agent_tools.team_tool_definitions(),
                    plan_mode=self.agent_tools.plan_mode,
                ),
                stream=True,
            )
        )

        field_thinking = ""
        full_response = ""
        tool_call_parts = {}
        usage_snapshot = None
        response_streamed = False

        for chunk in response:
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)

            message = self._get_field(chunk, "message", {})
            thinking = self._get_field(message, "thinking", "") or ""
            if thinking:
                field_thinking += thinking
                self._stream_agent_thinking(thinking)

            content = self._get_field(message, "content", "") or ""
            if content:
                full_response += content
                if not response_streamed:
                    self._separate_after_agent_thinking()
                    self.agent_output_needs_separator = False
                    print_stream_response_start(self.model)
                    self.agent_response_started = True
                    response_streamed = True
                    self.agent_response_streamed = True
                print_stream_response_continue(content)

            self._update_ollama_stream_tool_call_parts(
                tool_call_parts,
                self._get_field(message, "tool_calls", None) or [],
            )

        self._record_context_usage_snapshot(usage_snapshot)

        assistant_tool_calls, tool_calls = self._ollama_stream_tool_calls(
            tool_call_parts
        )
        thinking_content = _clean_reasoning_text(field_thinking)
        assistant_message = self._ollama_assistant_message(
            full_response,
            thinking_content,
            assistant_tool_calls,
        )
        return (
            assistant_message,
            thinking_content,
            full_response,
            tool_calls,
            response_streamed,
        )

    def _ollama_agent_response(self):
        full_thinking = ""
        final_response = ""

        for round_index in range(1, (self.max_agent_rounds * 2) + 1):
            if round_index > self.agent_round_limit:
                break
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)
            self._prepare_agent_model_round(round_index)
            (
                assistant_message,
                thinking_content,
                text,
                tool_calls,
                response_streamed,
            ) = self._run_model_turn_with_overflow_recovery(
                self._stream_ollama_agent_turn
            )
            self.conversation_history.append(assistant_message)
            full_thinking += thinking_content
            final_response += text
            if self._agent_should_stop():
                return self._agent_stopped_response(full_thinking, final_response)

            if not tool_calls:
                if self._append_agent_final_check_if_needed():
                    final_response = ""
                    continue
                final_response = self._agent_response_with_plan_exit_note(
                    final_response
                )
                if response_streamed:
                    plan_note = self.agent_plan_check_exit_note
                    if plan_note:
                        print_stream_response_continue(f"\n\n{plan_note}")
                else:
                    self._stream_agent_response_text(final_response, pseudo=True)
                return {"thinking": full_thinking, "response": final_response}

            if self._agent_tool_budget_exceeded(tool_calls):
                message = self._agent_tool_budget_message()
                for tool_call in tool_calls:
                    error_result = _error_text(message)
                    display = self._tool_display_for_result(
                        tool_call["name"],
                        tool_call.get("arguments", {}),
                        error_result,
                    )
                    self.conversation_history.append(
                        self._ollama_tool_result_message(
                            tool_call["name"],
                            error_result,
                            display=display,
                        )
                    )

                self._separate_after_agent_thinking()
                print_error(message)
                return {
                    "thinking": full_thinking,
                    "response": final_response or message,
                }

            for tool_call in tool_calls:
                if self._agent_should_stop():
                    return self._agent_stopped_response(full_thinking, final_response)
                tool_result = self._execute_agent_tool(
                    tool_call["name"], tool_call["arguments"]
                )
                self.conversation_history.append(
                    self._ollama_tool_result_message(
                        tool_call["name"],
                        tool_result,
                        display=self._consume_last_tool_display(),
                    )
                )
            finish_thinking_round()

        message = f"Agent loop stopped after {self.agent_round_limit} tool rounds."
        self._separate_after_agent_thinking()
        print_error(message)
        return {"thinking": full_thinking, "response": final_response or message}

    def _stream_anthropic_agent_turn(self):
        blocks = []
        active_block_index = None
        response_streamed = False

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=self._anthropic_messages(),
            system=self._agent_system_prompt(),
            tools=anthropic_tool_schemas(
                self.agent_tools.web_search_available,
                self.agent_tools.skills_available,
                self.agent_tools.todos_enabled,
                extra_definitions=self.agent_tools.plan_tool_definitions()
                + self.agent_tools.subagent_tool_definitions()
                + self.agent_tools.team_tool_definitions(),
                plan_mode=self.agent_tools.plan_mode,
            ),
            stream=True,
            **self._anthropic_request_options(),
        )

        usage_snapshot = None
        for chunk in response:
            if self._agent_should_stop():
                break
            chunk_usage = _response_token_usage(chunk)
            if chunk_usage is not None:
                usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
            chunk_type = self._get_field(chunk, "type", "")

            if chunk_type == "content_block_start":
                content_block = self._get_field(chunk, "content_block")
                block_type = self._get_field(content_block, "type", "")
                initial_reasoning = self._anthropic_reasoning_text(content_block, clean=False)
                if block_type == "text":
                    if initial_reasoning:
                        blocks.append({
                            "type": "thinking",
                            "thinking": initial_reasoning,
                        })
                        self._stream_agent_thinking(initial_reasoning)
                    block = {"type": "text", "text": ""}
                elif (
                    self._is_anthropic_reasoning_block_type(block_type)
                    or initial_reasoning
                ):
                    block = {
                        "type": "thinking",
                        "thinking": initial_reasoning,
                    }
                elif block_type == "tool_use":
                    block = {
                        "type": "tool_use",
                        "id": self._get_field(content_block, "id", "") or "",
                        "name": self._get_field(content_block, "name", "") or "",
                        "input": {},
                        "_input_json": "",
                    }
                else:
                    block = {"type": block_type or "unknown"}
                blocks.append(block)
                active_block_index = len(blocks) - 1
                continue

            if chunk_type == "content_block_delta" and active_block_index is not None:
                delta = self._get_field(chunk, "delta")
                delta_type = self._get_field(delta, "type", "")
                block = blocks[active_block_index]

                if delta_type == "text_delta":
                    text_delta = self._get_field(delta, "text", "") or ""
                    block["text"] = block.get("text", "") + text_delta
                    if text_delta:
                        if not response_streamed:
                            self._separate_after_agent_thinking()
                            self.agent_output_needs_separator = False
                            print_stream_response_start(self.model)
                            self.agent_response_started = True
                            response_streamed = True
                            self.agent_response_streamed = True
                        print_stream_response_continue(text_delta)
                elif self._is_anthropic_reasoning_delta_type(delta_type):
                    thinking_delta = self._anthropic_delta_reasoning_text(delta)
                    block["thinking"] = block.get("thinking", "") + thinking_delta
                    self._stream_agent_thinking(thinking_delta)
                elif delta_type == "signature_delta":
                    block["signature"] = block.get("signature", "") + (
                        self._get_field(delta, "signature", "") or ""
                    )
                elif delta_type == "input_json_delta":
                    block["_input_json"] = block.get("_input_json", "") + (
                        self._get_field(delta, "partial_json", "") or ""
                    )
                continue

            if chunk_type == "content_block_stop" and active_block_index is not None:
                block = blocks[active_block_index]
                if block.get("type") == "tool_use":
                    raw_input = block.pop("_input_json", "")
                    if raw_input:
                        block["input"] = self._parse_tool_arguments(raw_input)
                active_block_index = None

        for block in blocks:
            block.pop("_input_json", None)
        self._record_context_usage_snapshot(usage_snapshot)
        return blocks, response_streamed

    def _agent_should_stop(self):
        return self.agent_stop_requested

    def _agent_stopped_response(self, thinking, response):
        message = "Agent stopped by user."
        self._separate_after_agent_thinking()
        self._print_agent_stopped_by_user()
        return {
            "thinking": thinking,
            "response": response or message,
            "agent_stopped": True,
        }

    def _print_agent_stopped_by_user(self):
        print_warn("Agent stopped by user.")

    def _agent_tool_budget_exceeded(self, tool_calls):
        requested_tool_calls = sum(
            1
            for tool_call in list(tool_calls or [])
            if str(tool_call.get("name") or "") != SUBMIT_PLAN_TOOL_NAME
        )
        return self.agent_tool_calls + requested_tool_calls > self.agent_tool_call_limit

    def _agent_tool_budget_message(self):
        summary = self.agent_tools.todo_budget_summary()
        if summary:
            return (
                f"Agent stopped after {self.agent_tool_call_limit} tool calls.\n"
                f"{summary}"
            )
        return f"Agent stopped after {self.agent_tool_call_limit} tool calls."

    def _print_agent_round(self, round_index):
        return

    def _stream_agent_thinking(self, content):
        if not self.thinking_mode or not content:
            return
        leading_newline = True
        if self.agent_output_needs_separator:
            self.agent_output_needs_separator = False
            self.agent_thinking_streamed = False
            self.agent_thinking_needs_separator = False
            leading_newline = False
        if not self.agent_thinking_streamed:
            print_stream_thinking("", leading_newline=leading_newline)
            self.agent_thinking_streamed = True
        print_stream_thinking_continue(content)
        self.agent_thinking_needs_separator = True

    def _stream_agent_response_text(self, content, pseudo=False):
        if not self.stream_mode or not content:
            return
        if pseudo:
            content = clean_display_text(content)
            if not content:
                return
        if not self.agent_response_started:
            self._separate_after_agent_thinking()
            self.agent_output_needs_separator = False
            print_stream_response_start(self.model)
            self.agent_response_started = True
        if pseudo:
            for character in content:
                print_stream_response_continue(character)
        else:
            clean_and_print_stream_response(content)
        self.agent_response_streamed = True

    def _separate_after_agent_thinking(self):
        if not self.agent_thinking_needs_separator:
            return
        self.agent_thinking_needs_separator = False

    def _before_agent_visible_output(self):
        finish_thinking_round()
        self._separate_after_agent_thinking()

    def _prepare_agent_model_round(self, round_index):
        self.agent_round_index = int(round_index)
        if round_index > 1:
            self._auto_compact_context()
        self._print_agent_round(round_index)
        self._warn_agent_context_if_needed()

    def _warn_agent_context_if_needed(self):
        if self.agent_context_warning_sent:
            return
        estimated_chars = _estimate_history_chars(self.conversation_history)
        if estimated_chars < AGENT_CONTEXT_WARN_CHARS:
            return

        self.agent_context_warning_sent = True
        warning = (
            "Agent context budget warning: the current conversation and tool results are large. "
            "Use narrower searches, continue large files with offset/limit, and avoid repeating bulky outputs."
        )
        self._separate_after_agent_thinking()
        print_warn(warning)
        self.agent_output_needs_separator = True
        self.conversation_history.append({"role": "user", "content": warning})

    def _auto_compact_context(self):
        if not self.compaction_enable:
            return {"compacted": False, "reason": "Context compaction is disabled."}

        input_tokens, usage_source = self._context_tokens_for_compaction()
        input_budget_tokens = self._compaction_input_budget()
        estimated_chars = _estimate_history_chars(self.conversation_history)
        if input_tokens < input_budget_tokens:
            return {
                "compacted": False,
                "reason": "Context is within the available input budget.",
                "before_chars": estimated_chars,
                "input_tokens": input_tokens,
                "usage_source": usage_source,
                "input_budget_tokens": input_budget_tokens,
                "reserved_output_tokens": self._compaction_output_reserve(),
                "context_window_tokens": self.context_window_tokens,
            }

        prune_result = self._soft_prune_old_tool_results(input_budget_tokens)
        if prune_result.get("pruned_tool_results"):
            print_info(
                "Pruned "
                f"{prune_result['pruned_tool_results']} old tool result(s) "
                "before full context compaction."
            )
            input_tokens, usage_source = self._context_tokens_for_compaction()
            estimated_chars = _estimate_history_chars(self.conversation_history)
            if input_tokens < input_budget_tokens:
                return {
                    "compacted": False,
                    "reason": "Old tool results were pruned within the available input budget.",
                    "before_chars": estimated_chars,
                    "input_tokens": input_tokens,
                    "usage_source": usage_source,
                    "input_budget_tokens": input_budget_tokens,
                    "reserved_output_tokens": self._compaction_output_reserve(),
                    "context_window_tokens": self.context_window_tokens,
                    **prune_result,
                }

        result = self.compact_context(manual=False)
        if prune_result.get("pruned_tool_results"):
            result.update(prune_result)
        if result.get("error"):
            print_warn(result.get("reason", "Automatic context compaction failed."))
        return result

    def _context_tokens_for_compaction(self):
        estimated_tokens = self._estimate_current_context_tokens()
        api_tokens = max(
            int(self.last_context_input_tokens or 0),
            int(self.last_context_total_tokens or 0),
        )
        if api_tokens > 0:
            if estimated_tokens > api_tokens:
                return (
                    estimated_tokens,
                    f"{self.last_context_usage_source or 'api_usage'}+estimated",
                )
            return api_tokens, self.last_context_usage_source or "api_usage"
        return estimated_tokens, "estimated"

    def _compaction_output_reserve(self):
        return min(
            max(1, int(self.max_tokens or 1)),
            max(1, self.context_window_tokens - 1),
        )

    def _compaction_input_budget(self):
        return max(
            1,
            self.context_window_tokens - self._compaction_output_reserve(),
        )

    def _record_context_usage(self, response=None, *, source="api_usage"):
        self._record_context_usage_snapshot(
            _response_token_usage(response),
            source=source,
        )

    def _record_context_usage_snapshot(self, usage, *, source="api_usage"):
        self._append_request_usage(usage, source=source)
        if usage is not None and usage.get("input_tokens", 0) > 0:
            self._set_context_token_usage(usage, source)
            return
        self._set_context_input_tokens(
            self._estimate_current_context_tokens(), "estimated"
        )

    def _append_request_usage(
        self,
        usage,
        *,
        source="api_usage",
        kind=None,
        model=None,
        notify=False,
    ):
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            return
        token_keys = (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
        )
        normalized = {
            key: max(0, int(usage.get(key, 0) or 0))
            for key in token_keys
        }
        usage_available = bool(any(normalized.values()))
        if kind is None:
            if self.agent_running or self.agent_mode:
                kind = "agent"
            elif self._normal_tools_available():
                kind = "tool"
            else:
                kind = "chat"
        entry = {
            "id": f"usage-{uuid.uuid4().hex}",
            "timestamp": _utc_timestamp(),
            "kind": str(kind or "chat"),
            "model": str(model or self.current_model_name or self.model or ""),
            "api_type": str(self.api_type or ""),
            **normalized,
            "usage_available": usage_available,
            "source": str(source or "api_usage"),
        }
        with self.usage_history_lock:
            self.request_usage_history.append(entry)
        if notify and self.usage_history_callback is not None:
            try:
                self.usage_history_callback(self, dict(entry))
            except Exception as error:
                print_warn(f"Failed to persist request usage: {error}")
        return entry

    def _record_auxiliary_usage(
        self,
        response,
        *,
        kind,
        model,
        source,
    ):
        return self._append_request_usage(
            _response_token_usage(response),
            kind=kind,
            model=model,
            source=source,
            notify=True,
        )

    def _set_context_token_usage(self, usage, source):
        self.last_context_input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
        self.last_context_output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
        self.last_context_reasoning_tokens = max(
            0, int(usage.get("reasoning_tokens", 0) or 0)
        )
        self.last_context_cache_read_tokens = max(
            0, int(usage.get("cache_read_tokens", 0) or 0)
        )
        self.last_context_cache_write_tokens = max(
            0, int(usage.get("cache_write_tokens", 0) or 0)
        )
        self.last_context_total_tokens = max(
            self.last_context_input_tokens,
            int(usage.get("total_tokens", 0) or 0),
        )
        self.last_context_usage_source = str(source or "api_usage")
        set_context_usage(self.last_context_input_tokens, self.context_window_tokens)

    def _set_context_input_tokens(self, input_tokens, source):
        try:
            input_tokens = int(input_tokens or 0)
        except (TypeError, ValueError):
            input_tokens = 0
        if input_tokens <= 0:
            return
        self._set_context_token_usage(
            {"input_tokens": input_tokens, "total_tokens": input_tokens}, source
        )

    def get_context_usage_status(self):
        return {
            "input_tokens": self.last_context_input_tokens,
            "output_tokens": self.last_context_output_tokens,
            "reasoning_tokens": self.last_context_reasoning_tokens,
            "cache_read_tokens": self.last_context_cache_read_tokens,
            "cache_write_tokens": self.last_context_cache_write_tokens,
            "total_tokens": self.last_context_total_tokens,
            "source": self.last_context_usage_source,
            "context_window_tokens": self.context_window_tokens,
            "reserved_output_tokens": self._compaction_output_reserve(),
            "compaction_input_budget_tokens": self._compaction_input_budget(),
            "last_compaction_usage": dict(self.last_compaction_usage),
        }

    def _clear_context_usage(self):
        self.last_context_input_tokens = 0
        self.last_context_output_tokens = 0
        self.last_context_reasoning_tokens = 0
        self.last_context_cache_read_tokens = 0
        self.last_context_cache_write_tokens = 0
        self.last_context_total_tokens = 0
        self.last_context_usage_source = ""
        self.last_compaction_usage = {}

    def _record_compaction_usage(self, response, model=None):
        usage = _response_token_usage(response)
        self.last_compaction_usage = dict(usage or {})
        self._append_request_usage(
            usage,
            source="compaction_api_usage",
            kind="compaction",
            model=model,
        )

    def _estimate_current_context_tokens(self):
        if self.agent_running or self.agent_mode:
            messages = [{"role": "system", "content": self._agent_system_prompt()}]
        else:
            messages = [{"role": "system", "content": self._normal_system_prompt()}]
        messages += self._effective_history_messages(self.conversation_history)
        return _estimate_history_tokens(messages)

    def _estimate_effective_history_tokens(self, messages):
        return _estimate_history_tokens(self._effective_history_messages(messages))

    def _compaction_recent_token_budget(self, input_budget_tokens):
        input_budget_tokens = max(1, int(input_budget_tokens or 1))
        return min(
            COMPACTION_RECENT_TOKEN_MAX,
            max(
                COMPACTION_RECENT_TOKEN_MIN,
                input_budget_tokens // 4,
            ),
        )

    def _is_conversation_turn_start(self, message):
        if not isinstance(message, dict) or message.get("role") != "user":
            return False
        if self._message_has_tool_result(message):
            return False
        content = str(message.get("content", "") or "")
        return not content.startswith(COMPACTION_SUMMARY_PREFIX)

    def _compaction_turns(self, messages):
        starts = [
            index
            for index, message in enumerate(messages)
            if self._is_conversation_turn_start(message)
        ]
        return [
            (start, starts[index + 1] if index + 1 < len(starts) else len(messages))
            for index, start in enumerate(starts)
        ]

    def _split_compaction_turn(self, messages, turn, budget):
        if budget <= 0:
            return None
        start, end = turn
        if end - start <= 1:
            return None
        for candidate in range(start + 1, end):
            if self._estimate_effective_history_tokens(messages[candidate:end]) <= budget:
                return candidate
        return None

    def _compaction_message_windows(self, input_budget_tokens):
        existing_summary, messages = self._split_existing_compaction_summary(
            self.conversation_history
        )
        if not messages:
            return existing_summary, [], [], 0, 0

        recent_budget = self._compaction_recent_token_budget(input_budget_tokens)
        turns = self._compaction_turns(messages)
        if not turns:
            return existing_summary, messages, [], recent_budget, 0

        recent_turns = turns[-COMPACTION_TAIL_TURNS:]
        turn_sizes = [
            self._estimate_effective_history_tokens(messages[start:end])
            for start, end in recent_turns
        ]
        total = 0
        recent_start = None
        for turn, turn_tokens in reversed(list(zip(recent_turns, turn_sizes))):
            if total + turn_tokens <= recent_budget:
                total += turn_tokens
                recent_start = turn[0]
                continue

            split_start = self._split_compaction_turn(
                messages,
                turn,
                recent_budget - total,
            )
            if split_start is not None:
                recent_start = split_start
            break

        if recent_start is None or recent_start == 0:
            source_messages = messages
            recent_messages = []
        else:
            source_messages = messages[:recent_start]
            recent_messages = messages[recent_start:]
            source_messages, recent_messages = (
                self._fold_leading_tool_results_into_source(
                    source_messages,
                    recent_messages,
                )
            )

        recent_tokens = self._estimate_effective_history_tokens(recent_messages)
        return (
            existing_summary,
            source_messages,
            recent_messages,
            recent_budget,
            recent_tokens,
        )

    def _tool_result_pruned_message(self, message):
        if not isinstance(message, dict):
            return None, 0

        if message.get("role") == "tool":
            content = message.get("content", "")
            if not content or isinstance(message.get("compacted"), dict):
                return None, 0
            replacement = dict(message)
            replacement["compacted"] = self._compacted_metadata(content)
            return replacement, 1

        content = message.get("content")
        if not isinstance(content, list):
            return None, 0

        replacement_blocks = []
        replaced = 0
        for block in content:
            if self._get_field(block, "type") != "tool_result":
                replacement_blocks.append(block)
                continue
            plain_block = dict(self._plain_data(block) or {})
            if isinstance(plain_block.get("compacted"), dict):
                replacement_blocks.append(plain_block)
                continue
            block_content = plain_block.get("content", "")
            if not block_content:
                replacement_blocks.append(plain_block)
                continue
            plain_block["compacted"] = self._compacted_metadata(block_content)
            replacement_blocks.append(plain_block)
            replaced += 1

        if not replaced:
            return None, 0
        replacement = dict(message)
        replacement["content"] = replacement_blocks
        return replacement, replaced

    @staticmethod
    def _compacted_metadata(content):
        return {
            "at": _utc_timestamp(),
            "replacement": COMPACTION_TOOL_RESULT_PLACEHOLDER,
            "estimated_tokens": _estimate_history_tokens([{"content": content}]),
        }

    def _soft_prune_old_tool_results(self, input_budget_tokens):
        if not self.conversation_history:
            return {
                "pruned_tool_results": 0,
                "pruned_tool_result_tokens": 0,
            }

        input_budget_tokens = max(1, int(input_budget_tokens or 1))
        protect_tokens = min(
            COMPACTION_TOOL_PROTECT_TOKENS,
            max(1000, input_budget_tokens // 2),
        )
        prune_min_tokens = min(
            COMPACTION_TOOL_PRUNE_MIN_TOKENS,
            max(512, input_budget_tokens // 8),
        )
        protected = 0
        candidates = []
        saved_tokens = 0
        result_count = 0

        for index in range(len(self.conversation_history) - 1, -1, -1):
            message = self.conversation_history[index]
            message_tokens = self._estimate_effective_history_tokens([message])
            if protected < protect_tokens:
                protected += message_tokens
                continue

            replacement, replaced = self._tool_result_pruned_message(message)
            if replacement is None:
                continue
            replacement_tokens = self._estimate_effective_history_tokens([replacement])
            saved = max(0, message_tokens - replacement_tokens)
            if not saved:
                continue
            candidates.append((index, replacement))
            saved_tokens += saved
            result_count += replaced

        if saved_tokens < prune_min_tokens:
            return {
                "pruned_tool_results": 0,
                "pruned_tool_result_tokens": 0,
            }

        for index, replacement in candidates:
            self.conversation_history[index] = replacement
        self._set_context_input_tokens(
            self._estimate_current_context_tokens(),
            "estimated_after_tool_prune",
        )
        return {
            "pruned_tool_results": result_count,
            "pruned_tool_result_tokens": saved_tokens,
        }

    def compact_context(self, manual=False):
        before_messages = len(self.conversation_history)
        before_chars = _estimate_history_chars(self.conversation_history)
        before_input_tokens, usage_source = self._context_tokens_for_compaction()
        input_budget_tokens = self._compaction_input_budget()
        compact_model = (
            self.model
            if self.compaction_compact_model == AUTO_MODEL_SELECTION
            else self.compaction_compact_model
        )
        compact_model_label = (
            self.current_model_name
            if self.compaction_compact_model == AUTO_MODEL_SELECTION
            else str(compact_model or "").strip()
        )

        (
            existing_summary,
            source_messages,
            recent_messages,
            recent_token_budget,
            recent_tokens,
        ) = self._compaction_message_windows(input_budget_tokens)
        if not source_messages and not existing_summary:
            return {
                "compacted": False,
                "reason": "Context compaction cancelled: no messages older than the recent window.",
                "before_messages": before_messages,
                "before_chars": before_chars,
                "before_input_tokens": before_input_tokens,
                "usage_source": usage_source,
                "input_budget_tokens": input_budget_tokens,
                "context_window_tokens": self.context_window_tokens,
                "model": compact_model_label,
            }

        if not source_messages and existing_summary:
            return {
                "compacted": False,
                "reason": (
                    "Context compaction cancelled: just compacted recently. "
                    "Wait until more messages move beyond the recent window."
                ),
                "before_messages": before_messages,
                "before_chars": before_chars,
                "before_input_tokens": before_input_tokens,
                "usage_source": usage_source,
                "input_budget_tokens": input_budget_tokens,
                "context_window_tokens": self.context_window_tokens,
                "model": compact_model_label,
            }

        compaction_entry_id = f"compaction-{uuid.uuid4().hex}"
        compaction_mode = "manual" if manual else "auto"
        start_compaction_entry(compaction_entry_id, "running", compaction_mode)

        try:
            summary = self._create_compaction_summary(
                existing_summary,
                source_messages,
                compact_model,
            )
        except Exception as error:
            reason = f"Context compaction failed: {error}"
            finish_compaction_entry(
                compaction_entry_id,
                "failed",
                compaction_mode,
                reason,
            )
            return {
                "compacted": False,
                "error": True,
                "reason": reason,
                "before_messages": before_messages,
                "before_chars": before_chars,
                "before_input_tokens": before_input_tokens,
                "usage_source": usage_source,
                "input_budget_tokens": input_budget_tokens,
                "context_window_tokens": self.context_window_tokens,
                "model": compact_model_label,
            }

        summary = str(summary or "").strip()
        if not summary:
            reason = "Context compaction failed: compact model returned an empty summary."
            finish_compaction_entry(
                compaction_entry_id,
                "failed",
                compaction_mode,
                reason,
            )
            return {
                "compacted": False,
                "error": True,
                "reason": reason,
                "before_messages": before_messages,
                "before_chars": before_chars,
                "before_input_tokens": before_input_tokens,
                "usage_source": usage_source,
                "input_budget_tokens": input_budget_tokens,
                "context_window_tokens": self.context_window_tokens,
                "model": compact_model_label,
            }

        memory_update = self._schedule_memory_update_from_compaction(
            summary,
            source_messages,
            compact_model,
        )
        self.conversation_history = [
            {"role": "user", "content": self._compaction_summary_message(summary)},
            *recent_messages,
        ]
        removed_tool_results = self._sanitize_orphan_tool_results_in_history()
        after_chars = _estimate_history_chars(self.conversation_history)
        after_input_tokens = self._estimate_current_context_tokens()
        self._set_context_input_tokens(after_input_tokens, "estimated_after_compaction")
        finish_compaction_entry(
            compaction_entry_id,
            "done",
            compaction_mode,
            self._compaction_details_text(
                before_messages=before_messages,
                after_messages=len(self.conversation_history),
                before_chars=before_chars,
                after_chars=after_chars,
                before_input_tokens=before_input_tokens,
                after_input_tokens=after_input_tokens,
                input_budget_tokens=input_budget_tokens,
                reserved_output_tokens=self._compaction_output_reserve(),
                usage_source=usage_source,
                recent_token_budget=recent_token_budget,
                recent_tokens=recent_tokens,
                compact_model=compact_model_label,
                removed_tool_results=removed_tool_results,
                memory_update=memory_update,
            ),
        )
        return {
            "compacted": True,
            "manual": manual,
            "before_messages": before_messages,
            "after_messages": len(self.conversation_history),
            "before_chars": before_chars,
            "after_chars": after_chars,
            "before_input_tokens": before_input_tokens,
            "after_input_tokens": after_input_tokens,
            "usage_source": usage_source,
            "input_budget_tokens": input_budget_tokens,
            "reserved_output_tokens": self._compaction_output_reserve(),
            "context_window_tokens": self.context_window_tokens,
            "recent_token_budget": recent_token_budget,
            "recent_tokens": recent_tokens,
            "model": compact_model_label,
            "removed_orphan_tool_results": removed_tool_results,
            "compaction_usage": dict(self.last_compaction_usage),
            "memory_update": memory_update,
        }

    @staticmethod
    def _compaction_details_text(
        *,
        before_messages,
        after_messages,
        before_chars,
        after_chars,
        before_input_tokens,
        after_input_tokens,
        input_budget_tokens,
        reserved_output_tokens,
        usage_source,
        recent_token_budget,
        recent_tokens,
        compact_model,
        removed_tool_results,
        memory_update,
    ):
        lines = [
            f"Message: {before_messages} -> {after_messages}",
            f"Tokens: {before_input_tokens} -> {after_input_tokens}",
            f"Chars: {before_chars} -> {after_chars}",
            f"Input budget: {input_budget_tokens} (output reserve {reserved_output_tokens})",
            f"Recent: {recent_tokens}/{recent_token_budget} estimated tokens",
            f"Usage source: {usage_source}",
        ]
        compact_model = str(compact_model or "").strip()
        if compact_model:
            lines.append(f"Compact model: {compact_model}")
        return "\n".join(lines)

    def _create_compaction_summary(
        self, existing_summary, source_messages, compact_model
    ):
        prompt = self._compaction_prompt(existing_summary, source_messages)
        system_prompt = _with_persistent_memory(
            COMPACTION_SYSTEM_PROMPT,
            self.memory_store,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        temperature = min(float(self.temperature), 0.2)

        if self.api_type == API_TYPE_ANTHROPIC:
            response = self.client.messages.create(
                model=compact_model,
                max_tokens=COMPACTION_MAX_TOKENS,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            self._record_compaction_usage(response, compact_model)
            return self._anthropic_response_text(response)

        if self.api_type == API_TYPE_OLLAMA:
            response = self.client.chat(
                **self._ollama_chat_kwargs(
                    model=compact_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=COMPACTION_MAX_TOKENS,
                    include_reasoning=False,
                )
            )
            self._record_compaction_usage(response, compact_model)
            message = self._get_field(response, "message", {})
            return str(self._get_field(message, "content", "") or "")

        response = self.client.chat.completions.create(
            **self._chat_completion_kwargs(
                model=compact_model,
                messages=messages,
                temperature=temperature,
                max_tokens=COMPACTION_MAX_TOKENS,
                include_reasoning=False,
            )
        )
        self._record_compaction_usage(response, compact_model)
        message = response.choices[0].message
        return _clean_content_text(self._get_field(message, "content", "") or "")

    def _schedule_memory_update_from_compaction(
        self, summary, source_messages, compact_model
    ):
        compacted_messages = self._format_messages_for_compaction(source_messages)
        memory_model = self._memory_model_name()
        self._start_memory_background_task(
            self._update_memory_from_compaction,
            summary,
            compacted_messages,
            memory_model,
        )
        return {"changed": [], "scheduled": True}

    def _update_memory_from_compaction(self, summary, compacted_messages, memory_model):
        try:
            prompt = self.memory_store.build_update_prompt(compacted_messages, summary)
            raw_update = self._create_memory_update(prompt, memory_model)
            update = self._parse_memory_update_with_repair(
                raw_update,
                prompt,
                memory_model,
                source="compaction",
                expected="core_memory/preference_memory",
            )
            if not update:
                return {
                    "changed": [],
                    "error": "memory update model returned no parseable JSON",
                }
            update.pop("episodic_memory", None)
            with self.memory_lock:
                return self.memory_store.apply_update(update)
        except Exception as error:
            return {"changed": [], "error": str(error)}

    def update_session_episodic_memory(self):
        messages = self._last_completed_dialogue_messages()
        if not messages:
            return {"changed": [], "reason": "No completed dialogue turn to remember."}

        formatted_messages = self._format_messages_for_compaction(messages)
        generation = self.session_memory_generation
        self._start_memory_background_task(
            self._update_session_episodic_memory,
            formatted_messages,
            generation,
        )
        return {"changed": [], "scheduled": True}

    def _update_session_episodic_memory(self, formatted_messages, generation):
        with self.session_memory_lock:
            if generation != self.session_memory_generation:
                return {"changed": [], "reason": "Session memory update is stale."}
            try:
                with self.memory_lock:
                    current_heading = self.session_episodic_heading
                    current_entry = self.memory_store.episodic_topic_for_heading(
                        current_heading
                    )
                    if not current_entry:
                        current_entry = self.memory_store.latest_episodic_topic()
                        current_heading = self._episodic_topic_heading(current_entry)
                prompt = self.memory_store.build_session_episodic_prompt(
                    formatted_messages,
                    current_entry,
                )
                memory_model = self._memory_model_name()
                raw_update = self._create_memory_update(prompt, memory_model)
                update = self._parse_memory_update_with_repair(
                    raw_update,
                    prompt,
                    memory_model,
                    source="session_episodic",
                    expected="episodic_memory",
                )
                episodic_memory = ""
                if isinstance(update, dict):
                    episodic_memory = update.get("episodic_memory")
                if not episodic_memory:
                    return {
                        "changed": [],
                        "error": "session episodic memory model returned no episodic_memory",
                    }

                with self.memory_lock:
                    if generation != self.session_memory_generation:
                        return {
                            "changed": [],
                            "reason": "Session memory update is stale.",
                        }
                    result = self.memory_store.upsert_session_episodic_memory(
                        episodic_memory,
                        current_heading=current_heading,
                    )
                    if result.get("heading"):
                        self.session_episodic_heading = result["heading"]
                    return result
            except Exception as error:
                return {"changed": [], "error": str(error)}

    def _start_memory_background_task(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _episodic_topic_heading(topic):
        for line in str(topic or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    def _last_completed_dialogue_messages(self):
        last_assistant_index = None
        for index in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[index].get("role") == "assistant":
                last_assistant_index = index
                break
        if last_assistant_index is None:
            return []

        start_index = None
        for index in range(last_assistant_index - 1, -1, -1):
            if self.conversation_history[index].get("role") == "user":
                start_index = index
                break
        if start_index is None:
            return []

        return self.conversation_history[start_index : last_assistant_index + 1]

    def _parse_memory_update_with_repair(
        self,
        raw_update,
        original_prompt,
        memory_model,
        source,
        expected,
    ):
        update = parse_memory_update_response(raw_update)
        if update:
            return update

        repair_prompt = (
            "The previous memory update response was not valid JSON. "
            "Return only one valid JSON object. Do not include Markdown fences, comments, or explanation.\n"
            f"Expected top-level content: {expected}.\n\n"
            "Original instructions:\n"
            f"{str(original_prompt or '')[:8000]}\n\n"
            "Invalid response:\n"
            f"{str(raw_update or '')[:12000]}"
        )
        repair_response = ""
        try:
            repair_response = self._create_memory_update(repair_prompt, memory_model)
            repaired = parse_memory_update_response(repair_response)
            if repaired:
                return repaired
        except Exception:
            return {}

        return {}

    def _create_memory_update(self, prompt, memory_model):
        system_prompt = _with_persistent_memory(
            MEMORY_UPDATE_SYSTEM_PROMPT,
            self.memory_store,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        temperature = min(float(self.temperature), 0.2)

        if self.api_type == API_TYPE_ANTHROPIC:
            response = self.client.messages.create(
                model=memory_model,
                max_tokens=MEMORY_UPDATE_MAX_TOKENS,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            self._record_auxiliary_usage(
                response,
                kind="memory",
                model=memory_model,
                source="memory_api_usage",
            )
            return self._anthropic_response_text(response)

        if self.api_type == API_TYPE_OLLAMA:
            response = self.client.chat(
                **self._ollama_chat_kwargs(
                    model=memory_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=MEMORY_UPDATE_MAX_TOKENS,
                    include_reasoning=False,
                )
            )
            self._record_auxiliary_usage(
                response,
                kind="memory",
                model=memory_model,
                source="memory_api_usage",
            )
            message = self._get_field(response, "message", {})
            return str(self._get_field(message, "content", "") or "")

        response = self.client.chat.completions.create(
            **self._chat_completion_kwargs(
                model=memory_model,
                messages=messages,
                temperature=temperature,
                max_tokens=MEMORY_UPDATE_MAX_TOKENS,
                include_reasoning=False,
            )
        )
        self._record_auxiliary_usage(
            response,
            kind="memory",
            model=memory_model,
            source="memory_api_usage",
        )
        message = response.choices[0].message
        return _clean_content_text(self._get_field(message, "content", "") or "")

    def generate_session_title(self, user_message):
        source_text = clean_display_text(user_message or "")
        fallback_title = (
            " ".join(source_text.split())[:60] if source_text else "New Chat"
        )
        if not source_text:
            return fallback_title

        prompt = (
            "请根据这条用户消息生成一个对话标题。\n"
            "要求：突出任务主体，避免复述语气词，尽量短。\n\n"
            f"用户消息：\n{source_text}\n\n"
            "只返回标题。"
        )
        memory_model = self._memory_model_name()
        try:
            title = self._create_session_title(prompt, memory_model)
        except Exception as error:
            print_warn(f"Failed to generate session title: {error}")
            return fallback_title
        normalized = self._normalize_session_title(title)
        return normalized or fallback_title

    def _create_session_title(self, prompt, memory_model):
        messages = [
            {"role": "system", "content": SESSION_TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        temperature = min(float(self.temperature), 0.2)

        if self.api_type == API_TYPE_ANTHROPIC:
            response = self.client.messages.create(
                model=memory_model,
                max_tokens=SESSION_TITLE_MAX_TOKENS,
                temperature=temperature,
                system=SESSION_TITLE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            self._record_auxiliary_usage(
                response,
                kind="session_title",
                model=memory_model,
                source="session_title_api_usage",
            )
            return self._anthropic_response_text(response)

        if self.api_type == API_TYPE_OLLAMA:
            response = self.client.chat(
                **self._ollama_chat_kwargs(
                    model=memory_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=SESSION_TITLE_MAX_TOKENS,
                    include_reasoning=False,
                )
            )
            self._record_auxiliary_usage(
                response,
                kind="session_title",
                model=memory_model,
                source="session_title_api_usage",
            )
            message = self._get_field(response, "message", {})
            return str(self._get_field(message, "content", "") or "")

        response = self.client.chat.completions.create(
            **self._chat_completion_kwargs(
                model=memory_model,
                messages=messages,
                temperature=temperature,
                max_tokens=SESSION_TITLE_MAX_TOKENS,
                include_reasoning=False,
            )
        )
        self._record_auxiliary_usage(
            response,
            kind="session_title",
            model=memory_model,
            source="session_title_api_usage",
        )
        message = response.choices[0].message
        return _clean_content_text(self._get_field(message, "content", "") or "")

    @staticmethod
    def _normalize_session_title(title):
        text = clean_display_text(title or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = lines[0] if lines else ""
        text = re.sub(r"^(标题|Title)\s*[:：-]\s*", "", text, flags=re.IGNORECASE)
        text = text.strip(" \"'`[](){}<>:：，,。.!！？；;")
        text = " ".join(text.split())
        return text[:60] if text else ""

    def _print_memory_update_result(self, memory_update):
        if not memory_update:
            return
        changed = memory_update.get("changed") or []
        if changed:
            print_info("Persistent memory updated: " + ", ".join(changed) + ".")
        elif memory_update.get("error"):
            print_warn(f"Persistent memory update failed: {memory_update.get('error')}")

    def _record_preference_signal(self, user_message):
        try:
            self.memory_store.record_preference_signal(user_message)
        except Exception as error:
            print_warn(f"Failed to record preference memory: {error}")

    def _record_hot_history(self, history_start):
        try:
            history_start = max(0, int(history_start or 0))
            extra = {
                "model": self.model,
                "api_type": self.api_type,
                "agent_mode": self.agent_mode,
            }
            for message in self.conversation_history[history_start:]:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "")
                if not role:
                    continue
                message_extra = dict(extra)
                message_extra["message"] = self._plain_data(message)
                self.memory_store.append_history(
                    role,
                    message.get("content", ""),
                    extra=message_extra,
                )
        except Exception as error:
            print_warn(f"Failed to record hot history: {error}")

    def _compaction_prompt(self, existing_summary, source_messages):
        existing_summary = str(existing_summary or "").strip()
        compacted_messages = self._format_messages_for_compaction(source_messages)
        if not compacted_messages:
            compacted_messages = "(No additional messages.)"
        if not existing_summary:
            existing_summary = "(No existing summary.)"

        return (
            "为后续对话更新压缩摘要。遵循持久记忆和用户偏好，尤其语言偏好。只返回摘要。\n\n"
            "已有摘要：\n"
            f"{existing_summary}\n\n"
            "需要合并的消息：\n"
            f"{compacted_messages}\n\n"
            "只返回更新后的压缩摘要。"
        )

    def _format_messages_for_compaction(self, messages):
        formatted = []
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                continue
            role = message.get("role", "unknown")
            content = self._message_content_for_compaction(message)
            formatted.append(f"[{index}] {role}:\n{content}")
        return "\n\n".join(formatted)

    def _message_content_for_compaction(self, message):
        if not isinstance(message, dict):
            return "(empty)"
        message = self._effective_history_message(message)
        parts = []
        content = message.get("content", "")
        if content:
            parts.append(self._plain_text_for_compaction(content))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            parts.append(
                "tool_calls: "
                + json.dumps(self._plain_data(tool_calls), ensure_ascii=False)
            )
        tool_name = message.get("tool_name") or message.get("name")
        if tool_name:
            parts.append(f"tool_name: {tool_name}")
        return "\n".join(parts).strip() or "(empty)"

    def _plain_text_for_compaction(self, content):
        if isinstance(content, str):
            return content
        if isinstance(content, (list, dict)):
            try:
                return json.dumps(content, ensure_ascii=False, default=str)
            except TypeError:
                return clean_display_text(content)
        return str(content or "")

    def _split_existing_compaction_summary(self, messages):
        if not messages:
            return "", []
        first_message = messages[0]
        if not isinstance(first_message, dict):
            return "", [message for message in messages if isinstance(message, dict)]
        content = str(first_message.get("content", "") or "")
        if first_message.get("role") == "user" and content.startswith(
            COMPACTION_SUMMARY_PREFIX
        ):
            summary = content[len(COMPACTION_SUMMARY_PREFIX) :].strip()
            return summary, [
                message for message in messages[1:] if isinstance(message, dict)
            ]
        return "", [message for message in messages if isinstance(message, dict)]

    def _fold_leading_tool_results_into_source(self, source_messages, recent_messages):
        source_messages = list(source_messages)
        recent_messages = list(recent_messages)
        while recent_messages and self._message_has_tool_result(recent_messages[0]):
            source_messages.append(recent_messages.pop(0))
        return source_messages, recent_messages

    def _message_has_tool_result(self, message):
        if not isinstance(message, dict):
            return False
        if message.get("role") == "tool":
            return True
        content = message.get("content")
        if not isinstance(content, list):
            return False
        return any(self._get_field(block, "type") == "tool_result" for block in content)

    @staticmethod
    def _compaction_summary_message(summary):
        return f"{COMPACTION_SUMMARY_PREFIX}\n{summary.strip()}"

    def _sanitize_orphan_tool_results_in_history(self):
        available_tool_ids = set()
        cleaned = []
        removed_count = 0

        for message in self.conversation_history:
            filtered_message, removed, consumed_tool_ids = (
                self._filter_orphan_tool_results(
                    message,
                    available_tool_ids,
                )
            )
            removed_count += removed
            if filtered_message is None:
                continue

            cleaned.append(filtered_message)
            available_tool_ids.update(self._message_tool_use_ids(filtered_message))
            for tool_id in consumed_tool_ids:
                available_tool_ids.discard(tool_id)

        if removed_count:
            self.conversation_history = cleaned
        return removed_count

    def _filter_orphan_tool_results(self, message, available_tool_ids):
        role = message.get("role")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if tool_call_id and tool_call_id not in available_tool_ids:
                return None, 1, set()
            return message, 0, {tool_call_id} if tool_call_id else set()

        content = message.get("content")
        if not isinstance(content, list):
            return message, 0, set()

        filtered_content = []
        removed_count = 0
        consumed_tool_ids = set()
        for block in content:
            if self._get_field(block, "type") != "tool_result":
                filtered_content.append(block)
                continue

            tool_use_id = str(self._get_field(block, "tool_use_id", "") or "")
            if tool_use_id and tool_use_id not in available_tool_ids:
                removed_count += 1
                continue

            filtered_content.append(block)
            if tool_use_id:
                consumed_tool_ids.add(tool_use_id)

        if not removed_count:
            return message, 0, consumed_tool_ids
        if not filtered_content:
            return None, removed_count, consumed_tool_ids

        filtered_message = dict(message)
        filtered_message["content"] = filtered_content
        return filtered_message, removed_count, consumed_tool_ids

    def _message_tool_use_ids(self, message):
        tool_ids = []
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if self._get_field(block, "type") == "tool_use":
                    tool_id = str(self._get_field(block, "id", "") or "")
                    if tool_id:
                        tool_ids.append(tool_id)

        for tool_call in message.get("tool_calls") or []:
            tool_id = str(self._get_field(tool_call, "id", "") or "")
            if tool_id:
                tool_ids.append(tool_id)
        return tool_ids

    def _compact_agent_history(self, history_start, response):
        if history_start >= len(self.conversation_history):
            return

        user_message = self.conversation_history[history_start]
        if user_message.get("role") != "user":
            return

        assistant_text = response.get("response", "") or ""
        run_summary = self.agent_tools.session_summary()
        history_text = assistant_text
        if run_summary:
            visible_run_summary = self.agent_tools.finalize_internal_output(
                "session_summary", run_summary
            )
            history_text = (
                f"{assistant_text}\n\n[Agent run summary]\n{visible_run_summary}".strip()
            )

        self.conversation_history = self.conversation_history[:history_start] + [
            user_message,
            {"role": "assistant", "content": history_text},
        ]

    def _append_agent_final_check_if_needed(self):
        if self.agent_plan_rejected and self.agent_tools.plan_mode:
            return False
        if self.agent_tools.has_incomplete_todos():
            signature = self._agent_plan_check_signature()
            if self.agent_plan_check_signature == signature:
                self.agent_plan_check_exit_note = self._agent_plan_check_exit_note()
                print_warn("Agent plan check stopped to avoid an automatic loop.")
                return False
            self.agent_plan_check_signature = signature
            budget_summary = self.agent_tools.todo_budget_summary()
            quality_report = self.agent_tools.todo_quality_report()
            extra_guidance = ""
            if budget_summary:
                extra_guidance += f"\n\n{budget_summary}"
            if quality_report:
                extra_guidance += f"\n\n{quality_report}"
            self.conversation_history.append({
                "role": "user",
                "content": (
                    "Automatic task todo list check for this local agent run:\n\n"
                    f"{self.agent_tools.todo_incomplete_summary()}\n\n"
                    "There are still non-completed todo items. Continue using tools "
                    "to finish the remaining work. Respect depends_on before starting later "
                    "items, and update the todo list as each item changes. Only provide the "
                    "final response after every todo item is completed."
                    f"{extra_guidance}"
                ),
            })
            return True

        needs_verification = (
            self.agent_tools.session_has_changes()
            or self.agent_tools.has_unverified_completed_todos()
        )
        if self.agent_final_check_done or not needs_verification:
            return False

        self.agent_final_check_done = True
        check_result = self.agent_tools.final_check()
        verification_passed = self.agent_tools.final_check_passed(check_result)
        self.agent_tools.apply_todo_final_verification(
            verification_passed,
            check_result,
        )
        visible_check_result = self.agent_tools.finalize_internal_output(
            "final_check", check_result
        )

        if verification_passed:
            verification_instruction = (
                "Automatic final verification passed. Completed todo items with completion criteria "
                "are now tied to this verification result. "
            )
        else:
            verification_instruction = (
                "Automatic final verification failed, and the todo list now includes a failed "
                "automatic verification item. Continue using tools to fix the failure and update "
                "the todo list; if you cannot proceed, mark the relevant todo item blocked with a clear reason. "
            )
        self.conversation_history.append({
            "role": "user",
            "content": (
                "Automatic final verification for this local agent run:\n\n"
                f"{visible_check_result}\n\n"
                f"{verification_instruction}"
                "If the verification output shows a problem, continue using tools to fix it. "
                "Do not attribute pre-existing workspace changes to this run unless they are listed "
                "as agent-edited files or agent mutating commands. "
                "If the task is complete, provide the final response with a concise summary "
                "and mention what verification was performed."
            ),
        })
        return True

    def _agent_plan_check_signature(self):
        return (
            self.agent_tools.todo_revision(),
            self.agent_tools.session_change_count(),
            self.agent_tool_calls,
        )

    def _agent_plan_check_exit_note(self):
        summary = self.agent_tools.todo_incomplete_summary()
        return (
            "OmniAgent stopped the automatic plan check to avoid a repeat loop. "
            "The model returned a final response without using tools after the same "
            "plan check had already been sent, and the plan still has non-completed "
            "items:\n\n"
            f"{summary}"
        )

    def _agent_response_with_plan_exit_note(self, response):
        note = self.agent_plan_check_exit_note
        if not note:
            return response
        response = str(response or "").rstrip()
        if not response:
            return note
        return f"{response}\n\n{note}"

    def _execute_agent_tool(self, name, tool_input):
        if name != SUBMIT_PLAN_TOOL_NAME:
            self.agent_tool_calls += 1
        if name == DISPATCH_SUBAGENT_TOOL_NAME:
            self._subagent_dispatch_display = None
            with self._agent_tools_execution_lock:
                self.agent_tools.set_budget_context(
                    self.agent_tool_call_limit,
                    self.agent_tool_calls,
                )
                change_count_before = self.agent_tools.session_change_count()
                todo_revision_before = self.agent_tools.todo_revision()
                self.agent_tools.consume_display_payload()
                scope_error = self._write_scope_violation(
                    name, tool_input, {"kind": "lead", "name": "Lead"}
                )
            if scope_error:
                tool_result = _error_text(scope_error)
                self._last_tool_display = None
            else:
                # Do not hold the shared tool lock while subagents wait on model calls.
                # Their individual tool executions still acquire the lock briefly.
                tool_result = self.agent_tools.execute(name, tool_input)
            with self._agent_tools_execution_lock:
                if self.agent_tools.consume_output_separator():
                    self.agent_output_needs_separator = True
                if (
                    self.agent_tools.session_change_count() > change_count_before
                    or self.agent_tools.todo_revision() != todo_revision_before
                ):
                    self.agent_final_check_done = False
                tool_display = self.agent_tools.consume_display_payload()
                self._last_tool_display = (
                    self._subagent_dispatch_display or tool_display
                )
                self._subagent_dispatch_display = None
        else:
            with self._agent_tools_execution_lock:
                self.agent_tools.set_budget_context(
                    self.agent_tool_call_limit,
                    self.agent_tool_calls,
                )
                change_count_before = self.agent_tools.session_change_count()
                todo_revision_before = self.agent_tools.todo_revision()
                self.agent_tools.consume_display_payload()
                scope_error = self._write_scope_violation(
                    name, tool_input, {"kind": "lead", "name": "Lead"}
                )
                if scope_error:
                    tool_result = _error_text(scope_error)
                    self._last_tool_display = None
                else:
                    tool_result = self.agent_tools.execute(name, tool_input)
                if self.agent_tools.consume_output_separator():
                    self.agent_output_needs_separator = True
                if (
                    self.agent_tools.session_change_count() > change_count_before
                    or self.agent_tools.todo_revision() != todo_revision_before
                ):
                    self.agent_final_check_done = False
                self._last_tool_display = self.agent_tools.consume_display_payload()
        if name == SUBMIT_PLAN_TOOL_NAME:
            decision = self.agent_tools.consume_submitted_plan_approval()
            if decision is True:
                self.agent_plan_rejected = False
                self.agent_round_limit = min(
                    self.max_agent_rounds * 2,
                    self.agent_round_index + self.max_agent_rounds,
                )
                self.agent_tool_call_limit = (
                    self.agent_tool_calls + self.max_agent_tool_calls
                )
                self.set_plan_mode(False, notify=True)
            elif decision is False:
                self.agent_plan_rejected = True
                self.agent_round_limit = min(
                    self.max_agent_rounds * 2,
                    max(self.agent_round_limit, self.agent_round_index + 1),
                )
        if tool_result_is_error(name, tool_result, self._last_tool_display):
            self._last_tool_display = self._tool_display_for_result(
                name,
                tool_input,
                tool_result,
                existing_display=self._last_tool_display,
            )
        else:
            self._track_explored_tool(name, tool_input)
        # Tool-specific OpenCode-style output limits are applied by AgentTools.
        # The shared context budget remains the final history-level compaction layer.
        return str(tool_result or "")

    def _consume_last_tool_display(self):
        display = self._last_tool_display
        self._last_tool_display = None
        return display

    def _tool_display_for_result(
        self, name, tool_input, tool_result, existing_display=None
    ):
        if not isinstance(tool_input, dict):
            tool_input = {}
        if tool_result_is_error(name, tool_result, existing_display):
            if tool_display_is_error(existing_display):
                return existing_display
            display = build_tool_error_display(name, tool_input, tool_result)
            add_tool_error_entry(display)
            return display
        if existing_display is not None:
            return existing_display
        if name == "web_fetch":
            url = str(tool_input.get("url") or "").strip()
            if url:
                return {
                    "kind": "web_fetch",
                    "url": url,
                }
        if name == "web_search":
            query = str(tool_input.get("query") or "").strip()
            if query:
                return {
                    "kind": "web_search",
                    "content": query,
                }
        return None

    def _track_explored_tool(self, name, tool_input):
        if name not in _EXPLORED_TOOLS:
            return
        description = _format_explored_entry(name, tool_input)
        if description:
            add_explored_entry(name, description)

    def _dispatch_subagent(self, *, tasks):
        if not isinstance(tasks, list) or not tasks:
            return _error_text("dispatch_subagent requires at least one task.")
        if len(tasks) > MAX_SUBAGENT_TASKS_PER_BATCH:
            return _error_text(
                f"dispatch_subagent accepts at most {MAX_SUBAGENT_TASKS_PER_BATCH} tasks per batch."
            )

        prepared = []
        for index, item in enumerate(tasks, start=1):
            if not isinstance(item, dict):
                return _error_text(f"Subagent task {index} must be an object.")
            item_agent_type = str(item.get("agent_type") or "").strip()
            item_task = str(item.get("task") or "").strip()
            item_priority = item.get("priority", 1)
            if (
                isinstance(item_priority, bool)
                or not isinstance(item_priority, int)
                or item_priority < 1
            ):
                return _error_text(
                    f"Subagent task {index} priority must be a positive integer."
                )
            spec = self.agent_tools.subagent_registry.get(item_agent_type)
            if spec is None:
                return _error_text(
                    "Unknown subagent "
                    f"{item_agent_type!r}. Available: "
                    + ", ".join(self.agent_tools.subagent_registry.names())
                )
            if (
                self.agent_tools.plan_mode
                and spec.name not in PLAN_SUBAGENT_TYPES
            ):
                return _error_text(
                    "Plan mode only allows reader and researcher subagents. "
                    f"Requested: {item_agent_type!r}."
                )
            if not item_task:
                return _error_text(f"Subagent task {index} is empty.")
            item_purpose = str(item.get("purpose") or "").strip()
            subagent_task = compose_subagent_task(
                item_task,
                expected_output=str(item.get("expected_output") or "").strip(),
                evidence_required=str(item.get("evidence_required") or "").strip(),
                scope_limit=str(item.get("scope_limit") or "").strip(),
            )
            prepared.append({
                "index": index,
                "spec": spec,
                "effective_spec": self._effective_subagent_spec(spec),
                "task": item_task,
                "subagent_task": subagent_task,
                "purpose": item_purpose,
                "label": _single_line(item_purpose or item_task, 120),
                "priority": item_priority,
                "entry_id": uuid.uuid4().hex,
            })

        priority_groups = {}
        for item in prepared:
            priority_groups.setdefault(item["priority"], []).append(item)

        self._before_agent_visible_output()
        for item in prepared:
            start_subagent_entry(item["entry_id"], item["spec"].name)

        ordered_priorities = sorted(priority_groups)
        for priority in ordered_priorities[1:]:
            for item in priority_groups[priority]:
                append_subagent_event(item["entry_id"], {
                    "kind": "message",
                    "role": "status",
                    "content": (
                        f"Waiting for priority group {priority}; "
                        "earlier priority groups run first."
                    ),
                })

        completed_by_index = {}
        for group_position, priority in enumerate(ordered_priorities):
            if group_position > 0:
                for item in priority_groups[priority]:
                    append_subagent_event(item["entry_id"], {
                        "kind": "message",
                        "role": "status",
                        "content": f"Priority group {priority} started.",
                    })
            group_results = self._run_subagent_priority_group(
                priority_groups[priority]
            )
            for item in group_results:
                completed_by_index[item["index"]] = item
        completed = [completed_by_index[item["index"]] for item in prepared]

        displays = [
            {
                "kind": "subagent",
                "agent_type": item["spec"].name,
                "purpose": item["label"],
                "transcript": item["transcript"],
            }
            for item in completed
        ]
        self._subagent_dispatch_display = (
            displays[0]
            if len(displays) == 1
            else {"kind": "subagent_batch", "items": displays}
        )
        if len(completed) == 1:
            return completed[0]["result"]

        failure_count = sum(
            str(item["result"] or "").startswith("ERROR:") for item in completed
        )
        group_count = len(priority_groups)
        status = (
            f"Completed {len(completed)} subagent tasks across {group_count} priority "
            f"group{'s' if group_count != 1 else ''} with parallel reads and serialized writes"
            + (f" with {failure_count} failure(s)." if failure_count else ".")
        )
        sections = [status]
        for item in completed:
            sections.append(
                f"[{item['index']}] {item['spec'].name} - {item['label']}\n"
                f"{item['result']}"
            )
        return "\n\n".join(sections)

    def _run_subagent_priority_group(self, items):
        read_only_items = [
            item for item in items if not subagent_has_write_tools(item["spec"])
        ]
        write_items = [
            item for item in items if subagent_has_write_tools(item["spec"])
        ]

        if len(write_items) > 1:
            for queue_position, item in enumerate(write_items[1:], start=2):
                append_subagent_event(item["entry_id"], {
                    "kind": "message",
                    "role": "status",
                    "content": (
                        "Queued for serialized file editing "
                        f"({queue_position}/{len(write_items)})."
                    ),
                })

        if len(items) == 1:
            return [self._run_subagent_dispatch(items[0])]

        completed_by_index = {}
        worker_count = len(read_only_items) + (1 if write_items else 0)
        with ThreadPoolExecutor(
            max_workers=min(worker_count, MAX_SUBAGENT_WORKERS),
            thread_name_prefix="omni-subagent",
        ) as executor:
            futures = {
                executor.submit(self._run_subagent_dispatch, item): ("single", [item])
                for item in read_only_items
            }
            if write_items:
                futures[
                    executor.submit(self._run_subagent_write_queue, write_items)
                ] = ("writers", write_items)

            for future in as_completed(futures):
                future_kind, future_items = futures[future]
                try:
                    future_result = future.result()
                    if future_kind == "writers":
                        for item in future_result:
                            completed_by_index[item["index"]] = item
                    else:
                        completed_by_index[future_items[0]["index"]] = future_result
                except Exception as error:
                    for item in future_items:
                        completed_by_index[item["index"]] = {
                            **item,
                            "result": _error_text(
                                f"Subagent '{item['spec'].name}' failed: {error}"
                            ),
                            "transcript": [],
                        }
        return [completed_by_index[item["index"]] for item in items]

    def _run_subagent_write_queue(self, items):
        completed = []
        total = len(items)
        for queue_position, item in enumerate(items, start=1):
            if queue_position > 1:
                append_subagent_event(item["entry_id"], {
                    "kind": "message",
                    "role": "status",
                    "content": (
                        "Write slot acquired; starting queued task "
                        f"({queue_position}/{total})."
                    ),
                })
            completed.append(self._run_subagent_dispatch(item))
        return completed

    def _run_subagent_dispatch(self, item):
        spec = item["spec"]
        runner = SubagentRunner(
            parent_agent=self,
            spec=item["effective_spec"],
            tool_schemas=self._subagent_tool_schemas(spec),
            execute_tool=lambda name, args: self._execute_subagent_tool(
                spec, name, args
            ),
            event_callback=lambda event: append_subagent_event(item["entry_id"], event),
        )
        try:
            result = runner.run(item["subagent_task"])
        except Exception as error:
            result = _error_text(f"Subagent '{spec.name}' failed: {error}")
        return {
            **item,
            "result": result,
            "transcript": runner.transcript,
        }

    def _execute_subagent_tool(self, spec, name, tool_input):
        return self._execute_delegated_tool(
            name,
            tool_input,
            actor={"kind": "subagent", "name": spec.name},
        )

    def _execute_delegated_tool(
        self, name, tool_input, actor=None, stop_requested_callback=None
    ):
        with self._agent_tools_execution_lock:
            previous = self.agent_tools.suppress_visible_output
            previous_todos_enabled = self.agent_tools.todos_enabled
            previous_stop_requested = self.agent_tools.stop_requested_callback
            self.agent_tools.suppress_visible_output = True
            self.agent_tools.todos_enabled = False
            if stop_requested_callback is not None:
                self.agent_tools.set_stop_requested_callback(stop_requested_callback)
            try:
                self.agent_tools.consume_display_payload()
                scope_error = self._write_scope_violation(
                    name, tool_input, actor or {"kind": "delegated", "name": "Worker"}
                )
                if scope_error:
                    return _error_text(scope_error), None
                result = self.agent_tools.execute(
                    name, tool_input, allow_subagent_hint=False
                )
                display = self.agent_tools.consume_display_payload()
                self.agent_tools.consume_output_separator()
                return result, display
            finally:
                self.agent_tools.set_stop_requested_callback(previous_stop_requested)
                self.agent_tools.todos_enabled = previous_todos_enabled
                self.agent_tools.suppress_visible_output = previous

    def _execute_teammate(
        self,
        *,
        spec,
        task,
        purpose="",
        expected_output="",
        evidence_required="",
        scope_limit="",
        write_scope=(),
    ):
        if self.team_store is None:
            return {"result": _error_text("Agent team is disabled."), "display": None}
        resolved_name = self.team_store.resolve_name(spec.name)
        try:
            write_scope = self.team_store.normalize_write_scope(write_scope)
        except ValueError as error:
            return {"result": _error_text(str(error)), "display": None}
        if teammate_has_write_tools(spec) and not write_scope:
            return {
                "result": _error_text(
                    f"Teammate '{spec.name}' has file-writing tools and requires a non-empty write_scope."
                ),
                "display": None,
            }
        with self._team_tasks_lock:
            existing = next(
                (
                    record
                    for record in self._team_tasks.values()
                    if record.get("teammate_name") == resolved_name
                    and record.get("status") in ACTIVE_TEAMMATE_STATUSES
                ),
                None,
            )
            if existing is not None:
                return {
                    "result": _error_text(
                        f"Teammate '{spec.name}' already has an active task "
                        f"({existing.get('task_id', '')})."
                    ),
                    "display": None,
                }

        teammate_task = compose_teammate_task(
            task,
            expected_output=expected_output,
            evidence_required=evidence_required,
            scope_limit=scope_limit,
            write_scope=write_scope,
        )
        task_id = uuid.uuid4().hex
        label = _single_line(purpose or task, 120)
        stop_event = threading.Event()
        display = {
            "kind": "team_run",
            "task_id": task_id,
            "teammate_name": spec.name,
            "role": spec.role,
            "purpose": label,
            "status": "running",
            "result": "",
            "transcript": [],
            "write_scope": list(write_scope),
        }
        record = {
            "task_id": task_id,
            "teammate_name": resolved_name,
            "display_name": spec.name,
            "role": spec.role,
            "purpose": label,
            "status": "starting",
            "write_scope": tuple(write_scope),
            "report_count": 0,
            "prelude_transcript": [],
            "stop_event": stop_event,
            "display": display,
            "thread": None,
        }
        try:
            with self._team_tasks_lock:
                task_state = self.team_store.start_task(
                    spec.name,
                    task_id=task_id,
                    task=label,
                    write_scope=write_scope,
                )
                initial_status = str(task_state.get("status") or "running")
                record["status"] = initial_status
                display["status"] = initial_status
                self._team_tasks[task_id] = record
        except ValueError as error:
            return {"result": _error_text(str(error)), "display": None}
        self._before_agent_visible_output()
        start_team_entry(
            task_id, spec.name, spec.role, label, task_id, status=initial_status
        )
        if initial_status == "waiting":
            waiting_for = task_state.get("waiting_for") or {}
            owner = str(waiting_for.get("name") or "another teammate")
            owner_role = str(waiting_for.get("role") or "writer")
            owner_scope = ", ".join(waiting_for.get("write_scope") or ())
            wait_event = {
                "kind": "message",
                "role": "status",
                "content": (
                    f"Waiting for write scope held by {owner} ({owner_role}): "
                    f"{owner_scope}."
                ),
            }
            record["prelude_transcript"].append(dict(wait_event))
            display["transcript"].append(dict(wait_event))
            append_team_event(task_id, wait_event)
        worker = threading.Thread(
            target=(
                self._run_waiting_teammate_task
                if initial_status == "waiting"
                else self._run_teammate_task
            ),
            args=(record, spec, teammate_task),
            name=f"omniagent-team-{resolved_name}-{task_id[:8]}",
            daemon=True,
        )
        record["thread"] = worker
        try:
            worker.start()
        except Exception as error:
            error_text = f"Unable to start teammate '{spec.name}': {error}"
            record["status"] = "failed"
            record["result"] = _error_text(error_text)
            display["status"] = "failed"
            display["result"] = record["result"]
            try:
                self.team_store.update_status(
                    spec.name,
                    "failed",
                    task_id=task_id,
                    error=error_text,
                    write_scope=[],
                )
            except Exception:
                pass
            finish_team_entry(task_id, "failed", record["result"])
            return {"result": record["result"], "display": display}
        if initial_status == "waiting":
            waiting_for = task_state.get("waiting_for") or {}
            owner = str(waiting_for.get("name") or "another teammate")
            return {
                "result": (
                    f"Teammate '{spec.name}' queued background task {task_id}; "
                    f"waiting for write scope held by {owner}. "
                    "It will start automatically when the scope is released."
                ),
                "display": display,
            }
        return {
            "result": (
                f"Teammate '{spec.name}' started background task {task_id}. "
                "Use list_teammates to inspect status, send_message or broadcast to "
                "provide follow-up guidance, and read_inbox with wait_seconds to collect results."
            ),
            "display": display,
        }

    def _run_teammate_task(self, record, spec, teammate_task):
        task_id = str(record.get("task_id") or "")

        def on_event(event):
            if not isinstance(event, dict):
                return
            with self._team_tasks_lock:
                display = record.get("display") or {}
                display.setdefault("transcript", []).append(dict(event))
            append_team_event(task_id, event)

        runner = None
        result = ""
        status = "completed"
        error_text = ""
        transcript = []
        try:
            runtime_rules = [
                "You are a teammate, not the Lead. Do not use Lead-only lifecycle tools.",
                "Use report_to_lead only for important progress, blockers, findings, or questions.",
            ]
            write_scope = tuple(record.get("write_scope") or ())
            if teammate_has_write_tools(spec):
                runtime_rules.append(
                    "Direct file writes and any mutations through bash must stay inside the assigned "
                    f"write_scope: {', '.join(write_scope)}."
                )
            effective_spec = replace(
                spec,
                system_prompt=(
                    f"{spec.system_prompt.rstrip()}\n\nRuntime team contract:\n- "
                    + "\n- ".join(runtime_rules)
                ),
            )
            runner = TeamRunner(
                parent_agent=self,
                spec=effective_spec,
                tool_schemas=self._teammate_tool_schemas(spec),
                execute_tool=lambda name, args: self._execute_teammate_tool(
                    record, spec, name, args
                ),
                    team_store=self.team_store,
                api_type=self.api_type,
                event_callback=on_event,
                stop_event=record.get("stop_event"),
            )
            result = runner.run(teammate_task)
            if record.get("stop_event").is_set():
                status = "cancelled"
            elif str(result or "").startswith("ERROR:"):
                status = "failed"
                error_text = str(result)
        except Exception as error:
            status = "failed"
            error_text = format_worker_request_error(
                f"Teammate '{spec.name}'", error
            )
            result = _error_text(error_text)
        finally:
            if runner is not None:
                transcript = list(runner.transcript)

        self._complete_teammate_task(
            record,
            spec,
            status=status,
            result=str(result or ""),
            error_text=error_text,
            transcript=transcript,
        )

    def _run_waiting_teammate_task(self, record, spec, teammate_task):
        task_id = str(record.get("task_id") or "")
        stop_event = record.get("stop_event")
        cancelled_result = "Task cancelled while waiting for write_scope ownership."
        while stop_event is None or not stop_event.is_set():
            try:
                with self._agent_tools_execution_lock:
                    activated = self.team_store.try_activate_task(
                        spec.name, task_id=task_id
                    )
                if activated:
                    activation_event = {
                        "kind": "message",
                        "role": "status",
                        "content": "Write scope acquired; starting queued task.",
                    }
                    with self._team_tasks_lock:
                        record["status"] = "running"
                        display = record.get("display") or {}
                        display["status"] = "running"
                        record.setdefault("prelude_transcript", []).append(
                            dict(activation_event)
                        )
                        display.setdefault("transcript", []).append(
                            dict(activation_event)
                        )
                    update_team_entry_status(task_id, "running")
                    append_team_event(task_id, activation_event)
                    if stop_event is not None and stop_event.is_set():
                        self._complete_teammate_task(
                            record,
                            spec,
                            status="cancelled",
                            result=cancelled_result,
                            error_text=cancelled_result,
                            transcript=[],
                        )
                        return
                    self._run_teammate_task(record, spec, teammate_task)
                    return
            except Exception as error:
                error_text = format_worker_request_error(
                    f"Teammate '{spec.name}'", error
                )
                self._complete_teammate_task(
                    record,
                    spec,
                    status="failed",
                    result=_error_text(error_text),
                    error_text=error_text,
                    transcript=[],
                )
                return
            if stop_event is None:
                time.sleep(0.1)
            else:
                stop_event.wait(0.1)
        self._complete_teammate_task(
            record,
            spec,
            status="cancelled",
            result=cancelled_result,
            error_text=cancelled_result,
            transcript=[],
        )

    def _complete_teammate_task(
        self,
        record,
        spec,
        *,
        status,
        result,
        error_text="",
        transcript=None,
    ):
        task_id = str(record.get("task_id") or "")
        transcript = list(transcript or [])
        try:
            self.team_store.save_thread(spec.name, transcript)
        except Exception:
            pass
        with self._team_tasks_lock:
            try:
                if self.team_store.is_active(spec.name):
                    self.team_store.update_status(
                        spec.name,
                        status,
                        task_count=1,
                        task_id=task_id,
                        error=error_text if status in {"failed", "cancelled"} else None,
                        write_scope=[],
                    )
            except Exception:
                pass
            record["status"] = status
            record["result"] = str(result or "")
            display = record.get("display") or {}
            display["status"] = status
            display["result"] = str(result or "")
            display["transcript"] = [
                *list(record.get("prelude_transcript") or []),
                *transcript,
            ]
        try:
            self.team_store.send_message(
                spec.name,
                "lead",
                str(result or ""),
                kind="task_result",
                task_id=task_id,
                status=status,
            )
        except Exception:
            pass
        finish_team_entry(task_id, status, str(result or ""))

    def _execute_teammate_tool(self, record, spec, name, tool_input):
        if name == TEAMMATE_REPORT_TOOL_NAME:
            return self._report_teammate_to_lead(record, spec, tool_input)
        return self._execute_delegated_tool(
            name,
            tool_input,
            actor={
                "kind": "teammate",
                "name": spec.name,
                "role": spec.role,
                "task_id": str(record.get("task_id") or ""),
                "write_scope": tuple(record.get("write_scope") or ()),
            },
            stop_requested_callback=lambda: bool(
                record.get("stop_event") and record.get("stop_event").is_set()
            ),
        )

    def _report_teammate_to_lead(self, record, spec, tool_input):
        if not isinstance(tool_input, dict):
            return _error_text("report_to_lead input must be an object."), None
        report_kind = str(tool_input.get("kind") or "").strip().lower()
        message = str(tool_input.get("message") or "").strip()
        if report_kind not in TEAMMATE_REPORT_KINDS:
            return (
                _error_text(
                    "report_to_lead kind must be one of: "
                    + ", ".join(sorted(TEAMMATE_REPORT_KINDS))
                ),
                None,
            )
        if not message:
            return _error_text("report_to_lead message cannot be empty."), None
        with self._team_tasks_lock:
            report_count = int(record.get("report_count") or 0)
            if report_count >= MAX_TEAMMATE_REPORTS_PER_TASK:
                return (
                    _error_text(
                        f"report_to_lead limit reached ({MAX_TEAMMATE_REPORTS_PER_TASK} per task)."
                    ),
                    None,
                )
            record["report_count"] = report_count + 1
        task_id = str(record.get("task_id") or "")
        status = str(record.get("status") or "running")
        try:
            self.team_store.send_message(
                spec.name,
                "lead",
                message,
                kind="team_report",
                task_id=task_id,
                status=status,
                report_kind=report_kind,
            )
        except Exception as error:
            with self._team_tasks_lock:
                record["report_count"] = max(0, int(record.get("report_count") or 1) - 1)
            return _error_text(f"Unable to report to Lead: {error}"), None
        summary = f"Reported {report_kind} to Lead"
        return (
            summary + ".",
            {
                "kind": "team_report",
                "report_kind": report_kind,
                "summary": summary,
                "message": message,
            },
        )

    def _write_scope_violation(self, name, tool_input, actor):
        if name not in WRITE_TOOL_NAMES or self.team_store is None:
            return ""
        if not isinstance(tool_input, dict):
            return "Write tool input must be an object."
        file_path = str(tool_input.get("file_path") or "").strip()
        if not file_path:
            return "Write tool requires file_path."
        try:
            relative_path = self.team_store.workspace_relative_path(file_path)
        except ValueError as error:
            return str(error)
        actor = dict(actor or {})
        task_id = str(actor.get("task_id") or "")
        if actor.get("kind") == "teammate":
            scopes = tuple(actor.get("write_scope") or ())
            if not scopes or not any(
                path_matches_write_scope(relative_path, scope) for scope in scopes
            ):
                scope_text = ", ".join(scopes) or "(none)"
                return (
                    f"{actor.get('name') or 'Teammate'} cannot modify {relative_path}; "
                    f"assigned write_scope: {scope_text}."
                )
        owner = self.team_store.find_write_owner_for_path(
            relative_path, exclude_task_id=task_id
        )
        if owner is None:
            return ""
        scope_text = ", ".join(owner.get("write_scope") or ())
        return (
            f"Cannot modify {relative_path}; active owner "
            f"{owner.get('name') or 'Teammate'} ({owner.get('role') or 'writer'}) "
            f"holds write_scope: {scope_text}."
        )

    def _shutdown_teammate_task(self, teammate_name):
        if self.team_store is None:
            return ""
        resolved = self.team_store.resolve_name(teammate_name)
        cancelled = []
        waiting_cancelled = False
        with self._team_tasks_lock:
            for task_id, record in self._team_tasks.items():
                if (
                    record.get("teammate_name") == resolved
                    and record.get("status") in ACTIVE_TEAMMATE_STATUSES
                ):
                    was_waiting = record.get("status") == "waiting"
                    if was_waiting:
                        waiting_cancelled = True
                    stop_event = record.get("stop_event")
                    if stop_event is not None:
                        stop_event.set()
                    record["status"] = "cancelling"
                    display = record.get("display") or {}
                    display["status"] = "cancelling"
                    cancelled.append(task_id)
                    finish_team_entry(task_id, "cancelling", "")
            if cancelled:
                self.team_store.update_status(
                    teammate_name,
                    "cancelling",
                    task_id=cancelled[-1],
                    write_scope=[] if waiting_cancelled else None,
                )
        if cancelled:
            return "Cancellation requested for task(s): " + ", ".join(cancelled)
        return ""

    def _history_snapshot(self):
        return [dict(message) for message in self.conversation_history]

    def _restore_history(self, history):
        self.conversation_history = [dict(message) for message in history]

    def _stream_response(
        self,
        callback_thinking,
        callback_response,
        model_name,
        initial_thinking="",
        thinking_started=False,
    ):
        if self.api_type == API_TYPE_ANTHROPIC:
            return self._stream_anthropic_response(
                callback_thinking,
                callback_response,
                model_name,
                initial_thinking,
                thinking_started,
            )
        if self.api_type == API_TYPE_OLLAMA:
            return self._stream_ollama_response(
                callback_thinking,
                callback_response,
                model_name,
                initial_thinking,
                thinking_started,
            )

        try:
            kwargs = self._chat_completion_kwargs(
                messages=self.conversation_history,
                stream=True,
            )
            kwargs["stream_options"] = {"include_usage": True}
            try:
                response = self.client.chat.completions.create(**kwargs)
            except Exception as error:
                if not _stream_usage_unsupported(error):
                    raise
                kwargs.pop("stream_options", None)
                response = self.client.chat.completions.create(**kwargs)

            if self.thinking_mode and not thinking_started:
                print_stream_thinking("")
            field_thinking = ""
            tagged_thinking = ""
            raw_thinking = ""
            full_response = ""
            raw_response = ""
            thinking_ended = False
            usage_snapshot = None

            for chunk in response:
                if self._agent_should_stop():
                    break
                chunk_usage = _response_token_usage(chunk)
                if chunk_usage is not None:
                    usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                reasoning, field_thinking, raw_thinking = self._stream_reasoning_delta(
                    delta,
                    field_thinking,
                    raw_thinking,
                )
                if reasoning:
                    if callback_thinking and self.thinking_mode and not thinking_ended:
                        callback_thinking(reasoning)

                content, full_response, raw_response = self._stream_content_delta(
                    self._get_field(delta, "content", "") or "",
                    full_response,
                    raw_response,
                )
                tagged_reasoning, tagged_thinking = self._stream_tagged_reasoning_delta(
                    raw_response,
                    tagged_thinking,
                )
                if (
                    tagged_reasoning
                    and not thinking_ended
                    and callback_thinking
                    and self.thinking_mode
                ):
                    callback_thinking(tagged_reasoning)
                if content:
                    if not thinking_ended:
                        print_stream_response_start(model_name)
                        thinking_ended = True
                    if callback_response:
                        callback_response(content)

            if self._agent_should_stop():
                return self._agent_stopped_response(
                    _combine_reasoning_text(field_thinking, tagged_thinking),
                    full_response,
                )
            self.conversation_history.append(
                self._chat_stream_assistant_message(
                    full_response,
                    _combine_reasoning_text(field_thinking, tagged_thinking),
                )
            )
            self._record_context_usage_snapshot(usage_snapshot)
            return {
                "thinking": _combine_reasoning_text(field_thinking, tagged_thinking),
                "response": full_response,
            }

        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _stream_ollama_response(
        self,
        callback_thinking,
        callback_response,
        model_name,
        initial_thinking="",
        thinking_started=False,
    ):
        try:
            response = self.client.chat(
                **self._ollama_chat_kwargs(
                    messages=self.conversation_history,
                    stream=True,
                )
            )

            if self.thinking_mode and not thinking_started:
                print_stream_thinking("")
            field_thinking = ""
            tagged_thinking = ""
            full_response = ""
            raw_response = ""
            response_started = False
            usage_snapshot = None

            for chunk in response:
                if self._agent_should_stop():
                    break
                chunk_usage = _response_token_usage(chunk)
                if chunk_usage is not None:
                    usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
                message = self._get_field(chunk, "message", {})
                thinking = self._get_field(message, "thinking", "") or ""
                if thinking:
                    field_thinking += thinking
                    if (
                        callback_thinking
                        and self.thinking_mode
                        and not response_started
                    ):
                        callback_thinking(thinking)

                content, full_response, raw_response = self._stream_content_delta(
                    self._get_field(message, "content", "") or "",
                    full_response,
                    raw_response,
                )
                tagged_reasoning, tagged_thinking = self._stream_tagged_reasoning_delta(
                    raw_response,
                    tagged_thinking,
                )
                if (
                    tagged_reasoning
                    and not response_started
                    and callback_thinking
                    and self.thinking_mode
                ):
                    callback_thinking(tagged_reasoning)
                full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
                if content:
                    if not response_started:
                        print_stream_response_start(model_name)
                        response_started = True
                    if callback_response:
                        callback_response(content)

            full_thinking = _combine_reasoning_text(field_thinking, tagged_thinking)
            if self._agent_should_stop():
                return self._agent_stopped_response(
                    _clean_reasoning_text(full_thinking),
                    full_response,
                )
            self.conversation_history.append(
                self._ollama_assistant_message(
                    full_response,
                    full_thinking,
                )
            )
            self._record_context_usage_snapshot(usage_snapshot)
            return {
                "thinking": _clean_reasoning_text(full_thinking),
                "response": full_response,
            }

        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _stream_anthropic_response(
        self,
        callback_thinking,
        callback_response,
        model_name,
        initial_thinking="",
        thinking_started=False,
    ):
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self._normal_system_prompt(),
                messages=self._anthropic_messages(),
                stream=True,
                **self._anthropic_request_options(),
            )

            if self.thinking_mode and not thinking_started:
                print_stream_thinking("")
            field_thinking = ""
            tagged_thinking = ""
            full_response = ""
            raw_response = ""
            response_started = False
            blocks = _empty_anthropic_blocks()
            active_block_index = _no_active_block_index()
            usage_snapshot = None

            for chunk in response:
                if self._agent_should_stop():
                    break
                chunk_usage = _response_token_usage(chunk)
                if chunk_usage is not None:
                    usage_snapshot = _merge_token_usage(usage_snapshot, chunk_usage)
                chunk_type = self._get_field(chunk, "type", "")

                if chunk_type == "content_block_start":
                    content_block = self._get_field(chunk, "content_block")
                    block_type = self._get_field(content_block, "type")
                    initial_reasoning = self._anthropic_reasoning_text(content_block, clean=False)
                    if block_type == "text":
                        block = {"type": "text", "text": ""}
                    elif (
                        self._is_anthropic_reasoning_block_type(block_type)
                        or initial_reasoning
                    ):
                        block = {
                            "type": "thinking",
                            "thinking": initial_reasoning,
                        }
                        signature = self._get_field(content_block, "signature")
                        if signature:
                            block["signature"] = signature
                    elif block_type == "tool_use":
                        block = {
                            "type": "tool_use",
                            "id": self._get_field(content_block, "id", "") or "",
                            "name": self._get_field(content_block, "name", "") or "",
                            "input": self._get_field(content_block, "input", {}) or {},
                        }
                    else:
                        block = {"type": block_type or "unknown"}
                    blocks.append(block)
                    active_block_index = len(blocks) - 1
                    if initial_reasoning:
                        field_thinking += initial_reasoning
                        if (
                            callback_thinking
                            and self.thinking_mode
                            and not response_started
                        ):
                            callback_thinking(initial_reasoning)
                    if block_type == "text":
                        initial_text = self._get_field(content_block, "text", "") or ""
                        if initial_text:
                            block["text"] = block.get("text", "") + initial_text
                            content, full_response, raw_response = (
                                self._stream_content_delta(
                                    initial_text,
                                    full_response,
                                    raw_response,
                                )
                            )
                            tagged_reasoning, tagged_thinking = (
                                self._stream_tagged_reasoning_delta(
                                    raw_response,
                                    tagged_thinking,
                                )
                            )
                            if (
                                tagged_reasoning
                                and not response_started
                                and callback_thinking
                                and self.thinking_mode
                            ):
                                callback_thinking(tagged_reasoning)
                            if content:
                                if not response_started:
                                    print_stream_response_start(model_name)
                                    response_started = True
                                if callback_response:
                                    callback_response(content)
                    continue

                if chunk_type == "content_block_stop":
                    active_block_index = None
                    continue

                if chunk_type != "content_block_delta":
                    continue

                delta = self._get_field(chunk, "delta")
                delta_type = self._get_field(delta, "type", "")
                block = _no_anthropic_block()
                if active_block_index is not None:
                    block = blocks[active_block_index]

                if self._is_anthropic_reasoning_delta_type(delta_type):
                    thinking = self._anthropic_delta_reasoning_text(delta)
                    if thinking:
                        field_thinking += thinking
                        if block is not None:
                            block["thinking"] = block.get("thinking", "") + thinking
                        if (
                            callback_thinking
                            and self.thinking_mode
                            and not response_started
                        ):
                            callback_thinking(thinking)
                elif delta_type == "signature_delta":
                    if block is not None:
                        block["signature"] = block.get("signature", "") + (
                            self._get_field(delta, "signature", "") or ""
                        )
                elif delta_type == "text_delta":
                    text = self._get_field(delta, "text", "") or ""
                    if text:
                        if block is not None:
                            block["text"] = block.get("text", "") + text
                        content, full_response, raw_response = (
                            self._stream_content_delta(
                                text,
                                full_response,
                                raw_response,
                            )
                        )
                        tagged_reasoning, tagged_thinking = (
                            self._stream_tagged_reasoning_delta(
                                raw_response,
                                tagged_thinking,
                            )
                        )
                        if (
                            tagged_reasoning
                            and not response_started
                            and callback_thinking
                            and self.thinking_mode
                        ):
                            callback_thinking(tagged_reasoning)
                        if content:
                            if not response_started:
                                print_stream_response_start(model_name)
                                response_started = True
                            if callback_response:
                                callback_response(content)

            if self._agent_should_stop():
                return self._agent_stopped_response(
                    _combine_reasoning_text(field_thinking, tagged_thinking),
                    full_response,
                )
            history_content = _assistant_history_content(full_response)
            self.conversation_history.append({
                "role": "assistant",
                "content": history_content,
            })
            self._record_context_usage_snapshot(usage_snapshot)
            return {
                "thinking": _combine_reasoning_text(field_thinking, tagged_thinking),
                "response": full_response,
            }

        except Exception as error:
            if _is_context_overflow_error(error):
                raise
            print_error(_format_stream_error_message(error))
            return None

    def _parse_response(self, response):
        try:
            self._record_context_usage(response)
            message = response.choices[0].message
            assistant_message, thinking_content, text, _ = self._chat_message_parts(
                message
            )

            self.conversation_history.append(assistant_message)
            return {"thinking": thinking_content, "response": text}
        except (AttributeError, IndexError) as error:
            print_error(f"Failed to parse response: {error}")
            return None

    def _parse_ollama_response(self, response):
        try:
            self._record_context_usage(response)
            message = self._get_field(response, "message", {})
            assistant_message, thinking_content, text, _ = self._ollama_message_parts(
                message
            )

            self.conversation_history.append(assistant_message)
            return {"thinking": thinking_content, "response": text}
        except (AttributeError, TypeError) as error:
            print_error(f"Failed to parse response: {error}")
            return None

    def _parse_anthropic_response(self, response):
        try:
            self._record_context_usage(response)
            blocks = self._anthropic_content_blocks(
                self._get_field(response, "content", [])
            )
            full_thinking, full_response, _ = self._parse_anthropic_blocks(blocks)
            self.conversation_history.append({
                "role": "assistant",
                "content": blocks,
            })
            return {"thinking": full_thinking, "response": full_response}
        except (AttributeError, TypeError) as error:
            print_error(f"Failed to parse response: {error}")
            return None

    def _anthropic_response_text(self, response):
        _, text = self._anthropic_response_parts(response)
        return text

    def _anthropic_response_parts(self, response):
        content = self._get_field(response, "content", [])
        blocks = self._anthropic_content_blocks(content)
        full_thinking, full_response, _ = self._parse_anthropic_blocks(blocks)
        return full_thinking, full_response

    def _anthropic_content_blocks(self, content):
        if isinstance(content, str):
            return [{"type": "text", "text": content}]

        blocks = []
        for block in content or []:
            block_type = self._get_field(block, "type", "")
            thinking = self._anthropic_reasoning_text(block, clean=False)
            if block_type == "text":
                if thinking:
                    blocks.append({"type": "thinking", "thinking": thinking})
                blocks.append({
                    "type": "text",
                    "text": self._get_field(block, "text", "") or "",
                })
            elif block_type == "tool_use":
                blocks.append({
                    "type": "tool_use",
                    "id": self._get_field(block, "id", "") or "",
                    "name": self._get_field(block, "name", "") or "",
                    "input": self._get_field(block, "input", {}) or {},
                })
            elif self._is_anthropic_reasoning_block_type(block_type) or thinking:
                thinking_block = {
                    "type": "thinking",
                    "thinking": thinking,
                }
                signature = self._get_field(block, "signature")
                if signature:
                    thinking_block["signature"] = signature
                blocks.append(thinking_block)
        return blocks

    def _parse_anthropic_blocks(self, blocks):
        thinking = ""
        text = ""
        tool_uses = []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "thinking":
                thinking += self._anthropic_reasoning_text(block, clean=False)
            elif block_type == "text":
                text += block.get("text", "") or ""
            elif block_type == "tool_use":
                tool_uses.append(block)
        return _clean_reasoning_text(thinking), text, tool_uses

    def _chat_message_parts(self, message):
        raw_content = self._get_field(message, "content", "")
        if raw_content is None:
            raw_content = ""
        text = self._message_content_text(raw_content)
        thinking_content = self._message_reasoning_text(message)
        raw_tool_calls = self._get_field(message, "tool_calls", None) or []

        assistant_message = {
            "role": "assistant",
            "content": text,
        }
        if thinking_content:
            assistant_message["thinking"] = thinking_content
        reasoning_details = self._get_field(message, "reasoning_details", None)
        if reasoning_details:
            assistant_message["reasoning_details"] = self._plain_data(reasoning_details)

        tool_calls = []
        if raw_tool_calls:
            assistant_tool_calls = []
            for call in raw_tool_calls:
                call_id = self._get_field(call, "id", "") or ""
                function = self._get_field(call, "function", {}) or {}
                name = self._get_field(function, "name", "") or ""
                arguments = self._get_field(function, "arguments", {}) or {}
                parsed_arguments = self._parse_tool_arguments(arguments)

                assistant_tool_call = {
                    "id": call_id,
                    "type": self._get_field(call, "type", "function") or "function",
                    "function": {
                        "name": name,
                        "arguments": arguments
                        if isinstance(arguments, str)
                        else json.dumps(arguments),
                    },
                }
                assistant_tool_calls.append(assistant_tool_call)
                tool_calls.append({
                    "id": call_id,
                    "name": name,
                    "arguments": parsed_arguments,
                })
            assistant_message["tool_calls"] = assistant_tool_calls

        return assistant_message, thinking_content, text, tool_calls

    def _ollama_message_parts(self, message):
        text = str(self._get_field(message, "content", "") or "")
        thinking_content = _clean_reasoning_text(
            self._get_field(message, "thinking", "") or ""
        )
        raw_tool_calls = self._get_field(message, "tool_calls", None) or []

        tool_calls = []
        assistant_tool_calls = []
        for index, call in enumerate(raw_tool_calls):
            function = self._get_field(call, "function", {}) or {}
            name = self._get_field(function, "name", "") or ""
            arguments = self._get_field(function, "arguments", {}) or {}
            parsed_arguments = self._parse_tool_arguments(arguments)
            function_call = {
                "name": name,
                "arguments": parsed_arguments,
            }
            raw_index = self._get_field(function, "index", None)
            if raw_index is not None:
                function_call["index"] = raw_index
            elif len(raw_tool_calls) > 1:
                function_call["index"] = index
            assistant_tool_calls.append({
                "type": self._get_field(call, "type", "function") or "function",
                "function": function_call,
            })
            tool_calls.append({
                "name": name,
                "arguments": parsed_arguments,
            })

        assistant_message = self._ollama_assistant_message(
            text,
            thinking_content,
            assistant_tool_calls,
        )
        return assistant_message, thinking_content, text, tool_calls

    @staticmethod
    def _parse_tool_arguments(arguments):
        if isinstance(arguments, dict):
            return arguments
        if not arguments:
            return {}
        try:
            return json.loads(arguments)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _user_message_content(self, text, media_references=None):
        media_references = list(media_references or [])
        if not self._supports_structured_media_input():
            return text
        supported_media = [
            media
            for media in media_references
            if self._supports_extra_modality(media.get("kind"))
        ]
        if not supported_media:
            return text
        if self.api_type == API_TYPE_ANTHROPIC:
            return self._anthropic_user_media_content(text, supported_media)
        return self._openai_user_media_content(text, supported_media)

    def _supports_extra_modality(self, kind):
        return str(kind or "").strip().lower() in set(self.extra_modalities)

    def _supports_structured_media_input(self):
        return self.api_type != API_TYPE_OLLAMA

    def _openai_user_media_content(self, text, media_references):
        content = [{"type": "text", "text": text}]
        for media in media_references:
            data_url = self._media_reference_data_url(media)
            detail = media.get("detail") or "default"
            if media.get("kind") == "image":
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": detail,
                    },
                })
            elif media.get("kind") == "audio":
                content.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": media.get("data") or "",
                        "format": self._media_reference_audio_format(media),
                    },
                })
            elif media.get("kind") == "video":
                content.append({
                    "type": "video_url",
                    "video_url": {
                        "url": data_url,
                        "detail": detail,
                    },
                })
        return content

    def _anthropic_user_media_content(self, text, media_references):
        content = [{"type": "text", "text": text}]
        for media in media_references:
            kind = media.get("kind")
            if kind not in {"audio", "image", "video"}:
                continue
            block = {
                "type": kind,
                "source": {
                    "type": "base64",
                    "media_type": media.get("mime_type") or "",
                    "data": media.get("data") or "",
                },
                "detail": media.get("detail") or "default",
            }
            content.append(block)
        return content

    @staticmethod
    def _media_reference_data_url(media):
        mime_type = media.get("mime_type") or "application/octet-stream"
        data = media.get("data") or ""
        return f"data:{mime_type};base64,{data}"

    @staticmethod
    def _media_reference_audio_format(media):
        mime_type = str(media.get("mime_type") or "").strip().lower()
        if mime_type in {"audio/mpeg", "audio/mp3"}:
            return "mp3"
        if mime_type in {"audio/wav", "audio/x-wav"}:
            return "wav"
        if mime_type == "audio/flac":
            return "flac"
        if mime_type == "audio/ogg":
            return "ogg"
        if mime_type == "audio/webm":
            return "webm"
        if mime_type in {"audio/mp4", "audio/x-m4a"}:
            return "m4a"
        if mime_type == "audio/aac":
            return "aac"
        path = str(media.get("path") or "").strip().lower()
        if "." in path:
            return path.rsplit(".", 1)[1]
        return "mp3"

    def _anthropic_messages(self):
        messages = []
        for message in self._effective_history_messages(self.conversation_history):
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            messages.append({"role": role, "content": message.get("content", "")})
        return messages

    def _ollama_messages(self, messages=None):
        converted = []
        source_messages = (
            messages if messages is not None else self.conversation_history
        )
        for source_message in source_messages:
            message = self._effective_history_message(source_message)
            role = message.get("role")
            if role not in {"system", "user", "assistant", "tool"}:
                continue

            converted_message = {
                "role": role,
                "content": self._message_content_text_for_ollama(
                    message.get("content", "")
                ),
            }
            if role == "assistant":
                thinking = message.get("thinking")
                if thinking:
                    converted_message["thinking"] = thinking
                tool_calls = self._ollama_normalized_tool_calls(
                    message.get("tool_calls") or []
                )
                if tool_calls:
                    converted_message["tool_calls"] = tool_calls
            elif role == "tool":
                tool_name = message.get("tool_name") or message.get("name") or ""
                if tool_name:
                    converted_message["tool_name"] = tool_name
            converted.append(converted_message)
        return converted

    def _chat_agent_messages(self):
        return [
            {"role": "system", "content": self._agent_system_prompt()}
        ] + self._effective_history_messages(self.conversation_history)

    def _chat_messages(self, messages=None):
        source_messages = (
            messages if messages is not None else self.conversation_history
        )
        source_messages = self._effective_history_messages(source_messages)
        if source_messages and source_messages[0].get("role") == "system":
            return source_messages
        return [
            {"role": "system", "content": self._normal_system_prompt()}
        ] + source_messages

    def _ollama_agent_messages(self):
        return self._ollama_messages(
            [{"role": "system", "content": self._agent_system_prompt()}]
            + self.conversation_history
        )

    def _ollama_normal_messages(self, messages=None):
        source_messages = (
            messages if messages is not None else self.conversation_history
        )
        source_messages = self._effective_history_messages(source_messages)
        if source_messages and source_messages[0].get("role") == "system":
            return self._ollama_messages(source_messages)
        return self._ollama_messages(
            [{"role": "system", "content": self._normal_system_prompt()}]
            + source_messages
        )

    def _normal_system_prompt(self):
        prompt = NORMAL_SYSTEM_PROMPT
        if self._normal_web_search_available():
            prompt += (
                "\n联网搜索已开启。遇到近期、易变化、外部事实不足或需要来源支撑的问题时，"
                "使用 web_search；回答中引用搜索结果里的来源 URL。"
            )
        if self.agent_tools.program_docs_available:
            prompt += (
                "\nYou may use read_program_docs to read OmniAgent's built-in "
                "README when the user asks how to use, configure, learn, or "
                "troubleshoot this program. This does not grant general workspace "
                "file access in normal chat."
            )
        prompt += (
            "\nUse web_fetch when the user provides a specific public webpage URL "
            "and asks you to read or summarize that page."
            "\nWhen a tool reports `preview limited` and returns an "
            "`artifact://tool_...` URI, the complete output is preserved behind that "
            "read-only handle. If read_file or grep is available, pass the exact URI "
            "to that tool; never treat it as a normal absolute path or pass it to "
            "shell, git, write, or edit tools."
        )
        reference_files = getattr(self.agent_tools, "reference_files", {})
        reference_folders = getattr(self.agent_tools, "reference_folders", {})
        if reference_files or reference_folders:
            prompt += (
                "\n- For this request, local read-only access is available only through "
                "explicit user references. Always pass the exact reference label in the "
                "`reference` parameter; never try to read other local paths."
            )
        if reference_files:
            labels = ", ".join(reference_files)
            prompt += (
                "\n- The user referenced these files for this request: "
                f"{labels}. Use read_file with the exact `reference` label. Access is "
                "limited to that one file only."
            )
        if reference_folders:
            labels = ", ".join(reference_folders)
            prompt += (
                "\n- The user referenced these folders for this request: "
                f"{labels}. Access is read-only and lazy. Use list_dir or glob first, then "
                "read_file or grep with the exact `reference` label and a path relative to "
                "that folder. Do not use any local file tool without a `reference`."
            )
        return _with_user_custom_prompt(
            _with_persistent_memory(prompt, self.memory_store)
        )

    def _agent_system_prompt(self):
        prompt = AGENT_SYSTEM_PROMPT
        prompt += "\n\n" + AGENT_TODO_RULES
        if self.agent_tools.has_incomplete_todos():
            prompt += (
                "\n\nRestored todo list for this conversation:\n"
                f"{self.agent_tools.todo_summary(include_completed=True)}\n"
                "Continue from this stored list. Preserve existing todo ids and statuses, "
                "work from the in-progress or next ready item, and call update_todo with "
                "the full list whenever an item changes. Do not discard unfinished items "
                "unless the user explicitly replaces or cancels the task."
            )
        if self.agent_tools.plan_mode:
            prompt += (
                "\n\nYou are in Plan mode. This is a planning and clarification workflow "
                "for 'think it through before touching code'. Stay read-only: you may "
                "inspect the workspace and use only read/search tools plus ask_user and "
                "update_todo, and you may delegate only reader or researcher subagents. "
                "Do NOT modify files, run commands, or use Agent Team."
                "\n- Use Plan mode when the request is still ambiguous, the change is risky, "
                "the user wants design/options/roadmap first, or key decisions still need "
                "confirmation."
                "\n- ask_user is available in Build and Plan mode. In Plan mode, use it for short, "
                "high-impact clarification questions; you may batch a few related questions in one call."
                "\n- When the final implementation plan is ready, do not present it as a "
                "normal assistant response. The main Agent must call submit_plan exactly once "
                "with the complete plan. This displays the plan and asks the user whether to "
                "allow it. Subagents cannot call submit_plan."
                "\n- If submit_plan reports approval, Build mode becomes active in the same "
                "run. Immediately execute the approved plan with Build tools; do not ask the "
                "user to switch modes, and do not return to Plan mode after execution."
                "\n- If submit_plan reports rejection, do not implement the plan or make any "
                "other changes; remain in Plan mode and wait for the user's next instruction."
                "\n- update_todo is optional in Plan mode. Use it when a concrete execution "
                "todo list would help the later Build phase; otherwise a clear plan, design, "
                "or roadmap is enough."
            )
        prompt += (
            "\n- Use web_fetch when the user provides a specific public webpage URL "
            "and asks you to read or summarize that page."
        )
        if self.agent_tools.subagents_available:
            if self.agent_tools.plan_mode:
                prompt += (
                    "\n- In Plan mode, use dispatch_subagent only for bounded read-only repository "
                    "inspection or external research. Choose reader or researcher; do not "
                    "delegate implementation or mutation."
                    "\n- Use each task's positive integer priority to control execution order. "
                    "Lower numbers run first, omitted priorities default to 1, and tasks with "
                    "the same priority run concurrently; the call returns after every task finishes."
                    " Priority is an execution barrier, not a success dependency: later groups "
                    "still run after failures. If a later task needs an earlier task's returned "
                    "text or confirmed success, dispatch it separately after checking the result."
                    "\n- Each subagent has its own history and restricted tools; only its final "
                    "reply returns. Keep ownership of planning decisions and the final plan."
                )
            else:
                prompt += (
                    "\n- Use dispatch_subagent for short, synchronous, one-shot work such as "
                    "repository exploration, external research, auditing, verification, or a "
                    "scoped implementation whose final reply is sufficient. Dispatch it early "
                    "when that shape fits so detailed tool output stays out of the main context."
                    "\n- Put related tasks in one dispatch_subagent batch and assign each a positive "
                    "integer priority. Lower numbers run first, omitted priorities default to 1, "
                    "and the next priority group waits for the current group to finish. Choose the "
                    "narrowest matching role and provide a concrete task, expected output, evidence "
                    "requirement, and scope for each item."
                    "\n- Within one priority group, independent read-only tasks run concurrently. "
                    "Write-capable builders are serialized in tasks-array order and may run alongside "
                    "independent read-only tasks in that same group."
                    "\n- Use a later priority when a task must wait for an earlier builder's finished "
                    "workspace changes. Priority is an execution barrier, not a success dependency: "
                    "later groups still run after failures and are not automatically given earlier final "
                    "replies. Dispatch a separate call after checking success when the dependency is on "
                    "returned text or a successful result rather than observable workspace state."
                    "\n- Handle work directly only when it is a simple one-step task, tightly "
                    "coupled to the main reasoning, requires immediate user clarification, or no "
                    "available subagent has a useful tool set. Do not delegate merely to repeat "
                    "work already completed in the main context."
                    "\n- The subagent has its own history and restricted tools; only its final "
                    "reply returns. Keep ownership of user-facing decisions, integration, final "
                    "verification, and the final answer."
                )
        if self.agent_tools.team_available and not self.agent_tools.plan_mode:
            prompt += (
                "\n- Agent Team is enabled. Use spawn_teammate for background or long-running "
                "role-specific work that benefits from continuing ownership, status tracking, "
                "or follow-up messages. Choose a fitting specialist for architecture review, "
                "code review, debugging, infrastructure, implementation, or independent "
                "verification."
                "\n- Split independent responsibilities across multiple fitting teammates "
                "rather than asking one teammate to cover unrelated concerns. Give each task "
                "a narrow scope, expected output, and required evidence. Reuse active teammates "
                "through team messaging when follow-up belongs to the same role."
                "\n- spawn_teammate starts a background task and returns immediately. Use "
                "send_message or broadcast for follow-up guidance while it is running, then "
                "use read_inbox with wait_seconds to collect completion messages before relying "
                "on delegated findings. Use list_teammates to inspect lifecycle state and do not "
                "treat a started task as completed evidence."
                "\n- Delegate application-code implementation to implementer. Delegate CI/CD, "
                "Docker, deployment, build, environment, and infrastructure configuration to "
                "devops. Every write-capable teammate must receive a narrow write_scope."
                "\n- While a write-capable teammate is active, neither the Lead nor a Builder "
                "Subagent may modify files inside that teammate's write_scope. A conflicting "
                "spawn_teammate task waits automatically and starts after ownership is released; "
                "integrate only after ownership is released."
                "\n- Before the final answer, call read_inbox and collect every teammate result "
                "that the answer depends on; a started or running teammate is not evidence."
                "\n- Skip team delegation only for simple one-step work, tightly coupled edits "
                "where delegation would duplicate the lead agent's context, or when no teammate "
                "role fits. The lead agent remains responsible for integrating results, resolving "
                "conflicts, verifying the final state, and answering the user."
            )
        if (
            self.agent_tools.subagents_available
            and self.agent_tools.team_available
            and not self.agent_tools.plan_mode
        ):
            prompt += (
                "\n- When both subagents and Agent Team are available, use them for distinct "
                "scopes. Use a Subagent for short, synchronous, one-shot investigation, "
                "verification, or implementation whose final reply is sufficient. Use a "
                "teammate for background or long-running work that needs status tracking, "
                "follow-up messages, or continuing ownership. Never assign the same task scope "
                "to both a Subagent and a teammate."
            )
        if self.agent_tools.plan_mode:
            prompt += (
                "\n- Use ask_user only for an important uncertainty that materially affects "
                "the goal, scope, tradeoffs, or acceptance criteria and cannot be resolved "
                "from local files, tools, or web facts. You may ask one question or a short related batch."
                "\n- When you need the user to choose among options during planning, "
                "call ask_user instead of writing a numbered or bulleted choice list in normal "
                "assistant text. After ask_user returns, continue the planning work."
            )
        if self.agent_tools.web_search_available:
            prompt += (
                "\n- Use web_search for recent, unstable, or external facts when local files "
                "are insufficient. Cite source URLs from search results in the final answer."
            )
        reference_folders = getattr(self.agent_tools, "reference_folders", {})
        if reference_folders:
            labels = ", ".join(reference_folders)
            prompt += (
                "\n- The user referenced these folders for this request: "
                f"{labels}. Access is read-only and lazy. Use read_file, list_dir, grep, "
                "or glob with the reference parameter set to the exact label and a path "
                "relative to that folder. Do not use write, patch, shell, or git tools on "
                "referenced folders. This access expires after the request."
            )
        prompt += self.agent_tools.workspace_skills_usage_prompt()
        skills_prompt = self.agent_tools.skills_catalog_prompt()
        if skills_prompt:
            prompt += skills_prompt
        return _with_user_custom_prompt(
            _with_persistent_memory(prompt, self.memory_store)
        )

    def _reasoning_effort_value(self):
        return normalize_reasoning_effort_for_api(self.api_type, self.reasoning_effort)

    def _reasoning_disabled_by_effort(self):
        return not self._reasoning_effort_value()

    def _chat_completion_reasoning_effort(self, model=None):
        return self._reasoning_effort_value()

    def _anthropic_request_options(self, include_reasoning=True):
        if not include_reasoning:
            return {}
        effort = self._anthropic_reasoning_effort(self._reasoning_effort_value())
        if not effort:
            return {}
        return {"output_config": {"effort": effort}}

    @staticmethod
    def _anthropic_reasoning_effort(effort):
        return effort or ""

    @staticmethod
    def _ollama_reasoning_effort_value(effort):
        if not effort:
            return ""
        if effort == "low":
            return "low"
        if effort == "medium":
            return "medium"
        return effort

    def _ollama_reasoning_effort(self, model=None):
        effort = self._reasoning_effort_value()
        if not effort:
            return ""
        return self._ollama_reasoning_effort_value(effort)

    @staticmethod
    def _merge_extra_body(kwargs, extra_body):
        if not extra_body:
            return
        existing = kwargs.get("extra_body")
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(extra_body)
            kwargs["extra_body"] = merged
            return
        kwargs["extra_body"] = dict(extra_body)

    def _chat_completion_kwargs(
        self,
        model=None,
        messages=None,
        temperature=None,
        max_tokens=None,
        stream=False,
        tools=None,
        include_reasoning=True,
    ):
        kwargs = {
            "model": model or self.model,
            "messages": self._chat_messages(messages),
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if include_reasoning:
            reasoning_effort = self._chat_completion_reasoning_effort(model)
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
        if self.api_type == API_TYPE_GLM and include_reasoning:
            kwargs["thinking"] = {
                "type": (
                    "enabled"
                    if self.thinking_mode and not self._reasoning_disabled_by_effort()
                    else "disabled"
                )
            }
        elif include_reasoning and self.api_type == API_TYPE_GEMINI:
            if self.thinking_mode and not self._reasoning_disabled_by_effort():
                self._merge_extra_body(
                    kwargs,
                    {
                        "google": {
                            "thinking_config": {
                                "include_thoughts": True,
                            }
                        }
                    },
                )
        if stream:
            kwargs["stream"] = True
        if tools is not None:
            kwargs["tools"] = tools
        return kwargs

    def _ollama_chat_kwargs(
        self,
        model=None,
        messages=None,
        temperature=None,
        max_tokens=None,
        stream=False,
        tools=None,
        include_reasoning=True,
    ):
        options = {
            "temperature": self.temperature if temperature is None else temperature,
            "num_predict": self.max_tokens if max_tokens is None else max_tokens,
        }
        kwargs = {
            "model": model or self.model,
            "messages": self._ollama_normal_messages(messages),
            "options": options,
            "think": self._ollama_think_value(model, include_reasoning),
        }
        if stream:
            kwargs["stream"] = True
        if tools is not None:
            kwargs["tools"] = tools
        return kwargs

    def _chat_tool_schemas(self):
        include_web_search = self.agent_tools.web_search_available
        include_skills = self.agent_tools.skills_available
        include_plan = self.agent_tools.todos_enabled
        plan_mode = self.agent_tools.plan_mode
        extra_definitions = (
            self.agent_tools.plan_tool_definitions()
            + self.agent_tools.subagent_tool_definitions()
            + self.agent_tools.team_tool_definitions()
        )
        if self.api_type in {API_TYPE_OPENAI, API_TYPE_GEMINI}:
            return openai_tool_schemas(
                include_web_search,
                include_skills,
                include_plan,
                extra_definitions=extra_definitions,
                plan_mode=plan_mode,
            )
        return glm_tool_schemas(
            include_web_search,
            include_skills,
            include_plan,
            extra_definitions=extra_definitions,
            plan_mode=plan_mode,
        )

    def _subagent_tool_schemas(self, spec):
        effective_spec = self._effective_subagent_spec(spec)
        include_web_search = (
            self.agent_tools.web_search_available
            and "web_search" in effective_spec.tool_names
        )
        include_skills = self.agent_tools.skills_available and bool(
            {"list_skills", "read_skill"} & set(effective_spec.tool_names)
        )
        if self.api_type == API_TYPE_ANTHROPIC:
            return anthropic_tool_schemas(
                include_web_search,
                include_skills,
                False,
                only_tools=effective_spec.tool_names,
                exclude_tools=FORBIDDEN_SUBAGENT_TOOL_NAMES,
            )
        if self.api_type == API_TYPE_OLLAMA:
            return ollama_tool_schemas(
                include_web_search,
                include_skills,
                False,
                only_tools=effective_spec.tool_names,
                exclude_tools=FORBIDDEN_SUBAGENT_TOOL_NAMES,
            )
        if self.api_type in {API_TYPE_OPENAI, API_TYPE_GEMINI}:
            return openai_tool_schemas(
                include_web_search,
                include_skills,
                False,
                only_tools=effective_spec.tool_names,
                exclude_tools=FORBIDDEN_SUBAGENT_TOOL_NAMES,
            )
        return glm_tool_schemas(
            include_web_search,
            include_skills,
            False,
            only_tools=effective_spec.tool_names,
            exclude_tools=FORBIDDEN_SUBAGENT_TOOL_NAMES,
        )

    def _effective_subagent_spec(self, spec: SubagentSpec) -> SubagentSpec:
        if not self.agent_tools.plan_mode:
            return spec
        allowed_names = tuple(
            name for name in spec.tool_names if name in PLAN_MODE_ALLOWED_TOOLS
        )
        return replace(spec, tool_names=allowed_names)

    def _teammate_tool_schemas(self, spec):
        tool_names = tuple(spec.tool_names) + (TEAMMATE_REPORT_TOOL_NAME,)
        report_definition = [teammate_report_tool_definition()]
        include_web_search = (
            self.agent_tools.web_search_available and "web_search" in spec.tool_names
        )
        include_skills = self.agent_tools.skills_available and bool(
            {"list_skills", "read_skill"} & set(spec.tool_names)
        )
        excluded = FORBIDDEN_SUBAGENT_TOOL_NAMES | {
            "spawn_teammate",
            "list_teammates",
            "send_message",
            "read_inbox",
            "broadcast",
            "shutdown_teammate",
        }
        if self.api_type == API_TYPE_ANTHROPIC:
            return anthropic_tool_schemas(
                include_web_search,
                include_skills,
                False,
                extra_definitions=report_definition,
                only_tools=tool_names,
                exclude_tools=excluded,
            )
        if self.api_type == API_TYPE_OLLAMA:
            return ollama_tool_schemas(
                include_web_search,
                include_skills,
                False,
                extra_definitions=report_definition,
                only_tools=tool_names,
                exclude_tools=excluded,
            )
        if self.api_type in {API_TYPE_OPENAI, API_TYPE_GEMINI}:
            return openai_tool_schemas(
                include_web_search,
                include_skills,
                False,
                extra_definitions=report_definition,
                only_tools=tool_names,
                exclude_tools=excluded,
            )
        return glm_tool_schemas(
            include_web_search,
            include_skills,
            False,
            extra_definitions=report_definition,
            only_tools=tool_names,
            exclude_tools=excluded,
        )

    def _normal_web_search_tool_schemas(self):
        definitions = []
        tool_definition_by_name = {
            definition["name"]: definition for definition in TOOL_DEFINITIONS
        }
        if self.agent_tools.has_reference_access():
            for name in ("read_file", "list_dir", "grep", "glob"):
                definition = tool_definition_by_name.get(name)
                if definition is not None:
                    definitions.append(definition)
        update_todo_definition = tool_definition_by_name.get("update_todo")
        if update_todo_definition is not None:
            definitions.append(update_todo_definition)
        definitions.append(ASK_USER_TOOL_DEFINITION)
        if self.agent_tools.program_docs_available:
            definitions.append(PROGRAM_DOCS_TOOL_DEFINITION)
        definitions.append(WEB_FETCH_TOOL_DEFINITION)
        if self.agent_tools.web_search_available:
            definitions.append(WEB_SEARCH_TOOL_DEFINITION)

        if self.api_type == API_TYPE_ANTHROPIC:
            return definitions

        return [
            {
                "type": "function",
                "function": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "parameters": definition["input_schema"],
                },
            }
            for definition in definitions
        ]

    def _chat_tool_result_message(self, tool_call_id, name, content, display=None):
        message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "tool_name": name,
            "content": content,
        }
        if name:
            message["name"] = name
        if display:
            message["display"] = display
        return message

    @staticmethod
    def _ollama_tool_result_message(name, content, display=None):
        message = {
            "role": "tool",
            "tool_name": name,
            "content": content,
        }
        if display:
            message["display"] = display
        return message

    def _chat_stream_assistant_message(self, content, thinking):
        message = {"role": "assistant", "content": content}
        if thinking:
            message["thinking"] = thinking
        return message

    @staticmethod
    def _ollama_assistant_message(content, thinking="", tool_calls=None):
        message = {"role": "assistant", "content": content}
        if thinking:
            message["thinking"] = thinking
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def _ollama_think_value(self, model=None, include_reasoning=True):
        if not include_reasoning:
            return False
        reasoning_effort = self._ollama_reasoning_effort(model)
        if reasoning_effort:
            return reasoning_effort
        if not self.thinking_mode:
            return False
        model_name = str(model or self.model or "").lower()
        if "gpt-oss" in model_name:
            return "medium"
        return True

    def _message_content_text_for_ollama(self, content):
        if isinstance(content, str):
            return content
        if isinstance(content, (list, dict)):
            return clean_display_text(content)
        return str(content or "")

    def _ollama_normalized_tool_calls(self, tool_calls):
        normalized = []
        for index, call in enumerate(tool_calls or []):
            function = self._get_field(call, "function", {}) or {}
            name = self._get_field(function, "name", "") or ""
            arguments = self._parse_tool_arguments(
                self._get_field(function, "arguments", {}) or {}
            )
            function_call = {
                "name": name,
                "arguments": arguments,
            }
            raw_index = self._get_field(function, "index", None)
            if raw_index is not None:
                function_call["index"] = raw_index
            elif len(tool_calls) > 1:
                function_call["index"] = index
            normalized.append({
                "type": self._get_field(call, "type", "function") or "function",
                "function": function_call,
            })
        return normalized

    def _message_reasoning_text(self, message):
        return self._anthropic_reasoning_text(message)

    def _message_content_text(self, content):
        return str(content or "")

    def _stream_content_delta(self, content, current_response, raw_response):
        delta, raw_response = self._split_stream_delta(raw_response, content)
        if not delta and not content:
            return "", current_response, raw_response

        clean_response, _, _ = _split_tagged_think_text(raw_response)
        clean_delta, clean_response = self._split_stream_delta(
            current_response, clean_response
        )
        return clean_delta, clean_response, raw_response

    def _stream_tagged_reasoning_delta(self, raw_response, current_tagged_thinking):
        _, tagged_thinking, has_tagged_thinking = _split_tagged_think_text(raw_response)
        if not has_tagged_thinking:
            return "", current_tagged_thinking
        return self._split_stream_delta(current_tagged_thinking, tagged_thinking)

    @staticmethod
    def _is_anthropic_reasoning_block_type(block_type):
        return block_type in {"thinking", "reasoning", "reasoning_content"}

    @staticmethod
    def _is_anthropic_reasoning_delta_type(delta_type):
        return delta_type in {
            "thinking_delta",
            "reasoning_delta",
            "reasoning_content_delta",
        }

    def _stream_reasoning_delta(self, delta, current_thinking, raw_thinking):
        reasoning = self._anthropic_reasoning_text(
            delta, clean=False, include_details=False
        )
        if reasoning:
            raw_thinking += reasoning
            clean_thinking = _clean_reasoning_text(raw_thinking)
            clean_delta, clean_thinking = self._split_stream_delta(
                current_thinking, clean_thinking
            )
            return clean_delta, clean_thinking, raw_thinking
        reasoning_details = self._reasoning_details_text(
            self._get_field(delta, "reasoning_details", None)
        )
        if reasoning_details:
            if raw_thinking and reasoning_details.startswith(raw_thinking):
                raw_thinking = reasoning_details
            else:
                raw_thinking += reasoning_details
            clean_thinking = _clean_reasoning_text(raw_thinking)
            clean_delta, clean_thinking = self._split_stream_delta(
                current_thinking, clean_thinking
            )
            return clean_delta, clean_thinking, raw_thinking
        return "", current_thinking, raw_thinking

    def _anthropic_reasoning_text(self, item, clean=True, include_details=True):
        item_type = self._get_field(item, "type", "") or ""
        thinking = self._get_field(item, "thinking", "") or ""
        reasoning_content = self._get_field(item, "reasoning_content", "") or ""
        reasoning = self._get_field(item, "reasoning", "") or ""
        reasoning_details = ""
        if include_details:
            reasoning_details = self._reasoning_details_text(
                self._get_field(item, "reasoning_details", None)
            )
        compatible_text = ""
        if self._is_anthropic_reasoning_block_type(
            item_type
        ) or self._is_anthropic_reasoning_delta_type(item_type):
            compatible_text = (
                self._get_field(item, "text", "")
                or self._get_field(item, "content", "")
                or self._get_field(item, "delta", "")
                or ""
            )
        text = ""
        for part in (
            thinking,
            reasoning_content,
            reasoning,
            reasoning_details,
            compatible_text,
        ):
            text = _merge_reasoning_text(text, str(part or ""))
        if clean:
            return _clean_reasoning_text(text)
        return text

    def _anthropic_delta_reasoning_text(self, delta):
        return self._anthropic_reasoning_text(delta, clean=False)

    def _reasoning_details_text(self, details):
        if not details:
            return ""
        if isinstance(details, str):
            return details
        if isinstance(details, dict):
            return details.get("text") or details.get("content") or ""
        if isinstance(details, (list, tuple)):
            return "".join(self._reasoning_details_text(detail) for detail in details)

        text = self._get_field(details, "text", None)
        if text is not None:
            return str(text)
        content = self._get_field(details, "content", None)
        if content is not None:
            return str(content)
        return ""

    @staticmethod
    def _split_stream_delta(current_text, next_text):
        next_text = str(next_text or "")
        if not next_text:
            return "", current_text
        if current_text and next_text.startswith(current_text):
            return next_text[len(current_text) :], next_text
        return next_text, current_text + next_text

    def _plain_data(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._plain_data(item) for item in value]
        if isinstance(value, tuple):
            return [self._plain_data(item) for item in value]
        if isinstance(value, dict):
            return {key: self._plain_data(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return self._plain_data(value.model_dump(exclude_none=True))
        if hasattr(value, "to_dict"):
            return self._plain_data(value.to_dict())
        return value

    @staticmethod
    def _get_field(item, field, default=None):
        if isinstance(item, dict):
            return item.get(field, default)
        missing = object()
        direct = getattr(item, field, missing)
        if direct is not missing:
            return direct
        extra = getattr(item, "model_extra", None)
        if isinstance(extra, dict) and field in extra:
            return extra.get(field, default)
        return default

    def clear_history(self):
        self.conversation_history = []
        with self.usage_history_lock:
            self.request_usage_history = []
        self.session_episodic_heading = ""
        self.session_memory_generation += 1
        self.clear_todos()
        self._clear_context_usage()

    @staticmethod
    def _normalized_history_messages(history):
        return [
            dict(message)
            for message in list(history or [])
            if isinstance(message, dict)
        ]

    def _effective_history_messages(self, history):
        return [
            self._effective_history_message(message)
            for message in list(history or [])
            if isinstance(message, dict)
        ]

    def _effective_history_message(self, message):
        plain = self._plain_data(message)
        if not isinstance(plain, dict):
            return {}
        effective = dict(plain)
        compacted = effective.pop("compacted", None)
        if effective.get("role") == "tool" and isinstance(compacted, dict):
            effective["content"] = str(
                compacted.get("replacement") or COMPACTION_TOOL_RESULT_PLACEHOLDER
            )

        content = effective.get("content")
        if isinstance(content, list):
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    blocks.append(block)
                    continue
                effective_block = dict(block)
                block_compacted = effective_block.pop("compacted", None)
                if (
                    effective_block.get("type") == "tool_result"
                    and isinstance(block_compacted, dict)
                ):
                    effective_block["content"] = str(
                        block_compacted.get("replacement")
                        or COMPACTION_TOOL_RESULT_PLACEHOLDER
                    )
                blocks.append(effective_block)
            effective["content"] = blocks
        return effective

    def set_history(self, history, *, preserve_todos=False):
        self.conversation_history = self._normalized_history_messages(history)
        self.session_episodic_heading = ""
        self.session_memory_generation += 1
        if preserve_todos:
            self.resume_existing_plan = self.agent_tools.has_incomplete_todos()
        else:
            self.clear_todos()
        self._clear_context_usage()
        estimated_tokens = self._estimate_current_context_tokens()
        if estimated_tokens > 0:
            self._set_context_input_tokens(estimated_tokens, "estimated_loaded_history")

    def get_history(self):
        return self.conversation_history

    def set_usage_history(self, usage_history):
        with self.usage_history_lock:
            self.request_usage_history = [
                dict(item)
                for item in list(usage_history or [])
                if isinstance(item, dict)
            ]

    def append_usage_history(self, usage_history):
        entries = [
            dict(item)
            for item in list(usage_history or [])
            if isinstance(item, dict)
        ]
        if not entries:
            return
        with self.usage_history_lock:
            existing_ids = {
                str(item.get("id") or "")
                for item in self.request_usage_history
                if isinstance(item, dict)
            }
            for entry in entries:
                entry_id = str(entry.get("id") or "")
                if entry_id and entry_id in existing_ids:
                    continue
                self.request_usage_history.append(entry)
                if entry_id:
                    existing_ids.add(entry_id)

    def get_usage_history(self):
        with self.usage_history_lock:
            return [dict(item) for item in self.request_usage_history]


def _summarize_tool_input(tool_input):
    if isinstance(tool_input, str):
        text = tool_input
    else:
        try:
            text = json.dumps(tool_input, ensure_ascii=False)
        except TypeError:
            text = str(tool_input)
    return _single_line(text, 280)


def _summarize_tool_result(tool_result):
    if not tool_result:
        return "(empty)"
    return _single_line(str(tool_result).splitlines()[0], 220)


def _escape_rich_markup(text: str) -> str:
    return str(text or "").replace("[", r"\[")


def _format_explored_entry(name, tool_input):
    if not isinstance(tool_input, dict):
        tool_input = {}
    if name == "read_file":
        parts = ["[white]Read[/white]"]
        file_path = _escape_rich_markup(tool_input.get("file_path") or "")
        parts.append(f"[gray]{file_path}[/gray]")
        offset = tool_input.get("offset")
        limit = tool_input.get("limit")
        if offset is not None:
            parts.append(f"[gray]offset={offset}[/gray]")
        if limit is not None:
            parts.append(f"[gray]limit={limit}[/gray]")
        return " ".join(parts)
    if name == "read_program_docs":
        return "[white]Read program docs[/white]"
    if name == "list_skills":
        return "[white]List skills[/white]"
    if name == "read_skill":
        parts = ["[white]Read skill[/white]"]
        skill_name = _escape_rich_markup(tool_input.get("name") or "")
        if skill_name:
            parts.append(f"[gray]{skill_name}[/gray]")
        files = tool_input.get("files")
        if isinstance(files, list) and files:
            file_list = ", ".join(_escape_rich_markup(str(item)) for item in files)
            parts.append(f"[gray]files={file_list}[/gray]")
        return " ".join(parts)
    if name == "grep":
        parts = ["[white]Grep[/white]"]
        pattern = str(tool_input.get("pattern") or "")
        parts.append(f"[gray]{pattern}[/gray]")
        include = tool_input.get("include")
        if include:
            parts.append(f"[gray]include={include}[/gray]")
        path = tool_input.get("path")
        if path:
            parts.append(f"[gray]path={path}[/gray]")
        return " ".join(parts)
    if name == "glob":
        pattern = str(tool_input.get("pattern") or "")
        return f"[white]Glob[/white] [gray]{pattern}[/gray]"
    if name == "list_dir":
        path = str(tool_input.get("path") or ".")
        return f"[white]List dir[/white] [gray]{path}[/gray]"
    return ""


def _response_token_usage(response):
    usage = _usage_field(response, "usage")
    if usage is None:
        usage = _usage_field(_usage_field(response, "message"), "usage")
    breakdown = _usage_token_breakdown(usage) if usage is not None else None

    if breakdown is None:
        input_tokens = _usage_int(response, "prompt_eval_count")
        output_tokens = _usage_int(response, "eval_count")
        total_tokens = input_tokens + output_tokens
        if total_tokens > 0:
            breakdown = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": total_tokens,
            }

    return breakdown


def _merge_token_usage(current, incoming):
    if incoming is None:
        return current
    if current is None:
        return dict(incoming)

    merged = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        merged[key] = max(
            int(current.get(key, 0) or 0),
            int(incoming.get(key, 0) or 0),
        )
    reported_total = max(
        int(current.get("total_tokens", 0) or 0),
        int(incoming.get("total_tokens", 0) or 0),
    )
    calculated_total = (
        merged["input_tokens"]
        + merged["output_tokens"]
        + merged["reasoning_tokens"]
    )
    merged["total_tokens"] = max(reported_total, calculated_total)
    return merged


def _empty_anthropic_blocks() -> List[Dict[str, Any]]:
    return []


def _no_active_block_index() -> Optional[int]:
    return None


def _no_anthropic_block() -> Optional[Dict[str, Any]]:
    return None


def _assistant_history_content(content) -> Any:
    return content


def _usage_token_breakdown(usage):
    if usage is None:
        return None

    prompt_tokens = _usage_int(usage, "prompt_tokens")
    raw_input_tokens = (
        _usage_int(usage, "input_tokens")
        or _usage_int(usage, "input")
        or _usage_int(usage, "inputTokens")
    )

    explicit_cache_read = (
        _usage_int(usage, "cache_read_input_tokens")
        or _usage_int(usage, "cache_read")
    )
    explicit_cache_write = (
        _usage_int(usage, "cache_creation_input_tokens")
        or _usage_int(usage, "cache_creation_tokens")
        or _usage_int(usage, "cache_create")
    )
    prompt_details = (
        _usage_field(usage, "prompt_tokens_details")
        or _usage_field(usage, "input_tokens_details")
    )
    detail_cache_read = _usage_int(prompt_details, "cached_tokens")
    cache_read = explicit_cache_read or detail_cache_read
    cache_write = explicit_cache_write

    if prompt_tokens > 0:
        input_tokens = prompt_tokens
    else:
        input_tokens = raw_input_tokens + explicit_cache_read + explicit_cache_write

    raw_output_tokens = (
        _usage_int(usage, "completion_tokens")
        or _usage_int(usage, "output_tokens")
        or _usage_int(usage, "output")
        or _usage_int(usage, "outputTokens")
    )
    output_details = (
        _usage_field(usage, "completion_tokens_details")
        or _usage_field(usage, "output_tokens_details")
    )
    reasoning_tokens = (
        _usage_int(output_details, "reasoning_tokens")
        or _usage_int(usage, "reasoning_tokens")
    )
    output_tokens = max(0, raw_output_tokens - reasoning_tokens)

    total_tokens = (
        _usage_int(usage, "total_tokens")
        or _usage_int(usage, "totalTokens")
        or input_tokens + raw_output_tokens
    )
    if max(input_tokens, raw_output_tokens, total_tokens) <= 0:
        return None

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": total_tokens,
    }


def _usage_field(value, key, default=None):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    direct = getattr(value, key, default)
    if direct is not default:
        return direct
    extra = getattr(value, "model_extra", None)
    if isinstance(extra, dict) and key in extra:
        return extra.get(key, default)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return dumped.get(key, default)
    return default


def _usage_int(value, key):
    try:
        return int(_usage_field(value, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_context_overflow_error(error):
    if error is None:
        return False
    values = []
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.extend([
            str(current),
            str(getattr(current, "code", "") or ""),
            str(getattr(current, "type", "") or ""),
            str(getattr(current, "body", "") or ""),
        ])
        response = getattr(current, "response", None)
        if response is not None:
            values.extend([
                str(getattr(response, "text", "") or ""),
                str(getattr(response, "content", "") or ""),
            ])
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    text = " ".join(values).lower()
    patterns = (
        "context_length_exceeded",
        "maximum context length",
        "context window exceeded",
        "context window is exceeded",
        "exceeds the context window",
        "exceeded the context window",
        "exceeds the context length",
        "exceeded the context length",
        "context length exceeded",
        "context limit exceeded",
        "exceeds context limit",
        "exceeded context limit",
        "maximum number of tokens allowed",
        "input token count exceeds",
        "prompt is too long",
        "prompt too long",
        "input is too long",
        "input too long",
        "too many tokens",
        "token limit exceeded",
        "context token limit",
    )
    return any(pattern in text for pattern in patterns)


def _stream_usage_unsupported(error):
    text = str(error or "").lower()
    return "stream_options" in text or "include_usage" in text


def _estimate_history_chars(history):
    total = 0
    for message in history:
        try:
            total += len(json.dumps(message, ensure_ascii=False, default=str))
        except TypeError:
            total += len(str(message))
    return total


def _estimate_history_tokens(history):
    total = 0
    for message in history:
        try:
            serialized = json.dumps(message, ensure_ascii=False, default=str)
        except TypeError:
            serialized = str(message)
        total += _estimate_text_tokens(serialized) + 4
    return total


def _estimate_text_tokens(text):
    ascii_chars = 0
    non_ascii_tokens = 0
    for character in str(text or ""):
        if character.isspace():
            continue
        if ord(character) <= 0x7F:
            ascii_chars += 1
        else:
            non_ascii_tokens += 1
    return ((ascii_chars + 3) // 4) + non_ascii_tokens


def _clean_reasoning_text(content):
    return clean_thinking_text(content)


def _combine_reasoning_text(*parts):
    return _clean_reasoning_text("".join(str(part or "") for part in parts if part))


def _merge_reasoning_text(first, second):
    first = str(first or "")
    second = str(second or "")
    if not first:
        return second
    if not second:
        return first
    if second.startswith(first):
        return second
    if first.startswith(second):
        return first
    return first + second


def _split_tagged_think_text(content):
    text = str(content or "")
    if not text:
        return "", "", False

    open_pattern = re.compile(r"<\s*think\s*>", flags=re.IGNORECASE)
    close_pattern = re.compile(r"<\s*/\s*think\s*>", flags=re.IGNORECASE)
    partial_pattern = re.compile(
        r"<\s*/?\s*(?:t|th|thi|thin|think)?\s*$",
        flags=re.IGNORECASE,
    )

    content_parts = []
    thinking_parts = []
    position = 0
    in_thinking = False
    found_tag = False

    while position < len(text):
        if in_thinking:
            close_match = close_pattern.search(text, position)
            if close_match is None:
                thinking_parts.append(partial_pattern.sub("", text[position:]))
                break
            thinking_parts.append(text[position : close_match.start()])
            position = close_match.end()
            in_thinking = False
            found_tag = True
            continue

        open_match = open_pattern.search(text, position)
        close_match = close_pattern.search(text, position)

        if open_match is not None and (
            close_match is None or open_match.start() <= close_match.start()
        ):
            content_parts.append(text[position : open_match.start()])
            position = open_match.end()
            in_thinking = True
            found_tag = True
            continue

        if close_match is not None:
            content_parts.append(text[position : close_match.start()])
            position = close_match.end()
            found_tag = True
            continue

        tail = text[position:]
        cleaned_tail = partial_pattern.sub("", tail)
        if cleaned_tail != tail:
            found_tag = True
        content_parts.append(cleaned_tail)
        break

    return (
        "".join(content_parts),
        _clean_reasoning_text("".join(thinking_parts)),
        found_tag,
    )


def _clean_content_text(content):
    text = str(content or "")
    text = re.sub(
        r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"<\s*think\s*>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*/\s*think\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"<\s*/?\s*(?:t|th|thi|thin|think)?\s*$", "", text, flags=re.IGNORECASE
    )
    return text


def _single_line(text, max_chars):
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _error_text(message):
    return f"ERROR: {message}"
