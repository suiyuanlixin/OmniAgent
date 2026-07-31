from __future__ import annotations

import re
import shutil
import threading
from time import perf_counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.markup import escape as escape_markup
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Label, Static, TextArea

from ..chat import OmniAgent, USER_PROMPT_FILE, USER_PROMPT_TEMPLATE
from ..commands import COMMANDS, process_command
from ..config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    AUTO_MODEL_SELECTION,
    DEFAULT_EXTRA_MODALITY_LIMITS,
    SUPPORTED_EXTRA_MODALITIES,
    delete_model_profile,
    format_extra_modalities,
    load_config,
    normalize_optional_model_selection,
    parse_extra_modalities_config,
    parse_extra_modalities_input,
    parse_file_inline_chars,
    parse_multimodal_limit,
    normalize_reasoning_effort_for_api,
    rename_model_profile,
    save_config_field,
    save_config_fields,
    save_model_profile_field,
    supported_reasoning_efforts,
)
from ..installer import PROVIDERS, install_registry_skill
from ..memory import MemoryStore
from ..main import attach_external_file_references_with_media
from ..references import resolve_references
from ..search import TAVILY_SEARCH_DEPTHS, TAVILY_TOPICS, WEB_SEARCH_PROVIDERS
from ..session import (
    ProjectRecord,
    SESSION_TITLE_STATE_GENERATED,
    SESSION_TITLE_STATE_TEMPORARY,
    add_project,
    archive_session,
    archive_project_sessions,
    create_session,
    delete_session,
    get_project_by_name,
    list_archived_sessions,
    list_pinned_projects,
    list_pinned_sessions,
    list_sessions,
    load_projects,
    load_session,
    pin_project,
    pin_session,
    remove_project,
    rename_project,
    rename_session,
    save_session_record,
    unarchive_session,
    unpin_project,
    unpin_session,
)
from ..skills import APP_SKILLS_DIR, SkillRegistry
from .data import PROJECT_LOGO
from .runtime import clear_bridge, render_console_text, set_bridge
from .theme import render_css
from .widgets.chat_input import ChatInput, HalfRowSpacer
from .widgets.chat_view import (
    ChatView,
    MarkdownMessageStatic,
    SelectableMessageStatic,
)
from .widgets.memory_modal import MemoryModal
from .widgets.project_modal import ProjectModal
from .widgets.project_picker import ProjectPicker
from .widgets.reference_modal import ReferenceModal
from .widgets.settings import SettingsModal
from .widgets.sidebar import Sidebar
from .widgets.text_area_modal import PromptFileModal, TextAreaModal
from .widgets.todos_panel import TodosPanel
from ..team import TeamStore, display_teammate_name
from ..ui import (
    build_tool_error_display,
    clean_display_text,
    clean_display_text_preserve_newlines,
    clean_thinking_text,
    tool_result_is_error,
)


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
class _InlinePromptOption:
    title: str
    detail: str = ""
    value: str = ""
    recommended: bool = False


@dataclass
class _InlinePromptQuestion:
    question: str
    options: list[_InlinePromptOption]
    allow_custom: bool = False
    separate_options: bool = False
    custom_label: str = "Type your own answer"
    custom_placeholder: str = "Type your own answer..."
    default_option_index: int | None = None
    default_custom_value: str = ""


@dataclass
class _InlinePromptAnswer:
    selected_option_index: int | None = None
    custom_text: str = ""


