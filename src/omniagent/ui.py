import json
import re
import threading

from rich.console import Console

from .tui.runtime import get_bridge


VERSION = "4.0.0"

_console_override = threading.local()


class _ConsoleProxy:
    def __init__(self):
        self._console = Console()

    def _delegate(self):
        return getattr(_console_override, "console", self._console)

    def __getattr__(self, name):
        return getattr(self._delegate(), name)

    def print(self, *objects, **kwargs):
        override = getattr(_console_override, "console", None)
        if override is not None:
            return override.print(*objects, **kwargs)
        bridge = get_bridge()
        if bridge is not None:
            bridge.append_console_print(*objects, **kwargs)
            return None
        return self._console.print(*objects, **kwargs)

    def input(self, prompt="", *args, **kwargs):
        override = getattr(_console_override, "console", None)
        if override is not None:
            return override.input(prompt, *args, **kwargs)
        bridge = get_bridge()
        if bridge is not None:
            return bridge.request_console_input(prompt)
        return self._console.input(prompt, *args, **kwargs)


console = _ConsoleProxy()


def clean_display_text(text):
    if isinstance(text, list):
        text = "\n".join(_display_content_block(block) for block in text)
    elif isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    else:
        text = str(text or "")
    return "\n".join(line for line in text.strip().split("\n") if line.strip())


def clean_display_text_preserve_newlines(text):
    if isinstance(text, list):
        text = "\n".join(_display_content_block(block) for block in text)
    elif isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    else:
        text = str(text or "")
    return text.strip()


def clean_thinking_text(text):
    text = str(text or "")
    text = re.sub(r"<\s*/?\s*think\s*>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _tool_error_single_line(value, max_chars=120):
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item or "") for item in value[:3])
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _tool_error_summary(tool_name, tool_input):
    name = str(tool_name or "").strip()
    arguments = tool_input if isinstance(tool_input, dict) else {}
    if name == "update_todo":
        items = arguments.get("items")
        if isinstance(items, list):
            return f"{len(items)} todo item{'s' if len(items) != 1 else ''}"
    if name == "dispatch_subagent":
        tasks = arguments.get("tasks")
        if isinstance(tasks, list):
            return f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"
    if name == "ask_user":
        question = arguments.get("question")
        questions = arguments.get("questions")
        if not question and isinstance(questions, list) and questions:
            first = questions[0]
            if isinstance(first, dict):
                question = first.get("question")
        return _tool_error_single_line(question)

    preferred_keys = {
        "read_file": ("file_path", "reference"),
        "web_fetch": ("url",),
        "list_dir": ("path", "reference"),
        "write_file": ("file_path",),
        "edit_file": ("file_path",),
        "apply_patch": ("file_path",),
        "apply_unified_patch": ("file_path",),
        "bash": ("command",),
        "local_http_check": ("root", "paths"),
        "git_diff": ("file_path",),
        "grep": ("pattern", "path", "reference"),
        "glob": ("pattern", "reference"),
        "read_skill": ("name",),
        "web_search": ("query",),
        "report_to_lead": ("kind",),
        "spawn_teammate": ("teammate_type", "purpose"),
        "send_message": ("teammate_name", "recipient", "to"),
        "read_inbox": ("teammate_name",),
        "shutdown_teammate": ("teammate_name",),
    }.get(name, ())
    parts = []
    for key in preferred_keys:
        value = _tool_error_single_line(arguments.get(key), max_chars=80)
        if value and value not in parts:
            parts.append(value)
    return _tool_error_single_line(" ".join(parts))


def _tool_error_message(tool_name, error):
    error_text = clean_display_text_preserve_newlines(error)
    if error_text.startswith("ERROR:"):
        error_text = error_text[6:].lstrip()
    name = str(tool_name or "")
    if name not in {"bash", "git_status", "git_diff"}:
        return error_text
    exit_codes = re.findall(r"(?:^|\n)Exit code:\s*(-?\d+)", error_text)
    if not exit_codes or int(exit_codes[-1]) == 0:
        return error_text
    exit_code = int(exit_codes[-1])
    metadata_match = re.search(
        r"<shell_metadata>(.*?)</shell_metadata>\s*$",
        error_text,
        flags=re.DOTALL,
    )
    metadata_details = ""
    if metadata_match:
        metadata_lines = [
            line.strip()
            for line in metadata_match.group(1).splitlines()
            if line.strip()
            and not re.fullmatch(r"Exit code:\s*-?\d+", line.strip())
        ]
        metadata_details = "\n".join(metadata_lines)
        body = error_text[: metadata_match.start()].strip()
    else:
        body = re.sub(r"^Exit code:\s*-?\d+\s*", "", error_text).strip()
    if body == "(no output)":
        body = ""
    details = "\n\n".join(part for part in (body, metadata_details) if part)
    message = f"Command exited with code {exit_code}."
    return f"{message}\n\n{details}" if details else message


