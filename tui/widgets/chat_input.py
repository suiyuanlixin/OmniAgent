from __future__ import annotations

import os
from time import perf_counter
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container, VerticalScroll
from textual.strip import Strip
from textual.widgets import Button, Static, TextArea
from textual.widget import Widget
from textual.message import Message
from textual.reactive import reactive

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from commands import COMMANDS
from tui.data import THINKING_LEVELS, APPROVAL_LEVELS
from tui.theme import (
    PAGE_BACKGROUND,
    SURFACE_BACKGROUND,
    TEXT_MUTED,
    TEXT_PRIMARY,
    render_css,
)

TRIGGER_HORIZONTAL_PADDING = 1
OPTION_HORIZONTAL_PADDING = 0
OPTION_CONTENT_GUTTER = 2

PLAN_CHOICES = ("Plan", "Build")
PLAN_OPTIONS_WIDTH = (
    max(len(label) for label in PLAN_CHOICES)
    + (OPTION_HORIZONTAL_PADDING * 2)
    + OPTION_CONTENT_GUTTER
)
COMMAND_MENU_MAX_HEIGHT = 10
INPUT_MAX_HEIGHT = 10
MODIFIER_LATCH_WINDOW = 0.12
VK_SHIFT = 0x10
VK_CONTROL = 0x11
COMMAND_HINTS = {
    "/agent": "Open agent page",
    "/clear": "Reset chat",
    "/comp": "Compact context",
    "/help": "Open help page",
    "/memory": "Open memory page",
    "/quit": "Exit app",
    "/search": "Open web search",
    "/skills": "Open skills page",
    "/team": "Open team page",
}
COMMAND_SUGGESTIONS = [
    (command, COMMAND_HINTS.get(command, str(description or "").strip()))
    for command, description in sorted(
        COMMANDS.items(), key=lambda item: str(item[0]).lower()
    )
]

try:
    import ctypes
except ImportError:  # pragma: no cover - only relevant on non-Windows
    ctypes = None


class HalfRowSpacer(Static):
    """A 1-cell-high spacer that visually leaves a half-row gap.
    Reads ``color`` and ``background`` from CSS so different instances can use
    different border colours.
    """

    DEFAULT_CSS = render_css(
        """
    HalfRowSpacer {
        width: 100%;
        height: 1;
        background: $PAGE_BACKGROUND;
        color: $SURFACE_BACKGROUND;
    }
    """
    )

    def render(self):
        width = self.size.width
        if width <= 0:
            return ""
        colour = self.styles.color
        bg = self.styles.background
        return Text(
            "\u2580" * width,
            style=Style(
                color=colour.hex if colour else SURFACE_BACKGROUND,
                bgcolor=bg.hex if bg else PAGE_BACKGROUND,
            ),
        )


class BottomHalfRowSpacer(Static):
    """A 1-cell-high spacer that fills the lower half row."""

    DEFAULT_CSS = render_css(
        """
    BottomHalfRowSpacer {
        width: 100%;
        height: 1;
        background: $PAGE_BACKGROUND;
        color: $SURFACE_BACKGROUND;
    }
    """
    )

    def render(self):
        width = self.size.width
        if width <= 0:
            return ""
        colour = self.styles.color
        bg = self.styles.background
        return Text(
            "\u2584" * width,
            style=Style(
                color=colour.hex if colour else SURFACE_BACKGROUND,
                bgcolor=bg.hex if bg else PAGE_BACKGROUND,
            ),
        )


class CommandMenuRow(Static, can_focus=False):
    """Single command suggestion row with cropped two-tone text."""

    class Hovered(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class Chosen(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, command: str, description: str, index: int) -> None:
        super().__init__("", id=f"command-item-{index}", classes="command-item")
        self.command = str(command)
        self.description = str(description)
        self.index = index

    def render(self) -> Text:
        width = self.size.width
        if width <= 0:
            return Text()
        selected = self.has_class("selected")
        fg_command = PAGE_BACKGROUND if selected else TEXT_PRIMARY
        fg_description = PAGE_BACKGROUND if selected else TEXT_MUTED
        bg = TEXT_PRIMARY if selected else SURFACE_BACKGROUND
        content = Text(no_wrap=True, overflow="crop", style=Style(bgcolor=bg))
        content.append(self.command, style=Style(color=fg_command, bgcolor=bg))
        content.append("  ", style=Style(color=fg_command, bgcolor=bg))
        if self.description:
            content.append(
                self.description, style=Style(color=fg_description, bgcolor=bg)
            )
        content.truncate(width, overflow="crop", pad=True)
        return content

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.post_message(self.Hovered(self.index))
        event.stop()

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Chosen(self.index))
        event.stop()


