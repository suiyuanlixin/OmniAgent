from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, Container, VerticalScroll
from textual.widgets import Button, Input, Static
from textual.widget import Widget
from textual.message import Message
from textual.reactive import reactive

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
        padding-bottom: 1;
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
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 1;
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

    def compose(self) -> ComposeResult:
        with Vertical(id="command-menu-shell"):
            yield BottomHalfRowSpacer(id="command-menu-top-edge")
            yield VerticalScroll(id="command-menu")
        with Vertical(id="input-area"):
            with Horizontal(id="message-row"):
                yield Input(
                    placeholder="Type a message...",
                    id="message-input",
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message-input":
            if self._is_command_menu_open():
                self._execute_selected_command()
                return
            self._do_send()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "message-input":
            self._refresh_command_menu(event.value)

    def on_key(self, event: events.Key) -> None:
        focused = getattr(self.app, "focused", None)
        if getattr(focused, "id", None) != "message-input":
            return
        if not self._is_command_menu_open():
            return
        if event.key == "up":
            self._move_command_selection(-1)
            event.stop()
        elif event.key == "down":
            self._move_command_selection(1)
            event.stop()

    def _do_send(self) -> None:
        msg_input = self.query_one("#message-input", Input)
        content = msg_input.value.strip()
        if content:
            self.post_message(self.Send(content))
            msg_input.value = ""
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
        return " " not in text.strip()

    def _refresh_command_menu(self, value: str) -> None:
        if not self.is_mounted or not self._is_command_mode(value):
            self._visible_command_suggestions = list(COMMAND_SUGGESTIONS)
            self._sync_command_rows()
            self._hide_command_menu()
            return
        token = str(value or "").strip().lower()
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
        token = str(value or "").strip().lower()
        for index, (command, _) in enumerate(self._visible_command_suggestions):
            if command.startswith(token):
                return index
        return 0

    def _execute_selected_command(self) -> None:
        if not self._visible_command_suggestions:
            return
        command = self._visible_command_suggestions[self._command_selection_index][0]
        msg_input = self.query_one("#message-input", Input)
        msg_input.value = ""
        self._visible_command_suggestions = list(COMMAND_SUGGESTIONS)
        self._sync_command_rows()
        self._hide_command_menu()
        self.post_message(self.Send(command))

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

        for child in list(container.children):
            child.remove()

        max_width = (
            max(len(label) for label, _ in normalized)
            + (OPTION_HORIZONTAL_PADDING * 2)
            + OPTION_CONTENT_GUTTER
        )
        self._set_options_width(prefix, max_width)
        selected_label = normalized[0][0]
        for label, value in normalized:
            button = Button(label, id=f"{prefix}-{value}")
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