def build_tool_error_display(tool_name, tool_input, error):
    error_text = _tool_error_message(tool_name, error)
    return {
        "kind": "tool_error",
        "tool_name": str(tool_name or "").strip(),
        "summary": _tool_error_summary(tool_name, tool_input),
        "error": error_text or "Tool call failed.",
    }


def tool_display_is_error(display):
    if not isinstance(display, dict):
        return False
    kind = str(display.get("kind") or "")
    status = str(display.get("status") or "").strip().lower()
    if kind == "tool_error":
        return True
    if kind in {"file_edit", "file_write"} and status == "rejected":
        return True
    return kind == "team_action" and status in {"error", "failed"}


def tool_result_is_error(tool_name, result, display=None):
    if tool_display_is_error(display):
        return True
    if isinstance(display, dict) and str(display.get("error") or "").strip():
        return True
    text = str(result or "").strip()
    if text.startswith("ERROR:"):
        return True
    if str(tool_name or "") not in {
        "bash",
        "local_http_check",
        "git_status",
        "git_diff",
    }:
        return False
    exit_codes = re.findall(r"(?:^|\n)Exit code:\s*(-?\d+)", text)
    return bool(exit_codes and int(exit_codes[-1]) != 0)


def _display_content_block(block):
    if not isinstance(block, dict):
        return str(block)

    block_type = block.get("type")
    if block_type == "text":
        return block.get("text", "")
    if block_type == "thinking":
        return block.get("thinking", "")
    if block_type == "tool_use":
        return f"[tool_use] {block.get('name', '')} {json.dumps(block.get('input', {}), ensure_ascii=False)}"
    if block_type == "tool_result":
        return f"[tool_result] {block.get('content', '')}"
    return json.dumps(block, ensure_ascii=False)


def print_message(symbol, content, color=None):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_status_message(symbol, content)


def append_chat_status(text: str) -> None:
    bridge = get_bridge()
    if bridge is None:
        return
    if not hasattr(bridge, "append_status_text"):
        return
    bridge.append_status_text(text)


def print_success(content):
    print_message("[✓]", content)


def print_error(content):
    print_message("[✗]", content)


def print_warn(content):
    print_message("[!]", content)


def print_info(content):
    print_message("[-]", content)


def print_thinking(content):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_thinking_message(content)


def print_stream_thinking(content, leading_newline=True):
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_stream_thinking()
        if content:
            bridge.append_stream_thinking(content)


def append_stream_thinking(content):
    bridge = get_bridge()
    if bridge is not None:
        bridge.append_stream_thinking(content)


def start_thinking_timer():
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_thinking_timer()


def begin_overflow_replay_scope():
    bridge = get_bridge()
    if bridge is not None and hasattr(bridge, "begin_overflow_replay_scope"):
        bridge.begin_overflow_replay_scope()


def commit_overflow_replay_scope():
    bridge = get_bridge()
    if bridge is not None and hasattr(bridge, "commit_overflow_replay_scope"):
        bridge.commit_overflow_replay_scope()


def rollback_overflow_replay_scope():
    bridge = get_bridge()
    if bridge is not None and hasattr(bridge, "rollback_overflow_replay_scope"):
        bridge.rollback_overflow_replay_scope()


def print_stream_thinking_continue(content):
    content = str(content or "")
    if not content:
        return
    bridge = get_bridge()
    if bridge is not None:
        bridge.append_stream_thinking(content)


def finish_thinking_round():
    bridge = get_bridge()
    if bridge is not None:
        bridge.finish_thinking_round()


def clear_current_line():
    bridge = get_bridge()
    if bridge is not None:
        bridge.clear_current_lines(1)


def clear_current_lines(line_count):
    bridge = get_bridge()
    if bridge is not None:
        bridge.clear_current_lines(line_count)


def add_explored_entry(tool_name, description):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_explored_entry(tool_name, description)


def add_edit_entry(file_path, additions, deletions, diff, status=""):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_edit_entry(file_path, additions, deletions, diff, status)


def add_write_entry(file_path, additions, deletions, diff, status=""):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_write_entry(file_path, additions, deletions, diff, status)