class MessageTextArea(TextArea):
    BINDINGS = [
        Binding(
            "ctrl+a",
            "select_all",
            "Select all",
            show=False,
            priority=True,
        ),
        Binding(
            "shift+enter",
            "chat_insert_newline",
            "Insert newline",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+enter",
            "chat_insert_newline",
            "Insert newline",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+shift+enter",
            "chat_submit",
            "Submit message",
            show=False,
            priority=True,
        ),
    ] + TextArea.BINDINGS

    def __init__(self, owner: ChatInput, text: str = "", **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._owner = owner
        self._handling_paste = False
        self._last_paste_text = ""
        self._last_paste_at = 0.0

    async def _on_key(self, event: events.Key) -> None:
        if self._is_undo_granularity_key(event):
            self.history.checkpoint()
        if self._owner._handle_message_key(event, self):
            return
        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        if self._is_duplicate_paste(event.text):
            event.stop()
            return
        self._handling_paste = True
        try:
            await super()._on_paste(event)
            self._remember_paste(event.text)
        finally:
            self._handling_paste = False

    def action_paste(self) -> None:
        clipboard = str(self.app.clipboard or "")
        if self._is_duplicate_paste(clipboard):
            return
        super().action_paste()
        self._remember_paste(clipboard)

    def action_cursor_up(self, select: bool = False) -> None:
        if self._owner._handle_command_menu_navigation(-1):
            return
        super().action_cursor_up(select=select)

    def action_cursor_down(self, select: bool = False) -> None:
        if self._owner._handle_command_menu_navigation(1):
            return
        super().action_cursor_down(select=select)

    def action_chat_insert_newline(self) -> None:
        self._owner._insert_message_newline(self)

    def action_chat_submit(self) -> None:
        self._owner._submit_message_input()

    def _replace_via_keyboard(self, insert: str, start, end):
        if (
            not self._handling_paste
            and start == end
            and self._is_duplicate_paste(insert)
        ):
            return None
        if (
            not self._handling_paste
            and start == end
            and len(insert) > 1
            and "\n" not in insert
        ):
            result = None
            cursor = start
            for character in insert:
                self.history.checkpoint()
                result = self.replace(
                    character,
                    cursor,
                    cursor,
                    maintain_selection_offset=False,
                )
                cursor = result.end_location
            return result
        return super()._replace_via_keyboard(insert, start, end)

    def _is_undo_granularity_key(self, event: events.Key) -> bool:
        if not self.selection.is_empty:
            return True
        key = str(event.key or "")
        if event.is_printable:
            return True
        if key in {"enter", "ctrl+j", "ctrl+m"}:
            return True
        aliases = {str(alias) for alias in getattr(event, "aliases", []) or []}
        return "newline" in aliases

    def _remember_paste(self, text: str) -> None:
        self._last_paste_text = str(text or "")
        self._last_paste_at = perf_counter()

    def _is_duplicate_paste(self, text: str) -> bool:
        text = str(text or "")
        if not text:
            return False
        return (
            text == self._last_paste_text
            and (perf_counter() - self._last_paste_at) <= 0.3
        )

    def render_line(self, y: int):
        if y == 0 and not self.text:
            width = max(1, self.size.width)
            hint = "Type a message..."
            placeholder_style = Style(color=TEXT_MUTED, bgcolor=SURFACE_BACKGROUND)
            padded_hint = hint[:width].ljust(width)
            theme = self._theme
            if theme:
                theme.apply_css(self)
                draw_cursor = self.has_focus and (
                    not self.cursor_blink or self._cursor_visible
                )
                if draw_cursor and theme.cursor_style:
                    return Strip(
                        [
                            Segment(padded_hint[:1], theme.cursor_style),
                            Segment(padded_hint[1:], placeholder_style),
                        ],
                        cell_length=width,
                    )
            return Strip([Segment(padded_hint, placeholder_style)], cell_length=width)
        return super().render_line(y)


class ChatInput(Widget):
    """Chat input bar with config-driven model/thinking selectors."""

    DEFAULT_CSS = render_css(
        """
    ChatInput {
        width: 100%;
        min-width: 44;
        max-width: 78;
        height: auto;
        padding: 0;
        margin: 0;
        background: $PAGE_BACKGROUND;
    }
    ChatInput.stretch {
        width: 100%;
    }

    ChatInput > #input-area {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 1 1 0 1;
    }

    #message-row {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        background: $SURFACE_BACKGROUND;
    }

    #command-menu-shell {
        display: none;
        width: 100%;
        height: auto;
        background: $PAGE_BACKGROUND;
        padding: 0;
        margin: 0;
    }
    #command-menu-shell.open {
        display: block;
    }

    #command-menu {
        width: 100%;
        height: auto;
        max-height: 10;
        background: $SURFACE_BACKGROUND;
        padding: 0 1 0 1;
        margin: 0;
        overflow-y: auto;
        scrollbar-size: 0 0;
        scrollbar-gutter: auto;
        scrollbar-color: transparent;
        scrollbar-background: transparent;
        scrollbar-color-active: transparent;
        scrollbar-color-hover: transparent;
        scrollbar-background-active: transparent;
        scrollbar-background-hover: transparent;
    }

    #command-menu-top-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #command-menu CommandMenuRow {
        width: 100%;
        height: 1;
        min-height: 1;
        padding: 0 1;
        margin: 0;
        background: $SURFACE_BACKGROUND;
    }
    #command-menu CommandMenuRow.selected {
        background: $TEXT_PRIMARY;
    }
    #command-menu CommandMenuRow.hidden {
        display: none;
    }

    #controls-row {
        width: 100%;
        height: 1;
        align-horizontal: left;
    }

    #message-input {
        width: 100%;
        height: 1;
        max-height: 10;
        border: none;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 1;
        scrollbar-size: 0 0;
        & .text-area--cursor-line {
            background: $SURFACE_BACKGROUND;
        }
        & .text-area--selection {
            background: $TEXT_PRIMARY;
            color: $SURFACE_BACKGROUND;
        }
    }
    #message-input:focus {
        border: none;
        background: $SURFACE_BACKGROUND;
    }

    #input-area Button {
        min-width: 1;
        height: 1;
        margin: 0;
        border: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_MUTED;
        padding: 0;
        text-align: left;
    }
    #input-area Button:focus,
    #input-area Button:hover,
    #input-area Button.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }

    /* dropdown wrappers */
    #plan-drop, #approval-drop, #model-drop, #thinking-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
    }
    #approval-drop.hidden {
        display: none;
    }

    /* dropdown triggers */
    #plan-trigger, #approval-trigger, #model-trigger, #thinking-trigger {
        width: auto;
        height: 1;
        background: transparent;
        border: none;
        color: $TEXT_MUTED;
        margin: 0;
        padding: 0 1;
        text-align: left;
        content-align: left middle;
    }
    #input-area #model-trigger,
    #input-area #model-trigger:hover,
    #input-area #model-trigger:focus,
    #input-area #model-trigger.-active {
        color: $TEXT_PRIMARY;
    }

    /* dropdown option panels */
    #plan-options, #approval-options, #model-options, #thinking-options {
        display: none;
        width: auto;
        min-width: 0;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
        padding: 0;
        overlay: screen;
        constrain: none inside;
        align-horizontal: left;
    }
    #plan-options.open, #approval-options.open, #model-options.open, #thinking-options.open {
        display: block;
    }

    #plan-options Button, #approval-options Button, #model-options Button, #thinking-options Button {
        width: 100%;
        height: 1;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        border: none;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
        padding: 0 0;
        margin: 0;
    }
    #plan-options Button:hover, #approval-options Button:hover, #model-options Button:hover, #thinking-options Button:hover,
    #plan-options Button:focus, #approval-options Button:focus, #model-options Button:focus, #thinking-options Button:focus,
    #plan-options Button.-active, #approval-options Button.-active, #model-options Button.-active, #thinking-options Button.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $PAGE_BACKGROUND;
    }

    #plan-trigger.mode-plan,
    #plan-opt-plan {
        color: $PLAN_MODE;
    }
    #plan-trigger.mode-build,
    #plan-opt-build {
        color: $BUILD_MODE;
    }
    #approval-trigger.level-approve,
    #approval-approve {
        color: $APPROVE_FOR_ME;
    }
    #approval-trigger.level-full,
    #approval-full {
        color: $FULL_ACCESS;
    }

    #chat-input-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $INFO_BAR_BACKGROUND;
    }

    """
    )

    plan_mode = reactive(True)
    chat_active = reactive(False)
    allow_model_change = reactive(True)
    controls_locked = reactive(False)
    model_options: list[tuple[str, str]] = []
    thinking_options: list[tuple[str, str]] = THINKING_LEVELS.copy()
    selected_model_value = reactive("")
    selected_thinking_value = reactive("medium")
    selected_approval_value = reactive("confirm")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._command_selection_index = 0
        self._visible_command_suggestions = list(COMMAND_SUGGESTIONS)
        self._last_shift_down_at = 0.0
        self._last_ctrl_down_at = 0.0
        self._modifier_timer = None
        self._model_button_values: dict[str, str] = {}
        self._model_dropdown_serial = 0

    class Send(Message):
        def __init__(self, content: str) -> None:
            super().__init__()
            self.content = content

    class ModelChanged(Message):
        def __init__(self, label: str, value: str) -> None:
            super().__init__()
            self.label = label
            self.value = value

    class ThinkingChanged(Message):
        def __init__(self, label: str, value: str) -> None:
            super().__init__()
            self.label = label
            self.value = value

    class PlanModeChanged(Message):
        def __init__(self, enabled: bool) -> None:
            super().__init__()
            self.enabled = enabled

    class ApprovalChanged(Message):
        def __init__(self, label: str, value: str) -> None:
            super().__init__()
            self.label = label
            self.value = value

    def on_mount(self) -> None:
        self._set_options_width("plan", PLAN_OPTIONS_WIDTH)
        self._rebuild_dropdown(
            "approval", APPROVAL_LEVELS, self.selected_approval_value
        )
        self._rebuild_dropdown(
            "thinking", self.thinking_options, self.selected_thinking_value
        )
        self._fit_trigger_to_label("plan")
        self._set_approval_level(self.selected_approval_value)
        self._update_plan_build()
        if os.name == "nt":
            self._modifier_timer = self.set_interval(0.02, self._sample_modifier_keys)
        self.call_after_refresh(self._update_input_height)

    def on_unmount(self) -> None:
        if self._modifier_timer is not None:
            self._modifier_timer.pause()

    def compose(self) -> ComposeResult:
        with Vertical(id="command-menu-shell"):
            yield BottomHalfRowSpacer(id="command-menu-top-edge")
            yield VerticalScroll(id="command-menu")
        with Vertical(id="input-area"):
            with Horizontal(id="message-row"):
                yield MessageTextArea(
                    self,
                    "",
                    id="message-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                )

            with Horizontal(id="controls-row"):
                # Plan/Build toggle dropdown
                with Container(id="plan-drop"):
                    yield Button("Plan", id="plan-trigger")
                    with Container(id="plan-options"):
                        yield Button("Plan", id="plan-opt-plan")
                        yield Button("Build", id="plan-opt-build")

                # Approval dropdown
                with Container(id="approval-drop"):
                    yield Button("Ask for approval", id="approval-trigger")
                    yield Container(id="approval-options")

                # Model dropdown
                with Container(id="model-drop"):
                    yield Button("No model", id="model-trigger")
                    yield Container(id="model-options")

                # Thinking dropdown
                with Container(id="thinking-drop"):
                    yield Button("Medium", id="thinking-trigger")
                    yield Container(id="thinking-options")

        yield HalfRowSpacer(id="chat-input-bottom-edge")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "plan-opt-plan":
            if self.controls_locked:
                return
            self._set_plan_mode(True)
        elif btn_id == "plan-opt-build":
            if self.controls_locked:
                return
            self._set_plan_mode(False)

        elif btn_id == "plan-trigger":
            if self.controls_locked:
                return
            self._toggle_dropdown("plan-options")
        elif btn_id == "approval-trigger":
            if self.controls_locked:
                return
            self._toggle_dropdown("approval-options")
        elif btn_id == "model-trigger":
            if not self.allow_model_change or self.controls_locked:
                return
            self._toggle_dropdown("model-options")
        elif btn_id == "thinking-trigger":
            if self.controls_locked:
                return
            self._toggle_dropdown("thinking-options")

        elif btn_id and btn_id.startswith("approval-"):
            value = btn_id.removeprefix("approval-")
            self.selected_approval_value = value
            self._set_approval_level(value)
            self._select_dropdown_option("approval", str(event.button.label))
            self.post_message(self.ApprovalChanged(str(event.button.label), value))
        elif btn_id and btn_id.startswith("model-option-"):
            value = self._model_button_values.get(btn_id, "")
            if not value:
                return
            self.selected_model_value = value
            self._select_dropdown_option("model", str(event.button.label))
            self.post_message(self.ModelChanged(str(event.button.label), value))
        elif btn_id and btn_id.startswith("model-"):
            value = btn_id.removeprefix("model-")
            self.selected_model_value = value
            self._select_dropdown_option("model", str(event.button.label))
            self.post_message(self.ModelChanged(str(event.button.label), value))
        elif btn_id and btn_id.startswith("thinking-"):
            value = btn_id.removeprefix("thinking-")
            self.selected_thinking_value = value
            self._select_dropdown_option("thinking", str(event.button.label))
            self.post_message(self.ThinkingChanged(str(event.button.label), value))

    def on_command_menu_row_hovered(self, event: CommandMenuRow.Hovered) -> None:
        if self._is_command_menu_open():
            self._set_command_selection(event.index, scroll=False)
        event.stop()

    def on_command_menu_row_chosen(self, event: CommandMenuRow.Chosen) -> None:
        if self._is_command_menu_open():
            self._set_command_selection(event.index)
            self._execute_selected_command()
        event.stop()

    def _set_plan_mode(self, plan: bool) -> None:
        self.plan_mode = plan
        trigger = self.query_one("#plan-trigger", Button)
        trigger.label = "Plan" if plan else "Build"
        trigger.remove_class("mode-plan")
        trigger.remove_class("mode-build")
        trigger.add_class("mode-plan" if plan else "mode-build")
        self._fit_trigger_to_label("plan")
        self._close_all_dropdowns()
        self.post_message(self.PlanModeChanged(plan))

    def _set_options_width(self, prefix: str, width: int) -> None:
        options = self.query_one(f"#{prefix}-options", Container)
        options.styles.width = width
        options.styles.min_width = width

    def _fit_trigger_to_label(self, prefix: str) -> None:
        drop = self.query_one(f"#{prefix}-drop", Container)
        trigger = self.query_one(f"#{prefix}-trigger", Button)
        label_width = len(str(trigger.label)) + (TRIGGER_HORIZONTAL_PADDING * 2)
        drop.styles.width = label_width
        trigger.styles.width = label_width

    def _set_approval_level(self, level: str) -> None:
        trigger = self.query_one("#approval-trigger", Button)
        for css_class in ("level-approve", "level-full"):
            trigger.remove_class(css_class)
        if level == "approve":
            trigger.add_class("level-approve")
        elif level == "full":
            trigger.add_class("level-full")
        self._fit_trigger_to_label("approval")

    def _toggle_dropdown(self, options_id: str) -> None:
        options = self.query_one(f"#{options_id}", Container)
        if options.has_class("open"):
            options.remove_class("open")
        else:
            self._hide_command_menu()
            self._close_all_dropdowns()
            self._close_project_picker()
            options.add_class("open")

    def _close_project_picker(self) -> None:
        try:
            picker = self.app.query_one("#project-picker")
            picker._close_dropdown()
        except Exception:
            pass

    def _close_all_dropdowns(self) -> None:
        for oid in (
            "plan-options",
            "approval-options",
            "model-options",
            "thinking-options",
        ):
            try:
                opt = self.query_one(f"#{oid}", Container)
                opt.remove_class("open")
            except Exception:
                pass

    def _select_dropdown_option(self, prefix: str, label: str) -> None:
        trigger_id = f"{prefix}-trigger"
        trigger = self.query_one(f"#{trigger_id}", Button)
        trigger.label = str(label)
        self._fit_trigger_to_label(prefix)
        self._close_all_dropdowns()

    def on_text_area_changed(self, event) -> None:
        if getattr(getattr(event, "text_area", None), "id", None) != "message-input":
            return
        self._refresh_command_menu(event.text_area.text)
        self.call_after_refresh(self._update_input_height)

    def _do_send(self) -> None:
        msg_input = self._message_input()
        content = msg_input.text.strip()
        if content:
            self.post_message(self.Send(content))
            msg_input.load_text("")
            self._hide_command_menu()

    def watch_plan_mode(self, value: bool) -> None:
        self._update_plan_build()

    def _update_plan_build(self) -> None:
        try:
            trigger = self.query_one("#plan-trigger", Button)
            approval = self.query_one("#approval-drop", Container)
            if self.plan_mode:
                trigger.label = "Plan"
                trigger.remove_class("mode-build")
                trigger.add_class("mode-plan")
                approval.add_class("hidden")
            else:
                trigger.label = "Build"
                trigger.remove_class("mode-plan")
                trigger.add_class("mode-build")
                approval.remove_class("hidden")
            self._fit_trigger_to_label("plan")
        except Exception:
            pass

    def set_model_options(self, options, selected_value=""):
        self.model_options = [
            (str(label), str(value)) for label, value in options or []
        ]
        self.selected_model_value = str(
            selected_value or self.selected_model_value or ""
        )
        if self.is_mounted:
            self._rebuild_dropdown(
                "model", self.model_options, self.selected_model_value
            )

    def set_selected_model(self, selected_value):
        self.selected_model_value = str(selected_value or "")
        if self.is_mounted:
            self._update_dropdown_trigger(
                "model",
                self.model_options,
                self.selected_model_value,
                empty_label="No model",
            )

    def set_selected_thinking(self, selected_value):
        self.selected_thinking_value = str(selected_value or "medium")
        if self.is_mounted:
            self._rebuild_dropdown(
                "thinking", self.thinking_options, self.selected_thinking_value
            )

    def set_selected_approval(self, selected_value):
        self.selected_approval_value = str(selected_value or "confirm")
        if self.is_mounted:
            self._rebuild_dropdown(
                "approval", APPROVAL_LEVELS, self.selected_approval_value
            )
            self._set_approval_level(self.selected_approval_value)

    def set_model_change_allowed(self, allowed):
        self.allow_model_change = bool(allowed)
        if not self.is_mounted:
            return
        trigger = self.query_one("#model-trigger", Button)
        if self.allow_model_change:
            trigger.remove_class("disabled")
        else:
            self._close_all_dropdowns()

    def set_controls_locked(self, locked: bool) -> None:
        self.controls_locked = bool(locked)
        if not self.is_mounted:
            return
        if self.controls_locked:
            self._close_all_dropdowns()
            self._hide_command_menu()

    def _is_command_mode(self, value: str) -> bool:
        text = str(value or "")
        if not text.startswith("/"):
            return False
        return not any(char.isspace() for char in text[1:])

    def _refresh_command_menu(self, value: str) -> None:
        if not self.is_mounted or not self._is_command_mode(value):
            self._visible_command_suggestions = list(COMMAND_SUGGESTIONS)
            self._sync_command_rows()
            self._hide_command_menu()
            return
        token = str(value or "").lower()
        self._visible_command_suggestions = [
            (command, description)
            for command, description in COMMAND_SUGGESTIONS
            if command.lower().startswith(token)
        ]
        self._ensure_command_rows()
        self._sync_command_rows()
        if not self._visible_command_suggestions:
            self._hide_command_menu()
            return
        self._close_all_dropdowns()
        self._close_project_picker()
        self._show_command_menu()
        self._set_command_selection(self._suggested_command_index(value))

    def _ensure_command_rows(self) -> None:
        menu = self.query_one("#command-menu", VerticalScroll)
        if list(self.query("#command-menu CommandMenuRow")):
            return
        for index, (command, description) in enumerate(COMMAND_SUGGESTIONS):
            menu.mount(CommandMenuRow(command, description, index))
        self._set_command_selection(0, scroll=False)

    def _sync_command_rows(self) -> None:
        visible_commands = {
            command: index
            for index, (command, _) in enumerate(self._visible_command_suggestions)
        }
        for row in self.query("#command-menu CommandMenuRow"):
            visible_index = visible_commands.get(row.command)
            if visible_index is None:
                row.index = -1
                row.add_class("hidden")
                row.remove_class("selected")
            else:
                row.index = visible_index
                row.remove_class("hidden")
            row.refresh()

    def _show_command_menu(self) -> None:
        self.query_one("#command-menu-shell", Vertical).add_class("open")

    def _hide_command_menu(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#command-menu-shell", Vertical).remove_class("open")
        menu = self.query_one("#command-menu", VerticalScroll)
        menu.scroll_to(y=0, animate=False)

    def _is_command_menu_open(self) -> bool:
        if not self.is_mounted:
            return False
        return self.query_one("#command-menu-shell", Vertical).has_class("open")

    def _move_command_selection(self, step: int) -> None:
        if not self._visible_command_suggestions:
            return
        count = len(self._visible_command_suggestions)
        next_index = (self._command_selection_index + step) % count
        self._set_command_selection(next_index)

    def _set_command_selection(self, index: int, scroll: bool = True) -> None:
        if not self._visible_command_suggestions:
            self._command_selection_index = 0
            return
        index = max(0, min(index, len(self._visible_command_suggestions) - 1))
        self._command_selection_index = index
        for row in self.query("#command-menu CommandMenuRow"):
            if row.index == index:
                row.add_class("selected")
            else:
                row.remove_class("selected")
            row.refresh()
        if scroll:
            max_top = max(
                0, len(self._visible_command_suggestions) - COMMAND_MENU_MAX_HEIGHT
            )
            top = min(max(0, index - (COMMAND_MENU_MAX_HEIGHT - 1)), max_top)
            self.query_one("#command-menu", VerticalScroll).scroll_to(
                y=top, animate=False
            )

    def _suggested_command_index(self, value: str) -> int:
        token = str(value or "").lower()
        for index, (command, _) in enumerate(self._visible_command_suggestions):
            if command.startswith(token):
                return index
        return 0

    def _execute_selected_command(self) -> None:
        if not self._visible_command_suggestions:
            return
        command = self._visible_command_suggestions[self._command_selection_index][0]
        msg_input = self._message_input()
        msg_input.load_text("")
        self._visible_command_suggestions = list(COMMAND_SUGGESTIONS)
        self._sync_command_rows()
        self._hide_command_menu()
        self.post_message(self.Send(command))

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_input_height)

    def _message_input(self) -> MessageTextArea:
        return self.query_one("#message-input", MessageTextArea)

    def _handle_command_menu_navigation(self, step: int) -> bool:
        if not self._is_command_menu_open():
            return False
        self._move_command_selection(step)
        return True

    def _handle_message_key(
        self, event: events.Key, text_area: MessageTextArea
    ) -> bool:
        key = str(event.key or "")
        aliases = {str(alias) for alias in getattr(event, "aliases", []) or []}
        parts = key.split("+")
        normalized_enter = key in {"enter", "ctrl+j", "ctrl+m"} or "newline" in aliases
        if not normalized_enter and parts[-1] != "enter":
            return False
        modifiers = (
            set()
            if normalized_enter and key in {"ctrl+j", "ctrl+m"} | aliases
            else set(parts[:-1])
        )
        if os.name == "nt":
            ctrl_recent = self._ctrl_modifier_active()
            shift_recent = self._shift_modifier_active(ctrl_recent)
            if shift_recent:
                modifiers.add("shift")
            if ctrl_recent:
                modifiers.add("ctrl")
        if modifiers in ({"shift"}, {"ctrl"}):
            event.stop()
            event.prevent_default()
            self._insert_message_newline(text_area)
            return True
        if modifiers in (set(), {"ctrl", "shift"}):
            event.stop()
            event.prevent_default()
            self._submit_message_input()
            return True
        return False

    def _insert_message_newline(self, text_area: MessageTextArea | None = None) -> None:
        target = text_area or self._message_input()
        start, end = target.selection
        target._replace_via_keyboard("\n", start, end)
        self.call_after_refresh(self._update_input_height)

    def _submit_message_input(self) -> None:
        if self._is_command_menu_open():
            self._execute_selected_command()
        else:
            self._do_send()

    def _update_input_height(self) -> None:
        if not self.is_mounted:
            return
        text_area = self._message_input()
        width = max(1, text_area.content_region.width)
        lines = str(text_area.text or "").split("\n") or [""]
        height = 0
        for line in lines:
            line_width = max(1, cell_len(line))
            height += max(1, (line_width + width - 1) // width)
        text_area.styles.height = max(1, min(INPUT_MAX_HEIGHT, height))

    def _sample_modifier_keys(self) -> None:
        now = perf_counter()
        if _windows_key_down(VK_SHIFT):
            self._last_shift_down_at = now
        if _windows_key_down(VK_CONTROL):
            self._last_ctrl_down_at = now

    def _ctrl_modifier_active(self) -> bool:
        now = perf_counter()
        return _windows_key_down(VK_CONTROL) or (
            now - self._last_ctrl_down_at <= MODIFIER_LATCH_WINDOW
        )

    def _shift_modifier_active(self, ctrl_active: bool = False) -> bool:
        if _windows_key_down(VK_SHIFT):
            return True
        if not ctrl_active:
            return False
        now = perf_counter()
        return now - self._last_shift_down_at <= MODIFIER_LATCH_WINDOW

    def _rebuild_dropdown(self, prefix, options, selected_value):
        trigger = self.query_one(f"#{prefix}-trigger", Button)
        container = self.query_one(f"#{prefix}-options", Container)
        normalized = [(str(label), str(value)) for label, value in options or []]
        desired_ids = [f"{prefix}-{value}" for _, value in normalized]
        existing_ids = [child.id for child in container.children]
        if not normalized:
            if prefix == "model":
                trigger.label = "No model"
                self._fit_trigger_to_label(prefix)
            return

        if existing_ids == desired_ids:
            self._update_dropdown_trigger(prefix, normalized, selected_value)
            return

        container.remove_children()

        max_width = (
            max(len(label) for label, _ in normalized)
            + (OPTION_HORIZONTAL_PADDING * 2)
            + OPTION_CONTENT_GUTTER
        )
        self._set_options_width(prefix, max_width)
        selected_label = normalized[0][0]
        if prefix == "model":
            self._model_dropdown_serial += 1
            self._model_button_values = {}
        for index, (label, value) in enumerate(normalized):
            button_id = f"{prefix}-{value}"
            if prefix == "model":
                button_id = f"model-option-{self._model_dropdown_serial}-{index}"
                self._model_button_values[button_id] = value
            button = Button(label, id=button_id)
            container.mount(button)
            if value == selected_value:
                selected_label = label
        trigger.label = selected_label
        self._fit_trigger_to_label(prefix)

    def _update_dropdown_trigger(self, prefix, options, selected_value, empty_label=""):
        trigger = self.query_one(f"#{prefix}-trigger", Button)
        normalized = [(str(label), str(value)) for label, value in options or []]
        if not normalized:
            if empty_label:
                trigger.label = empty_label
                self._fit_trigger_to_label(prefix)
            return
        selected_label = normalized[0][0]
        for label, value in normalized:
            if value == selected_value:
                selected_label = label
                break
        trigger.label = selected_label
        self._fit_trigger_to_label(prefix)


def _windows_key_down(virtual_key: int) -> bool:
    if os.name != "nt" or ctypes is None:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)
    except Exception:
        return False
