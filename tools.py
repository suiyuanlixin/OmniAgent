import fnmatch
import heapq
import difflib
import ipaddress
import json
import queue
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from html.parser import HTMLParser
from pathlib import Path

from output import (
    TOOL_OUTPUT_LONG_LINE_CHARS,
    TOOL_OUTPUT_MAX_BYTES,
    TOOL_OUTPUT_MAX_LINES,
    ToolOutputStorageError,
    ToolOutputValue,
    ToolOutputWriter,
    artifact_uri,
    cleanup_tool_outputs,
    ensure_cleanup_thread,
    ensure_wrapped_view,
    finalize_tool_output,
    fits_tool_output,
    is_tool_output_path,
    resolve_artifact_uri,
)
from processes import process_group_options, terminate_process_tree
from todo import TodoStore
from skills import SkillRegistry
from ui import (
    add_edit_entry,
    add_question_entry,
    add_shell_entry,
    add_todo_entry,
    add_team_action_entry,
    add_web_fetch_entry,
    add_web_search_entry,
    add_write_entry,
    append_chat_status,
    build_tool_error_display,
    get_agent_confirmation,
    get_agent_choice,
    get_agent_choices,
    get_agent_diff_confirmation,
    get_agent_plan_confirmation,
    add_tool_error_entry,
    tool_display_is_error,
    tool_result_is_error,
)
from search import (
    DEFAULT_WEB_SEARCH_DEPTH,
    DEFAULT_WEB_SEARCH_ENABLE,
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_PROVIDER,
    DEFAULT_WEB_SEARCH_TOPIC,
    is_web_search_configured,
    normalize_tavily_search_depth,
    normalize_tavily_topic,
    normalize_web_search_provider,
    search_tavily,
)
from subagents import (
    DISPATCH_SUBAGENT_TOOL_NAME,
    MAX_SUBAGENT_TASKS_PER_BATCH,
    SubagentRegistry,
)
from team import (
    SPAWN_TEAMMATE_TOOL_NAME,
    LIST_TEAMMATES_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    READ_INBOX_TOOL_NAME,
    BROADCAST_TOOL_NAME,
    SHUTDOWN_TEAMMATE_TOOL_NAME,
    TEAM_TOOL_NAMES,
    display_teammate_name,
    teammate_has_write_tools,
)


DEFAULT_READ_LIMIT = TOOL_OUTPUT_MAX_LINES
MAX_READ_LINE_CHARS = TOOL_OUTPUT_LONG_LINE_CHARS
MAX_READ_BYTES = TOOL_OUTPUT_MAX_BYTES
MAX_GREP_MATCHES = 100
MAX_GLOB_MATCHES = 100
GENERIC_OUTPUT_EXEMPT_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "grep",
    "glob",
    "bash",
    DISPATCH_SUBAGENT_TOOL_NAME,
})
COMMAND_TIMEOUT_SECONDS = 60
GIT_TIMEOUT_SECONDS = 30
AGENT_APPROVAL_CONFIRM = "confirm"
AGENT_APPROVAL_APPROVE = "approve"
AGENT_APPROVAL_FULL = "full"
SUBMIT_PLAN_TOOL_NAME = "submit_plan"
PLAN_SUBAGENT_TYPES = frozenset({"reader", "researcher"})
PROGRAM_DOC_FILENAMES = ("README.md",)
WEB_FETCH_MAX_RESPONSE_BYTES = 1000000
WEB_FETCH_MAX_REDIRECTS = 5
NO_WORKSPACE_TOOLS = {
    "read_program_docs",
    "web_fetch",
    "web_search",
    "update_todo",
    "ask_user",
    SUBMIT_PLAN_TOOL_NAME,
    "read_file",
    "list_dir",
    "grep",
    "glob",
}
REFERENCE_ONLY_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "grep",
    "glob",
})

PLAN_MODE_ALLOWED_TOOLS = frozenset({
    "update_todo",
    "ask_user",
    SUBMIT_PLAN_TOOL_NAME,
    "dispatch_subagent",
    "read_file",
    "read_program_docs",
    "list_dir",
    "grep",
    "glob",
    "git_status",
    "git_diff",
    "web_fetch",
    "web_search",
    "list_skills",
    "read_skill",
})

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
}

PROGRAM_DOCS_TOOL_DEFINITION = {
    "name": "read_program_docs",
    "description": (
        "Read OmniAgent's built-in program documentation so the assistant can "
        "help users learn commands, configuration, agent mode, skills, and usage. "
        "This read-only tool only exposes approved documentation files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

WEB_FETCH_TOOL_DEFINITION = {
    "name": "web_fetch",
    "description": (
        "Fetch a single public HTTP/HTTPS URL and return extracted text or raw "
        "HTML/text. Use this when the user provides a specific webpage link. "
        "Blocks localhost, private, loopback, link-local, multicast, reserved, "
        "and other non-public addresses."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full public http:// or https:// URL to fetch.",
            },
            "extract_mode": {
                "type": "string",
                "enum": ["text", "raw"],
                "description": "text extracts readable page text; raw returns raw HTML/text. Defaults to text.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

SUBMIT_PLAN_TOOL_DEFINITION = {
    "name": SUBMIT_PLAN_TOOL_NAME,
    "description": (
        "Submit the main Agent's final implementation plan for user approval. "
        "This tool is available only to the main Agent in Plan mode. It displays the plan, "
        "asks whether the user allows it, and returns the decision. If allowed, OmniAgent "
        "switches to Build mode and the main Agent must immediately implement the approved plan."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "The complete final plan to display to the user for approval.",
            },
        },
        "required": ["plan"],
        "additionalProperties": False,
    },
}


ASK_USER_TOOL_DEFINITION = {
    "name": "ask_user",
    "description": (
        "Ask the user one important multiple-choice question, or a short batch of related questions, "
        "and return the selected option or typed answer for each. "
        "This tool is available in normal mode and in Agent Build/Plan mode. Use it instead of asking the user to "
        "choose from options in normal assistant text. "
        "Use only for uncertainty that materially affects goal, scope, tradeoffs, or acceptance "
        "criteria and cannot be resolved from local files, tools, or web facts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The single question to ask the user.",
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short option title shown on the first line.",
                        },
                        "detail": {
                            "type": "string",
                            "description": "Short explanation shown on the second line.",
                        },
                    },
                    "required": ["title", "detail"],
                },
                "description": "Two to eight mutually exclusive answer options with title and detail.",
            },
            "default_index": {
                "type": "integer",
                "description": "Optional 1-based default option index.",
            },
            "questions": {
                "type": "array",
                "description": "Optional batch of related multiple-choice questions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question to ask the user.",
                        },
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {
                                        "type": "string",
                                        "description": "Short option title shown on the first line.",
                                    },
                                    "detail": {
                                        "type": "string",
                                        "description": "Short explanation shown on the second line.",
                                    },
                                },
                                "required": ["title", "detail"],
                            },
                            "description": "Two to eight mutually exclusive answer options with title and detail.",
                        },
                        "default_index": {
                            "type": "integer",
                            "description": "Optional 1-based default option index.",
                        },
                    },
                    "required": ["question", "options"],
                },
            },
        },
    },
}

TOOL_DEFINITIONS = [
    {
        "name": "update_todo",
        "description": (
            "Replace the current task todo list with a full list of todo items. "
            "Use this for multi-step agent work. Supports dependencies, priorities, "
            "completion criteria, and blocked/failed states. Keep existing todo item "
            "ids until they are completed, blocked, or failed. At most one "
            "item may be in_progress."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": (
                        "The complete current todo item list. Preserve existing "
                        "items in this array until they are completed, blocked, or failed. "
                        "Use an empty array only when intentionally clearing an inactive todo list."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Short task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": [
                                    "pending",
                                    "in_progress",
                                    "completed",
                                    "blocked",
                                    "failed",
                                ],
                                "description": (
                                    "Current task state. blocked/failed require reason."
                                ),
                            },
                            "id": {
                                "type": "string",
                                "description": (
                                    "Stable id for dependencies, such as inspect, implement, verify."
                                ),
                            },
                            "priority": {
                                "type": "string",
                                "enum": [
                                    "p0",
                                    "p1",
                                    "p2",
                                    "p3",
                                    "high",
                                    "medium",
                                    "low",
                                ],
                                "description": (
                                    "Task priority. p0 is urgent, p1 high, p2 normal, p3 low."
                                ),
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Todo item ids that must be completed before this task can be "
                                    "in_progress or completed."
                                ),
                            },
                            "completion_criteria": {
                                "type": "array",
                                "items": {
                                    "oneOf": [
                                        {"type": "string"},
                                        {
                                            "type": "object",
                                            "properties": {
                                                "id": {
                                                    "type": "string",
                                                    "description": "Optional stable criterion id.",
                                                },
                                                "type": {
                                                    "type": "string",
                                                    "enum": [
                                                        "build",
                                                        "command",
                                                        "diff_check",
                                                        "file_change",
                                                        "file_exists",
                                                        "lint",
                                                        "manual",
                                                        "review",
                                                        "test",
                                                        "tool_output",
                                                    ],
                                                    "description": "Kind of evidence required.",
                                                },
                                                "target": {
                                                    "type": "string",
                                                    "description": (
                                                        "Command, file, diff check, or tool output "
                                                        "that should prove the condition."
                                                    ),
                                                },
                                                "expected": {
                                                    "type": "string",
                                                    "description": (
                                                        "Observable expected result, such as an exit "
                                                        "code, file state, or output phrase."
                                                    ),
                                                },
                                            },
                                        },
                                    ]
                                },
                                "description": (
                                    "Observable conditions required before this item may be "
                                    "considered done. Prefer structured objects with type, "
                                    "target, and expected."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": (
                                    "Required when status is blocked or failed. Explain the blocker "
                                    "or failure plainly."
                                ),
                            },
                            "verified": {
                                "type": "boolean",
                                "description": (
                                    "Whether the completion criteria were verified by tool output. "
                                    "Use only with completed todo items."
                                ),
                            },
                            "verification_note": {
                                "type": "string",
                                "description": (
                                    "Short evidence summary when verified is true, such as the "
                                    "test or diff check that passed."
                                ),
                            },
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    ASK_USER_TOOL_DEFINITION,
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace, a referenced file/folder, or an artifact:// tool-output URI using offset/limit pagination.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Workspace-relative/absolute file path, referenced path, or artifact:// tool-output URI.",
                },
                "reference": {
                    "type": "string",
                    "description": "Optional referenced folder label. Paths are relative to that read-only folder.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based first line to read. Defaults to 1.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "description": "Optional maximum number of lines to read. Defaults to 2000 and cannot exceed 2000.",
                },
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    PROGRAM_DOCS_TOOL_DEFINITION,
    WEB_FETCH_TOOL_DEFINITION,
    {
        "name": "list_dir",
        "description": "List files and directories under a workspace path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative or absolute directory path. Defaults to workspace root.",
                },
                "reference": {
                    "type": "string",
                    "description": "Optional referenced folder label. Paths are relative to that read-only folder.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to include nested entries. Defaults to false.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursive directory depth. Defaults to 2.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based first entry to return. Defaults to 1.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "description": "Optional maximum number of entries to return. Defaults to 2000 and cannot exceed 2000.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a UTF-8 text file in the configured workspace. Shows a unified diff before writing unless auto approval is enabled.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path or workspace-relative path to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write.",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Edit a text file by replacing an exact string. Shows a unified diff before writing unless auto approval is enabled.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path or workspace-relative path to edit.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence. Defaults to false for safer single edits.",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "apply_patch",
        "description": "Replace a 1-based inclusive line range in a text file. Shows a unified diff before writing unless auto approval is enabled.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path or workspace-relative path to edit.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-based first line to replace.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-based final line to replace.",
                },
                "new_content": {
                    "type": "string",
                    "description": "Replacement content for the selected line range. Empty string deletes the range.",
                },
            },
            "required": ["file_path", "start_line", "end_line", "new_content"],
        },
    },
    {
        "name": "apply_unified_patch",
        "description": "Apply a unified diff patch to one UTF-8 text file. Validates context lines and shows the resulting diff unless auto approval is enabled.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path or workspace-relative path to edit.",
                },
                "patch": {
                    "type": "string",
                    "description": "Unified diff for this file, including @@ hunk headers and +/-/space lines.",
                },
            },
            "required": ["file_path", "patch"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command inside the configured workspace. The command must exit; "
            "do not start foreground dev/static servers. Commands with obvious file writes "
            "or deletes require user confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to run from the workspace directory.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "local_http_check",
        "description": (
            "Start a temporary Python static HTTP server inside the workspace, request one "
            "or more local paths, then terminate the server before returning. Use this for "
            "static-site todo items like 'start static service + curl check 200' instead of "
            "running a foreground server with bash."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Workspace-relative directory to serve. Defaults to the workspace root.",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URL paths to request, such as ['/', '/settings']. Defaults to ['/'].",
                },
                "expected_status": {
                    "type": "integer",
                    "description": "Expected HTTP status for every path. Defaults to 200.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Total startup/request timeout in seconds, between 1 and 60. Defaults to 10.",
                },
            },
        },
    },
    {
        "name": "git_status",
        "description": "Show the workspace git status in short format. Read-only and does not require confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "git_diff",
        "description": "Show git diff output, diff stat, or diff whitespace checks for the workspace. Read-only and does not require confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional workspace-relative or absolute file path to limit the diff.",
                },
                "cached": {
                    "type": "boolean",
                    "description": "Show staged changes instead of unstaged changes. Defaults to false.",
                },
                "stat": {
                    "type": "boolean",
                    "description": "Return diff statistics instead of the full patch. Defaults to false.",
                },
                "check": {
                    "type": "boolean",
                    "description": "Run git diff --check to find whitespace/conflict-marker issues. Defaults to false.",
                },
            },
        },
    },
    {
        "name": "grep",
        "description": "Search workspace, referenced, or saved tool-output files with a regular expression. Returns at most 100 matches; narrow the path or pattern when results are limited.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Python regular expression to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative or absolute directory/file path to search.",
                },
                "reference": {
                    "type": "string",
                    "description": "Optional referenced folder label. Paths are relative to that read-only folder.",
                },
                "include": {
                    "type": "string",
                    "description": "Optional filename glob such as *.py.",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether matching is case-sensitive. Defaults to false.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "glob",
        "description": "Find files in the workspace by glob pattern. Returns at most 100 files; use a more specific pattern when results are limited.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Workspace-relative glob pattern, for example **/*.py.",
                },
                "reference": {
                    "type": "string",
                    "description": "Optional referenced folder label used as the read-only glob root.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
]


WEB_SEARCH_TOOL_DEFINITION = {
    "name": "web_search",
    "description": (
        "Search the public web with Tavily for current or external information. "
        "Use it for recent facts, releases, prices, laws, schedules, and source-backed answers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The web search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of search results to return. Defaults to the app setting.",
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "fast", "ultra-fast", "advanced"],
                "description": "Tavily search depth. basic/fast/ultra-fast cost 1 credit; advanced costs 2.",
            },
            "topic": {
                "type": "string",
                "enum": ["general", "news", "finance"],
                "description": "Search topic. Use news for current events and finance for market-related queries.",
            },
            "time_range": {
                "type": "string",
                "enum": ["day", "week", "month", "year", "d", "w", "m", "y"],
                "description": "Optional recency filter.",
            },
            "include_answer": {
                "type": "boolean",
                "description": "Whether Tavily should include its generated answer. Defaults to false.",
            },
            "include_raw_content": {
                "type": "boolean",
                "description": "Whether Tavily should include parsed page content. Use sparingly.",
            },
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domains to include.",
            },
            "exclude_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domains to exclude.",
            },
            "country": {
                "type": "string",
                "description": "Optional country boost for general search, such as united states or china.",
            },
        },
        "required": ["query"],
    },
}