def add_shell_entry(command, output):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_shell_entry(command, output)


def add_changed_files_entry(files):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_changed_files_entry(files)


def add_question_entry(question, answer):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_question_entry(question, answer)


def add_todo_entry(items, summary=None):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_todo_entry(items, summary)


def add_tool_error_entry(display):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_tool_error_entry(dict(display or {}))


def add_web_fetch_entry(url):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_web_fetch_entry(url)


def add_web_search_entry(content):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_web_search_entry(content)


def add_subagent_entry(agent_type, transcript):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_subagent_entry(agent_type, transcript)


def start_subagent_entry(entry_id, agent_type):
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_subagent_entry(entry_id, agent_type)


def append_subagent_event(entry_id, event):
    bridge = get_bridge()
    if bridge is not None:
        bridge.append_subagent_event(entry_id, event)


def start_team_entry(entry_id, teammate_name, role="", purpose="", task_id=""):
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_team_entry(entry_id, teammate_name, role, purpose, task_id)


def append_team_event(entry_id, event):
    bridge = get_bridge()
    if bridge is not None:
        bridge.append_team_event(entry_id, event)


def finish_team_entry(entry_id, status, result=""):
    bridge = get_bridge()
    if bridge is not None:
        bridge.finish_team_entry(entry_id, status, result)


def add_team_action_entry(action, summary, details="", status="success", metadata=None):
    bridge = get_bridge()
    if bridge is not None:
        bridge.add_team_action_entry(
            action, summary, details, status, metadata or {}
        )


def start_compaction_entry(entry_id, status, mode="auto"):
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_compaction_entry(entry_id, status, mode)


def finish_compaction_entry(entry_id, status, mode="auto", details=""):
    bridge = get_bridge()
    if bridge is not None:
        bridge.finish_compaction_entry(entry_id, status, mode, details)


def print_stream_response_start(model_name):
    bridge = get_bridge()
    if bridge is not None:
        bridge.start_stream_response(model_name)


def clean_and_print_stream_response(content):
    bridge = get_bridge()
    if bridge is not None:
        while "\n\n" in content:
            content = content.replace("\n\n", "\n")
        if content.startswith("\n"):
            content = content[1:]
        bridge.append_stream_response(content)


def print_stream_response_continue(content):
    bridge = get_bridge()
    if bridge is not None:
        bridge.append_stream_response(content)


def get_user_input(prompt_text, multiline=False):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_input(prompt_text, multiline=multiline).strip()
    return ""


def get_continue_confirmation():
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation("Continue?", "")
    return False


def get_agent_confirmation(title, detail):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation(title, detail)
    return False


def get_agent_plan_confirmation(plan):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_plan_confirmation(plan)
    return False


def get_agent_choice(question, options, default_index=1):
    bridge = get_bridge()
    normalized_options = [str(option) for option in options]
    if bridge is not None:
        return bridge.request_choice(question, options, default_index=default_index)
    default_index = max(1, min(len(normalized_options), int(default_index or 1)))
    return default_index, normalized_options[default_index - 1]


def get_agent_choices(questions):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_questions(questions)
    results = []
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        options = [str(option) for option in item.get("options") or []]
        if not options:
            continue
        default_index = max(1, min(len(options), int(item.get("default_index") or 1)))
        results.append((default_index, options[default_index - 1]))
    return results


def _todo_string_list(value):
    if isinstance(value, list):
        return [str(item or "") for item in value]
    if isinstance(value, str):
        return [value]
    return []


def get_agent_todo_confirmation(todos, next_tool=""):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation(
            "Approve current agent todo list?", next_tool
        )
    return False


def get_agent_edit_confirmation(file_path, occurrences, old_content, new_content):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation(
            f"Allow agent to edit file? ({file_path})",
            f"Occurrences to replace: {occurrences}",
        )
    return False


def get_agent_patch_confirmation(
    file_path, start_line, end_line, old_content, new_content
):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation(
            f"Allow agent to patch file? ({file_path}:{start_line}-{end_line})",
            "",
        )
    return False


def get_agent_diff_confirmation(title, file_path, diff_content):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation(f"{title} ({file_path})", "")
    return False


def set_todo_panel(items):
    bridge = get_bridge()
    if bridge is not None:
        bridge.set_todo_items(items)


def clear_todo_panel():
    set_todo_panel([])


def set_context_usage(input_tokens, context_window_tokens):
    bridge = get_bridge()
    if bridge is not None:
        bridge.set_context_usage(input_tokens, context_window_tokens)
