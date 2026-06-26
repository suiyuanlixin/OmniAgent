from __future__ import annotations

import threading
from time import perf_counter
from dataclasses import dataclass
from datetime import datetime

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Label, Static

from chat import OmniAgent
from commands import process_command
from config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    AUTO_MODEL_SELECTION,
    add_model_profile,
    delete_model_profile,
    load_config,
    normalize_optional_model_selection,
    rename_model_profile,
    save_config_field,
    save_config_fields,
)
from main import attach_external_file_references_with_media
from search import TAVILY_SEARCH_DEPTHS, TAVILY_TOPICS, WEB_SEARCH_PROVIDERS
from session import (
    ProjectRecord,
    add_project,
    create_session,
    delete_session,
    get_project_by_name,
    list_pinned_sessions,
    list_sessions,
    load_projects,
    load_session,
    pin_session,
    save_session_record,
    unpin_session,
)
from tui.data import PROJECT_LOGO
from tui.runtime import clear_bridge, render_console_text, set_bridge
from tui.theme import render_css
from tui.widgets.chat_input import ChatInput, HalfRowSpacer
from tui.widgets.chat_view import ChatView
from tui.widgets.choice_modal import ChoiceModal
from tui.widgets.confirm_modal import ConfirmModal
from tui.widgets.input_modal import InputModal
from tui.widgets.project_modal import ProjectModal
from tui.widgets.project_picker import ProjectPicker
from tui.widgets.settings import SettingsModal
from tui.widgets.sidebar import Sidebar
from ui import clean_display_text, clean_display_text_preserve_newlines


from textual.widgets._toast import Toast


# Override toast notification styling
Toast.DEFAULT_CSS = """
Toast {
    width: 60;
    max-width: 50%;
    height: auto;
    visibility: visible;
    margin-top: 1;
    padding: 1 2 1 2;
    background: #2a2a2a;
    border: none;
    border-left: none;
    link-background: initial;
    link-color: $foreground;
    link-style: underline;
    link-background-hover: $primary;
    link-color-hover: $foreground;
    link-style-hover: bold not underline;
}

.toast--title {
    text-style: bold;
    color: $foreground;
}

Toast.-information {
    border: none;
    border-left: none;
}

Toast.-information .toast--title {
    color: $foreground;
}

Toast.-warning {
    border: none;
    border-left: none;
}

Toast.-warning .toast--title {
    color: $foreground;
}

Toast.-error {
    border: none;
    border-left: none;
}

Toast.-error .toast--title {
    color: $foreground;
}
"""


@dataclass
class _BlockingModalRequest:
    event: threading.Event
    result: object = None