SKILL_TOOL_DEFINITIONS = [
    {
        "name": "list_skills",
        "description": "List reusable agent skills available from enabled skill sources.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "read_skill",
        "description": (
            "Read a skill's SKILL.md instructions and optionally additional files from that skill directory. "
            "Call this before following a matching skill workflow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name, such as git-commit.",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional skill-relative files to read after SKILL.md.",
                },
            },
            "required": ["name"],
        },
    },
]


def _filter_tool_definition_list(definitions, only_tools=None, exclude_tools=None):
    if only_tools is None and exclude_tools is None:
        return definitions
    allowed = set(only_tools) if only_tools is not None else None
    excluded = set(exclude_tools or [])
    filtered = []
    for definition in definitions:
        name = definition.get("name")
        if allowed is not None and name not in allowed:
            continue
        if name in excluded:
            continue
        filtered.append(definition)
    return filtered


def tool_definitions(
    include_web_search=False,
    include_skills=False,
    include_plan=True,
    extra_definitions=None,
    only_tools=None,
    exclude_tools=None,
    plan_mode=False,
):
    definitions = [
        tool
        for tool in TOOL_DEFINITIONS
        if include_plan or tool["name"] != "update_todo"
    ]
    if include_skills:
        definitions.extend(SKILL_TOOL_DEFINITIONS)
    if include_web_search:
        definitions.append(WEB_SEARCH_TOOL_DEFINITION)
    if extra_definitions:
        definitions.extend(extra_definitions)
    if plan_mode:
        only_tools = (only_tools or set()) | PLAN_MODE_ALLOWED_TOOLS
        only_tools = only_tools & {d["name"] for d in definitions}
    return _filter_tool_definition_list(definitions, only_tools, exclude_tools)


def anthropic_tool_schemas(
    include_web_search=False,
    include_skills=False,
    include_plan=True,
    extra_definitions=None,
    only_tools=None,
    exclude_tools=None,
    plan_mode=False,
):
    return tool_definitions(
        include_web_search,
        include_skills,
        include_plan,
        extra_definitions=extra_definitions,
        only_tools=only_tools,
        exclude_tools=exclude_tools,
        plan_mode=plan_mode,
    )


def glm_tool_schemas(
    include_web_search=False,
    include_skills=False,
    include_plan=True,
    extra_definitions=None,
    only_tools=None,
    exclude_tools=None,
    plan_mode=False,
):
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in tool_definitions(
            include_web_search,
            include_skills,
            include_plan,
            extra_definitions=extra_definitions,
            only_tools=only_tools,
            exclude_tools=exclude_tools,
            plan_mode=plan_mode,
        )
    ]


def openai_tool_schemas(
    include_web_search=False,
    include_skills=False,
    include_plan=True,
    extra_definitions=None,
    only_tools=None,
    exclude_tools=None,
    plan_mode=False,
):
    return glm_tool_schemas(
        include_web_search,
        include_skills,
        include_plan,
        extra_definitions=extra_definitions,
        only_tools=only_tools,
        exclude_tools=exclude_tools,
        plan_mode=plan_mode,
    )


def ollama_tool_schemas(
    include_web_search=False,
    include_skills=False,
    include_plan=True,
    extra_definitions=None,
    only_tools=None,
    exclude_tools=None,
    plan_mode=False,
):
    return glm_tool_schemas(
        include_web_search,
        include_skills,
        include_plan,
        extra_definitions=extra_definitions,
        only_tools=only_tools,
        exclude_tools=exclude_tools,
        plan_mode=plan_mode,
    )


class AgentToolError(Exception):
    pass


