import json
import threading

from rich.console import Console

from tui.runtime import get_bridge


VERSION = "3.0.0"

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


def print_stream_thinking_continue(content):
    while "\n\n" in content:
        content = content.replace("\n\n", "\n")
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


def get_agent_choice(question, options, default_index=1):
    bridge = get_bridge()
    if bridge is not None:
        selected = bridge.request_choice(question, options, default_index=default_index)
        normalized_options = [str(option) for option in options]
        return selected, normalized_options[selected - 1]
    normalized_options = [str(option) for option in options]
    default_index = max(1, min(len(normalized_options), int(default_index or 1)))
    return default_index, normalized_options[default_index - 1]


def _todo_string_list(value):
    if isinstance(value, list):
        return [str(item or "") for item in value]
    if isinstance(value, str):
        return [value]
    return []


def get_agent_plan_confirmation(todos, next_tool=""):
    bridge = get_bridge()
    if bridge is not None:
        return bridge.request_confirmation("Approve current agent plan?", next_tool)
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


def set_plan_panel(items):
    bridge = get_bridge()
    if bridge is not None:
        bridge.set_plan_items(items)


def clear_plan_panel():
    set_plan_panel([])


def set_context_usage(input_tokens, context_window_tokens):
    bridge = get_bridge()
    if bridge is not None:
        bridge.set_context_usage(input_tokens, context_window_tokens)