class AgentTUIApp(App):
    """Main Agent TUI application."""

    ALLOW_SELECT = False

    CSS = render_css(
        """
    Screen {
        background: $PAGE_BACKGROUND;
        color: $TEXT_PRIMARY;
        overflow: hidden;
        min-width: 49;
    }

    #left-edge {
        dock: left;
        width: 3;
        height: 1fr;
        padding: 0;
        background: transparent;
    }
    #left-edge.sidebar-hidden {
        width: 3;
        background: transparent;
    }
    #left-edge.sidebar-visible {
        width: 25%;
        min-width: 34;
        max-width: 58;
        background: $SURFACE_BACKGROUND;
    }

    #sidebar-toggle {
        width: 100%;
        min-width: 1;
        height: 1;
        background: $PAGE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        margin: 0;
        text-align: left;
        content-align: left middle;
        text-style: bold;
    }
    #sidebar-toggle:hover {
        background: $PAGE_BACKGROUND;
        color: $TEXT_PRIMARY;
    }
    #left-edge.sidebar-visible > #sidebar-toggle,
    #left-edge.sidebar-visible > #sidebar-toggle:hover {
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
    }

    #main-area {
        width: 1fr;
        height: 1fr;
        min-width: 46;
        padding: 0 3 0 0;
        align-horizontal: center;
    }
    #main-area.sidebar-visible {
        padding: 0 3 0 3;
    }

    #project-title-wrap {
        width: 100%;
        height: auto;
        min-width: 44;
        padding-left: 1;
        align-horizontal: center;
    }

    #chat-input-wrap {
        width: 100%;
        height: auto;
        min-width: 46;
        padding: 1 1 0 1;
        align-horizontal: center;
    }
    #chat-input-wrap > #chat-input {
        margin: 0;
    }

    #info-bar-wrap {
        width: 100%;
        height: auto;
        min-width: 46;
        padding: 0 1;
        align-horizontal: center;
    }

    #info-bar-shell {
        width: 100%;
        min-width: 44;
        max-width: 78;
        height: auto;
    }
    #info-bar-shell.stretch {
        width: 100%;
    }

    #info-bar-bottom {
        color: $INFO_BAR_BACKGROUND;
    }

    #info-bar {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        padding: 0 1;
    }
    #info-bar > #project-picker {
        margin: 0;
    }
    #info-bar > #project-picker.hidden {
        display: none;
    }
    #interrupt-hint {
        display: none;
        width: auto;
        height: 1;
        margin-left: 1;
    }
    #interrupt-hint.visible {
        display: block;
    }
    #interrupt-key {
        width: auto;
        color: $TEXT_PRIMARY;
    }
    #interrupt-text {
        width: auto;
        color: $TEXT_MUTED;
        margin-left: 1;
    }
    #info-bar > #context-label {
        width: 1fr;
        text-align: right;
        color: $TEXT_MUTED;
        height: 1;
        padding-right: 1;
    }

    #project-title {
        width: auto;
        height: 3;
        text-align: left;
        margin-bottom: 1;
        padding: 0;
    }
    #project-title.hidden {
        display: none;
    }

    #messages-wrap {
        display: none;
        width: 100%;
        height: 1fr;
        min-width: 46;
        padding: 0 1;
        align-horizontal: center;
        background: $PAGE_BACKGROUND;
    }
    #messages-wrap.visible {
        display: block;
    }
    #messages-shell {
        width: 100%;
        height: 1fr;
        min-width: 44;
        max-width: 78;
    }

    #messages-view {
        width: 100%;
        height: 1fr;
        background: $PAGE_BACKGROUND;
    }

    #input-wrapper {
        width: 100%;
        height: auto;
    }
    #input-wrapper.welcome {
        height: 1fr;
        align-vertical: middle;
    }

    """
    )

    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("ctrl+c", "quit_attempt", "Quit"),
    ]

    sidebar_visible: bool = False

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.chat: OmniAgent | None = None
        self.chat_busy = False
        self.current_session_record: dict | None = None
        self.current_project_name = ""
        self.plan_items: list[dict] = []
        self._stream_kind: str | None = None
        self._worker_lock = threading.Lock()
        self._message_started_at: float | None = None
        self._thinking_started_at: float | None = None
        self._thinking_elapsed_timer = None
        self._settings_skills_sources_expanded = False

    def _model_profile_choices(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = [(AUTO_MODEL_SELECTION, AUTO_MODEL_SELECTION)]
        options.extend((name, name) for name in self.config.model_list.keys())
        return options

    def _api_type_title(self, api_type: str) -> str:
        api_type = str(api_type or "").strip().lower()
        titles = {
            API_TYPE_OLLAMA: "Ollama",
            API_TYPE_OPENAI: "OpenAI",
            API_TYPE_ANTHROPIC: "Anthropic",
            API_TYPE_GEMINI: "Gemini",
            API_TYPE_GLM: "GLM",
        }
        if api_type in titles:
            return titles[api_type]
        return (api_type or "Other").title()

    def compose(self) -> ComposeResult:
        with Vertical(id="left-edge", classes="sidebar-hidden"):
            yield Static("=", id="sidebar-toggle")
            yield Sidebar(id="sidebar")

        with Vertical(id="main-area"):
            with Container(id="messages-wrap"):
                with Vertical(id="messages-shell"):
                    yield ChatView(id="messages-view")

            with Vertical(id="input-wrapper", classes="welcome"):
                with Container(id="project-title-wrap"):
                    yield Static(PROJECT_LOGO, id="project-title")
                with Container(id="chat-input-wrap"):
                    yield ChatInput(id="chat-input")
                with Container(id="info-bar-wrap"):
                    with Vertical(id="info-bar-shell"):
                        with Horizontal(id="info-bar"):
                            yield ProjectPicker(id="project-picker")
                            with Horizontal(id="interrupt-hint"):
                                yield Label("esc", id="interrupt-key")
                                yield Label("interrupt", id="interrupt-text")
                            yield Label("Context: 0 (0%)", id="context-label")
                        yield HalfRowSpacer(id="info-bar-bottom")

    def on_mount(self) -> None:
        set_bridge(self)
        self._thinking_elapsed_timer = self.set_interval(
            0.1, self._refresh_thought_elapsed, pause=True
        )
        self._reload_config()
        self._refresh_project_views()
        self._apply_config_to_controls()
        self._set_current_project("")
        self._set_input_enabled(True)

    def on_unmount(self) -> None:
        clear_bridge()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "side-new-chat":
            self._reset_chat_state()
        elif btn_id == "side-settings":
            self._open_settings()

    def on_click(self, event: events.Click) -> None:
        if not event.control:
            return
        if event.control.id == "sidebar-toggle":
            self.toggle_sidebar()

    def on_chat_input_send(self, event: ChatInput.Send) -> None:
        if self.chat_busy:
            self.add_status_message("[!]", "上一条消息还在处理中。")
            return

        try:
            self._ensure_ready_for_message()
        except Exception as error:
            self.add_status_message("[✗]", f"初始化对话失败: {error}")
            return

        self.start_chat()
        chat_view = self.query_one("#messages-view", ChatView)
        chat_view.add_message("user", event.content)
        chat_view.reset_explored()
        self._set_controls_locked(True)
        self._set_input_enabled(False)
        self.chat_busy = True
        self._message_started_at = perf_counter()
        self._thinking_started_at = None
        new_session = self.current_session_record is not None and (
            not self.current_session_record.get("conversation")
        )
        worker = threading.Thread(
            target=self._process_user_message,
            args=(event.content,),
            daemon=True,
        )
        worker.start()
        if new_session:
            self._refresh_project_views()

    def on_chat_input_model_changed(self, event: ChatInput.ModelChanged) -> None:
        save_config_field("current_model", event.value)
        self._reload_config()
        if self.chat is not None:
            model = self.config.active_model
            self.chat.configure(
                api_type=model.api_type,
                base_url=model.base_url,
                model=model.model,
                api_key=model.api_key,
                max_tokens=model.max_tokens,
                temperature=model.temperature,
                stream_mode=model.stream_mode,
                thinking_mode=model.thinking_mode,
                reasoning_effort=model.reasoning_effort,
            )
        self._apply_config_to_controls()

    def on_chat_input_thinking_changed(self, event: ChatInput.ThinkingChanged) -> None:
        thinking_enabled = event.value != "none"
        effort = "" if event.value in {"", "none"} else event.value
        save_config_fields({
            "thinking_mode": thinking_enabled,
            "reasoning_effort": effort,
        })
        self._reload_config()
        if self.chat is not None:
            self.chat.set_thinking_mode(thinking_enabled)
            self.chat.set_reasoning_effort(effort)
        self._apply_config_to_controls()

    def on_chat_input_plan_mode_changed(self, event: ChatInput.PlanModeChanged) -> None:
        save_config_field("agent_plan_enable", event.enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_plan_enabled(event.enabled)
        self._apply_config_to_controls()

    def on_chat_input_approval_changed(self, event: ChatInput.ApprovalChanged) -> None:
        save_config_field("agent_approval_mode", event.value)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_approval_mode(event.value)
        self._apply_config_to_controls()

    def on_project_picker_project_selected(
        self, event: ProjectPicker.ProjectSelected
    ) -> None:
        if self._conversation_started():
            return
        self._set_current_project(event.project)

    def on_project_picker_no_project(self, event: ProjectPicker.NoProject) -> None:
        if self._conversation_started():
            return
        self._set_current_project("")

    def on_project_picker_add_project(self, event: ProjectPicker.AddProject) -> None:
        if self._conversation_started():
            return
        self.push_screen(ProjectModal(), callback=self._handle_project_modal_result)

    def on_sidebar_session_selected(self, event: Sidebar.SessionSelected) -> None:
        if self.chat_busy:
            self.add_status_message("[!]", "当前正在处理中，暂时不能切换会话。")
            return
        record = load_session(event.session_path)
        if not record:
            self.add_status_message("[✗]", "无法读取所选会话。")
            return
        self._load_session_record(record)
        if self.sidebar_visible:
            self.toggle_sidebar()

    def on_sidebar_session_action_requested(
        self, event: Sidebar.SessionActionRequested
    ) -> None:
        if self.chat_busy:
            self.add_status_message("[!]", "当前正在处理中，暂时不能操作会话。")
            return
        session_path = str(event.session_path or "").strip()
        action = str(event.action or "").strip().lower()
        if not session_path or action not in {"pin", "unpin", "delete", "load"}:
            return
        try:
            if action == "pin":
                pin_session(session_path)
                self.add_status_message("[✓]", "已置顶对话。")
            elif action == "unpin":
                unpin_session(session_path)
                self.add_status_message("[✓]", "已取消置顶。")
            elif action == "delete":
                self._delete_session_record(session_path)
                self.add_status_message("[✓]", "已删除对话。")
            elif action == "load":
                record = load_session(session_path)
                if not record:
                    self.add_status_message("[✗]", "无法读取所选会话。")
                    return
                self._load_session_record(record)
                return
        except Exception as error:
            self.add_status_message("[✗]", f"会话操作失败: {error}")
            return
        self._refresh_project_views()

    def on_sidebar_settings_requested(self, event: Sidebar.SettingsRequested) -> None:
        self._open_settings()

    def toggle_sidebar(self) -> None:
        self.sidebar_visible = not self.sidebar_visible
        left_edge = self.query_one("#left-edge", Vertical)
        main_area = self.query_one("#main-area", Vertical)
        sidebar = self.query_one("#sidebar", Sidebar)
        toggle = self.query_one("#sidebar-toggle", Static)
        if self.sidebar_visible:
            left_edge.remove_class("sidebar-hidden")
            left_edge.add_class("sidebar-visible")
            main_area.add_class("sidebar-visible")
            sidebar.remove_class("sidebar-hidden")
            sidebar.add_class("sidebar-visible")
            toggle.update("= Sessions")
        else:
            left_edge.remove_class("sidebar-visible")
            left_edge.add_class("sidebar-hidden")
            main_area.remove_class("sidebar-visible")
            sidebar.remove_class("sidebar-visible")
            sidebar.add_class("sidebar-hidden")
            toggle.update("=")

    def action_dismiss(self) -> None:
        if self.chat_busy and self.chat is not None:
            self.chat.request_agent_stop()
            return
        if self.sidebar_visible:
            self.toggle_sidebar()
        elif self.is_modal_open:
            self.pop_screen()

    def action_quit_attempt(self) -> None:
        self.notify("Press Ctrl+Q to quit", title="Quit", severity="information")

    @property
    def is_modal_open(self) -> bool:
        return len(self.screen_stack) > 1

    def start_chat(self) -> None:
        messages_wrap = self.query_one("#messages-wrap", Container)
        input_wrapper = self.query_one("#input-wrapper", Vertical)
        chat_input = self.query_one("#chat-input", ChatInput)
        info_bar_shell = self.query_one("#info-bar-shell", Vertical)
        project_picker = self.query_one("#project-picker", ProjectPicker)
        interrupt_hint = self.query_one("#interrupt-hint", Horizontal)
        project_title = self.query_one("#project-title", Static)
        project_title.add_class("hidden")
        messages_wrap.add_class("visible")
        input_wrapper.remove_class("welcome")
        chat_input.chat_active = True
        chat_input.add_class("stretch")
        info_bar_shell.add_class("stretch")
        project_picker.add_class("hidden")
        interrupt_hint.add_class("visible")

    def append_console_print(self, *objects, **kwargs) -> None:
        text = render_console_text(*objects, **kwargs).rstrip()
        if not text:
            return
        self._call_ui(self._append_console_text, text)

    def request_console_input(self, prompt) -> str:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            prompt_text = render_console_text(prompt).strip()
        return self.request_input(prompt_text, multiline=False)

    def add_status_message(self, symbol, content) -> None:
        text = str(content or "").strip()
        if not text:
            return
        self._call_ui(self._show_notification, text)

    def _show_notification(self, text: str) -> None:
        self.notify(text, severity="information")

    def add_thinking_message(self, content) -> None:
        text = clean_display_text_preserve_newlines(content)
        if not text:
            return
        self._call_ui(
            self._append_thought_message, text, self._elapsed_since_thinking()
        )

    def start_stream_thinking(self) -> None:
        pass

    def start_thinking_timer(self) -> None:
        if self._thinking_started_at is None:
            self._thinking_started_at = perf_counter()
        self._resume_thinking_elapsed_timer()

    def append_stream_thinking(self, content) -> None:
        if self._thinking_started_at is None:
            self._thinking_started_at = perf_counter()
        self._resume_thinking_elapsed_timer()
        self._call_ui(self._append_thought_stream_widget, str(content or ""))

    def finish_thinking_round(self) -> None:
        elapsed = self._elapsed_since_thinking()
        self._call_ui(self._finish_thought_stream_widget, elapsed)
        self._thinking_started_at = None
        self._call_ui(self._reset_explored_widget)

    def _reset_explored_widget(self) -> None:
        self.query_one("#messages-view", ChatView).reset_explored()

    def start_stream_response(self, model_name) -> None:
        self._pause_thinking_elapsed_timer()
        self._call_ui(
            self._finish_thought_stream_widget,
            self._elapsed_since_thinking(),
        )
        self._thinking_started_at = None
        self._call_ui(self._start_stream_widget, "assistant", "")

    def append_stream_response(self, content) -> None:
        self._call_ui(self._append_stream_widget, "assistant", str(content or ""), "")

    def set_plan_items(self, items) -> None:
        self.plan_items = [item for item in items or [] if isinstance(item, dict)]

    def set_context_usage(self, input_tokens, context_window_tokens) -> None:
        self._call_ui(self._set_context_label, input_tokens, context_window_tokens)

    def request_confirmation(self, title, detail="") -> bool:
        request = _BlockingModalRequest(threading.Event())

        def show_modal() -> None:
            self.push_screen(
                ConfirmModal(str(title or "Confirm"), str(detail or "")),
                callback=lambda result: self._resolve_modal_request(
                    request, bool(result)
                ),
            )

        self._call_ui(show_modal)
        request.event.wait()
        return bool(request.result)

    def request_choice(self, question, options, default_index=1) -> int:
        request = _BlockingModalRequest(threading.Event())
        options = [str(option) for option in options or []]
        if not options:
            return 0

        def show_modal() -> None:
            self.push_screen(
                ChoiceModal(str(question or "Choose"), options),
                callback=lambda result: self._resolve_modal_request(
                    request, int(result or 0)
                ),
            )

        self._call_ui(show_modal)
        request.event.wait()
        if request.result:
            return int(request.result)
        return max(1, min(len(options), int(default_index or 1)))

    def request_input(self, prompt_text, multiline=False) -> str:
        request = _BlockingModalRequest(threading.Event())

        def show_modal() -> None:
            self.push_screen(
                InputModal(str(prompt_text or "Input"), multiline=bool(multiline)),
                callback=lambda result: self._resolve_modal_request(
                    request, str(result or "")
                ),
            )

        self._call_ui(show_modal)
        request.event.wait()
        return str(request.result or "")

    def clear_current_lines(self, line_count) -> None:
        return

    def _resolve_modal_request(self, request: _BlockingModalRequest, result) -> None:
        request.result = result
        request.event.set()

    def _call_ui(self, callback, *args) -> None:
        if threading.current_thread() is threading.main_thread():
            callback(*args)
        else:
            self.call_from_thread(callback, *args)

    def _append_console_text(self, text: str) -> None:
        self.query_one("#messages-view", ChatView).add_status(text)

    def _append_status_text(self, text: str) -> None:
        self.query_one("#messages-view", ChatView).add_status(text)
        self._stream_kind = None

    def _append_thought_message(self, text: str, elapsed_seconds: float) -> None:
        self.query_one("#messages-view", ChatView).add_thought(
            text, elapsed_seconds=elapsed_seconds
        )
        self._stream_kind = None

    def _append_thought_stream_widget(self, content: str) -> None:
        self.query_one("#messages-view", ChatView).append_thought_stream(content)
        self._stream_kind = "thought"

    def _finish_thought_stream_widget(self, elapsed_seconds: float) -> None:
        self.query_one("#messages-view", ChatView).finish_thought_stream(
            elapsed_seconds=elapsed_seconds
        )
        if self._stream_kind == "thought":
            self._stream_kind = None

    def _replace_thought_stream_widget(self, content: str, elapsed: float) -> None:
        self.query_one("#messages-view", ChatView).replace_thought_stream(
            content, elapsed
        )
        self._stream_kind = None

    def add_explored_entry(self, tool_name: str, description: str) -> None:
        self._call_ui(self._append_explored_entry, tool_name, description)

    def _append_explored_entry(self, tool_name: str, description: str) -> None:
        self.query_one("#messages-view", ChatView).add_explored_entry(
            tool_name, description
        )

    def _start_stream_widget(self, role: str, prefix: str) -> None:
        self.query_one("#messages-view", ChatView).start_stream(
            role=role, prefix=prefix
        )
        self._stream_kind = role

    def _append_stream_widget(self, role: str, content: str, prefix: str) -> None:
        view = self.query_one("#messages-view", ChatView)
        view.append_stream(content, role=role, prefix=prefix)
        self._stream_kind = role

    def _clear_recent_status(self, line_count: int) -> None:
        self.query_one("#messages-view", ChatView).remove_last_messages(1)
        self._stream_kind = None

    def _set_context_label(self, input_tokens, context_window_tokens) -> None:
        try:
            input_tokens = max(0, int(input_tokens or 0))
        except (TypeError, ValueError):
            input_tokens = 0
        try:
            context_window_tokens = max(1, int(context_window_tokens or 1))
        except (TypeError, ValueError):
            context_window_tokens = 1

        if input_tokens >= 1000:
            value = f"{input_tokens / 1000:.1f}k"
        else:
            value = str(input_tokens)
        percent = (input_tokens / context_window_tokens) * 100
        self.query_one("#context-label", Label).update(
            f"Context: {value} ({percent:.0f}%)"
        )

    def _reload_config(self) -> None:
        self.config = load_config()

    def _apply_config_to_controls(self) -> None:
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
        except NoMatches:
            return
        model_options = [(name, name) for name in self.config.model_list.keys()]
        chat_input.set_model_options(model_options, self.config.current_model)
        chat_input.plan_mode = bool(self.config.agent_plan_enable)
        chat_input.set_selected_approval(self.config.agent_approval_mode)
        chat_input.set_selected_thinking(self._thinking_value_from_config())

    def _thinking_value_from_config(self) -> str:
        active_model = self.config.active_model
        if not active_model.thinking_mode:
            return "none"
        return (
            str(active_model.reasoning_effort or "medium").strip().lower() or "medium"
        )

    def _refresh_project_views(self) -> None:
        pinned_paths = {
            str(session.get("session_path") or "")
            for session in list_pinned_sessions()
            if session.get("session_path")
        }
        project_rows = []
        project_names = []
        for project in load_projects():
            sessions = list_sessions(project)
            filtered = []
            for session in sessions:
                is_pinned = str(session.get("session_path") or "") in pinned_paths
                session["_pinned"] = is_pinned
                if not is_pinned:
                    filtered.append(session)
            project_rows.append({
                "name": project.name,
                "sessions": filtered,
            })
            project_names.append(project.name)

        pinned_sessions = list_pinned_sessions()
        for session in pinned_sessions:
            session["_pinned"] = True
        orphan_sessions = list_sessions(None)
        filtered_orphans = []
        for session in orphan_sessions:
            is_pinned = str(session.get("session_path") or "") in pinned_paths
            session["_pinned"] = is_pinned
            if not is_pinned:
                filtered_orphans.append(session)
        self.query_one("#sidebar", Sidebar).set_sessions(
            project_rows, pinned_sessions, filtered_orphans
        )
        picker = self.query_one("#project-picker", ProjectPicker)
        picker.set_projects(project_names)
        picker.set_current_project(self.current_project_name)

    def _set_current_project(self, project_name: str) -> None:
        self.current_project_name = str(project_name or "").strip()
        self.query_one("#project-picker", ProjectPicker).set_current_project(
            self.current_project_name
        )

    def _selected_project(self) -> ProjectRecord | None:
        if not self.current_project_name:
            return None
        return get_project_by_name(self.current_project_name)

    def _project_from_session(self, record: dict | None) -> ProjectRecord | None:
        data = (record or {}).get("project") or {}
        name = str(data.get("name") or "").strip()
        path = str(data.get("path") or "").strip()
        if not name or not path:
            return self._selected_project()
        return ProjectRecord(
            name=name,
            path=path,
            slug=str(data.get("slug") or name).strip(),
            created_at=str(
                data.get("created_at") or datetime.now().isoformat(timespec="seconds")
            ),
        )

    def _conversation_started(self) -> bool:
        return self.current_session_record is not None and bool(
            (self.current_session_record or {}).get("conversation")
        )

    def _set_controls_locked(self, locked: bool) -> None:
        self.query_one("#chat-input", ChatInput).set_controls_locked(locked)

    def _set_input_enabled(self, enabled: bool) -> None:
        widget = self.query_one("#message-input", Input)
        widget.disabled = not enabled

    def _open_settings(self) -> None:
        self.push_screen(SettingsModal(pages=self._settings_pages(), app=self))

    def _settings_pages(self) -> dict[str, dict]:
        return {
            "root": {
                "title": "Settings",
                "layout": "list",
                "rows": self._settings_home_rows,
            },
            "model_list": {
                "title": "Model list",
                "layout": "model_list",
                "show_search": False,
                "state": self._settings_model_page_state,
                "on_select_model": self._on_setting_model_changed,
                "on_add_model": self._on_setting_add_model,
            },
            "agent_mode": {
                "title": "Agent mode",
                "layout": "list",
                "rows": self._settings_agent_mode_rows,
            },
            "skills": {
                "title": "Skills",
                "layout": "list",
                "rows": self._settings_skills_rows,
            },
            "auto_compact": {
                "title": "Auto compact",
                "layout": "list",
                "rows": self._settings_auto_compact_rows,
            },
            "memory_system": {
                "title": "Memory system",
                "layout": "list",
                "rows": self._settings_memory_rows,
            },
            "web_search": {
                "title": "Web search",
                "layout": "list",
                "rows": self._settings_web_search_rows,
            },
        }

    def _settings_home_rows(self) -> list[dict]:
        return [
            {
                "name": "Model list",
                "value": ">",
                "keywords": "model list model_list current_model",
                "edit_type": "nav",
                "target_page": "model_list",
            },
            {
                "name": "Agent mode",
                "value": ">",
                "keywords": "agent mode agent_mode",
                "edit_type": "nav",
                "target_page": "agent_mode",
            },
            {
                "name": "Skills",
                "value": ">",
                "keywords": "skills",
                "edit_type": "nav",
                "target_page": "skills",
            },
            {
                "name": "Auto compact",
                "value": ">",
                "keywords": "auto compact auto_compact",
                "edit_type": "nav",
                "target_page": "auto_compact",
            },
            {
                "name": "Memory system",
                "value": ">",
                "keywords": "memory system memory_system",
                "edit_type": "nav",
                "target_page": "memory_system",
            },
            {
                "name": "Web search",
                "value": ">",
                "keywords": "web search web_search",
                "edit_type": "nav",
                "target_page": "web_search",
            },
        ]

    def _settings_model_page_state(self, selected_name: str = "") -> dict:
        models = [name for name in self.config.model_list.keys()]
        current_model = (
            self.config.current_model if self.config.current_model in models else ""
        )
        if selected_name and selected_name in models:
            current_model = selected_name

        grouped: dict[str, list[str]] = {}
        for model_name, profile in self.config.model_list.items():
            api_type = str(getattr(profile, "api_type", "") or "").strip().lower()
            grouped.setdefault(api_type, []).append(str(model_name))
        groups = [
            {
                "api_type": api_type,
                "title": self._api_type_title(api_type),
                "models": sorted(model_names, key=lambda x: x.lower()),
            }
            for api_type, model_names in grouped.items()
        ]
        groups.sort(key=lambda g: str(g.get("title") or "").lower())
        return {
            "models": models,
            "groups": groups,
            "selected_model": current_model,
            "rows": self._settings_model_rows(),
        }

    def _settings_model_rows(self) -> list[dict]:
        active_model = self.config.active_model
        bool_choices = [("true", "true"), ("false", "false")]
        reasoning_choices = [
            ("none", "none"),
            ("minimal", "minimal"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
        ]
        current_effort = str(active_model.reasoning_effort or "none")
        if current_effort not in {value for _, value in reasoning_choices}:
            current_effort = "none"

        rows = [
            {
                "name": "API type",
                "value": self._api_type_title(active_model.api_type),
                "keywords": "api_type",
                "edit_type": "none",
            },
            {
                "name": "Model name",
                "value": self.config.current_model,
                "keywords": "model name rename",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_name_changed(v),
            },
            {
                "name": "Base URL",
                "value": active_model.base_url,
                "keywords": "base_url",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_base_url_changed(v),
            },
            {
                "name": "Model",
                "value": active_model.model,
                "keywords": "model backend",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_id_changed(v),
            },
            {
                "name": "API key",
                "value": active_model.api_key,
                "keywords": "api_key",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_api_key_changed(v),
            },
            {
                "name": "Max tokens",
                "value": str(active_model.max_tokens),
                "keywords": "max_tokens",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_token_changed(v),
            },
            {
                "name": "Temperature",
                "value": str(active_model.temperature),
                "keywords": "temperature",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_temp_changed(v),
            },
            {
                "name": "Stream",
                "value": "true" if active_model.stream_mode else "false",
                "keywords": "stream_mode stream",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_stream_changed(v),
            },
            {
                "name": "Thinking",
                "value": "true" if active_model.thinking_mode else "false",
                "keywords": "thinking_mode thinking",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_model_thinking_changed(v),
            },
            {
                "name": "Context",
                "value": str(active_model.context_window_tokens),
                "keywords": "context_window_tokens context",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_context_changed(v),
            },
        ]
        if active_model.thinking_mode:
            rows.insert(
                -1,
                {
                    "name": "Reasoning effort",
                    "value": current_effort,
                    "keywords": "reasoning_effort",
                    "edit_type": "select",
                    "options": reasoning_choices,
                    "on_change": lambda v: (
                        self._on_setting_model_reasoning_effort_changed(v)
                    ),
                },
            )
        rows.append({"name": "", "value": "", "edit_type": "none"})
        rows.append({
            "name": "",
            "value": "Delete",
            "keywords": "delete",
            "edit_type": "action",
            "show_value": True,
            "on_activate": self._on_setting_delete_current_model,
        })
        return rows

    def _on_setting_model_name_changed(self, value: str) -> None:
        new_name = str(value or "").strip()
        if not new_name:
            return
        old_name = str(self.config.current_model or "").strip()
        if not old_name:
            return
        try:
            renamed = rename_model_profile(old_name, new_name)
        except Exception as error:
            self.add_status_message("[✗]", f"重命名失败: {error}")
            return
        self._reload_config()
        self._on_setting_model_changed(renamed)

    def _settings_agent_mode_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        return [
            {
                "name": "Max rounds",
                "value": str(self.config.max_agent_rounds),
                "keywords": "max_rounds",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_rounds_changed(v),
            },
            {
                "name": "Max tool calls",
                "value": str(self.config.max_agent_tool_calls),
                "keywords": "max_tool_calls",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_tool_calls_changed(v),
            },
            {
                "name": "Show thinking",
                "value": "true" if self.config.agent_show_thinking else "false",
                "keywords": "show_thinking",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_agent_show_thinking_changed(v),
            },
            {
                "name": "Plan mode",
                "value": "true" if self.config.agent_plan_enable else "false",
                "keywords": "plan_mode",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_plan_changed(v),
            },
            {
                "name": "Agent team",
                "value": "true" if self.config.agent_team_enable else "false",
                "keywords": "agent_team enable",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_agent_team_changed(v),
            },
        ]

    def _toggle_settings_skills_sources(self) -> None:
        self._settings_skills_sources_expanded = (
            not self._settings_skills_sources_expanded
        )

    def _settings_skills_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        rows = [
            {
                "name": "Enable",
                "value": "true" if self.config.skills_enable else "false",
                "keywords": "enable skills",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_skills_changed(v),
            },
            {
                "name": "Sources",
                "value": "v" if self._settings_skills_sources_expanded else ">",
                "keywords": "sources app workspace",
                "edit_type": "action",
                "on_activate": self._toggle_settings_skills_sources,
            },
            {
                "name": "Auto catalog",
                "value": "true" if self.config.skills_auto_catalog else "false",
                "keywords": "auto_catalog",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_skills_auto_catalog_changed(v),
            },
            {
                "name": "Max skill chars",
                "value": str(self.config.skills_max_chars),
                "keywords": "max_skill_chars",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_skills_max_changed(v),
            },
        ]
        if self._settings_skills_sources_expanded:
            rows[2:2] = [
                {
                    "name": "App",
                    "value": "true" if self.config.skills_source_app else "false",
                    "keywords": "sources app",
                    "edit_type": "toggle",
                    "options": bool_choices,
                    "indented": True,
                    "on_change": lambda v: self._on_setting_skills_source_app_changed(
                        v
                    ),
                },
                {
                    "name": "Workspace",
                    "value": "true" if self.config.skills_source_workspace else "false",
                    "keywords": "sources workspace",
                    "edit_type": "toggle",
                    "options": bool_choices,
                    "indented": True,
                    "on_change": lambda v: (
                        self._on_setting_skills_source_workspace_changed(v)
                    ),
                },
            ]
        return rows

    def _settings_auto_compact_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        model_choices = self._model_profile_choices()
        return [
            {
                "name": "Enable",
                "value": "true" if self.config.compaction_enable else "false",
                "keywords": "enable compact",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_compact_changed(v),
            },
            {
                "name": "Trigger ratio",
                "value": str(self.config.compaction_trigger_ratio),
                "keywords": "trigger_ratio",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_compact_ratio_changed(v),
            },
            {
                "name": "Keep recent messages",
                "value": str(self.config.compaction_keep_recent_messages),
                "keywords": "keep_recent_messages",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_compact_keep_recent_changed(v),
            },
            {
                "name": "Compact model",
                "value": normalize_optional_model_selection(
                    self.config.compaction_compact_model
                ),
                "keywords": "compact_model",
                "edit_type": "select",
                "options": model_choices,
                "on_change": lambda v: self._on_setting_compact_model_changed(v),
            },
        ]

    def _settings_memory_rows(self) -> list[dict]:
        model_choices = self._model_profile_choices()
        return [
            {
                "name": "Memory model",
                "value": normalize_optional_model_selection(self.config.memory_model),
                "keywords": "memory_model",
                "edit_type": "select",
                "options": model_choices,
                "on_change": lambda v: self._on_setting_memory_model_changed(v),
            },
        ]

    def _settings_web_search_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        provider_choices = [
            (provider, provider) for provider in sorted(WEB_SEARCH_PROVIDERS)
        ]
        search_depth_choices = [
            (depth, depth)
            for depth in ("basic", "fast", "ultra-fast", "advanced")
            if depth in TAVILY_SEARCH_DEPTHS
        ]
        topic_choices = [
            (topic, topic)
            for topic in ("general", "news", "finance")
            if topic in TAVILY_TOPICS
        ]
        return [
            {
                "name": "Enable",
                "value": "true" if self.config.web_search_enable else "false",
                "keywords": "enable web_search",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_search_changed(v),
            },
            {
                "name": "Provider",
                "value": self.config.web_search_provider,
                "keywords": "provider",
                "edit_type": "select",
                "options": provider_choices,
                "on_change": lambda v: self._on_setting_search_provider_changed(v),
            },
            {
                "name": "API key",
                "value": self.config.web_search_api_key,
                "keywords": "api_key",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_search_api_key_changed(v),
            },
            {
                "name": "Max results",
                "value": str(self.config.web_search_max_results),
                "keywords": "max_results",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_search_max_changed(v),
            },
            {
                "name": "Search depth",
                "value": self.config.web_search_depth,
                "keywords": "search_depth",
                "edit_type": "select",
                "options": search_depth_choices,
                "on_change": lambda v: self._on_setting_search_depth_changed(v),
            },
            {
                "name": "Topic",
                "value": self.config.web_search_topic,
                "keywords": "topic",
                "edit_type": "select",
                "options": topic_choices,
                "on_change": lambda v: self._on_setting_search_topic_changed(v),
            },
        ]

    def _sync_chat_from_active_model(self) -> None:
        if self.chat is None:
            return
        model = self.config.active_model
        self.chat.configure(
            api_type=model.api_type,
            base_url=model.base_url,
            model=model.model,
            api_key=model.api_key,
            max_tokens=model.max_tokens,
            temperature=model.temperature,
            stream_mode=model.stream_mode,
            thinking_mode=model.thinking_mode,
            reasoning_effort=model.reasoning_effort,
        )

    def _on_setting_add_model(self, model_name: str, source_name: str = "") -> str:
        model_name = str(model_name or "").strip()
        if not model_name:
            return ""
        try:
            created_name = add_model_profile(model_name, source_name)
        except Exception as error:
            self.add_status_message("[✗]", f"新增模型失败: {error}")
            return ""
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()
        return created_name

    def _on_setting_delete_current_model(self) -> None:
        name = str(self.config.current_model or "").strip()
        if not name:
            return
        try:
            delete_model_profile(name)
        except Exception as error:
            self.add_status_message("[✗]", f"删除模型失败: {error}")
            return
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_changed(self, value: str) -> None:
        save_config_field("current_model", value)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_api_type_changed(self, value: str) -> None:
        save_config_field("api_type", value)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_base_url_changed(self, value: str) -> None:
        save_config_field("base_url", value)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_id_changed(self, value: str) -> None:
        model_id = str(value or "").strip()
        if not model_id:
            return
        save_config_field("model", model_id)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_api_key_changed(self, value: str) -> None:
        save_config_field("api_key", str(value or "").strip())
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_thinking_changed(self, value: str) -> None:
        enabled = str(value or "").lower() in ("on", "true", "yes")
        save_config_field("thinking_mode", enabled)
        if not enabled:
            save_config_field("reasoning_effort", "")
        self._reload_config()
        if self.chat is not None:
            self.chat.set_thinking_mode(enabled)
            if not enabled:
                self.chat.set_reasoning_effort("")
        self._apply_config_to_controls()

    def _on_setting_model_reasoning_effort_changed(self, value: str) -> None:
        effort = str(value or "").strip().lower() or "none"
        save_config_field("reasoning_effort", effort)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_reasoning_effort(effort)
        self._apply_config_to_controls()

    def _on_setting_model_context_changed(self, value: str) -> None:
        try:
            tokens = max(1, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("context_window_tokens", tokens)
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_token_changed(self, value: str) -> None:
        try:
            tokens = max(1, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("max_tokens", tokens)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_max_tokens(tokens)
        self._apply_config_to_controls()

    def _on_setting_temp_changed(self, value: str) -> None:
        try:
            temp = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        save_config_field("temperature", temp)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_temperature(temp)
        self._apply_config_to_controls()

    def _on_setting_stream_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("stream_mode", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_stream_mode(enabled)
        self._apply_config_to_controls()

    def _on_setting_thinking_changed(self, value: str) -> None:
        thinking_enabled = value != "none"
        effort = "" if value in {"", "none"} else value
        save_config_fields({
            "thinking_mode": thinking_enabled,
            "reasoning_effort": effort,
        })
        self._reload_config()
        if self.chat is not None:
            self.chat.set_thinking_mode(thinking_enabled)
            self.chat.set_reasoning_effort(effort)
        self._apply_config_to_controls()

    def _on_setting_plan_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("agent_plan_enable", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_plan_enabled(enabled)
        self._apply_config_to_controls()

    def _on_setting_agent_team_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("agent_team_enable", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_team_mode(enabled)
        self._apply_config_to_controls()

    def _on_setting_approval_changed(self, value: str) -> None:
        save_config_field("agent_approval_mode", value)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_approval_mode(value)
        self._apply_config_to_controls()

    def _on_setting_agent_show_thinking_changed(self, value: str) -> None:
        enabled = str(value or "").lower() in ("on", "true", "yes")
        save_config_field("agent_show_thinking", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_show_thinking(enabled)
        self._apply_config_to_controls()

    def _on_setting_rounds_changed(self, value: str) -> None:
        try:
            rounds = max(1, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("max_agent_rounds", rounds)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_limits(max_rounds=rounds)
        self._apply_config_to_controls()

    def _on_setting_tool_calls_changed(self, value: str) -> None:
        try:
            calls = max(1, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("max_agent_tool_calls", calls)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_agent_limits(max_tool_calls=calls)
        self._apply_config_to_controls()

    def _on_setting_skills_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("skills_enable", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_skills_config(enabled=enabled)
        self._apply_config_to_controls()

    def _on_setting_skills_source_app_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("skills_source_app", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_skills_config(app_enabled=enabled)
        self._apply_config_to_controls()

    def _on_setting_skills_source_workspace_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("skills_source_workspace", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_skills_config(workspace_enabled=enabled)
        self._apply_config_to_controls()

    def _on_setting_skills_auto_catalog_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("skills_auto_catalog", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_skills_config(auto_catalog=enabled)
        self._apply_config_to_controls()

    def _on_setting_skills_max_changed(self, value: str) -> None:
        try:
            chars = max(1000, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("skills_max_chars", chars)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_skills_config(max_chars=chars)
        self._apply_config_to_controls()

    def _on_setting_search_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("web_search_enable", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.agent_tools.set_web_search_config(enabled=enabled)
        self._apply_config_to_controls()

    def _on_setting_search_max_changed(self, value: str) -> None:
        try:
            count = max(1, min(20, int(value)))
        except (TypeError, ValueError):
            return
        save_config_field("web_search_max_results", count)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_web_search_config(max_results=count)
        self._apply_config_to_controls()

    def _on_setting_search_provider_changed(self, value: str) -> None:
        save_config_field("web_search_provider", value)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_web_search_config(provider=value)
        self._apply_config_to_controls()

    def _on_setting_search_api_key_changed(self, value: str) -> None:
        api_key = str(value or "").strip()
        save_config_field("web_search_api_key", api_key)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_web_search_config(api_key=api_key)
        self._apply_config_to_controls()

    def _on_setting_search_depth_changed(self, value: str) -> None:
        save_config_field("web_search_depth", value)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_web_search_config(search_depth=value)
        self._apply_config_to_controls()

    def _on_setting_search_topic_changed(self, value: str) -> None:
        save_config_field("web_search_topic", value)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_web_search_config(topic=value)
        self._apply_config_to_controls()

    def _on_setting_debug_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("debug", enabled)
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_compact_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("compaction_enable", enabled)
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_compact_ratio_changed(self, value: str) -> None:
        try:
            ratio = max(0.1, min(0.95, float(value)))
        except (TypeError, ValueError):
            return
        save_config_field("compaction_trigger_ratio", ratio)
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_compact_keep_recent_changed(self, value: str) -> None:
        try:
            keep_recent = max(1, int(value))
        except (TypeError, ValueError):
            return
        save_config_field("compaction_keep_recent_messages", keep_recent)
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_compact_model_changed(self, value: str) -> None:
        save_config_field(
            "compaction_compact_model",
            normalize_optional_model_selection(value),
        )
        self._reload_config()
        self._apply_config_to_controls()

    def _on_setting_memory_model_changed(self, value: str) -> None:
        save_config_field("memory_model", normalize_optional_model_selection(value))
        self._reload_config()
        self._apply_config_to_controls()

    def _handle_project_modal_result(self, result: dict | None) -> None:
        if not result:
            return
        try:
            project = add_project(result.get("name"), result.get("path"))
        except Exception as error:
            self.add_status_message("[✗]", f"新建项目失败: {error}")
            return
        self._set_current_project(project.name)
        self._refresh_project_views()

    def _reset_chat_state(self) -> None:
        self._clear_loaded_session_state(refresh_sidebar=True)

    def _clear_loaded_session_state(self, refresh_sidebar: bool = True) -> None:
        self.chat = None
        self.chat_busy = False
        self.current_session_record = None
        self.plan_items = []
        self._stream_kind = None
        self._set_input_enabled(True)
        self._set_context_label(0, self.config.context_window_tokens)
        self._set_controls_locked(False)

        messages = self.query_one("#messages-view", ChatView)
        messages_wrap = self.query_one("#messages-wrap", Container)
        chat_input = self.query_one("#chat-input", ChatInput)
        input_wrapper = self.query_one("#input-wrapper", Vertical)
        info_bar_shell = self.query_one("#info-bar-shell", Vertical)
        project_picker = self.query_one("#project-picker", ProjectPicker)
        interrupt_hint = self.query_one("#interrupt-hint", Horizontal)
        project_title = self.query_one("#project-title", Static)
        chat_input.chat_active = False
        chat_input.remove_class("stretch")
        info_bar_shell.remove_class("stretch")
        project_picker.remove_class("hidden")
        interrupt_hint.remove_class("visible")
        project_title.remove_class("hidden")
        messages_wrap.remove_class("visible")
        messages.clear()
        input_wrapper.add_class("welcome")
        self._apply_config_to_controls()
        if refresh_sidebar:
            self._refresh_project_views()

    def _delete_session_record(self, session_path: str) -> None:
        current_path = str(
            (self.current_session_record or {}).get("session_path") or ""
        ).strip()
        delete_session(session_path)
        if current_path and current_path == str(session_path).strip():
            self._clear_loaded_session_state(refresh_sidebar=False)

    def _ensure_ready_for_message(self) -> None:
        if self.current_session_record is None:
            self.current_session_record = create_session(
                project=self._selected_project(),
                title="New Chat",
                model_name=self.config.current_model,
            )
        if self.chat is None:
            self.chat = self._build_chat(self.current_session_record)

    def _build_chat(self, session_record: dict) -> OmniAgent:
        project = self._project_from_session(session_record)
        workspace_dir = project.path if project is not None else None
        agent_mode = bool(project is not None)
        model = self.config.active_model
        chat = OmniAgent(
            model=model.model,
            api_key=model.api_key,
            api_type=model.api_type,
            base_url=model.base_url,
            max_tokens=model.max_tokens,
            context_window_tokens=model.context_window_tokens,
            temperature=model.temperature,
            stream_mode=model.stream_mode,
            thinking_mode=model.thinking_mode,
            reasoning_effort=model.reasoning_effort,
            agent_mode=agent_mode,
            workspace_dir=workspace_dir,
            max_agent_rounds=self.config.max_agent_rounds,
            max_agent_tool_calls=self.config.max_agent_tool_calls,
            agent_approval_mode=self.config.agent_approval_mode,
            agent_show_thinking=bool(self.config.agent_show_thinking),
            skills_enabled=self.config.skills_enable,
            skills_source_app=self.config.skills_source_app,
            skills_source_workspace=self.config.skills_source_workspace,
            skills_auto_catalog=self.config.skills_auto_catalog,
            skills_max_chars=self.config.skills_max_chars,
            compaction_enable=self.config.compaction_enable,
            compaction_trigger_ratio=self.config.compaction_trigger_ratio,
            compaction_keep_recent_messages=self.config.compaction_keep_recent_messages,
            compaction_compact_model=self.config.compaction_compact_model,
            memory_model=self.config.memory_model,
            debug=self.config.debug,
            web_search_enabled=self.config.web_search_enable,
            web_search_provider=self.config.web_search_provider,
            web_search_api_key=self.config.web_search_api_key,
            web_search_max_results=self.config.web_search_max_results,
            web_search_depth=self.config.web_search_depth,
            web_search_topic=self.config.web_search_topic,
            agent_plan_enabled=self.config.agent_plan_enable,
            agent_team_enable=self.config.agent_team_enable,
            history_path=session_record.get("history_path"),
        )
        return chat

    def _process_user_message(self, user_text: str) -> None:
        try:
            if user_text.startswith("/"):
                self._process_command_message(user_text)
                return

            enriched_text, media_references = (
                attach_external_file_references_with_media(user_text)
            )
            response = self.chat.send_message(
                enriched_text,
                stream_callback_thinking=self.append_stream_thinking,
                stream_callback_response=self.append_stream_response,
                media_references=media_references,
            )
            if response and not response.get("agent_stopped"):
                self.chat.update_session_episodic_memory()
            self._call_ui(self._finish_response, response)
        except Exception as error:
            self._call_ui(self._finish_with_error, error)

    def _process_command_message(self, command_text: str) -> None:
        base = command_text.split(maxsplit=1)[0].lower()
        if base == "/save":
            self._call_ui(self._finish_save_command)
            return
        if base == "/conf" and len(command_text.split()) == 1:
            self._call_ui(self._finish_open_settings_command)
            return

        should_continue = process_command(
            command_text, self.chat or self._build_chat_for_command()
        )
        self._reload_config()
        self._call_ui(self._after_command, base, should_continue)

    def _build_chat_for_command(self) -> OmniAgent:
        record = self.current_session_record or create_session(
            project=self._selected_project(),
            title="New Chat",
            model_name=self.config.current_model,
        )
        self.current_session_record = record
        self.chat = self._build_chat(record)
        return self.chat

    def _finish_save_command(self) -> None:
        self._persist_current_session()
        self.chat_busy = False
        self._set_input_enabled(True)
        self.add_status_message("[✓]", "当前会话已保存。")

    def _finish_open_settings_command(self) -> None:
        self.chat_busy = False
        self._set_input_enabled(True)
        self._open_settings()

    def _after_command(self, base: str, should_continue) -> None:
        self.chat_busy = False
        self._set_input_enabled(True)
        self._apply_config_to_controls()
        if should_continue is False:
            self.exit()
            return
        if base == "/clear":
            self._reset_chat_state()
            self.add_status_message("[✓]", "对话历史已清空。")
            return
        if base == "/conf":
            self._sync_chat_view_with_history()
        self._persist_current_session(refresh_sidebar=base in {"/conf"})

    def _finish_response(self, response) -> None:
        self._pause_thinking_elapsed_timer()
        self._finish_thought_stream_widget(
            self._elapsed_since_thinking(),
        )
        self.chat_busy = False
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._display_response(response)
        self._persist_current_session()
        self._message_started_at = None
        self._thinking_started_at = None

    def _finish_with_error(self, error: Exception) -> None:
        self._pause_thinking_elapsed_timer()
        self._finish_thought_stream_widget(
            self._elapsed_since_thinking(),
        )
        self.chat_busy = False
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self.add_status_message("[✗]", f"处理消息失败: {error}")
        self._persist_current_session()
        self._message_started_at = None
        self._thinking_started_at = None

    def _display_response(self, response) -> None:
        if not response:
            self.add_status_message("[✗]", "请求失败，请检查模型配置和网络连接。")
            return
        if response.get("agent_stopped"):
            return

        stream_mode = bool(
            self.chat and self.chat.stream_mode and not self.chat.agent_mode
        )
        if response.get("thinking") and response.get("thinking_streamed") is False:
            if self.chat is not None and self.chat.thinking_mode:
                self.add_thinking_message(response.get("thinking"))

        if stream_mode or response.get("response_streamed"):
            return

        reply = clean_display_text_preserve_newlines(response.get("response", ""))
        if reply:
            self.query_one("#messages-view", ChatView).add_message("assistant", reply)

    def _elapsed_since_thinking(self) -> float:
        if self._thinking_started_at is not None:
            elapsed = perf_counter() - self._thinking_started_at
            return max(0.0, elapsed)
        if self._message_started_at is not None:
            elapsed = perf_counter() - self._message_started_at
            return max(0.0, elapsed)
        return 0.0

    def _refresh_thought_elapsed(self) -> None:
        if self._thinking_started_at is None:
            return
        self.query_one("#messages-view", ChatView).update_thought_stream_elapsed(
            self._elapsed_since_thinking()
        )

    def _resume_thinking_elapsed_timer(self) -> None:
        if self._thinking_elapsed_timer is not None:
            self._thinking_elapsed_timer.resume()

    def _pause_thinking_elapsed_timer(self) -> None:
        if self._thinking_elapsed_timer is not None:
            self._thinking_elapsed_timer.pause()

    def _persist_current_session(self, refresh_sidebar: bool = True) -> None:
        if self.current_session_record is None or self.chat is None:
            return
        history = list(self.chat.get_history() or [])
        record = dict(self.current_session_record)
        record["conversation"] = history
        record["model_name"] = self.config.current_model
        project = self._selected_project()
        record["project"] = project.to_dict() if project is not None else None
        if (
            not str(record.get("title") or "").strip()
            or record.get("title") == "New Chat"
        ):
            record["title"] = self._session_title_from_history(history)
        self.current_session_record = save_session_record(record)
        if refresh_sidebar:
            self._refresh_project_views()

    def _session_title_from_history(self, history: list[dict]) -> str:
        for message in history or []:
            if str(message.get("role") or "") != "user":
                continue
            title = " ".join(clean_display_text(message.get("content", "")).split())
            if title:
                return title[:60]
        return "New Chat"

    def _sync_chat_view_with_history(self) -> None:
        history = list(self.chat.get_history() if self.chat is not None else [])
        self.start_chat()
        view = self.query_one("#messages-view", ChatView)
        view.clear()
        for message in history:
            role = str(message.get("role") or "")
            content = clean_display_text_preserve_newlines(message.get("content", ""))
            if role in {"user", "assistant"}:
                view.add_message(role, content)
            elif content:
                view.add_status(f"{role.upper()}: {content}")
        self.query_one("#chat-input", ChatInput).chat_active = True

    def _load_session_record(self, record: dict) -> None:
        self.current_session_record = record
        project = self._project_from_session(record)
        self._set_current_project(project.name if project is not None else "")
        if record.get("model_name") in self.config.model_list:
            save_config_field("current_model", record.get("model_name"))
            self._reload_config()
        self.chat = self._build_chat(record)
        self.chat.set_history(record.get("conversation") or [])
        self._sync_chat_view_with_history()
        self._apply_config_to_controls()
        self._refresh_project_views()