class AgentTools:
    def __init__(
        self,
        workspace_dir=None,
        approval_mode=AGENT_APPROVAL_CONFIRM,
        visible_output_callback=None,
        web_search_enabled=DEFAULT_WEB_SEARCH_ENABLE,
        web_search_provider=DEFAULT_WEB_SEARCH_PROVIDER,
        web_search_api_key="",
        web_search_max_results=DEFAULT_WEB_SEARCH_MAX_RESULTS,
        web_search_depth=DEFAULT_WEB_SEARCH_DEPTH,
        web_search_topic=DEFAULT_WEB_SEARCH_TOPIC,
        todo_update_callback=None,
        todos_enabled=True,
        skills_enabled=True,
        skills_app_enabled=True,
        skills_workspace_enabled=False,
        skills_auto_catalog=True,
        stop_requested_callback=None,
        plan_mode=False,
    ):
        self.workspace_dir = normalize_workspace_dir(workspace_dir)
        self.visible_output_callback = visible_output_callback
        self.todos_enabled = bool(todos_enabled)
        self.plan_mode = bool(plan_mode)
        self.stop_requested_callback = stop_requested_callback
        self._tool_output_view_cache = OrderedDict()
        self._display_deferred = False
        cleanup_tool_outputs()
        ensure_cleanup_thread()
        self.todo_store = TodoStore(
            on_change=todo_update_callback if self.todos_enabled else None,
            todo_dir=_todo_dir_for_workspace(self.workspace_dir),
        )
        self.todo_update_callback = todo_update_callback
        self.max_tool_calls = None
        self.used_tool_calls = 0
        self.skill_registry = SkillRegistry(
            enabled=skills_enabled,
            app_enabled=skills_app_enabled,
            workspace_enabled=skills_workspace_enabled,
            workspace_dir=self.workspace_dir,
            auto_catalog=skills_auto_catalog,
        )
        self.subagent_registry = SubagentRegistry(
            workspace_dir=self.workspace_dir,
            skills_summary_provider=self.skills_catalog_prompt,
        )
        self.subagent_executor = None
        self.team_executor = None
        self.team_shutdown_executor = None
        self.team_store = None
        self.team_enabled = False
        self.set_approval_mode(approval_mode)
        self.set_web_search_config(
            web_search_enabled,
            web_search_provider,
            web_search_api_key,
            web_search_max_results,
            web_search_depth,
            web_search_topic,
        )
        self._display_payload = None
        self._submitted_plan_approved = None
        self.suppress_visible_output = False
        self._session_original_contents = {}
        self.reference_files = {}
        self.reference_folders = {}
        self.begin_agent_session(clear_todos=False)

    @property
    def enabled(self):
        return self.workspace_dir is not None

    @property
    def program_docs_available(self):
        return bool(_program_doc_paths())

    def set_workspace_dir(self, workspace_dir):
        self.workspace_dir = normalize_workspace_dir(workspace_dir)
        self.todo_store.set_todo_dir(
            _todo_dir_for_workspace(self.workspace_dir),
            load=True,
        )
        self.skill_registry.configure(workspace_dir=self.workspace_dir)
        self.subagent_registry.configure(workspace_dir=self.workspace_dir)

    def set_approval_mode(self, approval_mode):
        mode = str(approval_mode or AGENT_APPROVAL_CONFIRM).strip().lower()
        if mode not in {
            AGENT_APPROVAL_CONFIRM,
            AGENT_APPROVAL_APPROVE,
            AGENT_APPROVAL_FULL,
        }:
            mode = AGENT_APPROVAL_CONFIRM
        self.approval_mode = mode

    def set_stop_requested_callback(self, callback):
        self.stop_requested_callback = callback

    def set_visible_output_callback(self, callback):
        self.visible_output_callback = callback

    def set_todo_update_callback(self, callback):
        self.todo_update_callback = callback
        self.todo_store.set_on_change(callback if self.todos_enabled else None)

    def set_todos_enabled(self, enabled):
        self.todos_enabled = bool(enabled)
        self.todo_store.set_on_change(
            self.todo_update_callback if self.todos_enabled else None
        )

    def set_plan_mode(self, enabled):
        self.plan_mode = bool(enabled)

    def set_budget_context(self, max_tool_calls=None, used_tool_calls=0):
        if max_tool_calls is None:
            self.max_tool_calls = None
        else:
            self.max_tool_calls = max(1, int(max_tool_calls))
        self.used_tool_calls = max(0, int(used_tool_calls or 0))

    def set_skills_enabled(self, enabled):
        self.skill_registry.configure(enabled=enabled)

    def set_skills_config(
        self,
        enabled=None,
        app_enabled=None,
        workspace_enabled=None,
        auto_catalog=None,
    ):
        self.skill_registry.configure(
            enabled=enabled,
            app_enabled=app_enabled,
            workspace_enabled=workspace_enabled,
            workspace_dir=self.workspace_dir,
            auto_catalog=auto_catalog,
        )

    @property
    def skills_available(self):
        return bool(self.skill_registry.enabled)

    def skills_catalog_prompt(self):
        return self.skill_registry.catalog_prompt()

    def workspace_skills_usage_prompt(self):
        return self.skill_registry.workspace_usage_prompt()

    def set_subagent_executor(self, executor):
        self.subagent_executor = executor

    def set_team_executor(self, executor):
        self.team_executor = executor

    def set_team_shutdown_executor(self, executor):
        self.team_shutdown_executor = executor

    @property
    def subagents_available(self):
        return self.enabled and self.subagent_executor is not None

    def _available_subagent_names(self):
        names = self.subagent_registry.names()
        if not self.plan_mode:
            return names
        return [name for name in names if name in PLAN_SUBAGENT_TYPES]

    def _available_subagent_description(self):
        if not self.plan_mode:
            return self.subagent_registry.describe()
        lines = []
        for name in sorted(PLAN_SUBAGENT_TYPES):
            spec = self.subagent_registry.get(name)
            if spec is not None:
                lines.append(f"- {spec.name}: {spec.description}")
        return "\n".join(lines)

    def plan_tool_definitions(self):
        if not self.plan_mode:
            return []
        return [SUBMIT_PLAN_TOOL_DEFINITION]

    def subagent_tool_definitions(self):
        if not self.subagents_available:
            return []
        return [self._dispatch_subagent_tool_definition()]

    def consume_submitted_plan_approval(self):
        decision = self._submitted_plan_approved
        self._submitted_plan_approved = None
        return decision

    def set_team_config(self, team_store=None, team_enabled=False):
        self.team_store = team_store
        self.team_enabled = (
            bool(team_enabled) and self.enabled and team_store is not None
        )

    @property
    def team_available(self):
        return getattr(self, "team_enabled", False)

    def team_tool_definitions(self):
        if not self.team_available:
            return []
        return [
            self._spawn_teammate_tool_definition(),
            self._list_teammates_tool_definition(),
            self._send_message_tool_definition(),
            self._read_inbox_tool_definition(),
            self._broadcast_tool_definition(),
            self._shutdown_teammate_tool_definition(),
        ]

    def _dispatch_subagent_tool_definition(self):
        usage = (
            "Use this for independent research or code reading that would otherwise add "
            "bulky tool output to the main conversation."
            if self.plan_mode
            else
            "Use this for independent research, code reading, audit, or scoped "
            "implementation tasks that would otherwise add bulky tool output to the main "
            "conversation."
        )
        task_properties = {
            "agent_type": {
                "type": "string",
                "enum": self._available_subagent_names(),
                "description": "The subagent role to dispatch.",
            },
            "task": {
                "type": "string",
                "description": (
                    "The delegated task. Include enough local context, target files, "
                    "and the desired final-reply shape."
                ),
            },
            "purpose": {
                "type": "string",
                "description": "Optional short label used for terminal status output.",
            },
            "expected_output": {
                "type": "string",
                "description": "Optional specific deliverable or format.",
            },
            "evidence_required": {
                "type": "string",
                "description": (
                    "Optional evidence requirement, such as file paths, line numbers, "
                    "URLs, command output, or diff summaries."
                ),
            },
            "scope_limit": {
                "type": "string",
                "description": (
                    "Optional hard boundary, such as read-only, a directory, or files "
                    "the subagent must not touch."
                ),
            },
            "priority": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Optional execution priority group. Lower numbers run first; tasks "
                    "with the same priority run concurrently when allowed. This is an order "
                    "barrier, not a success dependency; later groups still run after failures. "
                    "Defaults to 1."
                ),
            },
        }
        return {
            "name": DISPATCH_SUBAGENT_TOOL_NAME,
            "description": (
                "Dispatch one or more focused subagents with independent histories and "
                "restricted tool whitelists. Lower priority numbers run first, and the next "
                "priority group waits for the current group to finish, even if that group has "
                "failures. Within one priority "
                "group, read-only tasks run concurrently; write-capable subagents run one at a "
                "time in tasks-array order and may overlap independent read-only work. The call "
                "returns after every subagent finishes. Each subagent's final reply is "
                "added back to the main context. "
                f"{usage} For non-trivial tasks, actively look for independent bounded parts "
                "that can be delegated together early instead of doing all exploration in "
                "the main context.\n\n"
                "Available agent_type values:\n"
                f"{self._available_subagent_description()}"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_SUBAGENT_TASKS_PER_BATCH,
                        "description": (
                            "Subagent tasks grouped by priority. Lower numbers run first; tasks "
                            "at the same priority follow the read/write concurrency rules."
                        ),
                        "items": {
                            "type": "object",
                            "properties": task_properties,
                            "required": ["agent_type", "task"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
        }

    def _spawn_teammate_tool_definition(self):
        store = self.team_store if self.team_available else None
        return {
            "name": SPAWN_TEAMMATE_TOOL_NAME,
            "description": (
                "Spawn a persistent teammate into the agent team and optionally assign an "
                "immediate task. Teammates have independent contexts and tool whitelists. "
                "The teammate starts as a background task and reports completion to the lead inbox. "
                "Use list_teammates and read_inbox to coordinate and collect results. Use this to parallelize "
                "work across different roles. Use implementer for application code and devops "
                "for CI, Docker, deployment, build, environment, or infrastructure work. "
                "Writing teammates require an explicit write_scope.\n\n"
                "Available teammate types:\n"
                f"{store.describe() if store else ''}"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "teammate_type": {
                        "type": "string",
                        "enum": store.names(include_aliases=True) if store else [],
                        "description": "The teammate role to spawn.",
                    },
                    "task": {
                        "type": "string",
                        "description": "The task to assign immediately after spawning.",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional short label for terminal output.",
                    },
                    "expected_output": {
                        "type": "string",
                        "description": "Optional specific deliverable or format.",
                    },
                    "evidence_required": {
                        "type": "string",
                        "description": "Optional evidence requirement.",
                    },
                    "scope_limit": {
                        "type": "string",
                        "description": "Optional natural-language hard boundary for the task.",
                    },
                    "write_scope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Workspace-relative paths or globs reserved for this task. "
                            "Required for any teammate with file-writing tools."
                        ),
                    },
                },
                "required": ["teammate_type", "task"],
            },
        }

    def _list_teammates_tool_definition(self):
        return {
            "name": LIST_TEAMMATES_TOOL_NAME,
            "description": "List all active teammates in the agent team with their status and task count.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        }

    def _send_message_tool_definition(self):
        return {
            "name": SEND_MESSAGE_TOOL_NAME,
            "description": (
                "Send a message to a teammate's inbox. The teammate will process the "
                "message on next wake. Use this for follow-up communication with teammates."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "teammate_name": {
                        "type": "string",
                        "description": "The name of the teammate to message.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message content to send.",
                    },
                },
                "required": ["teammate_name", "message"],
            },
        }

    def _read_inbox_tool_definition(self):
        return {
            "name": READ_INBOX_TOOL_NAME,
            "description": (
                "Read pending messages from the lead's inbox (replies from teammates). "
                "Optionally read from a specific teammate's inbox."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "teammate_name": {
                        "type": "string",
                        "description": "Optional teammate name. If omitted, reads the lead inbox.",
                    },
                    "clear": {
                        "type": "boolean",
                        "description": "Whether to clear messages after reading. Default false.",
                    },
                    "wait_seconds": {
                        "type": "number",
                        "description": "Optionally wait up to 30 seconds for a message before returning.",
                    },
                },
            },
        }

    def _broadcast_tool_definition(self):
        return {
            "name": BROADCAST_TOOL_NAME,
            "description": (
                "Broadcast a message to multiple teammates at once. "
                "Optionally specify which teammates to include."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to broadcast.",
                    },
                    "teammate_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of teammate names. Broadcasts to all if omitted.",
                    },
                },
                "required": ["message"],
            },
        }

    def _shutdown_teammate_tool_definition(self):
        return {
            "name": SHUTDOWN_TEAMMATE_TOOL_NAME,
            "description": (
                "Shutdown and remove a teammate from the active team. "
                "The teammate's thread history is preserved for future reference."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "teammate_name": {
                        "type": "string",
                        "description": "The name of the teammate to shutdown.",
                    },
                },
                "required": ["teammate_name"],
            },
        }

    def skills_status(self):
        return self.skill_registry.status()

    def set_web_search_config(
        self,
        enabled=None,
        provider=None,
        api_key=None,
        max_results=None,
        search_depth=None,
        topic=None,
    ):
        if enabled is not None:
            self.web_search_enabled = bool(enabled)
        elif not hasattr(self, "web_search_enabled"):
            self.web_search_enabled = DEFAULT_WEB_SEARCH_ENABLE
        if provider is not None:
            self.web_search_provider = normalize_web_search_provider(provider)
        elif not hasattr(self, "web_search_provider"):
            self.web_search_provider = DEFAULT_WEB_SEARCH_PROVIDER
        if api_key is not None:
            self.web_search_api_key = str(api_key or "").strip()
        elif not hasattr(self, "web_search_api_key"):
            self.web_search_api_key = ""
        if max_results is not None:
            self.web_search_max_results = _bounded_int(
                max_results,
                DEFAULT_WEB_SEARCH_MAX_RESULTS,
                1,
                20,
                "web_search_max_results",
            )
        elif not hasattr(self, "web_search_max_results"):
            self.web_search_max_results = DEFAULT_WEB_SEARCH_MAX_RESULTS
        if search_depth is not None:
            self.web_search_depth = normalize_tavily_search_depth(search_depth)
        elif not hasattr(self, "web_search_depth"):
            self.web_search_depth = DEFAULT_WEB_SEARCH_DEPTH
        if topic is not None:
            self.web_search_topic = normalize_tavily_topic(topic)
        elif not hasattr(self, "web_search_topic"):
            self.web_search_topic = DEFAULT_WEB_SEARCH_TOPIC

    @property
    def web_search_available(self):
        return self.web_search_enabled and is_web_search_configured(
            self.web_search_provider,
            self.web_search_api_key,
        )

    def web_search_status(self):
        return {
            "enabled": self.web_search_enabled,
            "available": self.web_search_available,
            "provider": self.web_search_provider,
            "max_results": self.web_search_max_results,
            "search_depth": self.web_search_depth,
            "topic": self.web_search_topic,
        }

    def search_web(self, query, **kwargs):
        payload = {"query": query, **kwargs}
        return self._web_search(payload)

    def begin_agent_session(self, clear_todos=True):
        if clear_todos and self.todos_enabled:
            self.todo_store.clear()
        self.session_changed_files = []
        self._session_changed_file_set = set()
        self._session_original_contents = {}
        self.session_mutating_commands = []
        self.output_needs_separator = False

    def set_reference_folders(self, folders=None):
        self.reference_folders = {
            str(name): Path(path).resolve(strict=True)
            for name, path in dict(folders or {}).items()
        }

    def set_reference_files(self, files=None):
        self.reference_files = {
            str(name): Path(path).resolve(strict=True)
            for name, path in dict(files or {}).items()
        }

    def has_reference_access(self):
        return bool(self.reference_files or self.reference_folders)

    def clear_reference_files(self):
        self.reference_files = {}

    def clear_reference_folders(self):
        self.reference_folders = {}

    def consume_output_separator(self):
        needs_separator = self.output_needs_separator
        self.output_needs_separator = False
        return needs_separator

    def session_has_changes(self):
        return bool(self.session_changed_files or self.session_mutating_commands)

    def session_change_count(self):
        return len(self.session_changed_files) + len(self.session_mutating_commands)

    def todo_revision(self):
        return self.todo_store.revision

    def todo_status(self):
        status = self.todo_store.status(
            max_tool_calls=self.max_tool_calls,
            used_tool_calls=self.used_tool_calls,
        )
        status["enabled"] = self.todos_enabled
        if not self.todos_enabled:
            status["active_items"] = []
            status["quality_warnings"] = []
        return status

    def todo_summary(self, include_completed=True):
        if not self.todos_enabled:
            return "(todo disabled)"
        return self.todo_store.summary(include_completed=include_completed)

    def todo_incomplete_summary(self):
        if not self.todos_enabled:
            return "(todo disabled)"
        return self.todo_store.incomplete_summary()

    def has_incomplete_todos(self):
        return self.todos_enabled and self.todo_store.has_incomplete()

    def has_unverified_completed_todos(self):
        return (
            self.todos_enabled and self.todo_store.has_unverified_completed_criteria()
        )

    def todo_actionable_summary(self):
        if not self.todos_enabled:
            return "(todo disabled)"
        return self.todo_store.actionable_summary()

    def todo_quality_report(self):
        if not self.todos_enabled:
            return "Todo disabled."
        return self.todo_store.quality_report(
            max_tool_calls=self.max_tool_calls,
            used_tool_calls=self.used_tool_calls,
        )

    def todo_budget_summary(self):
        if not self.todos_enabled:
            return ""
        return self.todo_store.budget_summary(
            max_tool_calls=self.max_tool_calls,
            used_tool_calls=self.used_tool_calls,
        )

    def todo_history(self, limit=20):
        return self.todo_store.history_tail(limit)

    def retry_todo(self, todo_id, reason=""):
        return self.todo_store.retry_todo(todo_id, reason=reason)

    def unblock_todo(self, todo_id, reason=""):
        return self.todo_store.unblock_todo(todo_id, reason=reason)

    def apply_todo_final_verification(self, passed, check_result):
        if not self.todos_enabled:
            return False
        return self.todo_store.apply_final_verification(
            passed,
            _final_verification_note(check_result, passed),
        )

    def clear_todos(self):
        self.todo_store.clear()

    def session_summary(self):
        parts = []
        if self.session_changed_files:
            parts.append("Changed files: " + ", ".join(self.session_changed_files))
        if self.session_mutating_commands:
            parts.append(
                "Mutating commands: "
                + "; ".join(
                    command
                    for command in self.session_mutating_commands
                )
            )
        return "\n".join(parts)

    def changed_files_summary(self):
        result = []
        for display_path in self.session_changed_files:
            file_path = self._resolve_path(display_path)
            if not file_path.exists():
                continue
            current = file_path.read_text(encoding="utf-8", errors="replace")
            original = self._session_original_contents.get(display_path, "")
            if original == current:
                continue
            diff = _unified_diff_text(original, current, display_path)
            additions, deletions = _diff_stats(diff)
            result.append({
                "file_path": display_path,
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
            })
        return result

    def final_check(self):
        if not self.enabled:
            return _error_result("No workspace directory")

        sections = []
        diff_scope = "workspace"
        diff_path_args = []
        if self.session_changed_files and not self.session_mutating_commands:
            diff_scope = "agent-edited files"
            diff_path_args = ["--"] + self.session_changed_files

        if self.session_changed_files:
            sections.append(
                "Agent-edited files:\n"
                + "\n".join(f"- {path}" for path in self.session_changed_files)
            )
        if self.session_mutating_commands:
            sections.append(
                "Agent mutating commands:\n"
                + "\n".join(
                    f"- {command}"
                    for command in self.session_mutating_commands
                )
            )

        sections.append(
            f"git diff --check ({diff_scope}):\n"
            + self._run_git_command(
                ["diff", "--check"] + diff_path_args, "(no whitespace errors)"
            )
        )
        sections.append(
            "git status --short:\n"
            + self._run_git_command(["status", "--short"], "(working tree clean)")
        )
        sections.append(
            f"git diff --stat ({diff_scope}):\n"
            + self._run_git_command(
                ["diff", "--stat"] + diff_path_args, "(no tracked diff)"
            )
        )
        return "\n\n".join(sections)

    def final_check_passed(self, check_result):
        return _final_check_passed(check_result)

    def finalize_internal_output(self, name, text):
        return self._finalize_tool_output(name, text, allow_subagent_hint=True)

    def _is_tool_output_path(self, path):
        return is_tool_output_path(path)

    def _ensure_wrapped_view(self, path, has_long_line=None):
        return ensure_wrapped_view(
            path,
            cache=self._tool_output_view_cache,
            has_long_line=has_long_line,
        )

    def _requests_tool_output_path(self, name, tool_input):
        if name not in {"read_file", "grep"} or not isinstance(tool_input, dict):
            return False
        key = "file_path" if name == "read_file" else "path"
        path_text = str(tool_input.get(key) or "").strip()
        if not path_text:
            return False
        artifact_path = resolve_artifact_uri(path_text)
        if artifact_path is not None:
            return self._is_tool_output_path(artifact_path)
        if not _looks_absolute(path_text):
            return False
        return self._is_tool_output_path(Path(path_text))

    def _finalize_tool_output(self, name, text, allow_subagent_hint=True):
        record_mode = ""
        if name == "git_diff":
            record_mode = "diff"
        elif name == "web_search":
            record_mode = "search"
        return finalize_tool_output(
            text,
            strategy="head_tail",
            record_mode=record_mode,
            allow_subagent_hint=(
                bool(allow_subagent_hint) and self.subagents_available
            ),
            view_cache=self._tool_output_view_cache,
        )

    def _sync_display_payload_result(self, name, result):
        if not isinstance(self._display_payload, dict):
            return
        visible_result = str(result or "")
        kind = self._display_payload.get("kind")
        if kind == "shell":
            self._display_payload["output"] = visible_result
            return
        if kind != "team_action":
            return
        artifact_result = visible_result.startswith("[Tool output")
        if self._display_payload.get("status") == "error":
            self._display_payload["details"] = visible_result
            if artifact_result:
                metadata = dict(self._display_payload.get("metadata") or {})
                metadata.pop("error", None)
                self._display_payload["metadata"] = metadata
            return
        if artifact_result and name in {LIST_TEAMMATES_TOOL_NAME, READ_INBOX_TOOL_NAME}:
            self._display_payload["details"] = visible_result
            metadata = dict(self._display_payload.get("metadata") or {})
            metadata.pop("roster", None)
            metadata.pop("messages", None)
            self._display_payload["metadata"] = metadata

    def _emit_deferred_display(self):
        if not self._display_deferred:
            return
        self._display_deferred = False
        if self.suppress_visible_output or not isinstance(self._display_payload, dict):
            return
        payload = self._display_payload
        kind = payload.get("kind")
        self._before_visible_output()
        if kind == "shell":
            add_shell_entry(
                str(payload.get("command") or ""),
                str(payload.get("output") or ""),
            )
        elif kind == "team_action":
            add_team_action_entry(
                str(payload.get("action") or "team"),
                str(payload.get("summary") or ""),
                str(payload.get("details") or ""),
                str(payload.get("status") or "success"),
                dict(payload.get("metadata") or {}),
            )
        elif kind == "tool_error":
            add_tool_error_entry(payload)

    def _promote_tool_error_display(
        self, name, tool_input, result, *, was_error=False
    ):
        if not was_error:
            return result
        visible_result = str(result or "")
        if not tool_display_is_error(self._display_payload):
            self._display_payload = build_tool_error_display(
                name, tool_input, visible_result
            )
            self._display_deferred = True
        if not tool_result_is_error(name, visible_result):
            visible_result = (
                f"ERROR: {visible_result}"
                if visible_result
                else "ERROR: Tool call failed."
            )
        return visible_result

    def _finish_deferred_display(self, name, result):
        if tool_result_is_error(name, result, self._display_payload) and not (
            tool_display_is_error(self._display_payload)
        ):
            self._display_deferred = False
            return
        self._emit_deferred_display()

    def _finish_tool_result(
        self, name, result, tool_input=None, allow_subagent_hint=True
    ):
        was_error = tool_result_is_error(name, result, self._display_payload)
        try:
            if name not in GENERIC_OUTPUT_EXEMPT_TOOLS:
                result = self._finalize_tool_output(
                    name, result, allow_subagent_hint=allow_subagent_hint
                )
        except ToolOutputStorageError as error:
            result = _error_result(
                "Tool output could not be preserved by the Artifact store: " + str(error)
            )
            was_error = True
        self._sync_display_payload_result(name, result)
        result = self._promote_tool_error_display(
            name, tool_input, result, was_error=was_error
        )
        self._finish_deferred_display(name, result)
        return result

    def _finish_tool_error(
        self, name, result, tool_input=None, allow_subagent_hint=True
    ):
        try:
            if name != DISPATCH_SUBAGENT_TOOL_NAME:
                result = self._finalize_tool_output(
                    name, result, allow_subagent_hint=allow_subagent_hint
                )
        except ToolOutputStorageError as error:
            result = _error_result(
                "Tool error output could not be preserved by the Artifact store: "
                + str(error)
            )
        self._sync_display_payload_result(name, result)
        result = self._promote_tool_error_display(
            name, tool_input, result, was_error=True
        )
        self._finish_deferred_display(name, result)
        return result

    def execute(self, name, tool_input, allow_subagent_hint=True):
        try:
            self._display_payload = None
            self._display_deferred = False
            self._submitted_plan_approved = None
            if isinstance(tool_input, str):
                tool_input = json.loads(tool_input or "{}")
            if not isinstance(tool_input, dict):
                raise AgentToolError("Tool input must be an object.")
            if not self.enabled and name not in NO_WORKSPACE_TOOLS:
                return self._finish_tool_error(
                    name,
                    _error_result("No workspace directory"),
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            if (
                not self.enabled
                and name in REFERENCE_ONLY_TOOLS
                and not self.has_reference_access()
                and not self._requests_tool_output_path(name, tool_input)
            ):
                return self._finish_tool_error(
                    name,
                    _error_result(
                        "Tool is unavailable unless the user explicitly referenced a file or folder in this request."
                    ),
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            if name == SUBMIT_PLAN_TOOL_NAME and not allow_subagent_hint:
                return self._finish_tool_error(
                    name,
                    _error_result("submit_plan is available only to the main Agent."),
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            if name == SUBMIT_PLAN_TOOL_NAME and not self.plan_mode:
                return self._finish_tool_error(
                    name,
                    _error_result("submit_plan is available only in Plan mode."),
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            if self.plan_mode and name not in PLAN_MODE_ALLOWED_TOOLS:
                return self._finish_tool_error(
                    name,
                    _error_result(
                        f"Tool '{name}' is not available in Plan mode (read-only). "
                        "Switch to Build mode to use modification tools."
                    ),
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            handlers = {
                "update_todo": self._update_todo,
                "ask_user": self._ask_user,
                SUBMIT_PLAN_TOOL_NAME: self._submit_plan,
                "read_file": self._read_file,
                "read_program_docs": self._read_program_docs,
                "web_fetch": self._web_fetch,
                "list_dir": self._list_dir,
                "write_file": self._write_file,
                "edit_file": self._edit_file,
                "apply_patch": self._apply_patch,
                "apply_unified_patch": self._apply_unified_patch,
                "bash": self._bash,
                "local_http_check": self._local_http_check,
                "git_status": self._git_status,
                "git_diff": self._git_diff,
                "grep": self._grep,
                "glob": self._glob,
                "web_search": self._web_search,
                "list_skills": self._list_skills,
                "read_skill": self._read_skill,
                DISPATCH_SUBAGENT_TOOL_NAME: self._dispatch_subagent,
                SPAWN_TEAMMATE_TOOL_NAME: self._spawn_teammate,
                LIST_TEAMMATES_TOOL_NAME: self._list_teammates,
                SEND_MESSAGE_TOOL_NAME: self._send_message,
                READ_INBOX_TOOL_NAME: self._read_inbox,
                BROADCAST_TOOL_NAME: self._broadcast,
                SHUTDOWN_TEAMMATE_TOOL_NAME: self._shutdown_teammate,
            }
            handler = handlers.get(name)
            if handler is None:
                raise AgentToolError(f"Unknown tool: {name}")
            plan_gate_result = self._todo_action_gate(name, tool_input)
            if plan_gate_result is not None:
                return self._finish_tool_result(
                    name,
                    plan_gate_result,
                    tool_input=tool_input,
                    allow_subagent_hint=allow_subagent_hint,
                )
            result = handler(tool_input)
            return self._finish_tool_result(
                name,
                result,
                tool_input=tool_input,
                allow_subagent_hint=allow_subagent_hint,
            )
        except Exception as error:
            result = _error_result(str(error))
            if name in TEAM_TOOL_NAMES:
                try:
                    self._set_team_action_display(
                        name,
                        f"{name} failed",
                        str(error),
                        status="error",
                        metadata={"error": str(error)},
                    )
                except Exception:
                    self._display_payload = None
            return self._finish_tool_error(
                name,
                result,
                tool_input=tool_input,
                allow_subagent_hint=allow_subagent_hint,
            )

    def consume_display_payload(self):
        payload = self._display_payload
        self._display_payload = None
        return payload

    def _todo_display_items(self):
        items = []
        for item in self.todo_store.items:
            if getattr(item, "system", False):
                continue
            items.append({
                "id": str(getattr(item, "id", "") or ""),
                "content": str(getattr(item, "content", "") or ""),
                "status": str(getattr(item, "status", "") or ""),
                "priority": str(getattr(item, "priority", "") or ""),
                "verified": bool(getattr(item, "verified", False)),
                "reason": str(getattr(item, "reason", "") or ""),
            })
        return items

    @staticmethod
    def _todo_display_summary(items):
        items = [item for item in list(items or []) if isinstance(item, dict)]
        total = len(items)
        completed = sum(
            1 for item in items if str(item.get("status") or "") == "completed"
        )
        in_progress_content = next(
            (
                str(item.get("content") or "")
                for item in items
                if str(item.get("status") or "") == "in_progress"
            ),
            "",
        )
        return {
            "total": total,
            "completed": completed,
            "in_progress_content": in_progress_content,
            "has_blocked": any(
                str(item.get("status") or "") == "blocked" for item in items
            ),
            "has_failed": any(
                str(item.get("status") or "") == "failed" for item in items
            ),
        }

    def _todo_display_payload(self):
        items = self._todo_display_items()
        return {
            "kind": "todo",
            "summary": self._todo_display_summary(items),
            "items": items,
        }

    def _update_todo(self, tool_input):
        items = tool_input.get("items")
        self.todo_store.update(items)
        self._display_payload = self._todo_display_payload()
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_todo_entry(
                self._display_payload.get("items", []),
                self._display_payload.get("summary"),
            )
        return self.todo_store.tool_result(
            max_tool_calls=self.max_tool_calls,
            used_tool_calls=self.used_tool_calls,
        )

    def _submit_plan(self, tool_input):
        unknown = sorted(set(tool_input) - {"plan"})
        if unknown:
            raise AgentToolError(
                "Unsupported submit_plan parameter(s): " + ", ".join(unknown)
            )
        plan = _required_string(tool_input, "plan").strip()
        self._before_visible_output()
        approved = bool(get_agent_plan_confirmation(plan))
        self._submitted_plan_approved = approved
        self._display_payload = {
            "kind": "plan",
            "plan": plan,
            "approved": approved,
        }
        if approved:
            return (
                "The user allowed this plan. Build mode is now active. "
                "Begin implementing the approved plan immediately."
            )
        return (
            "The user did not allow this plan. Remain in Plan mode and do not implement it."
        )

    def _ask_user(self, tool_input):
        questions = _ask_user_questions(tool_input)
        self._before_visible_output()
        if len(questions) == 1:
            item = questions[0]
            selected_index, selected_text = get_agent_choice(
                item["question"],
                item["options"],
                default_index=item["default_index"],
            )
            if selected_index <= 0:
                self._display_payload = None
                self._display_user_rejection("Rejected by user: question.")
                return "User cancelled question."
            add_question_entry(item["question"], selected_text)
            self._display_payload = {
                "kind": "ask_user",
                "entries": [
                    {
                        "question": item["question"],
                        "answer": selected_text,
                    }
                ],
            }
            return f"User selected option {selected_index}: {selected_text}"

        answers = get_agent_choices(questions)
        if not answers:
            self._display_payload = None
            self._display_user_rejection("Rejected by user: question batch.")
            return "User cancelled question batch."
        entries = []
        response_lines = []
        for index, (item, answer) in enumerate(zip(questions, answers), 1):
            _, selected_text = answer
            add_question_entry(item["question"], selected_text)
            entries.append({
                "question": item["question"],
                "answer": selected_text,
            })
            response_lines.append(f"{index}. {selected_text}")
        self._display_payload = {
            "kind": "ask_user",
            "entries": entries,
        }
        return "User answers:\n" + "\n".join(response_lines)

    def _read_file(self, tool_input):
        allowed = {"file_path", "reference", "offset", "limit"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported read_file parameter(s): " + ", ".join(unknown)
            )
        file_path = self._resolve_read_path(
            _required_string(tool_input, "file_path"),
            tool_input.get("reference"),
            allow_tool_output=True,
        )
        if not file_path.is_file():
            raise AgentToolError(
                f"File does not exist: {self._display_path(file_path)}"
            )

        offset = _optional_positive_int(tool_input, "offset") or 1
        requested_limit = _optional_positive_int(tool_input, "limit") or DEFAULT_READ_LIMIT
        if requested_limit > DEFAULT_READ_LIMIT:
            raise AgentToolError(
                f"limit cannot exceed {DEFAULT_READ_LIMIT}."
            )

        def read_line_preview(source):
            fragment = source.readline(MAX_READ_LINE_CHARS + 2)
            if fragment == "":
                return None
            preview_parts = []
            total_chars = 0
            ended = fragment.endswith("\n")
            content = fragment[:-1] if ended else fragment
            if content.endswith("\r"):
                content = content[:-1]
            total_chars += len(content)
            preview_parts.append(content[:MAX_READ_LINE_CHARS])
            while not ended:
                fragment = source.readline(8192)
                if fragment == "":
                    break
                ended = fragment.endswith("\n")
                content = fragment[:-1] if ended else fragment
                if content.endswith("\r"):
                    content = content[:-1]
                total_chars += len(content)
                preview_chars = sum(len(part) for part in preview_parts)
                if preview_chars < MAX_READ_LINE_CHARS:
                    preview_parts.append(
                        content[: MAX_READ_LINE_CHARS - preview_chars]
                    )
            preview = "".join(preview_parts)[:MAX_READ_LINE_CHARS]
            return preview, total_chars > MAX_READ_LINE_CHARS

        page = []
        used_bytes = 0
        line_number = 0
        eof = False
        has_more = False
        next_offset = None
        long_line_seen = False
        with file_path.open(
            "r", encoding="utf-8", errors="replace", newline=None
        ) as source:
            while line_number < offset - 1:
                item = read_line_preview(source)
                if item is None:
                    eof = True
                    break
                line_number += 1
            if not eof:
                while len(page) < requested_limit:
                    item = read_line_preview(source)
                    if item is None:
                        eof = True
                        break
                    line_number += 1
                    preview, is_long = item
                    long_line_seen = long_line_seen or is_long
                    if is_long:
                        preview += "... [line continues in the wrapped view]"
                    rendered = f"{line_number}: {preview}"
                    size = len(rendered.encode("utf-8")) + (1 if page else 0)
                    if used_bytes + size > MAX_READ_BYTES:
                        has_more = True
                        next_offset = line_number
                        break
                    page.append((line_number, preview))
                    used_bytes += size
                if not eof and not has_more and len(page) >= requested_limit:
                    lookahead = read_line_preview(source)
                    if lookahead is None:
                        eof = True
                    else:
                        has_more = True
                        next_offset = page[-1][0] + 1
                        long_line_seen = long_line_seen or lookahead[1]

        if not page:
            if offset == 1 and line_number == 0 and eof:
                display_path = self._display_path(file_path)
                return (
                    f"File: {display_path}\nLines: 0\n\n(empty file)\n\n"
                    "(End of file - total 0 lines)"
                )
            if eof and line_number < offset:
                raise AgentToolError(
                    f"Offset {offset} is out of range for this file ({line_number} lines)."
                )

        display_path = self._display_path(file_path)
        view_path = self._ensure_wrapped_view(file_path, has_long_line=True) if long_line_seen else None
        view_notice = (
            f"\nReadable wrapped view for long lines: {self._display_path(view_path)}"
            if view_path is not None
            else ""
        )
        while page:
            body = "\n".join(f"{number}: {line}" for number, line in page)
            first_line = page[0][0]
            last_line = page[-1][0]
            if has_more:
                next_offset = next_offset or last_line + 1
                status = (
                    f"Showing lines {first_line}-{last_line}. "
                    f"Use offset={next_offset} to continue."
                )
                line_summary = f"Lines: {first_line}-{last_line}"
            else:
                total_lines = line_number
                status = f"End of file - total {total_lines} lines"
                line_summary = f"Lines: {first_line}-{last_line} of {total_lines}"
            result = (
                f"File: {display_path}\n"
                f"{line_summary}{view_notice}\n\n"
                f"{body}\n\n({status})"
            )
            if fits_tool_output(result):
                return result
            if len(page) == 1:
                return finalize_tool_output(
                    result,
                    strategy="head_tail",
                    allow_subagent_hint=False,
                    view_cache=self._tool_output_view_cache,
                )
            removed_line = page.pop()[0]
            has_more = True
            next_offset = removed_line

    def _read_program_docs(self, tool_input):
        unknown = sorted(set(tool_input))
        if unknown:
            raise AgentToolError(
                "Unsupported read_program_docs parameter(s): " + ", ".join(unknown)
            )
        paths = _program_doc_paths()
        if not paths:
            raise AgentToolError("Program documentation is not available.")

        writer = ToolOutputWriter()
        writer.write("Program documentation:\n\n")
        for index, path in enumerate(paths):
            if index:
                writer.write("\n\n")
            try:
                size = path.stat().st_size
                writer.write(f"File: {path.name}\nBytes: {size}\n\n")
                with path.open("r", encoding="utf-8", errors="replace") as source:
                    while True:
                        chunk = source.read(8192)
                        if not chunk:
                            break
                        if writer.write(chunk) is False:
                            break
                    if writer.storage_limited:
                        break
            except OSError as error:
                raise AgentToolError(
                    f"Failed to read program documentation: {path.name}"
                ) from error
        return writer.finalize(
            strategy="head_tail",
            allow_subagent_hint=self.subagents_available,
            view_cache=self._tool_output_view_cache,
        )

    def _web_fetch(self, tool_input):
        allowed = {"url", "extract_mode"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported web_fetch parameter(s): " + ", ".join(unknown)
            )
        url = _required_string(tool_input, "url")
        extract_mode = str(tool_input.get("extract_mode") or "text").strip().lower()
        if extract_mode not in {"text", "raw"}:
            raise AgentToolError("extract_mode must be text or raw.")
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_web_fetch_entry(url)
        self._display_payload = {
            "kind": "web_fetch",
            "url": url,
        }
        try:
            result = _fetch_public_webpage(url, extract_mode)
        except Exception as error:
            self._display_payload = {
                "kind": "web_fetch",
                "url": url,
                "error": str(error),
            }
            return _error_result(str(error))
        return result

    def _list_dir(self, tool_input):
        allowed = {"path", "reference", "recursive", "max_depth", "offset", "limit"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported list_dir parameter(s): " + ", ".join(unknown)
            )
        root = self._resolve_read_path(
            str(tool_input.get("path") or "."), tool_input.get("reference")
        )
        if not root.exists():
            raise AgentToolError(f"Path does not exist: {self._display_path(root)}")
        if not root.is_dir():
            raise AgentToolError(f"Path is not a directory: {self._display_path(root)}")

        recursive = _optional_bool(tool_input, "recursive", False)
        max_depth = _optional_positive_int(tool_input, "max_depth") or 2
        offset = _optional_positive_int(tool_input, "offset") or 1
        requested_limit = _optional_positive_int(tool_input, "limit") or DEFAULT_READ_LIMIT
        if requested_limit > DEFAULT_READ_LIMIT:
            raise AgentToolError(f"limit cannot exceed {DEFAULT_READ_LIMIT}.")

        def iter_entries():
            if recursive:
                for current_root, dirnames, filenames in os.walk(root):
                    current_path = Path(current_root)
                    depth = len(current_path.relative_to(root).parts)
                    dirnames[:] = [
                        name
                        for name in sorted(dirnames)
                        if name not in SKIP_DIRS and depth < max_depth
                    ]
                    for dirname in dirnames:
                        yield f"{self._display_path(current_path / dirname)}/"
                    for filename in sorted(filenames):
                        yield self._display_path(current_path / filename)
                return
            for child in root.iterdir():
                if child.name in SKIP_DIRS:
                    continue
                yield self._display_path(child) + ("/" if child.is_dir() else "")

        total_entries = 0

        def counted_entries():
            nonlocal total_entries
            for entry in iter_entries():
                total_entries += 1
                yield entry

        page_end = offset - 1 + requested_limit
        selected = heapq.nsmallest(page_end, counted_entries(), key=str.lower)
        if offset > total_entries and not (total_entries == 0 and offset == 1):
            raise AgentToolError(
                f"Offset {offset} is out of range for this directory ({total_entries} entries)."
            )
        page = selected[offset - 1 : page_end]
        display_path = self._display_path(root)
        if not page:
            return f"Directory: {display_path}\nEntries: 0\n\n(empty directory)"

        while page:
            last_entry = offset + len(page) - 1
            if last_entry < total_entries:
                status = (
                    f"Showing entries {offset}-{last_entry} of {total_entries}. "
                    f"Use offset={last_entry + 1} to continue."
                )
            else:
                status = f"End of directory - total {total_entries} entries"
            result = (
                f"Directory: {display_path}\n"
                f"Entries: {offset}-{last_entry} of {total_entries}\n\n"
                + "\n".join(page)
                + f"\n\n({status})"
            )
            if fits_tool_output(result):
                return result
            if len(page) == 1:
                return finalize_tool_output(
                    result,
                    strategy="head_tail",
                    allow_subagent_hint=False,
                    view_cache=self._tool_output_view_cache,
                )
            page.pop()

    def _write_file(self, tool_input):
        file_path = self._resolve_path(_required_string(tool_input, "file_path"))
        content = _required_string(tool_input, "content", allow_empty=True)
        action = "overwrite" if file_path.exists() else "create"
        old_content = (
            file_path.read_text(encoding="utf-8", errors="replace")
            if file_path.exists()
            else ""
        )
        diff = _unified_diff_text(old_content, content, self._display_path(file_path))

        if not self._confirm_diff(
            f"Allow agent to {action} file?",
            self._display_path(file_path),
            diff or f"(no content changes, {len(content)} characters)",
            "file_edit",
        ):
            additions, deletions = _diff_stats(diff)
            self._display_payload = {
                "kind": "file_write",
                "file_path": self._display_path(file_path),
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "status": "rejected",
            }
            self._before_visible_output()
            if not self.suppress_visible_output:
                add_write_entry(
                    self._display_path(file_path),
                    additions,
                    deletions,
                    diff,
                    status="rejected",
                )
            return _error_result("User rejected write_file.")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        self._record_changed_file(file_path, old_content)
        additions, deletions = _diff_stats(diff)
        self._display_payload = {
            "kind": "file_write",
            "file_path": self._display_path(file_path),
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_write_entry(self._display_path(file_path), additions, deletions, diff)
        return f"Wrote {len(content)} characters to {self._display_path(file_path)}."

    def _edit_file(self, tool_input):
        file_path = self._resolve_path(_required_string(tool_input, "file_path"))
        old_string = _required_string(tool_input, "old_string")
        new_string = _required_string(tool_input, "new_string", allow_empty=True)
        replace_all = _optional_bool(tool_input, "replace_all", False)

        if not file_path.is_file():
            raise AgentToolError(
                f"File does not exist: {self._display_path(file_path)}"
            )

        content = file_path.read_text(encoding="utf-8", errors="replace")
        occurrences = content.count(old_string)
        if occurrences == 0:
            raise AgentToolError("old_string was not found in the file.")
        if occurrences > 1 and not replace_all:
            raise AgentToolError(
                f"old_string occurs {occurrences} times. Set replace_all=true or provide a more specific string."
            )

        replace_count = occurrences if replace_all else 1
        updated = content.replace(old_string, new_string, replace_count)
        diff = _unified_diff_text(content, updated, self._display_path(file_path))

        if not self._confirm_diff(
            f"Allow agent to edit file? ({replace_count} replacement(s))",
            self._display_path(file_path),
            diff,
            "file_edit",
        ):
            additions, deletions = _diff_stats(diff)
            self._display_payload = {
                "kind": "file_edit",
                "file_path": self._display_path(file_path),
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "status": "rejected",
            }
            self._before_visible_output()
            if not self.suppress_visible_output:
                add_edit_entry(
                    self._display_path(file_path),
                    additions,
                    deletions,
                    diff,
                    status="rejected",
                )
            return _error_result("User rejected edit_file.")

        file_path.write_text(updated, encoding="utf-8")
        self._record_changed_file(file_path, content)
        additions, deletions = _diff_stats(diff)
        self._display_payload = {
            "kind": "file_edit",
            "file_path": self._display_path(file_path),
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_edit_entry(self._display_path(file_path), additions, deletions, diff)
        return (
            f"Edited {self._display_path(file_path)} ({replace_count} replacement(s))."
        )

    def _apply_patch(self, tool_input):
        file_path = self._resolve_path(_required_string(tool_input, "file_path"))
        start_line = _required_positive_int(tool_input, "start_line")
        end_line = _required_positive_int(tool_input, "end_line")
        new_content = _required_string(tool_input, "new_content", allow_empty=True)

        if not file_path.is_file():
            raise AgentToolError(
                f"File does not exist: {self._display_path(file_path)}"
            )
        if end_line < start_line:
            raise AgentToolError(
                "end_line must be greater than or equal to start_line."
            )

        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if start_line > len(lines) or end_line > len(lines):
            raise AgentToolError(
                f"Line range exceeds file length ({len(lines)} lines)."
            )

        old_lines = lines[start_line - 1 : end_line]
        new_lines = new_content.splitlines()
        old_display = _format_lines(old_lines, start_line, True)
        new_display = (
            _format_lines(new_lines, start_line, True)
            if new_lines
            else "(delete selected lines)"
        )
        updated_lines = lines[: start_line - 1] + new_lines + lines[end_line:]
        newline = _detect_newline(content)
        updated = newline.join(updated_lines)
        if content.endswith(("\n", "\r")):
            updated += newline
        diff = _unified_diff_text(content, updated, self._display_path(file_path))

        if not self._confirm_diff(
            f"Allow agent to patch file? (lines {start_line}-{end_line})",
            self._display_path(file_path),
            diff or f"Old lines:\n{old_display}\n\nNew lines:\n{new_display}",
            "file_edit",
        ):
            additions, deletions = _diff_stats(diff)
            self._display_payload = {
                "kind": "file_edit",
                "file_path": self._display_path(file_path),
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "status": "rejected",
            }
            self._before_visible_output()
            if not self.suppress_visible_output:
                add_edit_entry(
                    self._display_path(file_path),
                    additions,
                    deletions,
                    diff,
                    status="rejected",
                )
            return _error_result("User rejected apply_patch.")

        file_path.write_text(updated, encoding="utf-8")
        self._record_changed_file(file_path, content)
        additions, deletions = _diff_stats(diff)
        self._display_payload = {
            "kind": "file_edit",
            "file_path": self._display_path(file_path),
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_edit_entry(self._display_path(file_path), additions, deletions, diff)
        return (
            f"Patched {self._display_path(file_path)} (lines {start_line}-{end_line})."
        )

    def _apply_unified_patch(self, tool_input):
        file_path = self._resolve_path(_required_string(tool_input, "file_path"))
        patch = _required_string(tool_input, "patch")

        if not file_path.is_file():
            raise AgentToolError(
                f"File does not exist: {self._display_path(file_path)}"
            )

        content = file_path.read_text(encoding="utf-8", errors="replace")
        updated = _apply_unified_diff_to_content(content, patch)
        diff = _unified_diff_text(content, updated, self._display_path(file_path))

        if not self._confirm_diff(
            "Allow agent to apply unified patch?",
            self._display_path(file_path),
            diff or patch,
            "file_edit",
        ):
            additions, deletions = _diff_stats(diff)
            self._display_payload = {
                "kind": "file_edit",
                "file_path": self._display_path(file_path),
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "status": "rejected",
            }
            self._before_visible_output()
            if not self.suppress_visible_output:
                add_edit_entry(
                    self._display_path(file_path),
                    additions,
                    deletions,
                    diff,
                    status="rejected",
                )
            return _error_result("User rejected apply_unified_patch.")

        file_path.write_text(updated, encoding="utf-8")
        self._record_changed_file(file_path, content)
        additions, deletions = _diff_stats(diff)
        self._display_payload = {
            "kind": "file_edit",
            "file_path": self._display_path(file_path),
            "additions": additions,
            "deletions": deletions,
            "diff": diff,
        }
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_edit_entry(self._display_path(file_path), additions, deletions, diff)
        return f"Applied unified patch to {self._display_path(file_path)}."

    def _run_shell_stream(self, command, timeout_seconds):
        popen_options = {
            "cwd": str(self.workspace_dir),
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        popen_options.update(process_group_options())
        process = subprocess.Popen(command, **popen_options)
        writer = ToolOutputWriter()
        reader_error = []
        reader_done = threading.Event()
        storage_stop = threading.Event()
        saw_output = False

        def read_output():
            nonlocal saw_output
            try:
                if process.stdout is None:
                    return
                while True:
                    chunk = process.stdout.read(4096)
                    if not chunk:
                        break
                    saw_output = True
                    if not writer.write(chunk):
                        storage_stop.set()
                        break
            except Exception as error:
                reader_error.append(error)
            finally:
                reader_done.set()

        reader = threading.Thread(
            target=read_output,
            name="omni-shell-output",
            daemon=True,
        )
        reader.start()
        timed_out = False
        aborted = False
        storage_limited = False
        termination_status = "not-needed"
        termination_detail = ""
        deadline = time.monotonic() + timeout_seconds
        return_code = None

        def terminate_bounded():
            result = terminate_process_tree(process)
            return result.return_code, result.status, result.detail

        try:
            while True:
                return_code = process.poll()
                if return_code is not None:
                    break
                if callable(self.stop_requested_callback) and self.stop_requested_callback():
                    aborted = True
                    return_code, termination_status, termination_detail = terminate_bounded()
                    break
                if storage_stop.is_set():
                    storage_limited = True
                    return_code, termination_status, termination_detail = terminate_bounded()
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    return_code, termination_status, termination_detail = terminate_bounded()
                    break
                time.sleep(0.05)
        finally:
            reader.join(timeout=5)
            reader_stuck = reader.is_alive()
            if reader_stuck and process.stdout is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
                reader.join(timeout=1)
                reader_stuck = reader.is_alive()
            if process.poll() is None:
                fallback_code, fallback_status, fallback_detail = terminate_bounded()
                return_code = fallback_code
                if termination_status == "not-needed":
                    termination_status = fallback_status
                    termination_detail = fallback_detail

        return {
            "return_code": return_code,
            "writer": writer,
            "saw_output": saw_output,
            "timed_out": timed_out,
            "aborted": aborted,
            "storage_limited": storage_limited or writer.storage_limited,
            "termination_status": termination_status,
            "termination_detail": termination_detail,
            "reader_stuck": reader_stuck,
            "capture_error": str(reader_error[0]) if reader_error else "",
        }

    def _bash(self, tool_input):
        command = _required_string(tool_input, "command")
        self._validate_command_scope(command)

        risk_level, risk_reason = _command_risk(command)
        if risk_level == "blocked":
            raise AgentToolError(f"Command blocked: {risk_reason}")
        foreground_server_reason = _foreground_server_command_reason(command)
        if foreground_server_reason:
            return _error_result(
                f"{foreground_server_reason}. The bash tool only runs commands that exit. "
                "For local HTTP checks, use a bounded script that starts the server as a "
                "subprocess, performs the request, and terminates the server before exiting."
            )
        if risk_level == "confirm" and not self._confirm(
            "Allow agent to run a command?",
            f"{risk_reason}\n{command}",
            risk_reason,
        ):
            result = _error_result("User rejected bash command.")
            self._display_payload = {
                "kind": "shell",
                "command": command,
                "output": "Rejected by user.",
            }
            self._display_deferred = True
            return _error_result("User rejected bash command.")

        shell_result = self._run_shell_stream(command, COMMAND_TIMEOUT_SECONDS)
        if (
            risk_level == "confirm"
            and risk_reason != "script or shell execution detected"
        ):
            self._record_mutating_command(command)
        writer = shell_result["writer"]
        if not shell_result["saw_output"]:
            writer.write("(no output)")
        shell_metadata = [f"Exit code: {shell_result['return_code']}"]
        if shell_result["timed_out"]:
            shell_metadata.append(
                f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds."
            )
        if shell_result["aborted"]:
            shell_metadata.append("User aborted the command.")
        if shell_result["storage_limited"]:
            shell_metadata.append(
                "Command stopped because output reached the internal artifact storage safety limit."
            )
        termination_status = shell_result.get("termination_status") or "not-needed"
        if termination_status == "terminated":
            shell_metadata.append("Process tree termination confirmed.")
        elif termination_status == "terminated-after-tree-error":
            shell_metadata.append(
                "Process exited, but the process-tree termination command reported an error."
            )
        elif termination_status == "force-killed":
            shell_metadata.append("Process required force-kill after bounded termination wait.")
        elif termination_status == "unconfirmed":
            shell_metadata.append("Process termination could not be confirmed.")
        if shell_result.get("termination_detail") and termination_status != "not-needed":
            shell_metadata.append(
                "Termination detail: " + str(shell_result["termination_detail"])
            )
        if shell_result.get("reader_stuck"):
            shell_metadata.append("Shell output reader did not exit cleanly.")
        if shell_result["capture_error"] and not shell_result["storage_limited"]:
            shell_metadata.append(
                "Failed to capture shell output: " + shell_result["capture_error"]
            )
        suffix = (
            "\n\n<shell_metadata>\n"
            + "\n".join(shell_metadata)
            + "\n</shell_metadata>"
        )
        result = writer.finalize(
            strategy="tail",
            allow_subagent_hint=False,
            view_cache=self._tool_output_view_cache,
            suffix=suffix,
        )
        self._display_payload = {
            "kind": "shell",
            "command": command,
            "output": result,
        }
        self._display_deferred = True
        return result

    def _local_http_check(self, tool_input):
        root = self._resolve_path(str(tool_input.get("root") or "."))
        if not root.is_dir():
            raise AgentToolError(f"root is not a directory: {self._display_path(root)}")

        paths = _http_check_paths(tool_input.get("paths"))
        expected_status = _bounded_int(
            tool_input.get("expected_status"),
            200,
            100,
            599,
            "expected_status",
        )
        timeout_seconds = _bounded_int(
            tool_input.get("timeout_seconds"),
            10,
            1,
            60,
            "timeout_seconds",
        )
        port = _free_local_port()
        command = [
            sys.executable or "python",
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
        ]
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_group_options(),
        )

        try:
            _wait_for_local_port(process, port, timeout_seconds)
            lines = [
                f"Served {self._display_path(root)} at http://127.0.0.1:{port}",
                f"Expected status: {expected_status}",
            ]
            passed = True
            deadline = time.monotonic() + timeout_seconds
            for path in paths:
                remaining = max(0.5, min(5, deadline - time.monotonic()))
                url_path = _normalize_http_path(path)
                url = f"http://127.0.0.1:{port}{url_path}"
                status, detail = _request_http_status(url, remaining)
                ok = status == expected_status
                passed = passed and ok
                status_text = str(status) if status is not None else "no response"
                suffix = "OK" if ok else "FAILED"
                if detail:
                    lines.append(f"{suffix} {url_path} -> {status_text} ({detail})")
                else:
                    lines.append(f"{suffix} {url_path} -> {status_text}")
            result = "\n".join(lines)
            if not passed:
                result = _error_result(result)
            else:
                result = "Local HTTP check passed.\n" + result
            cmd_str = " ".join(command) + f" (serving {self._display_path(root)})"
            self._display_payload = {
                "kind": "shell",
                "command": cmd_str,
                "output": result,
            }
            self._display_deferred = True
            return result
        finally:
            _terminate_process(process)

    def _git_status(self, tool_input):
        args = ["status", "--short"]
        result = self._run_git_command(args, "(working tree clean)")
        cmd_str = "git " + " ".join(args)
        self._display_payload = {
            "kind": "shell",
            "command": cmd_str,
            "output": result,
        }
        self._display_deferred = True
        return result

    def _git_diff(self, tool_input):
        cached = _optional_bool(tool_input, "cached", False)
        stat = _optional_bool(tool_input, "stat", False)
        check = _optional_bool(tool_input, "check", False)
        if stat and check:
            raise AgentToolError("Use either stat=true or check=true, not both.")

        args = ["diff"]
        if cached:
            args.append("--cached")
        if check:
            args.append("--check")
            empty_message = "(no whitespace errors)"
        elif stat:
            args.append("--stat")
            empty_message = "(no tracked diff)"
        else:
            empty_message = "(no tracked diff)"

        file_path = tool_input.get("file_path")
        if file_path:
            resolved = self._resolve_path(file_path)
            args.extend(["--", str(resolved.relative_to(self.workspace_dir))])

        result = self._run_git_command(
            args,
            empty_message,
            record_mode="diff" if not stat and not check else "",
        )
        cmd_str = "git " + " ".join(args)
        self._display_payload = {
            "kind": "shell",
            "command": cmd_str,
            "output": result,
        }
        self._display_deferred = True
        records = _git_diff_records(result) if not stat and not check else ()
        return ToolOutputValue(text=result, records=records, record_mode="diff")

    def _grep(self, tool_input):
        ripgrep = shutil.which("rg")
        if ripgrep:
            return self._grep_ripgrep(tool_input, ripgrep)
        return self._grep_python(tool_input)

    def _grep_ripgrep(self, tool_input, ripgrep):
        allowed = {"pattern", "path", "reference", "include", "case_sensitive"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported grep parameter(s): " + ", ".join(unknown)
            )
        pattern = _required_string(tool_input, "pattern")
        search_path = self._resolve_read_path(
            str(tool_input.get("path") or "."),
            tool_input.get("reference"),
            allow_tool_output=True,
        )
        include = str(tool_input.get("include") or "*")
        case_sensitive = _optional_bool(tool_input, "case_sensitive", False)
        command = [
            ripgrep,
            "--json",
            "--no-config",
            "--color=never",
            "--glob",
            include,
        ]
        for skipped in sorted(SKIP_DIRS):
            command.extend(["--glob", f"!{skipped}/**"])
        if not case_sensitive:
            command.append("--ignore-case")
        command.extend(["--", pattern, str(search_path)])

        process = subprocess.Popen(
            command,
            cwd=str(self.workspace_dir or search_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        output_queue = queue.Queue(maxsize=64)
        reader_done = threading.Event()
        reader_stop = threading.Event()

        def enqueue_output(line):
            while not reader_stop.is_set():
                try:
                    output_queue.put(line, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def read_events():
            try:
                if process.stdout is None:
                    return
                for line in process.stdout:
                    if not enqueue_output(line):
                        break
            finally:
                reader_done.set()

        reader = threading.Thread(
            target=read_events,
            name="omni-ripgrep-output",
            daemon=True,
        )
        reader.start()
        matches = []
        diagnostics = deque(maxlen=20)
        deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
        limited = False
        try:
            while True:
                if len(matches) > MAX_GREP_MATCHES:
                    limited = True
                    reader_stop.set()
                    process.terminate()
                    break
                if time.monotonic() >= deadline:
                    reader_stop.set()
                    process.kill()
                    raise AgentToolError(
                        f"grep timed out after {GIT_TIMEOUT_SECONDS} seconds."
                    )
                try:
                    raw_event = output_queue.get(timeout=0.1)
                except queue.Empty:
                    if reader_done.is_set() and output_queue.empty():
                        break
                    continue
                try:
                    event = json.loads(raw_event)
                except ValueError:
                    detail = raw_event.strip()
                    if detail:
                        diagnostics.append(detail)
                    continue
                if event.get("type") != "match":
                    continue
                data = event.get("data") or {}
                path_text = str((data.get("path") or {}).get("text") or "")
                line_text = str((data.get("lines") or {}).get("text") or "")
                line = line_text.rstrip("\r\n")
                line_number = int(data.get("line_number") or 0)
                submatches = data.get("submatches") or []
                first = submatches[0] if submatches else {}
                byte_start = int(first.get("start") or 0)
                byte_end = int(first.get("end") or byte_start)
                encoded = line.encode("utf-8")
                char_start = len(encoded[:byte_start].decode("utf-8", errors="ignore"))
                char_end = len(encoded[:byte_end].decode("utf-8", errors="ignore"))
                context_before = 220
                context_after = 280
                excerpt_start = max(0, char_start - context_before)
                excerpt_end = min(len(line), char_end + context_after)
                excerpt = line[excerpt_start:excerpt_end]
                if excerpt_start > 0:
                    excerpt = "..." + excerpt
                if excerpt_end < len(line):
                    excerpt += "..."
                candidate = Path(path_text)
                if not candidate.is_absolute():
                    candidate = (self.workspace_dir or search_path.parent) / candidate
                candidate = candidate.resolve(strict=False)
                view_path = None
                if len(line) > MAX_READ_LINE_CHARS:
                    view_path = self._ensure_wrapped_view(
                        candidate, has_long_line=True
                    )
                matches.append({
                    "text": (
                        f"{self._display_path(candidate)}:{line_number}:{char_start + 1}: "
                        f"{excerpt}"
                    ),
                    "source_path": candidate,
                    "view_path": view_path,
                })
        finally:
            reader_stop.set()
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception:
                        pass
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            reader.join(timeout=2)

        if not matches:
            if diagnostics and process.returncode not in {0, 1, None}:
                raise AgentToolError("ripgrep failed: " + " ".join(diagnostics))
            return "No matches found."
        results_limited = limited or len(matches) > MAX_GREP_MATCHES
        visible_matches = matches[:MAX_GREP_MATCHES]
        return self._format_grep_matches(visible_matches, results_limited)

    def _format_grep_matches(self, visible_matches, results_limited):
        while visible_matches:
            sections = ["\n".join(item["text"] for item in visible_matches)]
            wrapped_views = {}
            for item in visible_matches:
                view_path = item.get("view_path")
                if view_path is not None:
                    wrapped_views[str(item["source_path"])] = view_path
            if wrapped_views:
                sections.append(
                    "Readable wrapped views for long matching lines:\n"
                    + "\n".join(
                        f"- {self._display_path(Path(source_path))}: "
                        f"{self._display_path(view_path)}"
                        for source_path, view_path in wrapped_views.items()
                    )
                )
            if results_limited:
                sections.append(
                    "Results limited. Use a more specific path, include glob, or pattern."
                )
            result = "\n\n".join(sections)
            if fits_tool_output(result):
                return result
            results_limited = True
            visible_matches.pop()
        return "Results limited. Use a more specific path, include glob, or pattern."

    def _grep_python(self, tool_input):
        allowed = {"pattern", "path", "reference", "include", "case_sensitive"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported grep parameter(s): " + ", ".join(unknown)
            )
        pattern = _required_string(tool_input, "pattern")
        search_path = self._resolve_read_path(
            str(tool_input.get("path") or "."),
            tool_input.get("reference"),
            allow_tool_output=True,
        )
        include = str(tool_input.get("include") or "*")
        case_sensitive = _optional_bool(tool_input, "case_sensitive", False)
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            regex = re.compile(pattern, flags)
        except re.error as error:
            raise AgentToolError(f"Invalid regex: {error}") from error

        files = (
            [search_path] if search_path.is_file() else self._iter_files(search_path)
        )
        matches = []
        for file_path in files:
            if len(matches) > MAX_GREP_MATCHES:
                break
            if not fnmatch.fnmatch(file_path.name, include):
                continue
            try:
                source = file_path.open(
                    "r", encoding="utf-8", errors="replace", newline=None
                )
            except Exception:
                continue
            try:
                for line_number, raw_line in enumerate(source, 1):
                    line = raw_line.rstrip("\r\n")
                    match = regex.search(line)
                    if match is None:
                        continue
                    column = match.start() + 1
                    context_before = 220
                    context_after = 280
                    excerpt_start = max(0, match.start() - context_before)
                    excerpt_end = min(len(line), match.end() + context_after)
                    excerpt = line[excerpt_start:excerpt_end]
                    if excerpt_start > 0:
                        excerpt = "..." + excerpt
                    if excerpt_end < len(line):
                        excerpt += "..."
                    view_path = None
                    if len(matches) < MAX_GREP_MATCHES and len(line) > MAX_READ_LINE_CHARS:
                        view_path = self._ensure_wrapped_view(file_path, has_long_line=True)
                    matches.append({
                        "text": (
                            f"{self._display_path(file_path)}:{line_number}:{column}: "
                            f"{excerpt}"
                        ),
                        "source_path": file_path.resolve(strict=False),
                        "view_path": view_path,
                    })
                    if len(matches) > MAX_GREP_MATCHES:
                        break
            finally:
                source.close()

        if not matches:
            return "No matches found."

        results_limited = len(matches) > MAX_GREP_MATCHES
        visible_matches = matches[:MAX_GREP_MATCHES]
        return self._format_grep_matches(visible_matches, results_limited)

    def _glob(self, tool_input):
        allowed = {"pattern", "reference"}
        unknown = sorted(set(tool_input) - allowed)
        if unknown:
            raise AgentToolError(
                "Unsupported glob parameter(s): " + ", ".join(unknown)
            )
        pattern = _required_string(tool_input, "pattern")
        if _has_parent_reference(pattern):
            raise AgentToolError(
                "Glob pattern cannot contain parent directory references."
            )
        reference = str(tool_input.get("reference") or "").strip()
        if reference:
            if _looks_absolute(pattern):
                raise AgentToolError(
                    "Referenced-folder glob patterns must be relative."
                )
            root = self._reference_root(reference)
            candidates = root.glob(pattern)
        elif _looks_absolute(pattern):
            root = self._resolve_path(pattern)
            candidates = iter([root] if root.exists() else [])
        else:
            candidates = self.workspace_dir.glob(pattern)

        def safe_files():
            for path in candidates:
                try:
                    resolved = path.resolve(strict=False)
                    if reference:
                        self._ensure_inside_root(resolved, root)
                    else:
                        self._ensure_inside_workspace(resolved)
                except AgentToolError:
                    continue
                if resolved.is_file():
                    yield self._display_path(resolved)

        safe_matches = heapq.nsmallest(
            MAX_GLOB_MATCHES + 1,
            safe_files(),
            key=str.lower,
        )
        if not safe_matches:
            return "No files found."

        results_limited = len(safe_matches) > MAX_GLOB_MATCHES
        visible_matches = safe_matches[:MAX_GLOB_MATCHES]
        while visible_matches:
            result = "\n".join(visible_matches)
            if results_limited:
                result += "\n\n(Results limited. Use a more specific path or pattern.)"
            if fits_tool_output(result):
                return result
            results_limited = True
            visible_matches.pop()

        return "Results limited. Use a more specific path or pattern."

    def _list_skills(self, tool_input):
        return self.skill_registry.list_for_tool()

    def _read_skill(self, tool_input):
        name = _required_string(tool_input, "name")
        writer = ToolOutputWriter()
        self.skill_registry.write_skill(name, tool_input.get("files"), writer)
        return writer.finalize(
            strategy="head_tail",
            allow_subagent_hint=self.subagents_available,
            view_cache=self._tool_output_view_cache,
        )

    def _dispatch_subagent(self, tool_input):
        if self.subagent_executor is None:
            raise AgentToolError("Subagent dispatch is not available.")

        unexpected = sorted(set(tool_input) - {"tasks"})
        if unexpected:
            raise AgentToolError(
                "dispatch_subagent only accepts the tasks array. Unexpected top-level "
                f"fields: {', '.join(unexpected)}."
            )
        if "tasks" not in tool_input:
            raise AgentToolError("dispatch_subagent requires the tasks array.")
        raw_tasks = tool_input["tasks"]
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise AgentToolError("dispatch_subagent requires a non-empty tasks array.")
        if len(raw_tasks) > MAX_SUBAGENT_TASKS_PER_BATCH:
            raise AgentToolError(
                f"dispatch_subagent accepts at most {MAX_SUBAGENT_TASKS_PER_BATCH} tasks per batch."
            )

        tasks = []
        allowed_task_fields = {
            "agent_type",
            "task",
            "purpose",
            "expected_output",
            "evidence_required",
            "scope_limit",
            "priority",
        }
        for index, raw_task in enumerate(raw_tasks, start=1):
            if not isinstance(raw_task, dict):
                raise AgentToolError(f"Subagent task {index} must be an object.")
            unexpected = sorted(set(raw_task) - allowed_task_fields)
            if unexpected:
                raise AgentToolError(
                    f"Subagent task {index} has unexpected fields: "
                    + ", ".join(unexpected)
                    + "."
                )
            agent_type = _required_string(raw_task, "agent_type")
            task = _required_string(raw_task, "task")
            priority = raw_task.get("priority", 1)
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or priority < 1
            ):
                raise AgentToolError(
                    f"Subagent task {index} priority must be a positive integer."
                )
            spec = self.subagent_registry.get(agent_type)
            if spec is None:
                raise AgentToolError(
                    "Unknown subagent "
                    f"{agent_type!r}. Available: "
                    + ", ".join(self._available_subagent_names())
                )
            if self.plan_mode and spec.name not in PLAN_SUBAGENT_TYPES:
                raise AgentToolError(
                    "Plan mode only allows reader and researcher subagents. "
                    f"Requested: {agent_type!r}."
                )
            tasks.append({
                "agent_type": agent_type,
                "task": task,
                "purpose": str(raw_task.get("purpose") or "").strip(),
                "expected_output": str(raw_task.get("expected_output") or "").strip(),
                "evidence_required": str(raw_task.get("evidence_required") or "").strip(),
                "scope_limit": str(raw_task.get("scope_limit") or "").strip(),
                "priority": priority,
            })

        return self.subagent_executor(tasks=tasks)

    def _set_team_action_display(
        self,
        action,
        summary,
        details="",
        *,
        status="success",
        metadata=None,
    ):
        self._display_payload = {
            "kind": "team_action",
            "action": str(action or "team"),
            "summary": str(summary or ""),
            "details": str(details or ""),
            "status": str(status or "success"),
            "metadata": dict(metadata or {}),
        }
        self._display_deferred = True

    def _spawn_teammate(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled. Enable it with /team on.")
        teammate_type = _required_string(tool_input, "teammate_type")
        task = _required_string(tool_input, "task")
        spec = self.team_store.get_spec(teammate_type)
        if spec is None:
            raise AgentToolError(
                f"Unknown teammate type {teammate_type!r}. Available: "
                + ", ".join(self.team_store.names(include_aliases=True))
            )
        purpose = str(tool_input.get("purpose") or "").strip()
        expected_output = str(tool_input.get("expected_output") or "").strip()
        evidence_required = str(tool_input.get("evidence_required") or "").strip()
        scope_limit = str(tool_input.get("scope_limit") or "").strip()
        raw_write_scope = tool_input.get("write_scope")
        try:
            write_scope = self.team_store.normalize_write_scope(raw_write_scope)
        except ValueError as error:
            raise AgentToolError(str(error)) from error
        if teammate_has_write_tools(spec) and not write_scope:
            raise AgentToolError(
                f"Teammate '{spec.name}' has file-writing tools and requires a non-empty write_scope."
            )
        if self.team_executor is None:
            raise AgentToolError("Team executor is not configured.")
        launch = self.team_executor(
            spec=spec,
            task=task,
            purpose=purpose,
            expected_output=expected_output,
            evidence_required=evidence_required,
            scope_limit=scope_limit,
            write_scope=write_scope,
        )
        if isinstance(launch, dict):
            display = launch.get("display")
            result = str(launch.get("result") or "Teammate task started.")
            if isinstance(display, dict):
                self._display_payload = display
            elif result.startswith("ERROR:"):
                self._set_team_action_display(
                    "spawn_teammate",
                    f"Failed to start {display_teammate_name(spec.name)}",
                    result,
                    status="error",
                    metadata={"teammate_name": spec.name},
                )
            return result
        return str(launch or "Teammate task started.")

    def _list_teammates(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled.")
        roster = self.team_store.get_roster()
        if not roster:
            result = "No active teammates."
            self._set_team_action_display("list_teammates", result)
            return result
        writer = ToolOutputWriter()
        writer.write("Active teammates:\n")
        for teammate in roster:
            line = (
                f"- {display_teammate_name(teammate.get('name', ''))} "
                f"({teammate.get('role', '?')}) [{teammate.get('status', 'unknown')}] "
                f"tasks: {teammate.get('task_count', 0)}"
            )
            task_id = str(teammate.get("task_id") or "")
            if task_id:
                line += f" task_id={task_id}"
            if writer.write(line + "\n") is False:
                break
        result = writer.finalize(
            strategy="head_tail",
            allow_subagent_hint=False,
            view_cache=self._tool_output_view_cache,
        )
        teammate_count = len(roster)
        teammate_label = "teammate" if teammate_count == 1 else "teammates"
        self._set_team_action_display(
            "list_teammates",
            f"{teammate_count} active {teammate_label}",
            result,
            metadata={"count": len(roster), "roster": roster},
        )
        return result

    def _send_message(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled.")
        teammate_name = _required_string(tool_input, "teammate_name")
        message = _required_string(tool_input, "message")
        if not self.team_store.is_active(teammate_name):
            raise AgentToolError(f"No active teammate found: {teammate_name!r}.")
        result = self.team_store.send_message("lead", teammate_name, message)
        self._set_team_action_display(
            "send_message",
            f"Message sent to {display_teammate_name(teammate_name)}",
            message,
            metadata={"target": teammate_name, "message": message},
        )
        return result

    def _read_inbox(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled.")
        teammate_name = str(tool_input.get("teammate_name") or "").strip()
        clear = bool(tool_input.get("clear", False))
        try:
            wait_seconds = float(tool_input.get("wait_seconds") or 0)
        except (TypeError, ValueError):
            wait_seconds = 0
        wait_seconds = min(30.0, max(0.0, wait_seconds))
        deadline = time.monotonic() + wait_seconds
        messages = []
        while True:
            messages = self.team_store.read_inbox(teammate_name, clear=clear)
            if messages or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        mailbox = display_teammate_name(teammate_name) if teammate_name else "lead"
        if not messages:
            result = "Inbox is empty."
            self._set_team_action_display(
                "read_inbox",
                "No new messages",
                metadata={"mailbox": mailbox, "count": 0, "cleared": clear},
            )
            return result
        writer = ToolOutputWriter()
        writer.write("Inbox messages:\n")
        for message in messages:
            sender = message.get("from", "?")
            content = str(message.get("content", ""))
            timestamp = message.get("timestamp", "?")
            sender_text = display_teammate_name(sender) if str(sender) != "lead" else "lead"
            status = str(message.get("status") or "")
            suffix = f" [{status}]" if status else ""
            if writer.write(f"[{timestamp}] {sender_text}{suffix}: {content}\n") is False:
                break
        result = writer.finalize(
            strategy="head_tail",
            allow_subagent_hint=False,
            view_cache=self._tool_output_view_cache,
        )
        message_count = len(messages)
        message_label = "message" if message_count == 1 else "messages"
        self._set_team_action_display(
            "read_inbox",
            f"{message_count} {message_label} from {mailbox}",
            result,
            metadata={
                "mailbox": mailbox,
                "count": len(messages),
                "cleared": clear,
                "messages": messages,
            },
        )
        return result

    def _broadcast(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled.")
        message = _required_string(tool_input, "message")
        teammate_names = tool_input.get("teammate_names")
        if teammate_names is not None and not isinstance(teammate_names, list):
            raise AgentToolError("teammate_names must be an array when provided.")
        result = self.team_store.broadcast("lead", message, teammate_names)
        targets = list(teammate_names or [
            teammate.get("name", "") for teammate in self.team_store.get_roster()
        ])
        target_count = len(targets)
        target_label = "teammate" if target_count == 1 else "teammates"
        self._set_team_action_display(
            "broadcast",
            f"Sent to {target_count} {target_label}" if targets else result,
            message,
            metadata={"targets": targets, "message": message},
        )
        return result

    def _shutdown_teammate(self, tool_input):
        if not self.team_available:
            raise AgentToolError("Agent team is disabled.")
        teammate_name = _required_string(tool_input, "teammate_name")
        cancellation = ""
        if self.team_shutdown_executor is not None:
            cancellation = str(self.team_shutdown_executor(teammate_name) or "")
        removed = self.team_store.remove_teammate(teammate_name)
        if removed:
            result = (
                "Teammate "
                f"'{display_teammate_name(teammate_name)}' shutdown and removed from team."
            )
            if cancellation:
                result += f" {cancellation}"
            self._set_team_action_display(
                "shutdown_teammate",
                f"Shutdown {display_teammate_name(teammate_name)}",
                result,
                metadata={"teammate_name": teammate_name, "cancelled": bool(cancellation)},
            )
            return result
        result = (
            "No active teammate found with name "
            f"'{display_teammate_name(teammate_name)}'."
        )
        self._set_team_action_display(
            "shutdown_teammate",
            result,
            status="warning",
            metadata={"teammate_name": teammate_name},
        )
        return result

    def _web_search(self, tool_input):
        if not self.web_search_enabled:
            raise AgentToolError("Web search is disabled. Use /search on to enable it.")
        if self.web_search_provider != DEFAULT_WEB_SEARCH_PROVIDER:
            raise AgentToolError(
                f"Unsupported web search provider: {self.web_search_provider}"
            )

        query = _required_string(tool_input, "query")
        self._before_visible_output()
        if not self.suppress_visible_output:
            add_web_search_entry(query)
        self._display_payload = {
            "kind": "web_search",
            "content": query,
        }
        max_results = (
            _optional_positive_int(tool_input, "max_results")
            or self.web_search_max_results
        )
        search_depth = str(tool_input.get("search_depth") or self.web_search_depth)
        topic = str(tool_input.get("topic") or self.web_search_topic)
        time_range = str(tool_input.get("time_range") or "")
        include_answer = _optional_bool(tool_input, "include_answer", False)
        include_raw_content = _optional_bool(tool_input, "include_raw_content", False)

        return search_tavily(
            query,
            api_key=self.web_search_api_key,
            max_results=max_results,
            search_depth=search_depth,
            topic=topic,
            time_range=time_range,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            include_domains=tool_input.get("include_domains"),
            exclude_domains=tool_input.get("exclude_domains"),
            country=tool_input.get("country", ""),
        )

    def _iter_files(self, root):
        if not root.exists():
            raise AgentToolError(f"Path does not exist: {self._display_path(root)}")
        if not root.is_dir():
            raise AgentToolError(f"Path is not a directory: {self._display_path(root)}")

        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                yield Path(current_root) / filename

    def _resolve_path(self, path_value):
        path_text = str(path_value or "").strip()
        if not path_text:
            raise AgentToolError("Path cannot be empty.")
        if _has_parent_reference(path_text):
            raise AgentToolError("Path cannot contain parent directory references.")

        path = Path(path_text)
        if not path.is_absolute():
            path = self.workspace_dir / path
        resolved = path.resolve(strict=False)
        self._ensure_inside_workspace(resolved)
        return resolved

    def _resolve_read_path(
        self, path_value, reference=None, allow_tool_output=False
    ):
        reference = str(reference or "").strip()
        if not reference:
            path_text = str(path_value or "").strip()
            if allow_tool_output and path_text:
                artifact_path = resolve_artifact_uri(path_text)
                if artifact_path is not None:
                    return artifact_path
                if _looks_absolute(path_text):
                    resolved = Path(path_text).resolve(strict=False)
                    if self._is_tool_output_path(resolved):
                        return resolved
            return self._resolve_path(path_value)
        reference_file = self._reference_file(reference)
        if reference_file is not None:
            return self._resolve_reference_file_path(path_value, reference_file)
        path_text = str(path_value or "").strip()
        if not path_text:
            raise AgentToolError("Path cannot be empty.")
        if _has_parent_reference(path_text) or _looks_absolute(path_text):
            raise AgentToolError(
                "Referenced-folder paths must be relative and cannot contain parent references."
            )
        root = self._reference_root(reference)
        resolved = (root / path_text).resolve(strict=False)
        self._ensure_inside_root(resolved, root)
        return resolved

    def _resolve_reference_file_path(self, path_value, file_path):
        path_text = str(path_value or "").strip()
        if path_text in {"", "."}:
            return file_path
        if _has_parent_reference(path_text) or _looks_absolute(path_text):
            raise AgentToolError(
                "Referenced-file paths must target the referenced file itself."
            )
        if path_text not in {file_path.name, file_path.as_posix()}:
            raise AgentToolError(
                "Referenced-file access is limited to the explicitly referenced file."
            )
        return file_path

    def _reference_file(self, reference):
        files = getattr(self, "reference_files", {})
        return files.get(str(reference))

    def _reference_root(self, reference):
        folders = getattr(self, "reference_folders", {})
        root = folders.get(str(reference))
        if root is None:
            raise AgentToolError(f"Referenced folder is unavailable: {reference}")
        return root

    def _ensure_inside_root(self, path, root):
        root_value = os.path.normcase(str(root))
        candidate = os.path.normcase(str(path))
        try:
            common = os.path.commonpath([root_value, candidate])
        except ValueError as error:
            raise AgentToolError("Path is outside the referenced folder.") from error
        if common != root_value:
            raise AgentToolError("Path is outside the referenced folder.")

    def _ensure_inside_workspace(self, path):
        workspace = os.path.normcase(str(self.workspace_dir))
        candidate = os.path.normcase(str(path))
        try:
            common = os.path.commonpath([workspace, candidate])
        except ValueError as error:
            raise AgentToolError("Path is outside the workspace.") from error
        if common != workspace:
            raise AgentToolError("Path is outside the workspace.")

    def _display_path(self, path):
        if self._is_tool_output_path(path):
            return artifact_uri(path)
        if self.workspace_dir is None:
            return str(path)
        try:
            return str(path.relative_to(self.workspace_dir))
        except (TypeError, ValueError):
            return str(path)

    def _record_changed_file(self, file_path, original_content=None):
        display_path = self._display_path(file_path)
        if display_path not in self._session_changed_file_set:
            self._session_changed_file_set.add(display_path)
            self.session_changed_files.append(display_path)
        if (
            original_content is not None
            and display_path not in self._session_original_contents
        ):
            self._session_original_contents[display_path] = original_content

    def _record_mutating_command(self, command):
        self.session_mutating_commands.append(command)

    def _run_git_command(self, args, empty_message, record_mode=""):
        try:
            process = subprocess.Popen(
                ["git"] + list(args),
                cwd=str(self.workspace_dir),
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **process_group_options(),
            )
        except FileNotFoundError:
            return "Exit code: 127\nERROR: git executable was not found."

        events = queue.Queue(maxsize=64)
        completed_streams = set()
        reader_stop = threading.Event()

        def enqueue_event(event):
            while not reader_stop.is_set():
                try:
                    events.put(event, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def read_stream(label, stream):
            try:
                if stream is None:
                    return
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    if not enqueue_event((label, chunk)):
                        break
            finally:
                enqueue_event((label, None))

        readers = [
            threading.Thread(
                target=read_stream,
                args=("stdout", process.stdout),
                name="omni-git-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=read_stream,
                args=("stderr", process.stderr),
                name="omni-git-stderr",
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        writer = ToolOutputWriter()
        saw_output = False
        stderr_started = False
        timed_out = False
        storage_limited = False
        deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
        while len(completed_streams) < 2 or not events.empty():
            if time.monotonic() >= deadline and process.poll() is None:
                timed_out = True
                terminate_process_tree(process)
                reader_stop.set()
            try:
                label, chunk = events.get(timeout=0.05)
            except queue.Empty:
                if process.poll() is not None and len(completed_streams) >= 2:
                    break
                continue
            if chunk is None:
                completed_streams.add(label)
                continue
            saw_output = True
            if label == "stderr" and not stderr_started:
                if not writer.write("\n[stderr]\n"):
                    storage_limited = True
                    reader_stop.set()
                    terminate_process_tree(process)
                    break
                stderr_started = True
            if not writer.write(chunk):
                storage_limited = True
                reader_stop.set()
                try:
                    process.kill()
                except Exception:
                    pass
                break

        try:
            return_code = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return_code = terminate_process_tree(process).return_code
        reader_stop.set()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        for reader in readers:
            reader.join(timeout=1)

        if not saw_output:
            writer.write(empty_message)
        suffix_lines = []
        if timed_out:
            suffix_lines.append(
                f"ERROR: git command timed out after {GIT_TIMEOUT_SECONDS} seconds."
            )
        if storage_limited or writer.storage_limited:
            suffix_lines.append(
                "ERROR: git output reached the internal artifact storage safety limit."
            )
        suffix = ""
        if suffix_lines:
            suffix = "\n\n" + "\n".join(suffix_lines)
        return writer.finalize(
            strategy="head_tail",
            record_mode=record_mode,
            allow_subagent_hint=False,
            view_cache=self._tool_output_view_cache,
            prefix=f"Exit code: {return_code}\n",
            suffix=suffix,
        )

    def _validate_command_scope(self, command):
        if _has_parent_reference(command):
            raise AgentToolError(
                "Bash command cannot contain parent directory references."
            )
        outside_paths = []
        for candidate in _absolute_path_candidates(command):
            try:
                resolved = Path(candidate).resolve(strict=False)
                self._ensure_inside_workspace(resolved)
            except Exception:
                outside_paths.append(candidate)
        if outside_paths:
            raise AgentToolError(
                "Bash command references paths outside the workspace: "
                + ", ".join(outside_paths)
            )
        if re.search(r"(?i)(\$env:|%[^%\s]+%|\$home|~)", command):
            raise AgentToolError(
                "Bash command cannot reference environment or home paths."
            )

    def _confirm_diff(self, title, file_path, diff_content, risk_reason):
        if self._auto_approves(risk_reason):
            return True
        self._before_visible_output()
        approved = get_agent_diff_confirmation(title, file_path, diff_content)
        return approved

    def _confirm(self, title, detail, risk_reason=""):
        if self._auto_approves(risk_reason):
            return True
        self._before_visible_output()
        return get_agent_confirmation(title, detail)

    def _display_user_rejection(self, message):
        self._before_visible_output()
        if not self.suppress_visible_output:
            append_chat_status(message)

    def _todo_action_gate(self, name, tool_input):
        if self.plan_mode:
            return None
        if not self.todos_enabled:
            return None
        return self._active_todo_gate(name)

    def _active_todo_gate(self, name):
        if not self.todos_enabled:
            return None
        if name == "update_todo":
            return None
        if not self.todo_store.requires_active_todo():
            return None
        active = self.todo_store.active_item()
        if active is not None:
            return None
        return _error_result(
            "Before using more tools, call update_todo and mark exactly one ready "
            "todo item as in_progress. This keeps the todo list synchronized with the "
            "work being executed."
        )

    def _before_visible_output(self):
        if self.suppress_visible_output:
            return
        if self.visible_output_callback:
            self.visible_output_callback()
        self.output_needs_separator = True

    def _auto_approves(self, risk_reason):
        if self.approval_mode == AGENT_APPROVAL_FULL:
            return True
        if self.approval_mode != AGENT_APPROVAL_APPROVE:
            return False
        blocked_reasons = (
            "delete command detected",
            "mutating git command detected",
            "package manager mutation detected",
            "package installation detected",
        )
        return risk_reason not in blocked_reasons


def normalize_workspace_dir(workspace_dir):
    if not workspace_dir:
        return None
    try:
        path = Path(str(workspace_dir)).expanduser().resolve(strict=True)
    except Exception:
        return None
    if not path.is_dir():
        return None
    return path


class _WebTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if str(tag or "").lower() in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if str(tag or "").lower() in {
            "article",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "li",
            "main",
            "p",
            "section",
            "td",
            "th",
            "tr",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if str(tag or "").lower() in {"script", "style", "noscript"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if str(tag or "").lower() in {
            "article",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "li",
            "main",
            "p",
            "section",
            "tr",
        }:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = str(data or "").strip()
        if text:
            self.parts.append(text)

    def text(self):
        text = " ".join(self.parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirects = getattr(req, "_omniagent_redirects", 0) + 1
        if redirects > WEB_FETCH_MAX_REDIRECTS:
            raise AgentToolError("too many redirects")
        _validate_public_http_url(newurl)
        next_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if next_request is not None:
            setattr(next_request, "_omniagent_redirects", redirects)
        return next_request


def _fetch_public_webpage(url, extract_mode):
    normalized_url = _validate_public_http_url(url)
    request = urllib.request.Request(
        normalized_url,
        headers={"User-Agent": "OmniAgent-web-fetch/1.0"},
        method="GET",
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    try:
        with opener.open(request, timeout=15) as response:
            final_url = response.geturl()
            _validate_public_http_url(final_url)
            content_type = (response.headers.get("Content-Type") or "").split(";")[0]
            content_type = content_type.strip().lower()
            if content_type and not _is_web_fetch_text_content_type(content_type):
                raise AgentToolError(f"unsupported content-type: {content_type}")
            data = response.read(WEB_FETCH_MAX_RESPONSE_BYTES + 1)
            if len(data) > WEB_FETCH_MAX_RESPONSE_BYTES:
                raise AgentToolError(
                    f"response too large (>{WEB_FETCH_MAX_RESPONSE_BYTES} bytes)"
                )
            charset = response.headers.get_content_charset() or "utf-8"
            raw_text = data.decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        raise AgentToolError(f"HTTP {error.code} fetching {normalized_url}") from error
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", error)
        raise AgentToolError(f"Failed to fetch {normalized_url}: {reason}") from error
    except TimeoutError as error:
        raise AgentToolError(f"Timed out fetching {normalized_url}") from error

    if extract_mode == "text":
        parser = _WebTextExtractor()
        parser.feed(raw_text)
        body = parser.text()
    else:
        body = raw_text

    return (
        f"URL: {final_url}\n"
        f"Mode: {extract_mode}\n"
        f"Characters: {len(body)}\n\n"
        f"{body}"
    )


def _validate_public_http_url(url):
    value = str(url or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise AgentToolError("web_fetch only allows http/https URLs.")
    if not parsed.hostname:
        raise AgentToolError("web_fetch URL must include a host.")
    hostname = parsed.hostname.strip().lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        raise AgentToolError(f"blocked host: {hostname}")
    if "%" in hostname:
        raise AgentToolError("zone identifiers are not allowed in hosts.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise AgentToolError(f"invalid URL port: {error}") from error
    for ip in _resolve_web_fetch_host_ips(hostname, port):
        if _is_blocked_web_fetch_ip(ip):
            raise AgentToolError(f"blocked non-public address: {ip}")
    return urllib.parse.urlunparse(parsed)


def _resolve_web_fetch_host_ips(hostname, port):
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise AgentToolError(f"host resolution failed: {error}") from error
        ips = []
        for info in infos:
            address = info[4][0]
            try:
                ips.append(ipaddress.ip_address(address))
            except ValueError:
                continue
        if not ips:
            raise AgentToolError("host resolved to no addresses.")
        return ips
    return [literal]


def _is_blocked_web_fetch_ip(ip):
    return any((
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ))


def _is_web_fetch_text_content_type(content_type):
    return content_type.startswith("text/") or content_type in {
        "application/atom+xml",
        "application/json",
        "application/ld+json",
        "application/rss+xml",
        "application/xhtml+xml",
        "application/xml",
    }


def _program_doc_paths():
    root = Path(__file__).resolve().parent
    paths = []
    for filename in PROGRAM_DOC_FILENAMES:
        path = root / filename
        if path.is_file():
            paths.append(path)
    return paths


def _todo_dir_for_workspace(workspace_dir):
    if workspace_dir is None:
        return None
    return Path(workspace_dir) / ".omniagent" / "todos"


def _final_check_passed(check_result):
    text = str(check_result or "")
    diff_check = _section_after(text, "git diff --check")
    if diff_check:
        exit_codes = [
            int(value) for value in re.findall(r"Exit code:\s*(-?\d+)", diff_check)
        ]
        if exit_codes and any(code != 0 for code in exit_codes):
            return False
    if re.search(r"(?m)^ERROR:", text):
        return False
    return True


def _final_verification_note(check_result, passed):
    text = str(check_result or "")
    if passed:
        return "Automatic final verification passed."

    diff_check = _section_after(text, "git diff --check")
    source = diff_check or text
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            "Exit code:" in stripped
            or stripped.startswith("ERROR:")
            or "[stderr]" in stripped
        ):
            lines.append(stripped)
        elif lines and len(lines) < 4:
            lines.append(stripped)
        if len(lines) >= 4:
            break
    if not lines:
        return "Automatic final verification failed."
    return " ".join(lines)


def _section_after(text, heading):
    marker_index = str(text or "").find(heading)
    if marker_index < 0:
        return ""
    section = text[marker_index:]
    next_section = section.find("\n\n", len(heading))
    if next_section >= 0:
        section = section[:next_section]
    return section


def _git_diff_records(text):
    value = str(text or "")
    matches = list(re.finditer(r"(?m)^diff --git ", value))
    if not matches:
        return ()
    records = []
    prefix = value[: matches[0].start()]
    if prefix:
        records.append(prefix.rstrip("\r\n"))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        records.append(value[match.start():end].rstrip("\r\n"))
    return tuple(record for record in records if record)


def _unified_diff_text(old_content, new_content, display_path):
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    diff_lines = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{display_path}",
        tofile=f"b/{display_path}",
        lineterm="",
    )
    return "\n".join(diff_lines)


def _diff_stats(diff_text):
    additions = 0
    deletions = 0
    for line in (diff_text or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _apply_unified_diff_to_content(content, patch):
    original_lines = content.splitlines()
    output_lines = []
    position = 0
    patch_lines = patch.splitlines()
    index = 0
    saw_hunk = False

    while index < len(patch_lines):
        line = patch_lines[index]
        hunk_match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not hunk_match:
            index += 1
            continue

        saw_hunk = True
        old_start = int(hunk_match.group(1))
        target = max(old_start - 1, 0)
        if target < position:
            raise AgentToolError("Unified patch hunks overlap or are out of order.")

        output_lines.extend(original_lines[position:target])
        position = target
        index += 1

        while index < len(patch_lines):
            hunk_line = patch_lines[index]
            if hunk_line.startswith("@@ "):
                break
            if hunk_line.startswith("\\"):
                index += 1
                continue
            if not hunk_line:
                raise AgentToolError("Invalid unified patch hunk line.")

            marker = hunk_line[0]
            text = hunk_line[1:]
            if marker == " ":
                _assert_patch_line_matches(original_lines, position, text)
                output_lines.append(original_lines[position])
                position += 1
            elif marker == "-":
                _assert_patch_line_matches(original_lines, position, text)
                position += 1
            elif marker == "+":
                output_lines.append(text)
            else:
                raise AgentToolError(f"Invalid unified patch hunk marker: {marker}")
            index += 1

    if not saw_hunk:
        raise AgentToolError("Unified patch does not contain any @@ hunks.")

    output_lines.extend(original_lines[position:])
    newline = _detect_newline(content)
    updated = newline.join(output_lines)
    if content.endswith(("\n", "\r")):
        updated += newline
    return updated


def _assert_patch_line_matches(lines, position, expected):
    if position >= len(lines):
        raise AgentToolError("Unified patch context exceeds file length.")
    actual = lines[position]
    if actual != expected:
        raise AgentToolError(
            "Unified patch context mismatch at line "
            f"{position + 1}. Expected {expected!r}, found {actual!r}."
        )


def _required_string(data, key, allow_empty=False):
    value = data.get(key)
    if not isinstance(value, str):
        raise AgentToolError(f"{key} must be a string.")
    if not allow_empty and not value:
        raise AgentToolError(f"{key} cannot be empty.")
    return value


def _ask_user_questions(tool_input):
    raw_questions = tool_input.get("questions")
    if raw_questions is None:
        question = _required_string(tool_input, "question")
        options = _required_ask_user_options(tool_input.get("options"))
        default_index = _bounded_int(
            tool_input.get("default_index"),
            1,
            1,
            len(options),
            "default_index",
        )
        return [
            {
                "question": question,
                "options": options,
                "default_index": default_index,
            }
        ]
    if not isinstance(raw_questions, list):
        raise AgentToolError("questions must be an array.")
    if len(raw_questions) < 1:
        raise AgentToolError("questions must contain at least 1 item.")
    questions = []
    for index, item in enumerate(raw_questions, 1):
        if not isinstance(item, dict):
            raise AgentToolError(f"questions[{index}] must be an object.")
        question = _required_string(item, "question")
        options = _required_ask_user_options(item.get("options"))
        default_index = _bounded_int(
            item.get("default_index"),
            1,
            1,
            len(options),
            f"questions[{index}].default_index",
        )
        questions.append({
            "question": question,
            "options": options,
            "default_index": default_index,
        })
    return questions


def _required_ask_user_options(value):
    if not isinstance(value, list):
        raise AgentToolError("options must be an array.")
    options = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise AgentToolError(f"options[{index}] must be an object.")
        title = " ".join(str(item.get("title") or "").split())
        detail = " ".join(str(item.get("detail") or "").split())
        if not title:
            raise AgentToolError(f"options[{index}].title cannot be empty.")
        if not detail:
            raise AgentToolError(f"options[{index}].detail cannot be empty.")
        options.append({
            "title": title,
            "detail": detail,
            "value": title,
        })
    if len(options) < 2 or len(options) > 8:
        raise AgentToolError("options must contain between 2 and 8 items.")
    return options


def _required_positive_int(data, key):
    value = _coerce_int(data.get(key), key)
    if value < 1:
        raise AgentToolError(f"{key} must be greater than 0.")
    return value


def _optional_positive_int(data, key):
    value = data.get(key)
    if value is None:
        return None
    value = _coerce_int(value, key)
    if value < 1:
        raise AgentToolError(f"{key} must be greater than 0.")
    return value


def _bounded_int(value, default, minimum, maximum, key):
    if value is None:
        return default
    value = _coerce_int(value, key)
    if value < minimum or value > maximum:
        raise AgentToolError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _coerce_int(value, key):
    if isinstance(value, bool):
        raise AgentToolError(f"{key} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as error:
            raise AgentToolError(f"{key} must be an integer.") from error
    else:
        raise AgentToolError(f"{key} must be an integer.")


def _optional_bool(data, key, default=False):
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _error_result(message):
    return f"ERROR: {message}"


def _format_lines(lines, start_line, line_numbers=True):
    if not line_numbers:
        return "\n".join(lines)
    if not lines:
        return ""
    width = len(str(start_line + len(lines) - 1))
    return "\n".join(
        f"{line_number:>{width}} | {line}"
        for line_number, line in enumerate(lines, start_line)
    )


def _detect_newline(content):
    return "\r\n" if "\r\n" in content else "\n"


def _has_parent_reference(value):
    return any(part == ".." for part in re.split(r"[\\/]+", str(value)))


def _looks_absolute(value):
    text = str(value)
    return bool(
        re.match(r"^[a-zA-Z]:[\\/]", text)
        or text.startswith("\\\\")
        or text.startswith("/")
    )


def _absolute_path_candidates(command):
    drive_paths = re.findall(r"[a-zA-Z]:[\\/][^\s\"'<>|]+", command)
    unc_paths = re.findall(r"\\\\[^\s\"'<>|]+", command)
    return drive_paths + unc_paths


def _http_check_paths(value):
    if value is None:
        return ["/"]
    if isinstance(value, str):
        paths = [value]
    elif isinstance(value, (list, tuple)):
        paths = [str(item) for item in value]
    else:
        raise AgentToolError("paths must be an array of strings.")
    normalized = []
    for path in paths:
        path = str(path or "").strip()
        if not path:
            continue
        normalized.append(path)
    return normalized or ["/"]


def _normalize_http_path(path):
    value = str(path or "/").strip() or "/"
    if not value.startswith("/"):
        value = "/" + value
    return urllib.parse.quote(value, safe="/:?&=#%+-._~")


def _free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_local_port(process, port, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = _communicate_process(process, 0.2)
            detail = stderr.strip() if stderr else "no stderr"
            raise AgentToolError(f"local HTTP server exited early: {detail}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError as error:
            last_error = str(error)
            time.sleep(0.1)
    raise AgentToolError(
        f"local HTTP server did not accept connections within {timeout_seconds} seconds"
        + (f": {last_error}" if last_error else "")
    )


def _request_http_status(url, timeout_seconds):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OmniAgent-local-http-check"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=max(0.5, timeout_seconds)
        ) as response:
            return int(response.status), ""
    except urllib.error.HTTPError as error:
        return int(error.code), str(error.reason or "")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, str(error)


def _terminate_process(process):
    if process is None:
        return
    terminate_process_tree(process, wait_seconds=2)
    for stream in (process.stdout, process.stderr, process.stdin):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _communicate_process(process, timeout):
    return process.communicate(timeout=timeout)


def _foreground_server_command_reason(command):
    lowered = str(command or "").lower()
    patterns = [
        (
            r"(?:^|[;&|]\s*)(?:python|python3|py)\s+-m\s+http\.server\b",
            "python -m http.server starts a foreground static server",
        ),
        (
            r"(?:^|[;&|]\s*)(?:npx\s+)?(?:http-server|live-server)\b",
            "static server command starts a foreground process",
        ),
        (
            r"(?:^|[;&|]\s*)(?:npx\s+)?serve(?:\.cmd)?\b",
            "serve starts a foreground static server",
        ),
        (
            r"(?:^|[;&|]\s*)(?:npx\s+)?vite(?:\.cmd)?\b",
            "vite starts a foreground dev server",
        ),
        (
            r"(?:^|[;&|]\s*)(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:dev|start|serve|preview)\b",
            "package script appears to start a foreground dev/static server",
        ),
        (
            r"(?:^|[;&|]\s*)next\s+dev\b",
            "next dev starts a foreground dev server",
        ),
        (
            r"(?:^|[;&|]\s*)astro\s+dev\b",
            "astro dev starts a foreground dev server",
        ),
    ]
    for pattern, reason in patterns:
        if re.search(pattern, lowered):
            return reason
    return ""


def _command_risk(command):
    lowered = command.lower()
    blocked_patterns = [
        (r"(^|\s)git\s+reset\s+--hard\b", "git reset --hard is blocked"),
        (r"(^|\s)git\s+clean\b", "git clean is blocked"),
        (
            r"(^|\s)(format|shutdown|restart-computer|stop-computer)\b",
            "system-level command is blocked",
        ),
        (
            r"(^|\s)(invoke-expression|iex|set-executionpolicy)\b",
            "dynamic PowerShell execution is blocked",
        ),
        (
            r"(^|\s)(rm|del|erase|rmdir|rd|remove-item|ri)\b[^\n]*(?:-recurse|-r|-rf|-fr|/s)\b",
            "recursive delete command is blocked",
        ),
    ]
    for pattern, reason in blocked_patterns:
        if re.search(pattern, lowered):
            return "blocked", reason

    confirm_patterns = [
        (r"(^|\s)(rm|del|erase|rmdir|rd|remove-item|ri)\b", "delete command detected"),
        (
            r"(^|\s)(mv|move|cp|copy|xcopy|robocopy|move-item|copy-item)\b",
            "file move/copy command detected",
        ),
        (
            r"(^|\s)(mkdir|md|new-item|ni|touch)\b",
            "directory/file creation command detected",
        ),
        (
            r"(^|\s)(set-content|add-content|out-file|tee|tee-object)\b",
            "file write command detected",
        ),
        (r"(^|\s)sed\s+(-i|--in-place)\b", "in-place file edit command detected"),
        (r">\s*[^&|]", "shell redirection detected"),
        (r">>\s*[^&|]", "shell append redirection detected"),
        (
            r"(^|\s)git\s+(checkout|reset|clean|apply|am|merge|rebase|commit|add|rm|mv)\b",
            "mutating git command detected",
        ),
        (
            r"(^|\s)(npm|pnpm|yarn)\s+(install|add|remove|update)\b",
            "package manager mutation detected",
        ),
        (r"(^|\s)pip\s+install\b", "package installation detected"),
        (
            r"(^|\s)(python|python3|py|node|deno|ruby|perl|powershell|pwsh|cmd|bash|sh)\b",
            "script or shell execution detected",
        ),
    ]
    for pattern, reason in confirm_patterns:
        if re.search(pattern, lowered):
            return "confirm", reason
    return "allow", ""