@dataclass
class _InlinePromptRequest:
    event: threading.Event
    questions: list[_InlinePromptQuestion]
    answers: list[_InlinePromptAnswer]
    current_index: int = 0
    cancelled: bool = False


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
        min-width: 0;
        padding: 1 1 0 1;
        align-horizontal: center;
    }
    #chat-input-wrap.with-todos {
        padding-top: 0;
    }
    #chat-input-wrap > #chat-input {
        margin: 0;
    }
    #chat-input-wrap.with-todos > #chat-input {
        margin: 0 1;
    }

    #info-bar-wrap {
        width: 100%;
        height: auto;
        min-width: 0;
        padding: 0 1;
        align-horizontal: center;
    }
    #info-bar-shell {
        width: 100%;
        min-width: 0;
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
    #prompt-dismiss {
        display: none;
        width: auto;
        min-width: 1;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
    }
    #prompt-dismiss.visible {
        display: block;
    }
    #prompt-dismiss:hover,
    #prompt-dismiss:focus,
    #prompt-dismiss.-active {
        background: transparent;
        color: $TEXT_PRIMARY;
    }
    #prompt-nav {
        display: none;
        width: 1fr;
        height: 1;
        align-horizontal: right;
    }
    #prompt-nav.visible {
        display: block;
    }
    #prompt-back,
    #prompt-next {
        width: auto;
        min-width: 1;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
    }
    #prompt-back {
        margin-right: 1;
    }
    #prompt-back.hidden {
        display: none;
    }
    #prompt-next:disabled,
    #prompt-back:disabled {
        color: $TEXT_MUTED;
    }
    #context-label.hidden {
        display: none;
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
        Binding("escape", "dismiss", "Dismiss"),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        ("ctrl+c", "quit_attempt", "Quit"),
    ]

    sidebar_visible: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._config_cache = load_config()
        self.chat: OmniAgent | None = None
        self.chat_busy = False
        self.current_session_record: dict | None = None
        self.current_project_name = ""
        self.todo_items: list[dict] = []
        self._stream_kind: str | None = None
        self._worker_lock = threading.Lock()
        self._message_started_at: float | None = None
        self._thinking_started_at: float | None = None
        self._thinking_elapsed_timer = None
        self._suppress_stream_output = False
        self._prompt_request: _InlinePromptRequest | None = None
        self._title_summary_sessions: set[str] = set()
        self._archived_project_filter = "__all__"
        self._interrupt_send_payload: tuple[str, str] | None = None
        self._settings_model_limit_key = "total"
        self._settings_model_profile_key = ""

    @property
    def config(self):
        return self._config_cache

    @config.setter
    def config(self, value) -> None:
        self._config_cache = value

    def _model_profile_choices(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = [(AUTO_MODEL_SELECTION, AUTO_MODEL_SELECTION)]
        options.extend(
            (profile.profile_name, key)
            for key, profile in self.config.model_list.items()
        )
        return options

    def _optional_model_choice_groups(self) -> list[dict]:
        groups = [
            {
                "provider": "auto",
                "title": "Auto",
                "models": [AUTO_MODEL_SELECTION],
                "options": [(AUTO_MODEL_SELECTION, AUTO_MODEL_SELECTION)],
            }
        ]
        groups.extend(self._grouped_model_choices())
        return groups

    def _valid_optional_model_selection(self, value: str) -> str:
        normalized = normalize_optional_model_selection(value)
        if normalized == AUTO_MODEL_SELECTION:
            return AUTO_MODEL_SELECTION
        if normalized in self.config.model_list:
            return normalized
        return AUTO_MODEL_SELECTION

    def _grouped_model_choices(self) -> list[dict]:
        grouped: dict[str, list[tuple[str, str]]] = {}
        for model_key, profile in self.config.model_list.items():
            provider = str(getattr(profile, "provider", "") or "").strip() or "Other"
            grouped.setdefault(provider, []).append(
                (str(profile.profile_name), str(model_key))
            )
        groups = [
            {
                "provider": provider,
                "title": provider,
                "models": [
                    value for _, value in sorted(options, key=lambda x: x[0].lower())
                ],
                "options": sorted(options, key=lambda x: x[0].lower()),
            }
            for provider, options in grouped.items()
        ]
        groups.sort(key=lambda g: str(g.get("title") or "").lower())
        return groups

    def compose(self) -> ComposeResult:
        with Vertical(id="left-edge", classes="sidebar-hidden"):
            yield Static("=", id="sidebar-toggle")
            yield Sidebar(id="sidebar")

        with Vertical(id="main-area"):
            with Container(id="messages-wrap"):
                with Vertical(id="messages-shell"):
                    yield ChatView(
                        id="messages-view",
                        markdown_enabled=bool(self.config.render_markdown),
                    )

            with Vertical(id="input-wrapper", classes="welcome"):
                with Container(id="project-title-wrap"):
                    yield Static(PROJECT_LOGO, id="project-title")
                yield TodosPanel(id="todos-panel-wrap")
                with Container(id="chat-input-wrap"):
                    yield ChatInput(id="chat-input")
                with Container(id="info-bar-wrap"):
                    with Vertical(id="info-bar-shell"):
                        with Horizontal(id="info-bar"):
                            yield ProjectPicker(id="project-picker")
                            with Horizontal(id="interrupt-hint"):
                                yield Label("esc", id="interrupt-key")
                                yield Label("interrupt", id="interrupt-text")
                            yield Button("Dismiss", id="prompt-dismiss")
                            with Horizontal(id="prompt-nav"):
                                yield Button("Back", id="prompt-back")
                                yield Button("Next", id="prompt-next")
                            yield Label("Context: 0.0k (0%)", id="context-label")
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
        self._sync_prompt_actions()

    def on_unmount(self) -> None:
        self._pause_thinking_elapsed_timer()
        self._thinking_started_at = None
        if self.chat is not None:
            self.chat.shutdown()
        clear_bridge()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "side-new-chat":
            self._reset_chat_state()
        elif btn_id == "side-settings":
            self._open_settings()
        elif btn_id == "prompt-dismiss":
            self._dismiss_inline_prompt()
        elif btn_id == "prompt-back":
            self._go_to_previous_prompt_question()
        elif btn_id == "prompt-next":
            self._advance_inline_prompt()

    def on_click(self, event: events.Click) -> None:
        if not event.control:
            return
        if event.control.id == "sidebar-toggle":
            self.toggle_sidebar()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        control = event.control
        if isinstance(control, (SelectableMessageStatic, MarkdownMessageStatic)):
            return
        try:
            self.query_one("#messages-view", ChatView).clear_message_selection()
        except Exception:
            return

    def on_chat_input_prompt_state_changed(
        self, event: ChatInput.PromptStateChanged
    ) -> None:
        self._sync_prompt_actions(can_submit=event.can_submit)

    def on_chat_input_prompt_submit_requested(
        self, event: ChatInput.PromptSubmitRequested
    ) -> None:
        self._advance_inline_prompt()

    def on_chat_input_send(self, event: ChatInput.Send) -> None:
        is_command = str(event.content or "").startswith("/")
        if self.chat_busy:
            if is_command and self.chat is not None:
                self._interrupt_send_payload = (event.content, event.display_content)
                self._interrupt_active_response()
                return
            self.query_one("#chat-input", ChatInput).enqueue_pending_message(
                event.content,
                event.display_content,
            )
            return
        self._dispatch_user_message(event.content, event.display_content)

    def on_chat_input_direct_send_requested(
        self, event: ChatInput.DirectSendRequested
    ) -> None:
        if self.chat_busy and self.chat is not None:
            self._interrupt_send_payload = (event.content, event.display_content)
            self._interrupt_active_response()
            return
        self._dispatch_user_message(event.content, event.display_content)

    def _dispatch_user_message(
        self, content: str, display_content: str | None = None
    ) -> None:
        display_content = content if display_content is None else display_content

        is_command = str(content or "").startswith("/")
        if not is_command:
            try:
                self._ensure_ready_for_message()
            except Exception as error:
                self.add_status_message("[✗]", f"初始化对话失败: {error}")
                return

        chat_view = self.query_one("#messages-view", ChatView)
        if not is_command:
            self.start_chat()
            project = self._selected_project()
            base_dir = project.path if project is not None else None
            chat_view.add_message("user", content, base_dir)
        chat_view.reset_turn_summaries()
        self._set_controls_locked(True)
        self.chat_busy = True
        self.query_one("#chat-input", ChatInput).set_chat_busy(True)
        self._suppress_stream_output = False
        self._message_started_at = perf_counter()
        self._thinking_started_at = None
        new_session = (
            (not is_command)
            and self.current_session_record is not None
            and (not self.current_session_record.get("conversation"))
        )
        if new_session:
            self._update_new_session_title_from_text(display_content)
            self._maybe_schedule_session_title_summary()
        worker = threading.Thread(
            target=self._process_user_message,
            args=(content,),
            daemon=True,
        )
        worker.start()

    def on_chat_input_reference_requested(
        self, event: ChatInput.ReferenceRequested
    ) -> None:
        self.push_screen(ReferenceModal(), callback=self._handle_reference_result)

    def _handle_reference_result(self, result: dict | None) -> None:
        if not result:
            return
        inserted = self.query_one("#chat-input", ChatInput).insert_reference(
            str(result.get("type") or ""), str(result.get("path") or "")
        )
        if not inserted:
            self.add_status_message("[✗]", "引用路径不存在或类型不匹配。")

    def on_chat_input_model_changed(self, event: ChatInput.ModelChanged) -> None:
        save_config_field("current_model", event.value)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._refresh_context_label_for_active_model()
        self._apply_config_to_controls()

    def _refresh_context_label_for_active_model(self) -> None:
        if self.chat is not None:
            self.chat.set_context_window_tokens(self.config.context_window_tokens)
            return
        self._set_context_label(0, self.config.context_window_tokens)

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
            extra_modalities=model.extra_modalities,
        )
        self.chat.set_context_window_tokens(model.context_window_tokens)

    def on_chat_input_thinking_changed(self, event: ChatInput.ThinkingChanged) -> None:
        thinking_enabled = event.value != "none"
        updates = {"thinking_mode": thinking_enabled}
        if thinking_enabled:
            updates["reasoning_effort"] = normalize_reasoning_effort_for_api(
                self.config.active_model.api_type, event.value
            )
        save_config_fields(updates)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_thinking_mode(thinking_enabled)
            if thinking_enabled:
                self.chat.set_reasoning_effort(
                    self.config.active_model.reasoning_effort
                )
        self._apply_config_to_controls()

    def _on_agent_plan_mode_changed(self, enabled: bool) -> None:
        self._call_ui(self._apply_agent_plan_mode_change, bool(enabled))

    def _apply_agent_plan_mode_change(self, enabled: bool) -> None:
        save_config_field("agent_plan_enable", enabled)
        self._reload_config()
        self._apply_config_to_controls()

    def on_chat_input_plan_mode_changed(self, event: ChatInput.PlanModeChanged) -> None:
        save_config_field("agent_plan_enable", event.enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_plan_mode(event.enabled)
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

    def on_sidebar_session_action_requested(
        self, event: Sidebar.SessionActionRequested
    ) -> None:
        if self.chat_busy:
            self.add_status_message("[!]", "当前正在处理中，暂时不能操作会话。")
            return
        session_path = str(event.session_path or "").strip()
        action = str(event.action or "").strip().lower()
        value = str(event.value or "")
        if not session_path or action not in {
            "pin",
            "unpin",
            "archive",
            "load",
            "rename",
        }:
            return
        try:
            if action == "pin":
                pin_session(session_path)
                self.add_status_message("[✓]", "已置顶对话。")
            elif action == "unpin":
                unpin_session(session_path)
                self.add_status_message("[✓]", "已取消置顶。")
            elif action == "archive":
                self._archive_session_record(session_path)
                self.add_status_message("[✓]", "已归档对话。")
            elif action == "rename":
                renamed = rename_session(session_path, value)
                if (
                    self.current_session_record is not None
                    and str(
                        self.current_session_record.get("session_path") or ""
                    ).strip()
                    == session_path
                ):
                    self.current_session_record = renamed
                self.add_status_message("[✓]", "已重命名对话。")
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

    def on_sidebar_project_action_requested(
        self, event: Sidebar.ProjectActionRequested
    ) -> None:
        if self.chat_busy:
            self.add_status_message("[!]", "当前正在处理中，暂时不能操作项目。")
            return
        project_slug = str(event.project_slug or "").strip()
        action = str(event.action or "").strip().lower()
        value = str(event.value or "")
        if not project_slug or action not in {
            "pin",
            "unpin",
            "rename",
            "archive",
            "remove",
        }:
            return

        selected_project = self._selected_project()
        current_session_project = self._project_from_session(
            self.current_session_record
        )

        try:
            if action == "pin":
                pin_project(project_slug)
                self.add_status_message("[✓]", "已置顶项目。")
            elif action == "unpin":
                unpin_project(project_slug)
                self.add_status_message("[✓]", "已取消置顶项目。")
            elif action == "rename":
                updated = rename_project(project_slug, value)
                if (
                    selected_project is not None
                    and selected_project.slug == project_slug
                ):
                    self._set_current_project(updated.name)
                if (
                    current_session_project is not None
                    and current_session_project.slug == project_slug
                    and self.current_session_record is not None
                ):
                    self.current_session_record["project"] = updated.to_dict()
                self.add_status_message("[✓]", "已重命名项目。")
            elif action == "archive":
                archived_count = archive_project_sessions(project_slug)
                if (
                    current_session_project is not None
                    and current_session_project.slug == project_slug
                ):
                    self._clear_loaded_session_state(refresh_sidebar=False)
                self.add_status_message(
                    "[✓]", f"已归档项目对话，共归档 {archived_count} 个对话。"
                )
            elif action == "remove":
                removed = remove_project(project_slug)
                if (
                    selected_project is not None
                    and selected_project.slug == project_slug
                ):
                    self._set_current_project("")
                if (
                    current_session_project is not None
                    and current_session_project.slug == project_slug
                ):
                    self._clear_loaded_session_state(refresh_sidebar=False)
                self.add_status_message("[✓]", f"已移除项目 {removed.name}。")
        except Exception as error:
            self.add_status_message("[✗]", f"项目操作失败: {error}")
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
        if self._prompt_request is not None:
            self._dismiss_inline_prompt()
            return
        if self._interrupt_active_response():
            return
        if self.sidebar_visible:
            self.toggle_sidebar()
        elif self.is_modal_open:
            self.pop_screen()

    def action_quit_attempt(self) -> None:
        self.notify("Press Ctrl+Q to quit", title="Quit", severity="information")

    def action_quit_app(self) -> None:
        self.exit()

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
        self._sync_prompt_actions()

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
        self.notify(escape_markup(text), severity="information")

    def add_thinking_message(self, content) -> None:
        if self._suppress_stream_output:
            return
        text = clean_thinking_text(content)
        if not text:
            return
        self._call_ui(
            self._append_thought_message, text, self._elapsed_since_thinking()
        )

    def start_stream_thinking(self) -> None:
        if self._suppress_stream_output:
            return

    def begin_overflow_replay_scope(self) -> None:
        self._call_ui(self._begin_overflow_replay_scope)

    def _begin_overflow_replay_scope(self) -> None:
        self.query_one("#messages-view", ChatView).begin_overflow_replay_scope()

    def commit_overflow_replay_scope(self) -> None:
        self._call_ui(self._commit_overflow_replay_scope)

    def _commit_overflow_replay_scope(self) -> None:
        self.query_one("#messages-view", ChatView).commit_overflow_replay_scope()

    def rollback_overflow_replay_scope(self) -> None:
        self._call_ui(self._rollback_overflow_replay_scope)

    def _rollback_overflow_replay_scope(self) -> None:
        self._pause_thinking_elapsed_timer()
        self._thinking_started_at = None
        self._stream_kind = None
        self.query_one("#messages-view", ChatView).rollback_overflow_replay_scope()

    def start_thinking_timer(self) -> None:
        if self._suppress_stream_output:
            return
        if self._thinking_started_at is None:
            self._thinking_started_at = perf_counter()
        self._resume_thinking_elapsed_timer()

    def append_stream_thinking(self, content) -> None:
        if self._suppress_stream_output:
            return
        if self._thinking_started_at is None:
            self._thinking_started_at = perf_counter()
        self._resume_thinking_elapsed_timer()
        self._call_ui(self._append_thought_stream_widget, str(content or ""))

    def finish_thinking_round(self) -> None:
        if self._suppress_stream_output:
            return
        elapsed = self._elapsed_since_thinking()
        self._call_ui(self._finish_thought_stream_widget, elapsed)
        self._thinking_started_at = None
        self._call_ui(self._reset_explored_widget)

    def _reset_explored_widget(self) -> None:
        self.query_one("#messages-view", ChatView).reset_explored()

    def start_stream_response(self, model_name) -> None:
        if self._suppress_stream_output:
            return
        self._pause_thinking_elapsed_timer()
        self._call_ui(
            self._finish_thought_stream_widget,
            self._elapsed_since_thinking(),
        )
        self._thinking_started_at = None
        self._call_ui(self._start_stream_widget, "assistant", "")

    def append_stream_response(self, content) -> None:
        if self._suppress_stream_output:
            return
        self._call_ui(self._append_stream_widget, "assistant", str(content or ""), "")

    def set_todo_items(self, items) -> None:
        self.todo_items = [item for item in items or [] if isinstance(item, dict)]
        self._call_ui(self._set_todo_panel_items, self.todo_items)

    def _set_todo_panel_items(self, items) -> None:
        has_items = bool(items)
        self.query_one("#todos-panel-wrap", TodosPanel).set_items(items)
        self.query_one("#chat-input", ChatInput).set_todo_visible(has_items)
        self.query_one("#chat-input-wrap", Container).set_class(
            has_items,
            "with-todos",
        )
        self.query_one("#info-bar-wrap", Container).set_class(
            has_items,
            "with-todos",
        )

    def set_context_usage(self, input_tokens, context_window_tokens) -> None:
        self._call_ui(self._set_context_label, input_tokens, context_window_tokens)

    def request_plan_confirmation(self, plan) -> bool:
        request = self._build_inline_prompt_request([
            _InlinePromptQuestion(
                question="Allow this plan?",
                options=[
                    _InlinePromptOption("Allow", value="Allow"),
                    _InlinePromptOption("Cancel", value="Cancel"),
                ],
                separate_options=True,
            )
        ])
        self._call_ui(self._open_plan_prompt, str(plan or "").strip(), request)
        request.event.wait()
        if request.cancelled:
            return False
        return bool(request.answers[0].selected_option_index == 0)

    def _open_plan_prompt(self, plan: str, request: _InlinePromptRequest) -> None:
        self.query_one("#messages-view", ChatView).add_plan_entry(plan)
        self._open_inline_prompt(request)

    def request_confirmation(self, title, detail="") -> bool:
        question = str(title or "Confirm").strip()
        detail_text = str(detail or "").strip()
        if detail_text:
            question = f"{question}\n{detail_text}"
        request = self._build_inline_prompt_request([
            _InlinePromptQuestion(
                question=question,
                options=[
                    _InlinePromptOption("Approve", value="Approve"),
                    _InlinePromptOption("Cancel", value="Cancel"),
                ],
                separate_options=True,
            )
        ])
        self._call_ui(self._open_inline_prompt, request)
        request.event.wait()
        if request.cancelled:
            return False
        return bool(request.answers[0].selected_option_index == 0)

    @staticmethod
    def _normalize_inline_option(
        option, recommended: bool = False
    ) -> _InlinePromptOption | None:
        if isinstance(option, _InlinePromptOption):
            value = option.value or option.title
            return _InlinePromptOption(
                title=option.title,
                detail=option.detail,
                value=value,
                recommended=option.recommended or bool(recommended),
            )
        if isinstance(option, dict):
            title = str(option.get("title") or "").strip()
            detail = str(option.get("detail") or "").strip()
            if not title:
                return None
            value = str(option.get("value") or title)
            return _InlinePromptOption(
                title=title,
                detail=detail,
                value=value,
                recommended=bool(option.get("recommended")) or bool(recommended),
            )
        title = str(option or "").strip()
        if not title:
            return None
        return _InlinePromptOption(
            title=title,
            detail="",
            value=title,
            recommended=bool(recommended),
        )

    def request_choice(self, question, options, default_index=1) -> tuple[int, str]:
        raw_options = list(options or [])
        if not raw_options:
            return 0, ""
        default_index = max(1, min(len(raw_options), int(default_index or 1)))
        normalized_options = []
        for index, option in enumerate(raw_options):
            normalized = self._normalize_inline_option(
                option,
                recommended=index == (default_index - 1),
            )
            if normalized is not None:
                normalized_options.append(normalized)
        if not normalized_options:
            return 0, ""
        request = self._build_inline_prompt_request([
            _InlinePromptQuestion(
                question=str(question or "Choose one"),
                options=normalized_options,
                allow_custom=True,
                default_option_index=default_index - 1,
            )
        ])
        self._call_ui(self._open_inline_prompt, request)
        request.event.wait()
        if request.cancelled:
            return 0, ""
        answer = request.answers[0]
        if answer.selected_option_index is not None:
            selected_index = int(answer.selected_option_index)
            return selected_index + 1, request.questions[0].options[
                selected_index
            ].value
        return len(normalized_options) + 1, str(answer.custom_text or "").strip()

    def request_questions(self, questions) -> list[tuple[int, str]]:
        normalized_questions = []
        for item in questions or []:
            if not isinstance(item, dict):
                continue
            raw_options = list(item.get("options") or [])
            if not raw_options:
                continue
            default_index = item.get("default_index")
            if default_index is None:
                default_option_index = None
            else:
                default_option_index = max(
                    0,
                    min(len(raw_options) - 1, int(default_index) - 1),
                )
            normalized_options = []
            for index, option in enumerate(raw_options):
                normalized = self._normalize_inline_option(
                    option,
                    recommended=index == default_option_index,
                )
                if normalized is not None:
                    normalized_options.append(normalized)
            if not normalized_options:
                continue
            normalized_questions.append(
                _InlinePromptQuestion(
                    question=str(item.get("question") or "Choose one"),
                    options=normalized_options,
                    allow_custom=True,
                    default_option_index=default_option_index,
                )
            )
        if not normalized_questions:
            return []
        request = self._build_inline_prompt_request(normalized_questions)
        self._call_ui(self._open_inline_prompt, request)
        request.event.wait()
        if request.cancelled:
            return []
        answers: list[tuple[int, str]] = []
        for prompt_question, answer in zip(request.questions, request.answers):
            if answer.selected_option_index is not None:
                selected_index = int(answer.selected_option_index)
                answers.append((
                    selected_index + 1,
                    prompt_question.options[selected_index].value,
                ))
            else:
                answers.append((
                    len(prompt_question.options) + 1,
                    str(answer.custom_text or "").strip(),
                ))
        return answers

    def request_input(self, prompt_text, multiline=False) -> str:
        request = self._build_inline_prompt_request([
            _InlinePromptQuestion(
                question=str(prompt_text or "Input"),
                options=[],
                allow_custom=True,
                default_custom_value="",
            )
        ])
        self._call_ui(self._open_inline_prompt, request)
        request.event.wait()
        if request.cancelled:
            return ""
        return str(request.answers[0].custom_text or "")

    def _build_inline_prompt_request(
        self,
        questions: list[_InlinePromptQuestion],
    ) -> _InlinePromptRequest:
        answers: list[_InlinePromptAnswer] = []
        for question in questions:
            answer = _InlinePromptAnswer(
                selected_option_index=question.default_option_index,
                custom_text=str(question.default_custom_value or ""),
            )
            answers.append(answer)
        return _InlinePromptRequest(
            event=threading.Event(),
            questions=list(questions),
            answers=answers,
        )

    def clear_current_lines(self, line_count) -> None:
        return

    def _open_inline_prompt(self, request: _InlinePromptRequest) -> None:
        self._prompt_request = request
        self.query_one("#todos-panel-wrap", TodosPanel).add_class("prompt-active")
        self._show_current_prompt_question()

    def _show_current_prompt_question(self) -> None:
        request = self._prompt_request
        if request is None or not request.questions:
            return
        index = max(0, min(request.current_index, len(request.questions) - 1))
        request.current_index = index
        question = request.questions[index]
        answer = request.answers[index]
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.set_prompt_state(
            active=True,
            current_index=index + 1,
            total=len(request.questions),
            question=question.question,
            options=[
                (option.title, option.detail, option.recommended)
                for option in question.options
            ],
            allow_custom=question.allow_custom,
            selected_option_index=answer.selected_option_index,
            custom_selected=(
                question.allow_custom and answer.selected_option_index is None
            ),
            custom_value=answer.custom_text,
            separate_options=question.separate_options,
            custom_label=question.custom_label,
            custom_placeholder=question.custom_placeholder,
        )
        self._set_input_enabled(bool(question.allow_custom))
        self._sync_prompt_actions(can_submit=chat_input.prompt_can_submit())
        if chat_input.prompt_uses_custom_input():
            chat_input.focus_prompt_input()
        else:
            self.query_one("#prompt-next", Button).focus()

    def _capture_current_prompt_answer(self, require_complete: bool) -> bool:
        request = self._prompt_request
        if request is None or not request.questions:
            return False
        index = request.current_index
        question = request.questions[index]
        selected_option_index, custom_text = self.query_one(
            "#chat-input", ChatInput
        ).get_prompt_answer()
        if selected_option_index is not None:
            request.answers[index] = _InlinePromptAnswer(
                selected_option_index=selected_option_index,
                custom_text="",
            )
            return True
        if question.allow_custom:
            request.answers[index] = _InlinePromptAnswer(
                selected_option_index=None,
                custom_text=str(custom_text or "").strip(),
            )
            if require_complete:
                return bool(str(custom_text or "").strip())
            return True
        if not require_complete:
            request.answers[index] = _InlinePromptAnswer()
            return True
        return False

    def _go_to_previous_prompt_question(self) -> None:
        request = self._prompt_request
        if request is None or request.current_index <= 0:
            return
        self._capture_current_prompt_answer(require_complete=False)
        request.current_index -= 1
        self._show_current_prompt_question()

    def _advance_inline_prompt(self) -> None:
        request = self._prompt_request
        if request is None:
            return
        if not self._capture_current_prompt_answer(require_complete=True):
            self._sync_prompt_actions(can_submit=False)
            return
        if request.current_index >= len(request.questions) - 1:
            self._finish_inline_prompt(cancelled=False)
            return
        request.current_index += 1
        self._show_current_prompt_question()

    def _dismiss_inline_prompt(self) -> None:
        if self._prompt_request is None:
            return
        self._finish_inline_prompt(cancelled=True)

    def _finish_inline_prompt(self, cancelled: bool) -> None:
        request = self._prompt_request
        if request is None:
            return
        request.cancelled = bool(cancelled)
        self._prompt_request = None
        self.query_one("#todos-panel-wrap", TodosPanel).remove_class("prompt-active")
        self.query_one("#chat-input", ChatInput).set_prompt_state(active=False)
        self._set_input_enabled(not self.chat_busy)
        self._sync_prompt_actions()
        request.event.set()

    def _sync_prompt_actions(self, can_submit: bool | None = None) -> None:
        chat_input = self.query_one("#chat-input", ChatInput)
        project_picker = self.query_one("#project-picker", ProjectPicker)
        interrupt_hint = self.query_one("#interrupt-hint", Horizontal)
        context_label = self.query_one("#context-label", Label)
        dismiss_button = self.query_one("#prompt-dismiss", Button)
        prompt_nav = self.query_one("#prompt-nav", Horizontal)
        back_button = self.query_one("#prompt-back", Button)
        next_button = self.query_one("#prompt-next", Button)
        if self._prompt_request is None:
            dismiss_button.remove_class("visible")
            prompt_nav.remove_class("visible")
            back_button.remove_class("hidden")
            context_label.remove_class("hidden")
            dismiss_button.styles.width = 9
            dismiss_button.styles.min_width = 9
            back_button.styles.width = 6
            back_button.styles.min_width = 6
            next_button.styles.width = 6
            next_button.styles.min_width = 6
            back_button.styles.margin_right = 1
            if chat_input.chat_active:
                project_picker.add_class("hidden")
                interrupt_hint.add_class("visible")
            else:
                project_picker.remove_class("hidden")
                interrupt_hint.remove_class("visible")
            return

        self._capture_current_prompt_answer(require_complete=False)
        project_picker.add_class("hidden")
        interrupt_hint.remove_class("visible")
        context_label.add_class("hidden")
        dismiss_button.add_class("visible")
        prompt_nav.add_class("visible")
        current_index = self._prompt_request.current_index
        if current_index <= 0:
            back_button.add_class("hidden")
            back_button.styles.margin_right = 0
        else:
            back_button.remove_class("hidden")
            back_button.styles.margin_right = 1
        next_button.label = (
            "Submit"
            if current_index >= len(self._prompt_request.questions) - 1
            else "Next"
        )
        dismiss_width = len(str(dismiss_button.label or "")) + 2
        back_width = len(str(back_button.label or "")) + 2
        next_width = len(str(next_button.label or "")) + 2
        dismiss_button.styles.width = dismiss_width
        dismiss_button.styles.min_width = dismiss_width
        back_button.styles.width = back_width
        back_button.styles.min_width = back_width
        next_button.styles.width = next_width
        next_button.styles.min_width = next_width
        next_button.disabled = (
            not chat_input.prompt_can_submit() if can_submit is None else not can_submit
        )
        if chat_input.prompt_uses_custom_input():
            chat_input.focus_prompt_input()
        elif self.focused is self.query_one("#message-input", TextArea):
            next_button.focus()

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

    def append_status_text(self, text: str) -> None:
        value = str(text or "").rstrip()
        if not value:
            return
        self._call_ui(self._append_status_text, value)

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

    def add_edit_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self._call_ui(
            self._append_edit_entry, file_path, additions, deletions, diff, status
        )

    def _append_edit_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self.query_one("#messages-view", ChatView).add_edit_entry(
            file_path, additions, deletions, diff, status
        )

    def add_write_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self._call_ui(
            self._append_write_entry, file_path, additions, deletions, diff, status
        )

    def _append_write_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self.query_one("#messages-view", ChatView).add_write_entry(
            file_path, additions, deletions, diff, status
        )

    def add_shell_entry(self, command: str, output: str) -> None:
        self._call_ui(self._append_shell_entry, command, output)

    def _append_shell_entry(self, command: str, output: str) -> None:
        self.query_one("#messages-view", ChatView).add_shell_entry(command, output)

    def add_changed_files_entry(self, files: list[dict]) -> None:
        self._call_ui(self._append_changed_files_entry, files)

    def _append_changed_files_entry(self, files: list[dict]) -> None:
        self.query_one("#messages-view", ChatView).add_changed_files_entry(files)

    def add_question_entry(self, question: str, answer: str) -> None:
        self._call_ui(self._append_question_entry, question, answer)

    def _append_question_entry(self, question: str, answer: str) -> None:
        self.query_one("#messages-view", ChatView).add_question_entry(question, answer)

    def add_todo_entry(self, items: list[dict], summary: dict | None = None) -> None:
        self._call_ui(self._append_todo_entry, items, summary)

    def _append_todo_entry(
        self, items: list[dict], summary: dict | None = None
    ) -> None:
        self.query_one("#messages-view", ChatView).add_todo_entry(items, summary)

    def add_tool_error_entry(self, display: dict) -> None:
        payload = dict(display or {})
        self._call_ui(
            self._append_tool_error_entry,
            str(payload.get("tool_name") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("error") or ""),
        )

    def _append_tool_error_entry(
        self, tool_name: str, summary: str, error: str
    ) -> None:
        self.query_one("#messages-view", ChatView).add_tool_error_entry(
            tool_name, summary, error
        )

    def add_web_fetch_entry(self, url: str) -> None:
        self._call_ui(self._append_web_fetch_entry, url)

    def _append_web_fetch_entry(self, url: str) -> None:
        self.query_one("#messages-view", ChatView).add_web_fetch_entry(url)

    def add_web_search_entry(self, content: str) -> None:
        self._call_ui(self._append_web_search_entry, content)

    def _append_web_search_entry(self, content: str) -> None:
        self.query_one("#messages-view", ChatView).add_web_search_entry(content)

    def add_subagent_entry(self, agent_type: str, transcript: list[dict]) -> None:
        self._call_ui(self._append_subagent_entry, agent_type, transcript)

    def _append_subagent_entry(self, agent_type: str, transcript: list[dict]) -> None:
        self.query_one("#messages-view", ChatView).add_subagent_entry(
            agent_type, transcript
        )

    def start_subagent_entry(self, entry_id: str, agent_type: str) -> None:
        self._call_ui(self._start_subagent_entry, entry_id, agent_type)

    def _start_subagent_entry(self, entry_id: str, agent_type: str) -> None:
        self.query_one("#messages-view", ChatView).start_subagent_entry(
            entry_id, agent_type
        )

    def append_subagent_event(self, entry_id: str, event: dict) -> None:
        self._call_ui(self._append_subagent_event, entry_id, event)

    def _append_subagent_event(self, entry_id: str, event: dict) -> None:
        self.query_one("#messages-view", ChatView).append_subagent_event(
            entry_id, event
        )

    def start_team_entry(
        self,
        entry_id: str,
        teammate_name: str,
        role: str = "",
        purpose: str = "",
        task_id: str = "",
    ) -> None:
        self._call_ui(
            self._start_team_entry,
            entry_id,
            teammate_name,
            role,
            purpose,
            task_id,
        )

    def _start_team_entry(
        self,
        entry_id: str,
        teammate_name: str,
        role: str = "",
        purpose: str = "",
        task_id: str = "",
    ) -> None:
        self.query_one("#messages-view", ChatView).start_team_entry(
            entry_id, teammate_name, role, purpose, task_id
        )

    def append_team_event(self, entry_id: str, event: dict) -> None:
        self._call_ui(self._append_team_event, entry_id, event)

    def _append_team_event(self, entry_id: str, event: dict) -> None:
        self.query_one("#messages-view", ChatView).append_team_event(entry_id, event)

    def finish_team_entry(self, entry_id: str, status: str, result: str = "") -> None:
        self._call_ui(self._finish_team_entry, entry_id, status, result)

    def _finish_team_entry(self, entry_id: str, status: str, result: str = "") -> None:
        updated = self.query_one("#messages-view", ChatView).finish_team_entry(
            entry_id, status, result
        )
        if updated:
            self._persist_current_session(refresh_sidebar=False)

    def add_team_action_entry(
        self,
        action: str,
        summary: str,
        details: str = "",
        status: str = "success",
        metadata: dict | None = None,
    ) -> None:
        self._call_ui(
            self._append_team_action_entry,
            action,
            summary,
            details,
            status,
            metadata or {},
        )

    def _append_team_action_entry(
        self,
        action: str,
        summary: str,
        details: str = "",
        status: str = "success",
        metadata: dict | None = None,
    ) -> None:
        self.query_one("#messages-view", ChatView).add_team_action_entry(
            action, summary, details, status, metadata or {}
        )

    def start_compaction_entry(
        self, entry_id: str, status: str, mode: str = "auto"
    ) -> None:
        self._call_ui(self._start_compaction_entry, entry_id, status, mode)

    def _start_compaction_entry(
        self, entry_id: str, status: str, mode: str = "auto"
    ) -> None:
        self.query_one("#messages-view", ChatView).start_compaction_entry(
            entry_id, status, mode
        )

    def finish_compaction_entry(
        self, entry_id: str, status: str, mode: str = "auto", details: str = ""
    ) -> None:
        self._call_ui(self._finish_compaction_entry, entry_id, status, mode, details)

    def _finish_compaction_entry(
        self, entry_id: str, status: str, mode: str = "auto", details: str = ""
    ) -> None:
        self.query_one("#messages-view", ChatView).finish_compaction_entry(
            entry_id, status, mode, details
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

        value = f"{input_tokens / 1000:.1f}k"
        percent = (input_tokens / context_window_tokens) * 100
        self.query_one("#context-label", Label).update(
            f"Context: {value} ({percent:.0f}%)"
        )

    def _reload_config(self) -> None:
        self.config = load_config()

    def _apply_config_to_controls(self) -> None:
        try:
            chat_view = self.query_one("#messages-view", ChatView)
        except NoMatches:
            chat_view = None
        if chat_view is not None:
            chat_view.set_markdown_enabled(bool(self.config.render_markdown))
        try:
            chat_input = self.query_one("#chat-input", ChatInput)
        except NoMatches:
            return
        model_options = [
            (profile.profile_name, key)
            for key, profile in self.config.model_list.items()
        ]
        chat_input.set_model_options(
            model_options,
            self.config.current_model,
            groups=self._grouped_model_choices(),
        )
        chat_input.set_thinking_options(
            self._reasoning_choices_for_api(
                self.config.active_model.api_type,
                include_off=True,
                title_case=True,
            )
        )
        chat_input.set_project_selected(bool(self.current_project_name))
        chat_input.plan_mode = bool(self.config.agent_plan_enable)
        chat_input.set_selected_approval(self.config.agent_approval_mode)
        chat_input.set_selected_thinking(self._thinking_value_from_config())

    @staticmethod
    def _reasoning_label(value: str, title_case: bool = False) -> str:
        text = str(value or "").strip().lower()
        if text == "none":
            return "Off" if title_case else "off"
        if text == "xhigh":
            return "XHigh" if title_case else "xhigh"
        return text.capitalize() if title_case else text

    def _reasoning_choices_for_api(
        self,
        api_type: str,
        *,
        include_off: bool = False,
        title_case: bool = False,
    ) -> list[tuple[str, str]]:
        choices = [
            (self._reasoning_label(value, title_case=title_case), value)
            for value in supported_reasoning_efforts(api_type)
        ]
        if include_off:
            return [
                (self._reasoning_label("none", title_case=title_case), "none")
            ] + choices
        return choices

    def _thinking_value_from_config(self) -> str:
        active_model = self.config.active_model
        if not active_model.thinking_mode:
            return "none"
        effort = normalize_reasoning_effort_for_api(
            active_model.api_type,
            active_model.reasoning_effort or "medium",
        )
        return effort or "medium"

    def _refresh_project_views(self) -> None:
        all_projects = load_projects()
        pinned_paths = {
            str(session.get("session_path") or "")
            for session in list_pinned_sessions()
            if session.get("session_path")
        }
        pinned_project_records = list_pinned_projects()
        pinned_project_slugs = {project.slug for project in pinned_project_records}
        pinned_project_rows = []
        project_rows = []
        project_names = []
        for project in all_projects:
            sessions = list_sessions(project)
            filtered = []
            for session in sessions:
                is_pinned = str(session.get("session_path") or "") in pinned_paths
                session["_pinned"] = is_pinned
                if not is_pinned:
                    filtered.append(session)
            row = {
                "name": project.name,
                "slug": project.slug,
                "sessions": filtered,
                "_pinned": project.slug in pinned_project_slugs,
            }
            if project.slug in pinned_project_slugs:
                pinned_project_rows.append(row)
            else:
                project_rows.append(row)
            project_names.append(project.name)
        pinned_project_rows.sort(
            key=lambda row: pinned_project_records.index(
                next(
                    project
                    for project in pinned_project_records
                    if project.slug == row["slug"]
                )
            )
        )
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
            project_rows, pinned_project_rows, pinned_sessions, filtered_orphans
        )
        picker = self.query_one("#project-picker", ProjectPicker)
        picker.set_projects(project_names)
        picker.set_current_project(self.current_project_name)

    def _set_current_project(self, project_name: str) -> None:
        self.current_project_name = str(project_name or "").strip()
        self.query_one("#project-picker", ProjectPicker).set_current_project(
            self.current_project_name
        )
        self.query_one("#chat-input", ChatInput).set_project_selected(
            bool(self.current_project_name)
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
        widget = self.query_one("#message-input", TextArea)
        widget.disabled = not enabled

    def _interrupt_active_response(self) -> bool:
        if not (self.chat_busy and self.chat is not None):
            return False
        self._suppress_stream_output = True
        self._pause_thinking_elapsed_timer()
        self._call_ui(
            self._finish_thought_stream_widget,
            self._elapsed_since_thinking(),
        )
        self._thinking_started_at = None
        self._stream_kind = None
        self.chat.request_agent_stop()
        return True

    def _maybe_dispatch_pending_message(self) -> None:
        if self.chat_busy:
            return
        chat_input = self.query_one("#chat-input", ChatInput)
        payload = self._interrupt_send_payload
        if payload is not None:
            self._interrupt_send_payload = None
            self._dispatch_user_message(payload[0], payload[1])
            return
        queued = chat_input.pop_next_pending_message()
        if queued is None:
            return
        self._dispatch_user_message(queued[0], queued[1])

    def _open_settings(self, page_id: str = "root") -> None:
        self.push_screen(
            SettingsModal(pages=self._settings_pages(), app=self, page_id=page_id)
        )

    def _open_user_prompt_editor(self) -> None:
        prompt_path = Path(USER_PROMPT_FILE)
        if not prompt_path.exists():
            try:
                prompt_path.write_text(USER_PROMPT_TEMPLATE, encoding="utf-8")
            except OSError as error:
                self.add_status_message("[✗]", f"创建 {USER_PROMPT_FILE} 失败: {error}")
                return
        try:
            value = prompt_path.read_text(encoding="utf-8")
        except OSError as error:
            self.add_status_message("[✗]", f"读取 {USER_PROMPT_FILE} 失败: {error}")
            return
        self.push_screen(
            PromptFileModal("System prompt", value=value),
            callback=self._handle_user_prompt_result,
        )

    def _handle_user_prompt_result(self, result: str | None) -> None:
        if result is None:
            return
        try:
            Path(USER_PROMPT_FILE).write_text(str(result), encoding="utf-8")
        except OSError as error:
            self.add_status_message("[✗]", f"保存 {USER_PROMPT_FILE} 失败: {error}")
            return
        self.add_status_message("[✓]", f"已保存 {USER_PROMPT_FILE}")

    def _normalize_archived_project_filter(self, value: str) -> str:
        filter_value = str(value or "").strip()
        if filter_value == "__none__":
            return "__none__"
        valid_slugs = {project.slug for project in load_projects()}
        if filter_value in valid_slugs:
            return filter_value
        return "__all__"

    def _archived_project_filter_options(self) -> list[dict]:
        projects = load_projects()
        options = [{"label": "All project", "value": "__all__"}]
        options.append({"type": "separator"})
        options.extend(
            {"label": project.name, "value": project.slug} for project in projects
        )
        options.append({"type": "separator"})
        options.append({"label": "Without project", "value": "__none__"})
        return options

    def _archived_project_filter_label(self) -> str:
        filter_value = self._normalize_archived_project_filter(
            self._archived_project_filter
        )
        if filter_value == "__none__":
            return "Without project"
        if filter_value == "__all__":
            return "All project"
        for project in load_projects():
            if project.slug == filter_value:
                return project.name
        return "All project"

    def _on_archived_project_filter_changed(self, value: str) -> None:
        self._archived_project_filter = self._normalize_archived_project_filter(value)

    def _on_archived_chat_action(self, session_path: str, action: str) -> None:
        action_name = str(action or "").strip().lower()
        session_path = str(session_path or "").strip()
        if not session_path:
            return
        if action_name == "unarchive":
            self._unarchive_session_record(session_path)
            self.add_status_message("[✓]", "已取消归档对话。")
        elif action_name == "remove":
            self._delete_session_record(session_path)
            self.add_status_message("[✓]", "已永久删除对话。")
        else:
            return
        self._refresh_project_views()

    def _on_archived_bulk_remove(self, session_paths: list[str]) -> None:
        paths = [
            str(path or "").strip()
            for path in list(session_paths or [])
            if str(path or "").strip()
        ]
        if not paths:
            return
        for session_path in paths:
            self._delete_session_record(session_path)
        self._refresh_project_views()
        self.add_status_message("[✓]", f"已永久删除 {len(paths)} 个对话。")

    def _settings_archived_chats_state(self, query: str = "") -> dict:
        self._archived_project_filter = self._normalize_archived_project_filter(
            self._archived_project_filter
        )
        normalized_query = " ".join(str(query or "").strip().lower().split())
        selected_filter = self._archived_project_filter
        project_order = {
            project.slug: index for index, project in enumerate(load_projects())
        }
        groups_by_key: dict[str, dict] = {}
        filtered_session_paths: list[str] = []

        for session in list_archived_sessions():
            session_path = str(session.get("session_path") or "").strip()
            if not session_path:
                continue
            project_data = session.get("project") or {}
            project_name = str(project_data.get("name") or "").strip()
            project_slug = str(project_data.get("slug") or "").strip()
            group_value = project_slug if project_name else "__none__"
            if selected_filter == "__none__" and project_name:
                continue
            if (
                selected_filter not in {"__all__", "__none__"}
                and project_slug != selected_filter
            ):
                continue

            title = str(session.get("title") or "New Chat")
            search_text = f"{title} {project_name}".lower()
            if normalized_query and normalized_query not in search_text:
                continue
            filtered_session_paths.append(session_path)

            if group_value not in groups_by_key:
                if project_name:
                    order = (
                        0,
                        project_order.get(project_slug, len(project_order)),
                        project_name.lower(),
                    )
                    group_title = project_name
                else:
                    order = (2, 0, "")
                    group_title = "Without project"
                groups_by_key[group_value] = {
                    "title": group_title,
                    "order": order,
                    "sessions": [],
                }

            groups_by_key[group_value]["sessions"].append({
                "title": title,
                "session_path": session_path,
            })

        groups = sorted(groups_by_key.values(), key=lambda item: item["order"])
        return {
            "filter_label": self._archived_project_filter_label(),
            "filter_value": selected_filter,
            "filter_options": self._archived_project_filter_options(),
            "bulk_remove_label": "Remove all",
            "bulk_remove_paths": filtered_session_paths,
            "groups": groups,
            "empty_label": "No archived chats",
        }

    def _settings_pages(self) -> dict[str, dict]:
        return {
            "root": {
                "title": "Settings",
                "layout": "list",
                "rows": self._settings_home_rows,
            },
            "general": {
                "title": "General",
                "layout": "list",
                "rows": self._settings_general_rows,
            },
            "archived_chats": {
                "title": "Archived chats",
                "layout": "archived_chats",
                "search_placeholder": "Search archived chats",
                "state": self._settings_archived_chats_state,
                "on_header_select_change": self._on_archived_project_filter_changed,
                "on_archived_bulk_remove": self._on_archived_bulk_remove,
                "on_archived_action": self._on_archived_chat_action,
            },
            "model_list": {
                "title": "Model list",
                "layout": "model_list",
                "show_search": False,
                "state": self._settings_model_page_state,
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
            "installed_skills": {
                "title": "Installed skills",
                "layout": "model_list",
                "show_search": False,
                "add_label": "Install skill",
                "add_page": "add_skill",
                "state": self._settings_installed_skills_state,
            },
            "add_skill": {
                "title": "Install skill",
                "layout": "list",
                "show_search": False,
                "rows": self._settings_add_skill_rows,
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
            "help": {
                "title": "Commands",
                "layout": "list",
                "show_search": False,
                "rows": self._help_command_rows,
            },
            "team": {
                "title": "Agent team",
                "layout": "model_list",
                "show_search": False,
                "add_label": "Add member",
                "state": self._settings_team_page_state,
                "on_add_item": self._on_setting_add_team_member,
            },
        }

    def _settings_home_rows(self) -> list[dict]:
        return [
            {
                "name": "General",
                "value": ">",
                "keywords": "general markdown",
                "edit_type": "nav",
                "target_page": "general",
            },
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
                "name": "System prompt",
                "value": "",
                "keywords": "system prompt prompt.md edit",
                "edit_type": "action",
                "on_activate": self._open_user_prompt_editor,
            },
            {
                "name": "Web search",
                "value": ">",
                "keywords": "web search web_search",
                "edit_type": "nav",
                "target_page": "web_search",
            },
            {
                "name": "Archived chats",
                "value": ">",
                "keywords": "archived chats archive chat history",
                "edit_type": "nav",
                "target_page": "archived_chats",
            },
        ]

    def _settings_general_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        return [
            {
                "name": "Use markdown",
                "value": "true" if self.config.render_markdown else "false",
                "keywords": "markdown render_markdown",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_render_markdown_changed(v),
            },
        ]

    def _help_command_rows(self) -> list[dict]:
        return [
            {
                "name": command,
                "value": description,
                "keywords": f"{command} {description}",
                "edit_type": "none",
            }
            for command, description in sorted(
                COMMANDS.items(), key=lambda item: item[0]
            )
        ]

    def _settings_model_page_state(self, selected_name: str = "") -> dict:
        config = self.config
        models = list(config.model_list.keys())
        if not models:
            self._settings_model_profile_key = ""
            return {
                "models": [],
                "groups": [],
                "selected_model": "",
                "rows": [],
                "footer_actions": [],
                "empty_list_label": "",
                "blank_detail_when_empty": True,
            }

        if selected_name in config.model_list:
            selected_model = selected_name
        elif self._settings_model_profile_key in config.model_list:
            selected_model = self._settings_model_profile_key
        elif config.current_model in config.model_list:
            selected_model = config.current_model
        else:
            selected_model = models[0]
        self._settings_model_profile_key = selected_model

        return {
            "models": models,
            "groups": self._grouped_model_choices(),
            "selected_model": selected_model,
            "item_labels": {
                key: profile.profile_name
                for key, profile in config.model_list.items()
            },
            "rows": self._settings_model_rows(selected_model),
            "footer_actions": [
                {
                    "label": "Delete",
                    "disabled": not bool(selected_model),
                    "on_activate": lambda key=selected_model: (
                        self._on_setting_delete_model(key)
                    ),
                }
            ],
            "empty_list_label": "",
            "blank_detail_when_empty": True,
        }

    def _settings_model_rows(self, model_key: str = "") -> list[dict]:
        config = self.config
        selected_key = (
            model_key if model_key in config.model_list else config.active_model_name
        )
        active_model = config.model_list.get(selected_key, config.active_model)
        bool_choices = [("true", "true"), ("false", "false")]
        reasoning_choices = self._reasoning_choices_for_api(active_model.api_type)
        current_effort = normalize_reasoning_effort_for_api(
            active_model.api_type,
            active_model.reasoning_effort or "medium",
        )
        if current_effort not in {value for _, value in reasoning_choices}:
            current_effort = "medium"

        rows = [
            {
                "name": "Provider",
                "value": active_model.provider,
                "keywords": "provider",
                "edit_type": "none",
            },
            {
                "name": "API type",
                "value": active_model.api_type,
                "keywords": "api_type",
                "edit_type": "select",
                "options": [
                    ("Ollama", API_TYPE_OLLAMA),
                    ("OpenAI", API_TYPE_OPENAI),
                    ("Anthropic", API_TYPE_ANTHROPIC),
                    ("Gemini", API_TYPE_GEMINI),
                    ("GLM", API_TYPE_GLM),
                ],
                "on_change": lambda v: self._on_setting_model_api_type_changed(v),
            },
            {
                "name": "Model name",
                "value": active_model.profile_name,
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
                "name": "Extra modalities",
                "value": format_extra_modalities(active_model.extra_modalities),
                "keywords": "extra_modalities modalities audio image video",
                "edit_type": "modalities",
                "options": [
                    ("audio", "audio"),
                    ("image", "image"),
                    ("video", "video"),
                ],
                "on_change": lambda v: self._on_setting_model_extra_modalities_changed(
                    v
                ),
            },
            {
                "name": "Limit",
                "keywords": "extra_modalities multimodal_limit upload size total",
                "edit_type": "input",
                "unit": "MB",
                "limit_selector": True,
            },
            {
                "name": "Context",
                "value": str(active_model.context_window_tokens),
                "keywords": "context_window_tokens context",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_model_context_changed(v),
            },
        ]
        if active_model.api_type == API_TYPE_GLM:
            rows = [row for row in rows if row.get("name") != "Base URL"]
        if active_model.extra_modalities:
            limit_options = [
                (modality.title(), modality)
                for modality in SUPPORTED_EXTRA_MODALITIES
                if modality in active_model.extra_modalities
            ]
            limit_options.append(("Total", "total"))
            available_limit_keys = {value for _label, value in limit_options}
            if self._settings_model_limit_key not in available_limit_keys:
                self._settings_model_limit_key = limit_options[0][1]
            selected_limit_key = self._settings_model_limit_key
            limit_row = next(row for row in rows if row.get("name") == "Limit")
            limit_row.update(
                {
                    "limit_key": selected_limit_key,
                    "options": limit_options,
                    "value": str(
                        active_model.multimodal_limit
                        if selected_limit_key == "total"
                        else active_model.extra_modalities[selected_limit_key]
                    ),
                    "on_limit_select": self._on_setting_model_limit_selected,
                    "on_change": lambda v, key=selected_limit_key: (
                        self._on_setting_model_limit_changed(key, v)
                    ),
                }
            )
        else:
            rows = [row for row in rows if row.get("name") != "Limit"]

        if active_model.thinking_mode:
            rows.insert(
                next(
                    index
                    for index, row in enumerate(rows)
                    if row.get("name") == "Extra modalities"
                ),
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
        return rows

    def _on_setting_model_name_changed(self, value: str) -> None:
        new_name = str(value or "").strip()
        if not new_name:
            return
        old_name = self._settings_model_target_key()
        if not old_name:
            return
        was_current = old_name == self.config.current_model
        try:
            renamed = rename_model_profile(old_name, new_name)
        except Exception as error:
            self.add_status_message("[✗]", f"模型重命名失败: {error}")
            return
        self._settings_model_profile_key = renamed
        self._reload_config()
        if was_current:
            self._sync_chat_from_active_model()
        self._apply_config_to_controls()

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
                "name": "File inline chars",
                "value": str(self.config.file_inline_chars),
                "keywords": "file_inline_chars file attachment upload reference characters",
                "edit_type": "input",
                "on_change": lambda v: self._on_setting_file_inline_chars_changed(v),
            },
            {
                "name": "Agent team",
                "value": "true" if self.config.agent_team_enable else "false",
                "keywords": "agent_team enable",
                "edit_type": "toggle",
                "options": bool_choices,
                "accessory_label": "config" if self.config.agent_team_enable else "",
                "accessory_target_page": "team",
                "on_change": lambda v: self._on_setting_agent_team_changed(v),
            },
        ]

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
                "name": "Installed skills",
                "value": ">",
                "keywords": "installed skills browser",
                "edit_type": "nav",
                "target_page": "installed_skills",
            },
            {
                "name": "Sources",
                "value": "",
                "keywords": "sources app workspace",
                "edit_type": "none",
            },
            {
                "name": "App",
                "value": "true" if self.config.skills_source_app else "false",
                "keywords": "sources app",
                "edit_type": "toggle",
                "options": bool_choices,
                "indented": True,
                "on_change": lambda v: self._on_setting_skills_source_app_changed(v),
            },
            {
                "name": "Workspace",
                "value": "true" if self.config.skills_source_workspace else "false",
                "keywords": "sources workspace",
                "edit_type": "toggle",
                "options": bool_choices,
                "indented": True,
                "on_change": lambda v: self._on_setting_skills_source_workspace_changed(
                    v
                ),
            },
            {
                "name": "Auto catalog",
                "value": "true" if self.config.skills_auto_catalog else "false",
                "keywords": "auto_catalog",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._on_setting_skills_auto_catalog_changed(v),
            },
        ]
        return rows

    def _skills_registry_for_page(self) -> SkillRegistry:
        project = self._project_from_session(self.current_session_record)
        workspace_dir = project.path if project is not None else None
        return SkillRegistry(
            enabled=True,
            app_enabled=True,
            workspace_enabled=bool(workspace_dir),
            workspace_dir=workspace_dir,
            auto_catalog=self.config.skills_auto_catalog,
        )

    def _skill_records_for_page(self) -> list[dict]:
        source_order = {"app": 0, "workspace": 1}
        records = self._skills_registry_for_page().list_skill_records()
        records.sort(
            key=lambda record: (
                source_order.get(str(record.get("source") or ""), 99),
                str(record.get("name") or "").lower(),
            )
        )
        return records

    def _skill_record_for_page(self, skill_name: str = "") -> dict | None:
        records = self._skill_records_for_page()
        if not records:
            return None
        target = str(skill_name or "").strip().lower()
        for record in records:
            if (
                str(record.get("key") or "").strip().lower() == target
                or str(record.get("name") or "").strip().lower() == target
            ):
                return record
        return records[0]

    def _installed_skill_key_for_path(self, skill_path: Path) -> str:
        target = skill_path.resolve()
        for record in self._skill_records_for_page():
            try:
                record_path = Path(str(record.get("path") or "")).resolve()
            except OSError:
                continue
            if record_path == target:
                return str(record.get("key") or "")
        return ""

    def _settings_installed_skills_state(self, selected_name: str = "") -> dict:
        records = self._skill_records_for_page()
        selected = self._skill_record_for_page(selected_name)
        selected_key = str((selected or {}).get("key") or "")
        if not records:
            return {
                "models": [],
                "groups": [],
                "selected_model": "",
                "show_group_titles": False,
                "allow_group_collapse": False,
                "item_labels": {},
                "rows": [],
                "footer_actions": [],
                "empty_list_label": "",
                "blank_detail_when_empty": True,
            }
        groups = []
        for source in ("app", "workspace"):
            names = [
                str(record.get("key") or "")
                for record in records
                if str(record.get("source") or "") == source
            ]
            if not names:
                continue
            groups.append({
                "api_type": source,
                "title": "App" if source == "app" else "Workspace",
                "models": names,
            })
        return {
            "models": [str(record.get("key") or "") for record in records],
            "groups": groups,
            "selected_model": selected_key,
            "show_group_titles": True,
            "allow_group_collapse": False,
            "item_labels": {
                str(record.get("key") or ""): str(record.get("name") or "")
                for record in records
            },
            "rows": self._settings_installed_skill_rows(selected_key),
            "footer_actions": [
                {
                    "label": "Delete",
                    "disabled": not bool(selected_key),
                    "on_activate": (
                        lambda current=selected_key: self._on_setting_skill_deleted(
                            current
                        )
                    ),
                }
            ],
            "empty_list_label": "No skills",
            "blank_detail_when_empty": True,
        }

    def _settings_installed_skill_rows(self, skill_name: str) -> list[dict]:
        record = self._skill_record_for_page(skill_name)
        if record is None:
            return []

        source = str(record.get("source") or "")
        source_label = "App" if source == "app" else "Workspace"
        source_enabled = (
            self.config.skills_source_app
            if source == "app"
            else self.config.skills_source_workspace
        )
        provider = str(record.get("provider") or "")
        provider_label = {
            "clawhub": "ClawHub",
            "skillhub": "SkillHub",
        }.get(provider, "Local")
        triggers_text = "\n".join(
            str(item)
            for item in list(record.get("triggers") or [])
            if str(item).strip()
        )
        if not triggers_text:
            triggers_text = "(empty)"
        files_text = "\n".join(
            str(item) for item in list(record.get("files") or []) if str(item).strip()
        )
        if not files_text:
            files_text = "(empty)"
        skill_md_text = str(record.get("skill_md") or "").strip() or "(empty)"
        description_text = str(record.get("description") or "").strip() or "(empty)"
        version_text = str(record.get("version") or "").strip() or "Local"
        slug_text = str(record.get("slug") or "").strip() or "(local)"
        target_text = str(record.get("target") or "").strip()
        target_label = {
            "app": "App",
            "workspace": "Workspace",
        }.get(target_text, source_label)
        registry_text = str(record.get("registry") or "").strip() or "(local)"
        installed_at = str(record.get("installed_at") or "").strip() or "(unknown)"
        return [
            {
                "name": "Name",
                "value": str(record.get("name") or ""),
                "keywords": "name",
                "edit_type": "none",
            },
            {
                "name": "Source",
                "value": source_label,
                "keywords": "source",
                "edit_type": "none",
            },
            {
                "name": "Loaded",
                "value": (
                    "true" if self.config.skills_enable and source_enabled else "false"
                ),
                "keywords": "loaded enabled",
                "edit_type": "none",
            },
            {
                "name": "Installed via",
                "value": provider_label,
                "keywords": "provider clawhub skillhub",
                "edit_type": "none",
            },
            {
                "name": "Slug",
                "value": slug_text,
                "keywords": "slug",
                "edit_type": "none",
            },
            {
                "name": "Version",
                "value": version_text,
                "keywords": "version",
                "edit_type": "none",
            },
            {
                "name": "Target",
                "value": target_label,
                "keywords": "target app workspace",
                "edit_type": "none",
            },
            {
                "name": "Installed at",
                "value": installed_at,
                "keywords": "installed at time",
                "edit_type": "none",
            },
            {
                "name": "Registry",
                "value": "",
                "keywords": "registry",
                "edit_type": "none",
                "long_value": registry_text,
            },
            {
                "name": "Path",
                "value": "",
                "keywords": "path",
                "edit_type": "none",
                "long_value": str(record.get("path") or ""),
            },
            {
                "name": "Description",
                "value": "",
                "keywords": "description",
                "edit_type": "none",
                "long_value": description_text,
            },
            {
                "name": "Triggers",
                "value": "",
                "keywords": "triggers",
                "edit_type": "none",
                "long_value": triggers_text,
            },
            {
                "name": "Files",
                "value": "",
                "keywords": "files",
                "edit_type": "none",
                "long_value": files_text,
            },
            {
                "name": "SKILL.md",
                "value": "",
                "keywords": "skill instructions markdown",
                "edit_type": "none",
                "long_value": skill_md_text,
            },
        ]

    def _ensure_skill_install_draft(self) -> dict[str, str]:
        project = self._project_from_session(self.current_session_record)
        default_target = "workspace" if project is not None else "app"
        draft = getattr(self, "_skill_install_draft", None)
        if not isinstance(draft, dict):
            draft = {
                "provider": "clawhub",
                "name": "",
                "slug": "",
                "target": default_target,
                "version": "",
                "registry": "",
                "force": "false",
            }
        if str(draft.get("target") or "") not in {"app", "workspace"}:
            draft["target"] = default_target
        self._skill_install_draft = draft
        return draft

    def _set_add_skill_field(self, key: str, value: str) -> None:
        draft = self._ensure_skill_install_draft()
        text = str(value or "")
        if key == "version":
            stripped = text.strip()
            if not stripped:
                text = ""
            elif stripped.lower() == "latest":
                text = "Latest"
            else:
                text = stripped
        elif key in {"provider", "target", "force"}:
            text = text.strip()
        draft[key] = text

    def _settings_add_skill_rows(self) -> list[dict]:
        draft = dict(self._ensure_skill_install_draft())
        registry = self._skills_registry_for_page()
        provider = str(draft.get("provider") or "clawhub").strip().lower()
        target_choices = [("App", "app"), ("Workspace", "workspace")]
        disabled_targets = (
            ["workspace"] if registry.workspace_skills_dir is None else []
        )
        rows = [
            {
                "name": "Name",
                "value": str(draft.get("name") or ""),
                "keywords": "name local directory",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_skill_field("name", v),
            },
            {
                "name": "Provider",
                "value": str(draft.get("provider") or "clawhub"),
                "keywords": "provider clawhub skillhub",
                "edit_type": "select",
                "options": [("ClawHub", "clawhub"), ("SkillHub", "skillhub")],
                "on_change": lambda v: self._set_add_skill_field("provider", v),
            },
            {
                "name": "Slug",
                "value": str(draft.get("slug") or ""),
                "keywords": "slug name owner",
                "edit_type": "input",
                "placeholder_value": (
                    "@owner/skill-name" if provider == "clawhub" else "skill-name"
                ),
                "on_change": lambda v: self._set_add_skill_field("slug", v),
            },
            {
                "name": "Target",
                "value": str(draft.get("target") or "app"),
                "keywords": "target app workspace",
                "edit_type": "select",
                "options": target_choices,
                "disabled_options": disabled_targets,
                "on_change": lambda v: self._set_add_skill_field("target", v),
            },
            {
                "name": "Version",
                "value": str(draft.get("version") or ""),
                "keywords": "version latest",
                "edit_type": "input",
                "placeholder_value": "Latest",
                "on_change": lambda v: self._set_add_skill_field("version", v),
            },
            {
                "name": "Registry",
                "value": str(draft.get("registry") or ""),
                "keywords": "registry url",
                "edit_type": "input",
                "placeholder_value": str(
                    PROVIDERS.get(provider, {}).get("default_registry") or ""
                ),
                "on_change": lambda v: self._set_add_skill_field("registry", v),
            },
            {
                "name": "Force",
                "value": str(draft.get("force") or "false"),
                "keywords": "force overwrite",
                "edit_type": "toggle",
                "options": [("true", "true"), ("false", "false")],
                "on_change": lambda v: self._set_add_skill_field("force", v),
            },
        ]
        rows.append({"name": "", "value": "", "edit_type": "none"})
        rows.append({
            "name": "",
            "value": "Install",
            "keywords": "install add skill",
            "edit_type": "action",
            "show_value": True,
            "on_activate": self._install_skill_from_draft,
        })
        return rows

    def _refresh_chat_skills_registry(self) -> None:
        if self.chat is None:
            return
        self.chat.set_skills_config(
            enabled=self.config.skills_enable,
            app_enabled=self.config.skills_source_app,
            workspace_enabled=self.config.skills_source_workspace,
            auto_catalog=self.config.skills_auto_catalog,
        )

    def _install_skill_from_draft(self) -> str:
        draft = dict(self._ensure_skill_install_draft())
        provider = str(draft.get("provider") or "clawhub").strip().lower()
        display_name = str(draft.get("name") or "").strip() or None
        local_name = display_name or None
        slug = str(draft.get("slug") or "").strip()
        if not slug:
            self.add_status_message("[!]", "Skill slug 不能为空。")
            return ""
        target = str(draft.get("target") or "app").strip().lower()
        registry = str(draft.get("registry") or "").strip() or None
        version_text = str(draft.get("version") or "").strip()
        version = (
            None
            if not version_text or version_text.lower() == "latest"
            else version_text
        )
        force = str(draft.get("force") or "").lower() in ("true", "on", "yes")
        page_registry = self._skills_registry_for_page()
        if target == "workspace":
            skills_dir = page_registry.workspace_skills_dir
            if skills_dir is None:
                self.add_status_message("[!]", "请先选择项目后再安装到 Workspace。")
                return ""
        else:
            skills_dir = APP_SKILLS_DIR.resolve()
            target = "app"
        try:
            result = install_registry_skill(
                provider,
                slug,
                skills_dir,
                target=target,
                version=version,
                registry=registry,
                force=force,
                dry_run=False,
                local_name=local_name,
                display_name=display_name,
            )
        except Exception as error:
            self.add_status_message("[✗]", f"安装 Skill 失败: {error}")
            return ""
        self._skill_install_draft = {
            **draft,
            "name": "",
            "slug": "",
            "version": "",
            "registry": "",
            "force": "false",
        }
        self._refresh_chat_skills_registry()
        selected_key = self._installed_skill_key_for_path(result.install_dir)
        if selected_key:
            self._set_settings_selected_item(selected_key)
        self.add_status_message(
            "[✓]", f"已安装 Skill: {display_name or result.install_dir.name}"
        )
        return "installed_skills"

    def _on_setting_skill_deleted(self, skill_name: str) -> None:
        record = self._skill_record_for_page(skill_name)
        if record is None:
            self.add_status_message("[!]", "未找到可删除的 Skill。")
            return
        registry = self._skills_registry_for_page()
        try:
            skill_path = Path(str(record.get("path") or "")).resolve()
        except OSError:
            self.add_status_message("[✗]", "Skill 路径无效，无法删除。")
            return
        allowed_roots = [registry.app_skills_dir.resolve()]
        if registry.workspace_skills_dir is not None:
            allowed_roots.append(registry.workspace_skills_dir.resolve())
        if not any(
            self._path_within_root(skill_path, root) and skill_path.parent == root
            for root in allowed_roots
        ):
            self.add_status_message("[✗]", "Skill 不在允许删除的目录中。")
            return
        if not skill_path.exists():
            self.add_status_message("[!]", f"Skill 已不存在: {skill_path.name}")
            return
        try:
            shutil.rmtree(skill_path)
        except OSError as error:
            self.add_status_message("[✗]", f"删除 Skill 失败: {error}")
            return
        self._refresh_chat_skills_registry()
        remaining = self._skill_records_for_page()
        next_key = ""
        deleted_key = str(record.get("key") or "")
        for item in remaining:
            candidate_key = str(item.get("key") or "")
            if candidate_key != deleted_key:
                next_key = candidate_key
                break
        self._set_settings_selected_item(next_key)
        self.add_status_message("[✓]", f"已删除 Skill: {record.get('name')}")

    def _path_within_root(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _settings_auto_compact_rows(self) -> list[dict]:
        bool_choices = [("true", "true"), ("false", "false")]
        model_choice_groups = self._optional_model_choice_groups()
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
                "name": "Compact model",
                "value": self._valid_optional_model_selection(
                    self.config.compaction_compact_model
                ),
                "keywords": "compact_model",
                "edit_type": "select",
                "option_groups": model_choice_groups,
                "on_change": lambda v: self._on_setting_compact_model_changed(v),
            },
        ]

    def _settings_memory_rows(self) -> list[dict]:
        model_choice_groups = self._optional_model_choice_groups()
        return [
            {
                "name": "Memory model",
                "value": self._valid_optional_model_selection(self.config.memory_model),
                "keywords": "memory_model",
                "edit_type": "select",
                "option_groups": model_choice_groups,
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

    def _team_store_for_page(self) -> TeamStore | None:
        project = self._project_from_session(self.current_session_record)
        workspace_dir = project.path if project is not None else None
        if self.chat is not None and getattr(self.chat, "team_store", None) is not None:
            self.chat.team_store.reload_specs()
            return self.chat.team_store
        return TeamStore(workspace_dir=workspace_dir)

    def _current_settings_modal(self) -> SettingsModal | None:
        screen = self.screen
        if isinstance(screen, SettingsModal):
            return screen
        return None

    def _set_settings_selected_item(self, name: str) -> None:
        modal = self._current_settings_modal()
        if modal is not None:
            modal._selected_model_name = str(name or "")

    def _refresh_settings_modal(self) -> None:
        modal = self._current_settings_modal()
        if modal is not None:
            modal._render_current_page(modal._current_query())

    def _team_status_for_page(self) -> dict:
        store = self._team_store_for_page()
        roster = store.get_roster() if store is not None else []
        available_types = store.names() if store is not None else []
        return {
            "enabled": bool(self.config.agent_team_enable),
            "active_count": len(roster),
            "teammates": roster,
            "available_types": available_types,
        }

    def _team_records_for_page(self) -> list[dict]:
        store = self._team_store_for_page()
        return store.spec_records() if store is not None else []

    def _team_record_for_page(self, name: str = "") -> dict | None:
        records = self._team_records_for_page()
        if not records:
            return None
        target = str(name or "").strip().lower()
        for record in records:
            if (
                str(record.get("key") or "") == target
                or str(record.get("name") or "").strip().lower() == target
            ):
                return record
        return records[0]

    def _settings_team_page_state(self, selected_name: str = "") -> dict:
        records = self._team_records_for_page()
        names = [str(record.get("name") or "") for record in records]
        selected = self._team_record_for_page(selected_name)
        selected_name = str((selected or {}).get("name") or "")
        selected_key = str((selected or {}).get("key") or "")
        source = str((selected or {}).get("source") or "builtin")
        can_delete = source == "custom"
        can_reset = bool((selected or {}).get("builtin")) and bool(
            (selected or {}).get("customized")
        )
        return {
            "models": names,
            "groups": [{"api_type": "members", "title": "", "models": names}],
            "selected_model": selected_name,
            "show_group_titles": False,
            "allow_group_collapse": False,
            "item_classes": {},
            "rows": self._settings_team_member_rows(selected_name),
            "footer_actions": [
                {
                    "label": "Delete",
                    "disabled": not selected_key or not can_delete,
                    "on_activate": (
                        lambda current=selected_key: (
                            self._on_setting_team_member_deleted(current)
                        )
                    ),
                },
                {
                    "label": "Reset",
                    "disabled": not selected_key or not can_reset,
                    "on_activate": (
                        lambda current=selected_key: self._on_setting_team_member_reset(
                            current
                        )
                    ),
                },
            ],
        }

    def _settings_team_member_rows(self, teammate_name: str) -> list[dict]:
        record = self._team_record_for_page(teammate_name)
        status = self._team_status_for_page()
        roster_by_name = {
            str(self._team_store_for_page().resolve_name(item.get("name"))): item
            for item in list(status.get("teammates") or [])
        }
        record_key = str((record or {}).get("key") or "")
        teammate = roster_by_name.get(record_key)
        if record is None:
            return [{"name": "No members", "value": "", "edit_type": "none"}]
        can_rename = not bool(record.get("builtin"))
        source = str(record.get("source") or "builtin")
        source_label = {
            "builtin": "Builtin",
            "override": "Override",
            "custom": "Custom",
        }.get(source, source.title())
        description_text = str(record.get("description") or "").strip() or "(empty)"
        tools_text = "\n".join(
            str(tool) for tool in list(record.get("tool_names") or [])
        )
        if not tools_text:
            tools_text = "(empty)"
        rows = [
            {
                "name": "Enable",
                "value": "true" if self.config.agent_team_enable else "false",
                "keywords": "team enable",
                "edit_type": "toggle",
                "options": [("true", "true"), ("false", "false")],
                "on_change": lambda v: self._on_setting_team_enabled_changed(v),
            },
            {
                "name": "Name",
                "value": str(record.get("name") or ""),
                "keywords": "name teammate name",
                "edit_type": "input" if can_rename else "none",
                "on_change": lambda v, current=record_key: (
                    self._on_setting_team_member_name_changed(current, v)
                ),
            },
            {
                "name": "Role",
                "value": str(record.get("role") or ""),
                "keywords": "role",
                "edit_type": "input",
                "on_change": lambda v, current=record_key: (
                    self._on_setting_team_member_field_changed(current, "role", v)
                ),
            },
            {
                "name": "Description",
                "value": "Edit",
                "keywords": "description",
                "edit_type": "action",
                "show_value": True,
                "long_value": description_text,
                "on_activate": lambda current=record_key: (
                    self._open_team_description_editor(current)
                ),
            },
            {
                "name": "Max turns",
                "value": str(record.get("max_turns") or ""),
                "keywords": "max turns rounds",
                "edit_type": "input",
                "on_change": lambda v, current=record_key: (
                    self._on_setting_team_member_field_changed(current, "max_turns", v)
                ),
            },
            {
                "name": "Tools",
                "value": "Edit",
                "keywords": "tools tool names",
                "edit_type": "action",
                "show_value": True,
                "long_value": tools_text,
                "on_activate": lambda current=record_key: self._open_team_tools_editor(
                    current
                ),
            },
            {
                "name": "System prompt",
                "value": "Edit",
                "keywords": "system prompt edit",
                "edit_type": "action",
                "show_value": True,
                "on_activate": lambda current=record_key: self._open_team_prompt_editor(
                    current
                ),
            },
            {
                "name": "Source",
                "value": source_label,
                "keywords": "source builtin custom override",
                "edit_type": "none",
            },
            {
                "name": "Active",
                "value": "true" if teammate else "false",
                "keywords": "active running spawned",
                "edit_type": "none",
            },
            {
                "name": "Task count",
                "value": str((teammate or {}).get("task_count") or 0),
                "keywords": "task count",
                "edit_type": "none",
            },
        ]
        if teammate:
            rows.append({
                "name": "Runtime status",
                "value": str(teammate.get("status") or "active"),
                "keywords": "runtime status",
                "edit_type": "none",
            })
            rows.append({
                "name": "Runtime",
                "value": "Shutdown",
                "keywords": "shutdown stop teammate",
                "edit_type": "action",
                "show_value": True,
                "on_activate": lambda current=record_key: (
                    self._on_setting_team_shutdown(current)
                ),
            })
        return rows

    def _sync_team_store_from_page(self) -> TeamStore | None:
        store = self._team_store_for_page()
        if store is not None:
            store.reload_specs()
        if self.chat is not None and getattr(self.chat, "team_store", None) is not None:
            self.chat.team_store.reload_specs()
        return store

    def _on_setting_team_enabled_changed(self, value: str) -> None:
        enabled = str(value or "").lower() in ("on", "true", "yes")
        save_config_field("agent_team_enable", enabled)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_team_mode(enabled)
        self._apply_config_to_controls()

    def _on_setting_add_team_member(self, _selected_name: str = "") -> str:
        store = self._sync_team_store_from_page()
        if store is None or store.config_path is None:
            self.add_status_message("[!]", "请先选择项目后再创建 team 成员。")
            return ""
        try:
            created = store.create_default_member("member")
        except Exception as error:
            self.add_status_message("[✗]", f"新增成员失败: {error}")
            return ""
        record = store.get_spec_record(created)
        selected_name = str(
            (record or {}).get("name") or display_teammate_name(created)
        )
        self._set_settings_selected_item(selected_name)
        return selected_name

    def _save_team_member_record(self, current_name: str, **changes) -> str:
        store = self._sync_team_store_from_page()
        if store is None or store.config_path is None:
            raise ValueError("请先选择项目后再编辑 team 成员。")
        record = store.get_spec_record(current_name)
        if record is None:
            raise ValueError(f"Unknown teammate: {current_name}")
        saved_name = store.save_spec(
            str(changes.get("name", record.get("name")) or ""),
            old_name=current_name,
            role=str(changes.get("role", record.get("role")) or ""),
            description=str(
                changes.get("description", record.get("description")) or ""
            ),
            system_prompt=str(
                changes.get("system_prompt", record.get("system_prompt")) or ""
            ),
            tool_names=changes.get("tool_names", record.get("tool_names") or []),
            max_turns=int(changes.get("max_turns", record.get("max_turns") or 1)),
        )
        self._sync_team_store_from_page()
        saved_record = store.get_spec_record(saved_name)
        self._set_settings_selected_item(
            str((saved_record or {}).get("name") or display_teammate_name(saved_name))
        )
        return saved_name

    def _on_setting_team_member_name_changed(
        self, current_name: str, value: str
    ) -> None:
        new_name = str(value or "").strip()
        if not new_name or new_name == current_name:
            return
        try:
            self._save_team_member_record(current_name, name=new_name)
        except Exception as error:
            self.add_status_message("[✗]", f"重命名成员失败: {error}")

    def _on_setting_team_member_field_changed(
        self, current_name: str, field: str, value: str
    ) -> None:
        payload = {}
        if field == "max_turns":
            try:
                payload[field] = max(1, int(str(value or "").strip()))
            except (TypeError, ValueError):
                self.add_status_message("[!]", "Max turns 必须是正整数。")
                return
        elif field == "tool_names":
            payload[field] = [
                part.strip() for part in str(value or "").split(",") if part.strip()
            ]
        else:
            payload[field] = str(value or "").strip()
        try:
            self._save_team_member_record(current_name, **payload)
        except Exception as error:
            self.add_status_message("[✗]", f"更新成员失败: {error}")

    def _open_team_prompt_editor(self, teammate_name: str) -> None:
        record = self._team_record_for_page(teammate_name)
        if record is None:
            return
        self.push_screen(
            TextAreaModal(
                f"Edit prompt: {record.get('name')}",
                value=str(record.get("system_prompt") or ""),
            ),
            callback=lambda result, current=teammate_name: (
                self._handle_team_prompt_result(current, result)
            ),
        )

    def _open_team_description_editor(self, teammate_name: str) -> None:
        record = self._team_record_for_page(teammate_name)
        if record is None:
            return
        self.push_screen(
            TextAreaModal(
                f"Edit description: {record.get('name')}",
                value=str(record.get("description") or ""),
            ),
            callback=lambda result, current=teammate_name: (
                self._handle_team_description_result(current, result)
            ),
        )

    def _handle_team_description_result(
        self, teammate_name: str, result: str | None
    ) -> None:
        if result is None:
            return
        try:
            self._save_team_member_record(
                teammate_name, description=str(result).strip()
            )
        except Exception as error:
            self.add_status_message("[✗]", f"保存 description 失败: {error}")
            return
        self._refresh_settings_modal()

    def _open_team_tools_editor(self, teammate_name: str) -> None:
        record = self._team_record_for_page(teammate_name)
        if record is None:
            return
        value = "\n".join(str(tool) for tool in list(record.get("tool_names") or []))
        self.push_screen(
            TextAreaModal(
                f"Edit tools: {record.get('name')}",
                value=value,
            ),
            callback=lambda result, current=teammate_name: (
                self._handle_team_tools_result(current, result)
            ),
        )

    def _handle_team_tools_result(self, teammate_name: str, result: str | None) -> None:
        if result is None:
            return
        tool_names = []
        for line in str(result).splitlines():
            for part in line.split(","):
                name = part.strip()
                if name and name not in tool_names:
                    tool_names.append(name)
        try:
            self._save_team_member_record(teammate_name, tool_names=tool_names)
        except Exception as error:
            self.add_status_message("[✗]", f"保存 tools 失败: {error}")
            return
        self._refresh_settings_modal()

    def _handle_team_prompt_result(
        self, teammate_name: str, result: str | None
    ) -> None:
        if result is None or result == "":
            return
        try:
            self._save_team_member_record(teammate_name, system_prompt=str(result))
        except Exception as error:
            self.add_status_message("[✗]", f"保存 prompt 失败: {error}")
            return
        self._refresh_settings_modal()

    def _on_setting_team_member_deleted(self, name: str) -> None:
        store = self._sync_team_store_from_page()
        if store is None:
            return
        removed = store.delete_spec(name)
        if not removed:
            self.add_status_message(
                "[!]", f"未找到可删除的成员定义: {display_teammate_name(name)}"
            )
            return
        records = store.spec_records()
        next_name = str((records[0].get("name") if records else "") or "")
        self._set_settings_selected_item(next_name)
        self.add_status_message("[✓]", f"已删除成员定义: {display_teammate_name(name)}")

    def _on_setting_team_member_reset(self, name: str) -> None:
        store = self._sync_team_store_from_page()
        if store is None:
            return
        record = store.get_spec_record(name)
        if record is None:
            return
        if not bool(record.get("builtin")):
            self.add_status_message(
                "[!]", f"仅内置成员支持重置: {display_teammate_name(name)}"
            )
            return
        if not bool(record.get("customized")):
            self.add_status_message(
                "[!]", f"成员未被修改，无需重置: {display_teammate_name(name)}"
            )
            return
        removed = store.delete_spec(name)
        if not removed:
            self.add_status_message("[!]", f"重置失败: {display_teammate_name(name)}")
            return
        refreshed = store.get_spec_record(name)
        self._set_settings_selected_item(
            str((refreshed or {}).get("name") or display_teammate_name(name))
        )
        self.add_status_message("[✓]", f"已重置成员定义: {display_teammate_name(name)}")

    def _on_setting_team_shutdown(self, name: str) -> None:
        removed = False
        if self.chat is not None and getattr(self.chat, "team_store", None) is not None:
            try:
                self.chat._shutdown_teammate_task(name)
                removed = bool(self.chat.team_store.remove_teammate(name))
            except Exception:
                removed = False
        else:
            store = self._team_store_for_page()
            if store is not None:
                try:
                    removed = bool(store.remove_teammate(name))
                except Exception:
                    removed = False
        if removed:
            self.add_status_message(
                "[✓]", f"已关闭 teammate: {display_teammate_name(name)}"
            )
        else:
            self.add_status_message(
                "[!]", f"未找到 teammate: {display_teammate_name(name)}"
            )

    def _memory_store_for_page(self) -> MemoryStore:
        history_path = ""
        if self.current_session_record is not None:
            history_path = str(
                self.current_session_record.get("history_path") or ""
            ).strip()
        return MemoryStore(history_path=history_path or None)

    def _memory_sections(self) -> list[dict]:
        store = self._memory_store_for_page()
        episodic_blocks = []
        for path in sorted(
            store.episodic_dir.glob("*.md"), key=lambda item: item.stem, reverse=True
        ):
            if not path.is_file():
                continue
            body = store.episodic_for_date(path.stem)
            if body:
                episodic_blocks.append(f"## {path.stem}\n\n{body}")
        return [
            {"id": "core", "label": "Core memory", "content": store.read_core_body()},
            {
                "id": "prefs",
                "label": "Preference memory",
                "content": store.read_preference_body(),
            },
            {
                "id": "episodic",
                "label": "Episodic memory",
                "content": "\n\n".join(episodic_blocks),
            },
        ]

    def _open_memory(self) -> None:
        self.push_screen(MemoryModal(self._memory_sections()))


    def _settings_model_target_key(self) -> str:
        config = self.config
        if self._settings_model_profile_key in config.model_list:
            return self._settings_model_profile_key
        return config.current_model if config.current_model in config.model_list else ""

    def _save_settings_model_field(self, key: str, value) -> bool:
        target = self._settings_model_target_key()
        if not target:
            return False
        was_current = target == self.config.current_model
        save_model_profile_field(target, key, value)
        self._reload_config()
        if was_current:
            self._sync_chat_from_active_model()
        self._apply_config_to_controls()
        return True

    def _on_setting_delete_model(self, name: str) -> None:
        target = str(name or "").strip()
        if not target:
            return
        was_current = target == self.config.current_model
        try:
            delete_model_profile(target)
        except Exception as error:
            self.add_status_message("[✗]", f"删除模型失败: {error}")
            return
        self._reload_config()
        config = self.config
        self._settings_model_profile_key = (
            config.current_model
            if config.current_model in config.model_list
            else next(iter(config.model_list.keys()), "")
        )
        if was_current:
            self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_changed(self, value: str) -> None:
        save_config_field("current_model", value)
        self._reload_config()
        self._sync_chat_from_active_model()
        self._apply_config_to_controls()

    def _on_setting_model_api_type_changed(self, value: str) -> None:
        self._save_settings_model_field("api_type", value)

    def _on_setting_model_base_url_changed(self, value: str) -> None:
        self._save_settings_model_field("base_url", value)

    def _on_setting_model_id_changed(self, value: str) -> None:
        model_id = str(value or "").strip()
        if not model_id:
            return
        self._save_settings_model_field("model", model_id)

    def _on_setting_model_api_key_changed(self, value: str) -> None:
        self._save_settings_model_field("api_key", str(value or "").strip())

    def _on_setting_model_thinking_changed(self, value: str) -> None:
        enabled = str(value or "").lower() in ("on", "true", "yes")
        self._save_settings_model_field("thinking_mode", enabled)

    def _on_setting_model_reasoning_effort_changed(self, value: str) -> None:
        target = self._settings_model_target_key()
        profile = self.config.model_list.get(target)
        if profile is None:
            return
        effort = normalize_reasoning_effort_for_api(
            profile.api_type,
            value or "medium",
        )
        self._save_settings_model_field("reasoning_effort", effort)

    def _on_setting_model_extra_modalities_changed(self, value: str) -> None:
        text = str(value or "")
        try:
            selected = parse_extra_modalities_input(text, required=True)
        except ValueError as error:
            self.add_status_message("[!]", str(error))
            return
        target = self._settings_model_target_key()
        profile = self.config.model_list.get(target)
        if profile is None:
            return
        current = profile.extra_modalities
        updated = {
            modality: current.get(
                modality, DEFAULT_EXTRA_MODALITY_LIMITS[modality]
            )
            for modality in selected
        }
        self._save_settings_model_field("extra_modalities", updated)

    def _on_setting_model_limit_selected(self, key: str) -> None:
        self._settings_model_limit_key = str(key or "total")

    def _on_setting_model_limit_changed(self, key: str, value: str) -> None:
        if key == "total":
            try:
                limit = parse_multimodal_limit(value)
            except ValueError as error:
                self.add_status_message("[!]", str(error))
                return
            self._save_settings_model_field("multimodal_limit", limit)
            return

        target = self._settings_model_target_key()
        profile = self.config.model_list.get(target)
        if profile is None:
            return
        limits = dict(profile.extra_modalities)
        if key not in limits:
            return
        limits[key] = value
        try:
            limits = parse_extra_modalities_config(limits)
        except ValueError as error:
            self.add_status_message("[!]", str(error))
            return
        self._save_settings_model_field("extra_modalities", limits)

    def _on_setting_model_context_changed(self, value: str) -> None:
        try:
            tokens = max(1, int(value))
        except (TypeError, ValueError):
            return
        if self._save_settings_model_field("context_window_tokens", tokens):
            self._refresh_context_label_for_active_model()

    def _on_setting_token_changed(self, value: str) -> None:
        try:
            tokens = max(1, int(value))
        except (TypeError, ValueError):
            return
        self._save_settings_model_field("max_tokens", tokens)

    def _on_setting_temp_changed(self, value: str) -> None:
        try:
            temp = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        self._save_settings_model_field("temperature", temp)

    def _on_setting_stream_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        self._save_settings_model_field("stream_mode", enabled)

    def _on_setting_thinking_changed(self, value: str) -> None:
        thinking_enabled = value != "none"
        updates = {"thinking_mode": thinking_enabled}
        if thinking_enabled:
            updates["reasoning_effort"] = normalize_reasoning_effort_for_api(
                self.config.active_model.api_type, value
            )
        save_config_fields(updates)
        self._reload_config()
        if self.chat is not None:
            self.chat.set_thinking_mode(thinking_enabled)
            if thinking_enabled:
                self.chat.set_reasoning_effort(
                    self.config.active_model.reasoning_effort
                )
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

    def _on_setting_file_inline_chars_changed(self, value: str) -> None:
        try:
            chars = parse_file_inline_chars(value)
        except ValueError as error:
            self.add_status_message("[!]", str(error))
            return
        save_config_field("file_inline_chars", chars)
        self._reload_config()
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

    def _on_setting_compact_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("compaction_enable", enabled)
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

    def _on_setting_render_markdown_changed(self, value: str) -> None:
        enabled = value.lower() in ("on", "true", "yes")
        save_config_field("render_markdown", enabled)
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
        self._prompt_request = None
        if self.chat is not None:
            self.chat.shutdown()
        self.chat = None
        self.chat_busy = False
        self.current_session_record = None
        self.todo_items = []
        self._set_todo_panel_items([])
        self._stream_kind = None
        self._suppress_stream_output = False
        self._interrupt_send_payload = None
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
        chat_input.set_chat_busy(False)
        chat_input.clear_pending_messages()
        chat_input.set_prompt_state(active=False)
        chat_input.remove_class("stretch")
        info_bar_shell.remove_class("stretch")
        project_picker.remove_class("hidden")
        interrupt_hint.remove_class("visible")
        project_title.remove_class("hidden")
        messages_wrap.remove_class("visible")
        messages.clear()
        input_wrapper.add_class("welcome")
        self._sync_prompt_actions()
        self._apply_config_to_controls()
        if refresh_sidebar:
            self._refresh_project_views()

    def _archive_session_record(self, session_path: str) -> None:
        current_path = str(
            (self.current_session_record or {}).get("session_path") or ""
        ).strip()
        archive_session(session_path)
        if current_path and current_path == str(session_path).strip():
            self._clear_loaded_session_state(refresh_sidebar=False)

    def _delete_session_record(self, session_path: str) -> None:
        current_path = str(
            (self.current_session_record or {}).get("session_path") or ""
        ).strip()
        delete_session(session_path)
        if current_path and current_path == str(session_path).strip():
            self._clear_loaded_session_state(refresh_sidebar=False)

    def _unarchive_session_record(self, session_path: str) -> None:
        unarchive_session(session_path)

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
            extra_modalities=model.extra_modalities,
            agent_mode=agent_mode,
            workspace_dir=workspace_dir,
            max_agent_rounds=self.config.max_agent_rounds,
            max_agent_tool_calls=self.config.max_agent_tool_calls,
            agent_approval_mode=self.config.agent_approval_mode,
            skills_enabled=self.config.skills_enable,
            skills_source_app=self.config.skills_source_app,
            skills_source_workspace=self.config.skills_source_workspace,
            skills_auto_catalog=self.config.skills_auto_catalog,
            compaction_enable=self.config.compaction_enable,
            compaction_compact_model=(
                AUTO_MODEL_SELECTION
                if self.config.compaction_compact_model == AUTO_MODEL_SELECTION
                else self.config.selected_backend_model(
                    self.config.compaction_compact_model
                )
            ),
            memory_model=(
                AUTO_MODEL_SELECTION
                if self.config.memory_model == AUTO_MODEL_SELECTION
                else self.config.selected_backend_model(self.config.memory_model)
            ),
            web_search_enabled=self.config.web_search_enable,
            web_search_provider=self.config.web_search_provider,
            web_search_api_key=self.config.web_search_api_key,
            web_search_max_results=self.config.web_search_max_results,
            web_search_depth=self.config.web_search_depth,
            web_search_topic=self.config.web_search_topic,
            agent_plan_enabled=self.config.agent_plan_enable,
            agent_team_enable=self.config.agent_team_enable,
            current_model_name=self.config.active_model_label,
            history_path=session_record.get("history_path"),
            usage_history_callback=(
                lambda source_chat, entry, session_path=session_record.get(
                    "session_path"
                ): self._on_chat_usage_entry(
                    session_path,
                    source_chat,
                    entry,
                )
            ),
            plan_mode_changed_callback=self._on_agent_plan_mode_changed,
        )
        chat.set_usage_history(session_record.get("usage_history") or [])
        return chat

    def _process_user_message(self, user_text: str) -> None:
        try:
            if user_text.startswith("/"):
                self._process_command_message(user_text)
                return

            project = self._selected_project()
            base_dir = project.path if project is not None else None
            enriched_text, media_references, reference_files, reference_folders = (
                attach_external_file_references_with_media(
                    user_text,
                    base_dir,
                    self.config.active_model.extra_modalities,
                    self.config.active_model.multimodal_limit,
                    self.config.file_inline_chars,
                )
            )
            response = self.chat.send_message(
                enriched_text,
                stream_callback_thinking=self.append_stream_thinking,
                stream_callback_response=self.append_stream_response,
                media_references=media_references,
                reference_files=reference_files,
                reference_folders=reference_folders,
            )
            if response and not response.get("agent_stopped"):
                self.chat.update_session_episodic_memory()
            self._call_ui(self._finish_response, response)
        except Exception as error:
            self._call_ui(self._finish_with_error, error)

    def _process_command_message(self, command_text: str) -> None:
        base = command_text.split(maxsplit=1)[0].lower()
        if base == "/help":
            self._call_ui(self._finish_open_settings_page_command, "help")
            return
        if base == "/memory":
            self._call_ui(self._finish_open_memory_command)
            return
        if base == "/team":
            self._call_ui(self._finish_open_settings_page_command, "team")
            return
        if base == "/search":
            self._call_ui(self._finish_open_settings_page_command, "web_search")
            return
        if base == "/skills":
            self._call_ui(self._finish_open_settings_page_command, "skills")
            return
        if base == "/agent":
            self._call_ui(self._finish_open_settings_page_command, "agent_mode")
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

    def _finish_open_settings_page_command(self, page_id: str) -> None:
        self.chat_busy = False
        self._suppress_stream_output = False
        self.query_one("#chat-input", ChatInput).set_chat_busy(False)
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._sync_prompt_actions()
        self._open_settings(page_id)

    def _finish_open_memory_command(self) -> None:
        self.chat_busy = False
        self._suppress_stream_output = False
        self.query_one("#chat-input", ChatInput).set_chat_busy(False)
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._sync_prompt_actions()
        self._open_memory()

    def _after_command(self, base: str, should_continue) -> None:
        self.chat_busy = False
        self._suppress_stream_output = False
        self.query_one("#chat-input", ChatInput).set_chat_busy(False)
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._sync_prompt_actions()
        self._apply_config_to_controls()
        if should_continue is False:
            self.exit()
            return
        if base == "/clear":
            self._reset_chat_state()
            self.add_status_message("[✓]", "对话历史已清空。")
            return
        self._persist_current_session()
        self._maybe_dispatch_pending_message()

    def _finish_response(self, response) -> None:
        self._pause_thinking_elapsed_timer()
        self._finish_thought_stream_widget(
            self._elapsed_since_thinking(),
        )
        self.chat_busy = False
        self._suppress_stream_output = False
        self.query_one("#chat-input", ChatInput).set_chat_busy(False)
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._sync_prompt_actions()
        self._display_response(response)
        self._maybe_show_changed_files()
        self._persist_current_session()
        self._message_started_at = None
        self._thinking_started_at = None
        self._maybe_dispatch_pending_message()

    def _maybe_show_changed_files(self) -> None:
        if self.chat is None:
            return
        try:
            summary = self.chat.agent_tools.changed_files_summary()
        except Exception:
            return
        if not summary:
            return
        self.query_one("#messages-view", ChatView).add_changed_files_entry(summary)

    def _finish_with_error(self, error: Exception) -> None:
        self._pause_thinking_elapsed_timer()
        self._finish_thought_stream_widget(
            self._elapsed_since_thinking(),
        )
        self.chat_busy = False
        self._suppress_stream_output = False
        self.query_one("#chat-input", ChatInput).set_chat_busy(False)
        self._set_input_enabled(True)
        self._set_controls_locked(False)
        self._sync_prompt_actions()
        self.add_status_message("[✗]", f"处理消息失败: {error}")
        self._persist_current_session()
        self._message_started_at = None
        self._thinking_started_at = None
        self._maybe_dispatch_pending_message()

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
        try:
            self.query_one("#messages-view", ChatView).update_thought_stream_elapsed(
                self._elapsed_since_thinking()
            )
        except NoMatches:
            # The timer can tick during shutdown after the chat view is already gone.
            self._pause_thinking_elapsed_timer()
            self._thinking_started_at = None

    def _resume_thinking_elapsed_timer(self) -> None:
        if self._thinking_elapsed_timer is not None:
            self._thinking_elapsed_timer.resume()

    def _pause_thinking_elapsed_timer(self) -> None:
        if self._thinking_elapsed_timer is not None:
            self._thinking_elapsed_timer.pause()

    def _on_chat_usage_entry(
        self,
        session_path,
        source_chat: OmniAgent,
        entry: dict,
    ) -> None:
        self._call_ui(
            self._persist_chat_usage_entry,
            str(session_path or ""),
            source_chat,
            dict(entry or {}),
        )

    def _persist_chat_usage_entry(
        self,
        session_path: str,
        source_chat: OmniAgent,
        entry: dict,
    ) -> None:
        session_path = str(session_path or "").strip()
        if not session_path or not isinstance(entry, dict):
            return
        current_path = ""
        if self.current_session_record is not None:
            current_path = str(
                self.current_session_record.get("session_path") or ""
            ).strip()
        if current_path == session_path and self.chat is not None:
            if source_chat is not self.chat:
                self.chat.append_usage_history([entry])
            self._persist_current_session(refresh_sidebar=False)
            return

        record = load_session(session_path)
        if not record:
            return
        usage_history = [
            dict(item)
            for item in list(record.get("usage_history") or [])
            if isinstance(item, dict)
        ]
        entry_id = str(entry.get("id") or "")
        if entry_id and any(
            str(item.get("id") or "") == entry_id for item in usage_history
        ):
            return
        usage_history.append(dict(entry))
        record["usage_history"] = usage_history
        save_session_record(record)

    def _persist_current_session(self, refresh_sidebar: bool = True) -> None:
        if self.current_session_record is None or self.chat is None:
            return
        history = list(self.chat.get_history() or [])
        record = dict(self.current_session_record)
        view = self.query_one("#messages-view", ChatView)
        record["conversation"] = history
        record["usage_history"] = self.chat.get_usage_history()
        record["ui_transcript"] = view.get_transcript()
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

    @staticmethod
    def _session_title_from_text(text: str) -> str:
        title = " ".join(clean_display_text(text or "").split())
        return title[:60] if title else "New Chat"

    def _update_new_session_title_from_text(self, text: str) -> None:
        if self.current_session_record is None:
            return
        record = dict(self.current_session_record)
        if str(record.get("title") or "").strip() not in {"", "New Chat"}:
            return
        record["title"] = self._session_title_from_text(text)
        record["title_state"] = SESSION_TITLE_STATE_TEMPORARY
        record["title_seed_text"] = str(text or "")
        record["title_summary_pending"] = True
        self.current_session_record = save_session_record(record)
        self._refresh_project_views()

    def _maybe_schedule_session_title_summary(self) -> None:
        if self.current_session_record is None:
            return
        record = dict(self.current_session_record)
        if (
            str(record.get("title_state") or "").strip()
            != SESSION_TITLE_STATE_TEMPORARY
        ):
            return
        session_path = str(record.get("session_path") or "").strip()
        seed_text = str(record.get("title_seed_text") or "").strip()
        expected_title = str(record.get("title") or "").strip()
        if not session_path or not seed_text or not expected_title:
            return
        if session_path in self._title_summary_sessions:
            return
        chat = self._build_chat(record)
        self._title_summary_sessions.add(session_path)
        worker = threading.Thread(
            target=self._generate_session_title_summary,
            args=(chat, session_path, seed_text, expected_title),
            daemon=True,
        )
        worker.start()

    def _generate_session_title_summary(
        self,
        chat: OmniAgent,
        session_path: str,
        seed_text: str,
        expected_title: str,
    ) -> None:
        try:
            generated_title = chat.generate_session_title(seed_text)
            self._call_ui(
                self._apply_generated_session_title,
                session_path,
                generated_title,
                expected_title,
            )
        finally:
            self._call_ui(self._clear_pending_title_summary, session_path)

    def _clear_pending_title_summary(self, session_path: str) -> None:
        self._title_summary_sessions.discard(str(session_path or "").strip())

    def _apply_generated_session_title(
        self,
        session_path: str,
        generated_title: str,
        expected_title: str,
    ) -> None:
        record = load_session(session_path)
        if not record:
            return
        if (
            str(record.get("title_state") or "").strip()
            != SESSION_TITLE_STATE_TEMPORARY
        ):
            return
        if str(record.get("title") or "").strip() != str(expected_title or "").strip():
            return
        title = self._session_title_from_text(generated_title)
        if title == "New Chat":
            return
        record["title"] = title
        record["title_state"] = SESSION_TITLE_STATE_GENERATED
        record.pop("title_seed_text", None)
        record["title_summary_pending"] = False
        updated = save_session_record(record)
        if (
            self.current_session_record is not None
            and str(self.current_session_record.get("session_path") or "").strip()
            == str(session_path or "").strip()
        ):
            self.current_session_record = updated
        self._refresh_project_views()

    def _session_title_from_history(self, history: list[dict]) -> str:
        for message in history or []:
            if str(message.get("role") or "") != "user":
                continue
            title = self._session_title_from_text(message.get("content", ""))
            if title != "New Chat":
                return title
        return "New Chat"

    def _sync_chat_view_with_history(self) -> None:
        history = list(self.chat.get_history() if self.chat is not None else [])
        self.start_chat()
        view = self.query_one("#messages-view", ChatView)
        view.clear()
        transcript = []
        if self.current_session_record is not None:
            saved_transcript = self.current_session_record.get("ui_transcript")
            if isinstance(saved_transcript, list):
                transcript = saved_transcript
        if transcript:
            project = self._selected_project()
            base_dir = project.path if project is not None else None
            transcript = self._restore_transcript_reference_content(
                transcript, history, base_dir
            )
            view.load_transcript(transcript, base_dir)
            self.query_one("#chat-input", ChatInput).chat_active = True
            return
        for message in history:
            self._replay_history_message(view, message)
        self.query_one("#chat-input", ChatInput).chat_active = True

    def _restore_transcript_reference_content(
        self, transcript: list[dict], history: list[dict], base_dir=None
    ) -> list[dict]:
        user_contents = [
            message.get("content", "")
            for message in history
            if isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content", ""), str)
        ]
        user_index = 0
        restored = []
        for entry in transcript:
            item = dict(entry) if isinstance(entry, dict) else entry
            if (
                isinstance(item, dict)
                and item.get("kind") == "message"
                and item.get("role") == "user"
            ):
                if user_index < len(user_contents):
                    source = self._reference_display_source(user_contents[user_index])
                    if resolve_references(source, base_dir):
                        item["content"] = source
                user_index += 1
            elif isinstance(item, dict) and item.get("kind") == "compaction":
                item["details"] = self._normalize_compaction_transcript_details(
                    item.get("details", "")
                )
            restored.append(item)
        return restored

    def _normalize_compaction_transcript_details(self, details: str) -> str:
        text = str(details or "").strip()
        if not text:
            return ""
        model_name_by_id = {
            str(getattr(profile, "model", "") or "").strip(): str(
                profile.profile_name or ""
            ).strip()
            for profile in self.config.model_list.values()
            if str(getattr(profile, "model", "") or "").strip()
        }
        lines: list[str] = []
        message_match = re.search(
            r"\bmessages?\s*:\s*([0-9]+)\s*->\s*([0-9]+)",
            text,
            flags=re.IGNORECASE,
        )
        if message_match:
            lines.append(
                f"Message: {message_match.group(1)} -> {message_match.group(2)}"
            )
        char_match = re.search(
            r"\bchars?\s*:\s*([0-9]+)\s*->\s*([0-9]+)",
            text,
            flags=re.IGNORECASE,
        )
        if char_match:
            lines.append(f"Chars: {char_match.group(1)} -> {char_match.group(2)}")
        model_match = re.search(
            r"\bcompact model\s*:\s*(.+?)(?=\s+Memory updated:|\s+Memory update failed:|\s+Memory update:\s*scheduled|$)",
            text,
            flags=re.IGNORECASE,
        )
        if model_match:
            raw_model = str(model_match.group(1) or "").strip()
            if raw_model:
                lines.append(
                    f"Compact model: {model_name_by_id.get(raw_model, raw_model)}"
                )
        return "\n".join(lines) if lines else text

    @staticmethod
    def _reference_display_source(content: str) -> str:
        text = str(content or "")
        positions = [
            position
            for marker in (
                "\n\n[Referenced external files]",
                "\n\n[Referenced folders]",
            )
            if (position := text.find(marker)) >= 0
        ]
        return text[: min(positions)].rstrip() if positions else text

    def _replay_history_message(self, view: ChatView, message: dict) -> None:
        if not isinstance(message, dict):
            return
        role = str(message.get("role") or "")
        content = message.get("content", "")

        if role == "assistant":
            self._replay_assistant_history(view, message)
            return

        if role == "tool":
            self._replay_tool_result_message(view, message)
            return

        if role == "user" and self._is_tool_result_content(content):
            for block in list(content or []):
                self._replay_tool_result_block(view, block)
            return

        display_content = (
            self._reference_display_source(content) if role == "user" else content
        )
        text = clean_display_text_preserve_newlines(display_content)
        if role == "user":
            view.reset_turn_summaries()
            if text:
                project = self._selected_project()
                base_dir = project.path if project is not None else None
                view.add_message("user", text, base_dir)
            return
        if text:
            view.add_status(f"{role.upper()}: {text}")

    def _replay_assistant_history(self, view: ChatView, message: dict) -> None:
        content = message.get("content", "")
        if isinstance(content, list):
            for block in content:
                self._replay_assistant_block(view, block)
            return

        thinking = clean_display_text_preserve_newlines(
            message.get("thinking")
            or message.get("reasoning")
            or message.get("reasoning_content")
            or message.get("reasoning_details")
            or ""
        )
        if thinking:
            view.add_thought(thinking)

        text_content = content
        if thinking and isinstance(content, str):
            text_content = self._strip_think_tags(content)
        text = clean_display_text_preserve_newlines(text_content)
        if text:
            view.add_message("assistant", text)

        for tool_call in list(message.get("tool_calls") or []):
            self._replay_tool_call(view, tool_call)

    def _replay_assistant_block(self, view: ChatView, block: dict) -> None:
        if not isinstance(block, dict):
            text = clean_display_text_preserve_newlines(block)
            if text:
                view.add_message("assistant", text)
            return

        block_type = str(block.get("type") or "")
        if block_type == "thinking":
            thinking = clean_display_text_preserve_newlines(
                block.get("thinking") or block.get("text") or block.get("content") or ""
            )
            if thinking:
                view.add_thought(thinking)
            return
        if block_type == "text":
            text = clean_display_text_preserve_newlines(block.get("text") or "")
            if text:
                view.add_message("assistant", text)
            return
        if block_type == "tool_use":
            self._replay_tool_call(view, block)
            return

        text = clean_display_text_preserve_newlines(block)
        if text:
            view.add_status(text)

    def _replay_tool_call(self, view: ChatView, tool_call: dict) -> None:
        if not isinstance(tool_call, dict):
            return
        function = tool_call.get("function") or {}
        name = str(
            tool_call.get("name")
            or function.get("name")
            or tool_call.get("tool_name")
            or ""
        )
        if name in {"update_todo", "ask_user", "web_fetch", "web_search"}:
            return
        arguments = (
            tool_call.get("input")
            if "input" in tool_call
            else function.get("arguments", tool_call.get("arguments", ""))
        )
        detail = clean_display_text_preserve_newlines(arguments)
        label = f"Tool call: {name}".strip()
        if detail:
            label = f"{label}\n{detail}"
        view.add_status(label)

    def _replay_tool_result_message(self, view: ChatView, message: dict) -> None:
        name = str(message.get("tool_name") or message.get("name") or "")
        if self._replay_tool_result_display(view, message.get("display")):
            return
        content = clean_display_text_preserve_newlines(message.get("content", ""))
        if tool_result_is_error(name, content):
            display = build_tool_error_display(name, {}, content)
            view.add_tool_error_entry(
                str(display.get("tool_name") or ""),
                str(display.get("summary") or ""),
                str(display.get("error") or ""),
            )
            return
        if name == "update_todo":
            return
        label = f"Tool result: {name}".strip()
        if content:
            label = f"{label}\n{content}"
        view.add_status(label)

    def _replay_tool_result_block(self, view: ChatView, block: dict) -> None:
        if not isinstance(block, dict):
            return
        name = str(block.get("tool_name") or "")
        if self._replay_tool_result_display(view, block.get("display")):
            return
        content = clean_display_text_preserve_newlines(block.get("content", ""))
        tool_use_id = str(block.get("tool_use_id") or "")
        is_error = bool(block.get("is_error"))
        if is_error or tool_result_is_error(name, content):
            display = build_tool_error_display(name, {}, content)
            view.add_tool_error_entry(
                str(display.get("tool_name") or ""),
                str(display.get("summary") or ""),
                str(display.get("error") or ""),
            )
            return
        if name == "update_todo":
            return
        label = "Tool result"
        if tool_use_id:
            label += f": {tool_use_id}"
        if content:
            label = f"{label}\n{content}"
        view.add_status(label)

    @staticmethod
    def _replay_tool_result_display(view: ChatView, display) -> bool:
        if not isinstance(display, dict):
            return False
        kind = str(display.get("kind") or "")
        if kind == "tool_error":
            view.add_tool_error_entry(
                str(display.get("tool_name") or ""),
                str(display.get("summary") or ""),
                str(display.get("error") or ""),
            )
            return True
        if kind == "plan":
            plan = clean_display_text_preserve_newlines(display.get("plan", ""))
            if plan:
                view.add_plan_entry(plan)
                return True
            return False
        if kind == "ask_user":
            entries = display.get("entries")
            if isinstance(entries, list):
                rendered = False
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    question = clean_display_text_preserve_newlines(
                        entry.get("question", "")
                    )
                    answer = clean_display_text_preserve_newlines(
                        entry.get("answer", "")
                    )
                    if question or answer:
                        view.add_question_entry(question, answer)
                        rendered = True
                if rendered:
                    return True
            question = clean_display_text_preserve_newlines(display.get("question", ""))
            answer = clean_display_text_preserve_newlines(display.get("answer", ""))
            if question or answer:
                view.add_question_entry(question, answer)
                return True
            return False
        if kind == "todo":
            items = display.get("items")
            summary = display.get("summary")
            if isinstance(items, list):
                view.add_todo_entry(
                    items, summary if isinstance(summary, dict) else None
                )
                return True
            return False
        if kind == "web_fetch":
            url = clean_display_text_preserve_newlines(display.get("url", ""))
            if url:
                view.add_web_fetch_entry(url)
                return True
        if kind == "web_search":
            content = clean_display_text_preserve_newlines(display.get("content", ""))
            if content:
                view.add_web_search_entry(content)
                return True
        if kind == "file_edit":
            file_path = clean_display_text_preserve_newlines(
                display.get("file_path", "")
            )
            additions = int(display.get("additions", 0) or 0)
            deletions = int(display.get("deletions", 0) or 0)
            diff = display.get("diff", "")
            status = clean_display_text_preserve_newlines(display.get("status", ""))
            if file_path:
                view.add_edit_entry(file_path, additions, deletions, diff, status)
                return True
        if kind == "file_write":
            file_path = clean_display_text_preserve_newlines(
                display.get("file_path", "")
            )
            additions = int(display.get("additions", 0) or 0)
            deletions = int(display.get("deletions", 0) or 0)
            diff = display.get("diff", "")
            status = clean_display_text_preserve_newlines(display.get("status", ""))
            if file_path:
                view.add_write_entry(file_path, additions, deletions, diff, status)
                return True
        if kind == "shell":
            command = clean_display_text_preserve_newlines(display.get("command", ""))
            output = display.get("output", "")
            if command:
                view.add_shell_entry(command, output)
                return True
        if kind == "subagent":
            agent_type = clean_display_text_preserve_newlines(
                display.get("agent_type", "")
            )
            transcript = display.get("transcript")
            if agent_type and isinstance(transcript, list):
                view.add_subagent_entry(agent_type, transcript)
                return True
        if kind == "subagent_batch":
            rendered = False
            for item in list(display.get("items") or []):
                if not isinstance(item, dict):
                    continue
                agent_type = clean_display_text_preserve_newlines(
                    item.get("agent_type", "")
                )
                transcript = item.get("transcript")
                if agent_type and isinstance(transcript, list):
                    view.add_subagent_entry(agent_type, transcript)
                    rendered = True
            if rendered:
                return True
        if kind == "team_run":
            transcript = display.get("transcript")
            if isinstance(transcript, list):
                view.add_team_entry(
                    str(display.get("teammate_name") or "teammate"),
                    str(display.get("role") or ""),
                    str(display.get("purpose") or ""),
                    str(display.get("task_id") or ""),
                    str(display.get("status") or "completed"),
                    transcript,
                    str(display.get("result") or ""),
                )
                return True
        if kind == "team_action":
            view.add_team_action_entry(
                str(display.get("action") or "team"),
                str(display.get("summary") or ""),
                str(display.get("details") or ""),
                str(display.get("status") or "success"),
                dict(display.get("metadata") or {}),
            )
            return True
        return False

    @staticmethod
    def _is_tool_result_content(content) -> bool:
        if not isinstance(content, list) or not content:
            return False
        return all(
            isinstance(block, dict) and str(block.get("type") or "") == "tool_result"
            for block in content
        )

    @staticmethod
    def _strip_think_tags(content: str) -> str:
        text = str(content or "")
        text = re.sub(
            r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<\s*/?\s*think\s*>", "", text, flags=re.IGNORECASE)
        return text

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
