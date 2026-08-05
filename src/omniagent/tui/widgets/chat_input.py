from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
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

from ...i18n import display_width, fit_to_width, t
from ...commands import COMMANDS
from ...references import resolve_references
from ..data import approval_levels, thinking_levels
from ..theme import (
    PAGE_BACKGROUND,
    REFERENCE_BACKGROUND,
    SURFACE_BACKGROUND,
    TEXT_MUTED,
    TEXT_PRIMARY,
    render_css,
)

TRIGGER_HORIZONTAL_PADDING = 1
OPTION_HORIZONTAL_PADDING = 0
OPTION_CONTENT_GUTTER = 2

COMMAND_MENU_MAX_HEIGHT = 10
INPUT_MAX_HEIGHT = 10
MAX_PENDING_MESSAGES = 5
MODIFIER_LATCH_WINDOW = 0.12
VK_SHIFT = 0x10
VK_CONTROL = 0x11
COMMAND_HINT_KEYS = {
    "/agent": "input.cmd_hint.agent",
    "/clear": "input.cmd_hint.clear",
    "/comp": "input.cmd_hint.comp",
    "/help": "input.cmd_hint.help",
    "/memory": "input.cmd_hint.memory",
    "/quit": "input.cmd_hint.quit",
    "/search": "input.cmd_hint.search",
    "/skills": "input.cmd_hint.skills",
    "/team": "input.cmd_hint.team",
}


# The English defaults callers still hand us; treated as "unset" so the
# localized label wins. An explicit, caller-authored label passes through.
_DEFAULT_CUSTOM_LABEL = "Type your own answer"
_DEFAULT_CUSTOM_PLACEHOLDER = "Type your own answer..."


def prompt_custom_label(value: str = "") -> str:
    text = str(value or "")
    if not text or text == _DEFAULT_CUSTOM_LABEL:
        return t("input.custom_answer_label")
    return text


def prompt_custom_placeholder(value: str = "") -> str:
    text = str(value or "")
    if not text or text == _DEFAULT_CUSTOM_PLACEHOLDER:
        return t("input.custom_answer_placeholder")
    return text


def plan_choices() -> tuple[str, str]:
    """(Plan, Build) mode labels for the active language."""
    return (t("input.mode.plan"), t("input.mode.build"))


def plan_options_width() -> int:
    return (
        max(display_width(label) for label in plan_choices())
        + (OPTION_HORIZONTAL_PADDING * 2)
        + OPTION_CONTENT_GUTTER
    )


def command_suggestions() -> list[tuple[str, str]]:
    """Command menu rows resolved against the active language."""
    return [
        (
            command,
            t(COMMAND_HINT_KEYS[command])
            if command in COMMAND_HINT_KEYS
            else str(description or "").strip(),
        )
        for command, description in sorted(
            COMMANDS.items(), key=lambda item: str(item[0]).lower()
        )
    ]


@dataclass
class InputReference:
    start: int
    end: int
    syntax: str


@dataclass
class PendingMessageEntry:
    message_id: int
    content: str
    display_content: str


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


class PromptOptionRow(Static, can_focus=False):
    class Selected(Message):
        def __init__(self, index: int | None, is_custom: bool = False) -> None:
            super().__init__()
            self.index = index
            self.is_custom = is_custom

    def __init__(
        self,
        title: str,
        detail: str,
        index: int | None,
        is_custom: bool = False,
        recommended: bool = False,
    ) -> None:
        super().__init__("", classes="prompt-option")
        self.title = str(title or "")
        self.detail = str(detail or "")
        self.index = index
        self.is_custom = bool(is_custom)
        self.recommended = bool(recommended)
        self.is_selected = False

    def set_selected(self, selected: bool) -> None:
        self.is_selected = bool(selected)
        self.refresh()

    def render(self) -> Text:
        width = max(1, self.size.width)
        marker = "●" if self.is_selected else "○"
        title = self.title
        if self.recommended:
            title = t("input.option_recommended", title=title)
        prefix = f"  {marker} "
        prefix_style = Style(color=TEXT_PRIMARY, bgcolor=SURFACE_BACKGROUND)
        title_style = Style(color=TEXT_PRIMARY, bgcolor=SURFACE_BACKGROUND)
        detail_style = Style(color=TEXT_MUTED, bgcolor=SURFACE_BACKGROUND)
        content = Text()
        first_line = Text(no_wrap=True, overflow="crop")
        first_line.append(prefix, style=prefix_style)
        first_line.append(title, style=title_style)
        first_line.truncate(width, overflow="crop", pad=True)
        content.append_text(first_line)
        if self.detail:
            content.append("\n")
            second_line = Text(no_wrap=True, overflow="crop")
            second_line.append(" " * len(prefix), style=prefix_style)
            second_line.append(self.detail, style=detail_style)
            second_line.truncate(width, overflow="crop", pad=True)
            content.append_text(second_line)
        return content

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Selected(self.index, is_custom=self.is_custom))
        event.stop()


class PendingMessageRow(Static, can_focus=False):
    class Selected(Message):
        def __init__(self, message_id: int) -> None:
            super().__init__()
            self.message_id = int(message_id)

    def __init__(self, message_id: int, text: str) -> None:
        super().__init__("", classes="pending-item")
        self.message_id = int(message_id)
        self.label_text = str(text or "")

    def render(self) -> Text:
        width = max(1, self.size.width)
        display_text = " ".join(self.label_text.splitlines())
        content = Text(no_wrap=True, overflow="crop")
        content.append(
            display_text,
            style=Style(color=TEXT_PRIMARY, bgcolor=SURFACE_BACKGROUND),
        )
        content.truncate(width, overflow="crop", pad=True)
        return content

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Selected(self.message_id))
        event.stop()


class PendingSendButton(Button):
    def __init__(self, message_id: int) -> None:
        super().__init__("↑", classes="pending-send")
        self.message_id = int(message_id)


class PendingDeleteButton(Button):
    def __init__(self, message_id: int) -> None:
        super().__init__("×", classes="pending-delete")
        self.message_id = int(message_id)


class ModelGroupToggle(Static, can_focus=False):
    pass


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
        self._input_references = []
        self._normalizing_references = False
        self._suppress_placeholder = False
        self._placeholder_background = SURFACE_BACKGROUND
        self.pending_message_id: int | None = None

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
        self._owner._submit_text_area(self)

    def _replace_via_keyboard(self, insert: str, start, end):
        start, end = self._expand_reference_locations(start, end, False)
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

    def _delete_via_keyboard(self, start, end):
        start, end = self._expand_reference_locations(start, end)
        return super()._delete_via_keyboard(start, end)

    def replace(self, insert, start, end, *, maintain_selection_offset=True):
        start_offset = self._location_to_offset(start)
        end_offset = self._location_to_offset(end)
        result = super().replace(
            insert,
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )
        if not self._normalizing_references:
            self._update_reference_offsets(start_offset, end_offset, len(insert))
        return result

    def load_text(self, text: str) -> None:
        self._input_references = []
        super().load_text(text)

    def normalize_references(self, base_dir=None) -> None:
        if self._normalizing_references:
            return
        existing_ranges = [(item.start, item.end) for item in self._input_references]
        references = [
            reference
            for reference in resolve_references(self.text, base_dir)
            if not any(
                reference.start < end and reference.end > start
                for start, end in existing_ranges
            )
        ]
        if not references:
            return
        self._normalizing_references = True
        try:
            for reference in reversed(references):
                replacement = f" {reference.display} "
                start = self._offset_to_location(reference.start)
                end = self._offset_to_location(reference.end)
                super().replace(
                    replacement,
                    start,
                    end,
                    maintain_selection_offset=False,
                )
                self._update_reference_offsets(
                    reference.start, reference.end, len(replacement)
                )
                self._input_references.append(
                    InputReference(
                        reference.start,
                        reference.start + len(replacement),
                        reference.syntax,
                    )
                )
            self._input_references.sort(key=lambda item: item.start)
        finally:
            self._normalizing_references = False
        line_cache = getattr(self, "_line_cache", None)
        if line_cache is not None:
            line_cache.clear()
        self.refresh()

    def serialized_text(self) -> str:
        value = self.text
        for reference in reversed(self._input_references):
            value = value[: reference.start] + reference.syntax + value[reference.end :]
        return value

    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        line_start = self._location_to_offset((line_index, 0))
        line_end = line_start + len(self.document.get_line(line_index))
        for reference in self._input_references:
            if reference.start >= line_start and reference.end <= line_end:
                line.stylize(
                    Style(color=TEXT_PRIMARY, bgcolor=REFERENCE_BACKGROUND),
                    reference.start - line_start,
                    reference.end - line_start,
                )
        return line

    def _expand_reference_locations(self, start, end, include_boundaries=True):
        start_offset = self._location_to_offset(start)
        end_offset = self._location_to_offset(end)
        low, high = sorted((start_offset, end_offset))
        for reference in self._input_references:
            touches = low < reference.end and high > reference.start
            at_left = include_boundaries and low == high == reference.start
            at_right = include_boundaries and low == high == reference.end
            if touches or at_left or at_right:
                low = min(low, reference.start)
                high = max(high, reference.end)
        if start_offset <= end_offset:
            return self._offset_to_location(low), self._offset_to_location(high)
        return self._offset_to_location(high), self._offset_to_location(low)

    def _update_reference_offsets(self, start, end, inserted_length):
        delta = inserted_length - (end - start)
        updated = []
        for reference in self._input_references:
            if reference.end <= start:
                updated.append(reference)
            elif reference.start >= end:
                updated.append(
                    InputReference(
                        reference.start + delta,
                        reference.end + delta,
                        reference.syntax,
                    )
                )
        self._input_references = updated

    def _location_to_offset(self, location):
        row, column = location
        lines = self.text.split("\n")
        return sum(len(line) + 1 for line in lines[:row]) + column

    def _offset_to_location(self, offset):
        remaining = max(0, offset)
        lines = self.text.split("\n")
        for row, line in enumerate(lines):
            if remaining <= len(line):
                return row, remaining
            remaining -= len(line) + 1
        return len(lines) - 1, len(lines[-1])

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
            hint = (
                ""
                if self._suppress_placeholder
                else self._owner.input_placeholder(self)
            )
            placeholder_style = Style(
                color=TEXT_MUTED,
                bgcolor=self._placeholder_background,
            )
            # Must be cell-accurate: Strip below declares cell_length=width,
            # and CJK placeholders occupy two cells per glyph.
            padded_hint = fit_to_width(hint, width)
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
        min-width: 0;
        max-width: 78;
        height: auto;
        padding: 0;
        margin: 0;
        background: $PAGE_BACKGROUND;
    }
    ChatInput.stretch {
        width: 100%;
    }
    ChatInput.prompt-mode #prompt-shell {
        display: block;
    }
    ChatInput.prompt-mode > #input-area {
        padding: 0;
    }
    ChatInput.prompt-mode #controls-row {
        display: none;
    }
    ChatInput.prompt-mode.prompt-no-input #message-row {
        display: none;
        padding: 0;
    }
    ChatInput.prompt-mode #message-row {
        padding: 0 2 0 4;
    }
    ChatInput.prompt-mode #message-input {
        padding: 0;
    }
    ChatInput.prompt-separated-options #prompt-options {
        margin-top: 1;
    }
    ChatInput.prompt-separated-options #prompt-question {
        min-height: 1;
    }

    ChatInput > #input-area {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 1 1 0 1;
    }

    #prompt-shell {
        display: none;
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0;
    }
    #prompt-top-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }
    #prompt-progress {
        width: 100%;
        color: $TEXT_PRIMARY;
        padding: 0 2;
    }
    #prompt-question {
        width: 100%;
        min-height: 2;
        height: auto;
        color: $TEXT_PRIMARY;
        margin-top: 1;
        margin-bottom: 0;
        padding: 0 2;
    }
    #prompt-options {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        margin-top: 0;
    }
    #prompt-options PromptOptionRow {
        width: 100%;
        height: auto;
        min-height: 1;
        background: $SURFACE_BACKGROUND;
        padding: 0;
        margin: 0;
    }

    #message-row {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        background: $SURFACE_BACKGROUND;
    }

    #pending-shell {
        display: none;
        width: 100%;
        height: auto;
        margin: 0;
        background: $SURFACE_BACKGROUND;
        padding: 0 1 0 1;
    }
    #pending-top-gap {
        display: none;
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }
    ChatInput.todo-visible #pending-top-gap {
        color: $SURFACE_BACKGROUND;
    }
    #pending-top-gap.visible {
        display: block;
    }
    #pending-shell.visible {
        display: block;
    }
    ChatInput.prompt-mode #pending-top-gap,
    ChatInput.prompt-mode #pending-shell {
        display: none;
    }
    #pending-list {
        width: 100%;
        height: auto;
        max-height: 5;
        background: transparent;
        overflow-y: hidden;
    }
    #pending-list .pending-row {
        width: 100%;
        height: 1;
        min-height: 1;
        background: $SURFACE_BACKGROUND;
    }
    #pending-list PendingMessageRow {
        width: 1fr;
        height: 1;
        min-height: 1;
        padding: 0 1;
        background: $SURFACE_BACKGROUND;
    }
    #pending-list #pending-empty {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: $SURFACE_BACKGROUND;
        padding: 0 1;
    }
    #pending-list MessageTextArea {
        width: 1fr;
        height: 1;
        min-height: 1;
        max-height: 1;
        border: none;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        overflow-y: hidden;
        scrollbar-size: 0 0;
        & .text-area--cursor-line {
            background: $SURFACE_BACKGROUND;
        }
        & .text-area--selection {
            background: $TEXT_PRIMARY;
            color: $SURFACE_BACKGROUND;
        }
    }
    #pending-list MessageTextArea:focus {
        border: none;
        background: $SURFACE_BACKGROUND;
    }
    #pending-list .pending-delete {
        min-width: 3;
        height: 1;
        padding: 0;
        margin: 0;
        border: none;
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $SURFACE_BACKGROUND;
        text-align: center;
        content-align: center middle;
    }
    #pending-list .pending-send {
        width: 3;
        min-width: 3;
        height: 1;
        padding: 0;
        margin: 0 1 0 0;
        border: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
        text-align: center;
        content-align: center middle;
    }
    #pending-list .pending-delete:hover,
    #pending-list .pending-delete:focus,
    #pending-list .pending-delete.-active,
    #pending-list .pending-send:hover,
    #pending-list .pending-send:focus,
    #pending-list .pending-send.-active {
        border: none;
    }
    #pending-list .pending-delete:hover,
    #pending-list .pending-delete:focus,
    #pending-list .pending-delete.-active {
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $SURFACE_BACKGROUND;
    }
    #pending-list .pending-send:hover,
    #pending-list .pending-send:focus,
    #pending-list .pending-send.-active {
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }
    #pending-list .pending-delete:disabled,
    #pending-list .pending-send:disabled {
        color: $TEXT_MUTED;
    }
    #pending-list .pending-send:disabled {
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_MUTED;
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
    #add-reference {
        width: 3;
        min-width: 3;
        padding: 0;
        color: $TEXT_PRIMARY;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        text-align: left;
        content-align: left middle;
        border: none;
        border-top: none;
        border-bottom: none;
        outline: none;
        text-style: none;
    }
    #add-reference:hover,
    #add-reference:focus,
    #add-reference.-active {
        color: $TEXT_PRIMARY;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        content-align: left middle;
        border: none;
        border-top: none;
        border-bottom: none;
        outline: none;
        text-style: none;
    }
    #input-area #add-reference,
    #input-area #add-reference:hover,
    #input-area #add-reference:focus,
    #input-area #add-reference.-active {
        color: $TEXT_PRIMARY;
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
    #plan-drop.hidden,
    #approval-drop.hidden {
        display: none;
    }

    /* dropdown triggers */
    #plan-trigger, #approval-trigger, #model-trigger, #thinking-trigger {
        width: auto;
        /* Textual's Button defaults to min-width: 16. _fit_trigger_to_label
           computes narrower widths for short labels (common in Chinese), and
           without this the button stays 16 cells and overflows its drop. */
        min-width: 0;
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
    #model-options {
        max-height: 12;
        overflow-y: auto;
        scrollbar-size: 0 0;
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
    #model-options .model-group-toggle {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        padding: 0 1 0 1;
        content-align: left middle;
    }
    #model-options .model-group-toggle:hover {
        color: $TEXT_PRIMARY;
    }
    #model-options .model-group-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }
    #model-options .model-group-list {
        width: 100%;
        height: auto;
    }
    #model-options .model-group-list.hidden {
        display: none;
    }
    #model-options Button.model-option-item {
        padding: 0 0 0 0;
    }
    #model-options Button.model-option-item.selected,
    #model-options Button.model-option-item.selected:focus,
    #model-options Button.model-option-item.selected.-active {
        color: $TEXT_PRIMARY;
        text-style: bold;
    }
    #model-options Button.model-option-item.selected:hover {
        background: $TEXT_PRIMARY;
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
    project_selected = reactive(False)
    allow_model_change = reactive(True)
    controls_locked = reactive(False)
    prompt_active = reactive(False)
    model_options: list[tuple[str, str]] = []
    selected_model_value = reactive("")
    selected_thinking_value = reactive("medium")
    selected_approval_value = reactive("confirm")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Resolved per instance, not at class level, so a language switch
        # re-labels the dropdown.
        self.thinking_options: list[tuple[str, str]] = thinking_levels()
        self._command_selection_index = 0
        self._visible_command_suggestions = command_suggestions()
        self._last_shift_down_at = 0.0
        self._last_ctrl_down_at = 0.0
        self._modifier_timer = None
        self._model_button_values: dict[str, str] = {}
        self._model_dropdown_serial = 0
        self._model_option_groups: list[dict[str, object]] = []
        self._collapsed_model_groups: set[str] = set()
        self._model_group_button_keys: dict[str, str] = {}
        self._model_group_button_list_ids: dict[str, str] = {}
        self._prompt_question = ""
        self._prompt_options: list[tuple[str, str, bool]] = []
        self._prompt_current_index = 1
        self._prompt_total = 1
        self._prompt_allow_custom = False
        self._prompt_custom_label = prompt_custom_label()
        self._prompt_custom_placeholder = prompt_custom_placeholder()
        self._prompt_selected_option_index: int | None = None
        self._prompt_custom_selected = False
        self._prompt_saved_text = ""
        self._prompt_syncing = False
        self._pending_messages: list[PendingMessageEntry] = []
        self._next_pending_message_id = 1
        self._editing_pending_message_id: int | None = None
        self._chat_busy = False
        self._suggested_input = ""
        self._input_revision = 0

    class Send(Message):
        def __init__(self, content: str, display_content: str | None = None) -> None:
            super().__init__()
            self.content = content
            self.display_content = (
                content if display_content is None else display_content
            )

    class ReferenceRequested(Message):
        pass

    class DirectSendRequested(Message):
        def __init__(self, content: str, display_content: str | None = None) -> None:
            super().__init__()
            self.content = content
            self.display_content = (
                content if display_content is None else display_content
            )

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

    class PromptStateChanged(Message):
        def __init__(self, can_submit: bool) -> None:
            super().__init__()
            self.can_submit = bool(can_submit)

    class PromptSubmitRequested(Message):
        pass

    def on_mount(self) -> None:
        self._set_options_width("plan", plan_options_width())
        self._rebuild_dropdown(
            "approval", approval_levels(), self.selected_approval_value
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
        self.call_after_refresh(self._update_pending_shell)

    def on_unmount(self) -> None:
        if self._modifier_timer is not None:
            self._modifier_timer.pause()

    def compose(self) -> ComposeResult:
        with Vertical(id="command-menu-shell"):
            yield BottomHalfRowSpacer(id="command-menu-top-edge")
            yield VerticalScroll(id="command-menu")
        yield BottomHalfRowSpacer(id="pending-top-gap")
        with Horizontal(id="pending-shell"):
            yield Vertical(id="pending-list")
        with Vertical(id="input-area"):
            with Vertical(id="prompt-shell"):
                yield BottomHalfRowSpacer(id="prompt-top-edge")
                yield Static("", id="prompt-progress")
                yield Static("", id="prompt-question")
                yield Vertical(id="prompt-options")
            with Horizontal(id="message-row"):
                yield MessageTextArea(
                    self,
                    "",
                    id="message-input",
                    soft_wrap=True,
                    show_line_numbers=False,
                )

            with Horizontal(id="controls-row"):
                yield Button("+", id="add-reference")
                # Plan/Build toggle dropdown
                plan_label, build_label = plan_choices()
                with Container(id="plan-drop"):
                    yield Button(plan_label, id="plan-trigger")
                    with Container(id="plan-options"):
                        yield Button(plan_label, id="plan-opt-plan")
                        yield Button(build_label, id="plan-opt-build")

                # Approval dropdown
                with Container(id="approval-drop"):
                    yield Button(t("input.approval.confirm"), id="approval-trigger")
                    yield Container(id="approval-options")

                # Model dropdown
                with Container(id="model-drop"):
                    yield Button(t("input.no_model"), id="model-trigger")
                    yield Container(id="model-options")

                # Thinking dropdown
                with Container(id="thinking-drop"):
                    yield Button(t("input.thinking.medium"), id="thinking-trigger")
                    yield Container(id="thinking-options")

        yield HalfRowSpacer(id="chat-input-bottom-edge")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if isinstance(event.button, PendingSendButton):
            self._request_direct_send_for_message(event.button.message_id)
        elif isinstance(event.button, PendingDeleteButton):
            self._remove_pending_message(event.button.message_id)
        elif btn_id == "add-reference":
            if not self.controls_locked and not self.prompt_active:
                self.post_message(self.ReferenceRequested())
        elif btn_id == "plan-opt-plan":
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

    def on_click(self, event: events.Click) -> None:
        control = getattr(event, "control", None) or getattr(event, "widget", None)
        while control is not None:
            control_id = getattr(control, "id", None)
            if control_id and str(control_id).startswith("model-group-toggle-"):
                if not self.controls_locked:
                    self._toggle_model_group(str(control_id))
                event.stop()
                return
            control = getattr(control, "parent", None)

    def on_command_menu_row_chosen(self, event: CommandMenuRow.Chosen) -> None:
        if self._is_command_menu_open():
            self._set_command_selection(event.index)
            self._execute_selected_command()
        event.stop()

    def on_prompt_option_row_selected(self, event: PromptOptionRow.Selected) -> None:
        if not self.prompt_active:
            return
        if event.is_custom:
            self._select_prompt_custom(focus=True)
        else:
            self._select_prompt_option(event.index)
        event.stop()

    def on_pending_message_row_selected(
        self, event: PendingMessageRow.Selected
    ) -> None:
        self._start_pending_edit(event.message_id)
        event.stop()

    def _set_plan_mode(self, plan: bool) -> None:
        self.plan_mode = plan
        plan_label, build_label = plan_choices()
        trigger = self.query_one("#plan-trigger", Button)
        trigger.label = plan_label if plan else build_label
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
        label_width = display_width(str(trigger.label)) + (
            TRIGGER_HORIZONTAL_PADDING * 2
        )
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

    def _toggle_model_group(self, button_id: str) -> None:
        group_key = self._model_group_button_keys.get(button_id, "")
        list_id = self._model_group_button_list_ids.get(button_id, "")
        if not list_id:
            return
        try:
            group_list = self.query_one(f"#{list_id}", Vertical)
        except Exception:
            return
        if group_list.has_class("hidden"):
            group_list.remove_class("hidden")
            self._collapsed_model_groups.discard(group_key)
        else:
            group_list.add_class("hidden")
            self._collapsed_model_groups.add(group_key)

    def on_text_area_changed(self, event) -> None:
        text_area = getattr(event, "text_area", None)
        text_area_id = getattr(text_area, "id", None)
        if getattr(text_area, "pending_message_id", None) is not None:
            self._update_direct_send_button_state()
            return
        if text_area_id != "message-input":
            return
        self._input_revision += 1
        self._clear_suggested_input_state()
        if self.prompt_active:
            if (
                self._prompt_allow_custom
                and not self._prompt_syncing
                and str(event.text_area.text or "").strip()
            ):
                self._select_prompt_custom()
            self._hide_command_menu()
            self.call_after_refresh(self._update_input_height)
            self.post_message(self.PromptStateChanged(self.prompt_can_submit()))
            self._update_direct_send_button_state()
            return
        event.text_area.normalize_references(self.reference_base_dir())
        self._refresh_command_menu(event.text_area.text)
        self.call_after_refresh(self._update_input_height)
        self._update_direct_send_button_state()

    def _do_send(self) -> None:
        if self._chat_busy and len(self._pending_messages) >= MAX_PENDING_MESSAGES:
            self._notify_pending_limit_reached()
            return
        payload = self._take_message_input_payload()
        if payload is None:
            return
        content, display_content = payload
        self.post_message(self.Send(content, display_content))

    def reference_base_dir(self):
        try:
            project = self.app._selected_project()
        except Exception:
            project = None
        return Path(project.path).resolve() if project is not None else None

    def insert_reference(self, reference_type: str, path: str) -> bool:
        syntax = f"[@{reference_type}:{str(path or '').strip()}]"
        target = self._message_input()
        references = resolve_references(syntax, self.reference_base_dir())
        if (
            len(references) != 1
            or references[0].start != 0
            or references[0].end != len(syntax)
        ):
            return False
        start, end = target._expand_reference_locations(*target.selection)
        target.history.checkpoint()
        target.replace(syntax, start, end, maintain_selection_offset=False)
        target.normalize_references(self.reference_base_dir())
        target.focus()
        self.call_after_refresh(self._update_input_height)
        return True

    def watch_plan_mode(self, value: bool) -> None:
        self._update_plan_build()

    def _update_plan_build(self) -> None:
        try:
            plan_drop = self.query_one("#plan-drop", Container)
            trigger = self.query_one("#plan-trigger", Button)
            approval = self.query_one("#approval-drop", Container)
            if self.project_selected:
                plan_drop.remove_class("hidden")
            else:
                plan_drop.add_class("hidden")
                approval.add_class("hidden")
                self._close_all_dropdowns()
                self._fit_trigger_to_label("plan")
                return
            plan_label, build_label = plan_choices()
            if self.plan_mode:
                trigger.label = plan_label
                trigger.remove_class("mode-build")
                trigger.add_class("mode-plan")
                approval.add_class("hidden")
            else:
                trigger.label = build_label
                trigger.remove_class("mode-plan")
                trigger.add_class("mode-build")
                approval.remove_class("hidden")
            self._fit_trigger_to_label("plan")
        except Exception:
            pass

    def set_model_options(self, options, selected_value="", groups=None):
        self.model_options = [
            (str(label), str(value)) for label, value in options or []
        ]
        self._model_option_groups = self._normalize_model_groups(
            self.model_options, groups
        )
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
            self._rebuild_dropdown(
                "model", self.model_options, self.selected_model_value
            )

    def set_selected_thinking(self, selected_value):
        available_values = [value for _, value in self.thinking_options]
        fallback = (
            "medium"
            if "medium" in available_values
            else (available_values[0] if available_values else "none")
        )
        selected = str(selected_value or fallback)
        if selected not in available_values:
            selected = fallback
        self.selected_thinking_value = selected
        if self.is_mounted:
            self._rebuild_dropdown(
                "thinking", self.thinking_options, self.selected_thinking_value
            )

    def set_thinking_options(self, options):
        normalized = [(str(label), str(value)) for label, value in list(options or [])]
        if not normalized:
            normalized = thinking_levels()
        self.thinking_options = normalized
        self.set_selected_thinking(self.selected_thinking_value)

    def set_selected_approval(self, selected_value):
        self.selected_approval_value = str(selected_value or "confirm")
        if self.is_mounted:
            self._rebuild_dropdown(
                "approval", approval_levels(), self.selected_approval_value
            )
            self._set_approval_level(self.selected_approval_value)

    def set_project_selected(self, selected: bool) -> None:
        self.project_selected = bool(selected)
        if self.is_mounted:
            self._update_plan_build()

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

    def relabel_for_language(self) -> None:
        """Re-resolve every label this widget cached at compose time.

        Trigger widths are refit because CJK labels need roughly twice the
        cells of their English equivalents.
        """
        if not self.is_mounted:
            return
        self.thinking_options = thinking_levels()
        self._rebuild_dropdown(
            "approval", approval_levels(), self.selected_approval_value
        )
        self._rebuild_dropdown(
            "thinking", self.thinking_options, self.selected_thinking_value
        )
        self._sync_thinking_trigger_label()
        self._sync_approval_trigger_label()
        # _update_plan_build re-resolves the Plan/Build label and refits the
        # trigger without posting PlanModeChanged, which _set_plan_mode would.
        self._set_options_width("plan", plan_options_width())
        self._update_plan_build()
        self._set_approval_level(self.selected_approval_value)
        self._visible_command_suggestions = command_suggestions()
        self._ensure_command_rows()
        self._sync_command_rows()
        try:
            editor = self.query_one("#message-input", MessageTextArea)
        except Exception:
            editor = None
        if editor is not None:
            editor.refresh()

    def _sync_thinking_trigger_label(self) -> None:
        label = next(
            (
                text
                for text, value in self.thinking_options
                if value == self.selected_thinking_value
            ),
            "",
        )
        if not label:
            return
        trigger = self.query_one("#thinking-trigger", Button)
        trigger.label = label
        self._fit_trigger_to_label("thinking")

    def _sync_approval_trigger_label(self) -> None:
        label = next(
            (
                text
                for text, value in approval_levels()
                if value == self.selected_approval_value
            ),
            "",
        )
        if not label:
            return
        trigger = self.query_one("#approval-trigger", Button)
        trigger.label = label
        self._fit_trigger_to_label("approval")

    def _is_command_mode(self, value: str) -> bool:
        text = str(value or "")
        if not text.startswith("/"):
            return False
        return not any(char.isspace() for char in text[1:])

    def _refresh_command_menu(self, value: str) -> None:
        if not self.is_mounted or not self._is_command_mode(value):
            self._visible_command_suggestions = command_suggestions()
            self._sync_command_rows()
            self._hide_command_menu()
            return
        token = str(value or "").lower()
        self._visible_command_suggestions = [
            (command, description)
            for command, description in command_suggestions()
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
        for index, (command, description) in enumerate(command_suggestions()):
            menu.mount(CommandMenuRow(command, description, index))
        self._set_command_selection(0, scroll=False)

    def _sync_command_rows(self) -> None:
        visible_commands = {
            command: index
            for index, (command, _) in enumerate(self._visible_command_suggestions)
        }
        # Descriptions are re-read so a language switch reaches mounted rows.
        descriptions = dict(command_suggestions())
        for row in self.query("#command-menu CommandMenuRow"):
            row.description = descriptions.get(row.command, row.description)
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
        self._visible_command_suggestions = command_suggestions()
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
        if key == "tab" or "tab" in aliases:
            if self._accept_suggested_input(text_area):
                event.stop()
                event.prevent_default()
                return True
            return False
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
            self._submit_text_area(text_area)
            return True
        return False

    def _insert_message_newline(self, text_area: MessageTextArea | None = None) -> None:
        target = text_area or self._message_input()
        start, end = target.selection
        target._replace_via_keyboard("\n", start, end)
        self.call_after_refresh(self._update_input_height)

    def _submit_text_area(self, text_area: MessageTextArea | None = None) -> None:
        target = text_area or self._message_input()
        if target.pending_message_id is not None:
            self._commit_pending_edit()
            return
        self._submit_message_input()

    def _submit_message_input(self) -> None:
        if self.prompt_active:
            if self.prompt_can_submit():
                self.post_message(self.PromptSubmitRequested())
            return
        if self._is_command_menu_open():
            self._execute_selected_command()
        else:
            self._do_send()

    def _update_input_height(self) -> None:
        if not self.is_mounted:
            return
        text_area = self._message_input()
        horizontal_padding = int(text_area.styles.padding.left or 0) + int(
            text_area.styles.padding.right or 0
        )
        width = max(1, text_area.content_region.width - horizontal_padding)
        lines = str(text_area.text or "").split("\n") or [""]
        height = 0
        for line in lines:
            line_width = max(1, cell_len(line))
            height += max(1, (line_width + width - 1) // width)
        text_area.styles.height = max(1, min(INPUT_MAX_HEIGHT, height))

    def _take_message_input_payload(self) -> tuple[str, str] | None:
        msg_input = self._message_input()
        content = msg_input.serialized_text().strip()
        if not content:
            return None
        display_content = msg_input.text.strip()
        msg_input.load_text("")
        self._hide_command_menu()
        self.call_after_refresh(self._update_input_height)
        self._update_direct_send_button_state()
        return content, display_content

    def _has_message_input_payload(self) -> bool:
        msg_input = self._message_input()
        return bool(msg_input.serialized_text().strip())

    def _request_direct_send_for_message(self, message_id: int) -> None:
        payload = self._remove_pending_message(message_id)
        if payload is None:
            return
        self.post_message(self.DirectSendRequested(payload[0], payload[1]))

    def _pending_entry(self, message_id: int) -> PendingMessageEntry | None:
        for entry in self._pending_messages:
            if entry.message_id == message_id:
                return entry
        return None

    def _start_pending_edit(self, message_id: int) -> None:
        if self._pending_entry(message_id) is None:
            return
        self._commit_pending_edit()
        self._editing_pending_message_id = message_id
        self._rebuild_pending_list()
        self.call_after_refresh(self._focus_pending_editor)

    def _focus_pending_editor(self) -> None:
        if self._editing_pending_message_id is None:
            return
        editor = self._find_pending_editor(self._editing_pending_message_id)
        if editor is None:
            return
        editor.focus()

    def _commit_pending_edit(self) -> None:
        if self._editing_pending_message_id is None or not self.is_mounted:
            return
        editor = self._find_pending_editor(self._editing_pending_message_id)
        if editor is None:
            self._editing_pending_message_id = None
            self._update_pending_shell()
            return
        content = editor.serialized_text().strip()
        display_content = editor.text.strip()
        updated_entries: list[PendingMessageEntry] = []
        for entry in self._pending_messages:
            if entry.message_id != self._editing_pending_message_id:
                updated_entries.append(entry)
                continue
            if content:
                updated_entries.append(
                    PendingMessageEntry(
                        message_id=entry.message_id,
                        content=content,
                        display_content=display_content,
                    )
                )
        self._pending_messages = updated_entries
        self._editing_pending_message_id = None
        self._update_pending_shell()

    def _rebuild_pending_list(self) -> None:
        if not self.is_mounted:
            return
        container = self.query_one("#pending-list", Vertical)
        container.remove_children()
        for entry in self._pending_messages:
            if entry.message_id == self._editing_pending_message_id:
                editor = MessageTextArea(
                    self,
                    entry.content,
                    soft_wrap=False,
                    show_line_numbers=False,
                    classes="pending-editor",
                )
                editor.pending_message_id = entry.message_id
                editor._suppress_placeholder = True
                editor._placeholder_background = SURFACE_BACKGROUND
                editor.normalize_references(self.reference_base_dir())
                container.mount(
                    Horizontal(
                        editor,
                        PendingSendButton(entry.message_id),
                        PendingDeleteButton(entry.message_id),
                        classes="pending-row",
                    )
                )
            else:
                container.mount(
                    Horizontal(
                        PendingMessageRow(entry.message_id, entry.display_content),
                        PendingSendButton(entry.message_id),
                        PendingDeleteButton(entry.message_id),
                        classes="pending-row",
                    )
                )

    def _find_pending_editor(self, message_id: int) -> MessageTextArea | None:
        for editor in self.query("#pending-list MessageTextArea"):
            if getattr(editor, "pending_message_id", None) == message_id:
                return editor
        return None

    def _ensure_ui_thread(self, callback, *args) -> bool:
        if threading.current_thread() is threading.main_thread():
            return True
        if not self.is_mounted:
            return False
        try:
            self.app.call_from_thread(callback, *args)
        except Exception:
            return False
        return False

    def _update_pending_shell(self) -> None:
        if not self.is_mounted:
            return
        top_gap = self.query_one("#pending-top-gap", BottomHalfRowSpacer)
        shell = self.query_one("#pending-shell", Horizontal)
        show_shell = bool(self._pending_messages) and not self.prompt_active
        if show_shell:
            top_gap.add_class("visible")
            shell.add_class("visible")
        else:
            top_gap.remove_class("visible")
            shell.remove_class("visible")
            self._editing_pending_message_id = None
        self._rebuild_pending_list()
        self._update_direct_send_button_state()

    def set_todo_visible(self, visible: bool) -> None:
        self.set_class(bool(visible), "todo-visible")
        self._update_pending_shell()

    def _update_direct_send_button_state(self) -> None:
        return

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
        if prefix == "model":
            self._rebuild_model_dropdown(container, trigger, normalized, selected_value)
            return
        desired_ids = [f"{prefix}-{value}" for _, value in normalized]
        existing_ids = [child.id for child in container.children]
        if not normalized:
            if prefix == "model":
                trigger.label = t("input.no_model")
                self._fit_trigger_to_label(prefix)
            return

        if existing_ids == desired_ids:
            # Option ids derive from values, which are language-independent, so
            # a relabel lands here with the buttons already mounted. Their text
            # still has to be refreshed.
            self._sync_dropdown_option_labels(prefix, container, normalized)
            self._update_dropdown_trigger(prefix, normalized, selected_value)
            return

        if existing_ids:
            await_remove = container.remove_children()
            self._update_dropdown_trigger(prefix, normalized, selected_value)
            self.run_worker(
                partial(
                    self._remount_dropdown_after_remove,
                    prefix,
                    normalized,
                    str(selected_value or ""),
                    await_remove,
                ),
                name=f"{prefix}-dropdown-rebuild",
                group=f"chat-input-{prefix}-dropdown",
                exit_on_error=False,
                exclusive=True,
            )
            return

        self._mount_dropdown_buttons(
            prefix, container, trigger, normalized, str(selected_value or "")
        )

    def _mount_dropdown_buttons(
        self,
        prefix: str,
        container: Container,
        trigger: Button,
        normalized: list[tuple[str, str]],
        selected_value: str,
    ) -> None:
        max_width = (
            max(display_width(label) for label, _ in normalized)
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

    async def _remount_dropdown_after_remove(
        self,
        prefix: str,
        normalized: list[tuple[str, str]],
        selected_value: str,
        await_remove,
    ) -> None:
        await await_remove
        if not self.is_mounted:
            return
        try:
            trigger = self.query_one(f"#{prefix}-trigger", Button)
            container = self.query_one(f"#{prefix}-options", Container)
        except Exception:
            return
        self._mount_dropdown_buttons(
            prefix, container, trigger, normalized, selected_value
        )

    def _normalize_model_groups(self, options, groups=None) -> list[dict[str, object]]:
        normalized_groups: list[dict[str, object]] = []
        for group in list(groups or []):
            group_options = [
                (str(label), str(value))
                for label, value in list(group.get("options") or [])
            ]
            if not group_options:
                continue
            normalized_groups.append({
                "provider": str(group.get("provider") or ""),
                "title": str(group.get("title") or "") or t("input.model_group.other"),
                "options": group_options,
            })
        if normalized_groups:
            return normalized_groups
        normalized_options = [
            (str(label), str(value)) for label, value in options or []
        ]
        if not normalized_options:
            return []
        return [
            {
                "provider": "",
                "title": t("input.model_group.models"),
                "options": normalized_options,
            }
        ]

    def _rebuild_model_dropdown(
        self,
        container: Container,
        trigger: Button,
        options: list[tuple[str, str]],
        selected_value: str,
    ) -> None:
        if not options:
            trigger.label = t("input.no_model")
            self._fit_trigger_to_label("model")
            return

        groups = self._normalize_model_groups(options, self._model_option_groups)
        selected_label = options[0][0]
        selected_group_key = ""
        for group in groups:
            for label, value in list(group.get("options") or []):
                if value == selected_value:
                    selected_label = label
                    selected_group_key = str(group.get("provider") or "")
                    break
            if selected_group_key:
                break
        if selected_group_key:
            self._collapsed_model_groups.discard(selected_group_key)

        max_width = 0
        for group in groups:
            max_width = max(max_width, cell_len(str(group.get("title") or "")) + 2)
            for label, _ in list(group.get("options") or []):
                max_width = max(max_width, cell_len(str(label)) + 2)
        self._set_options_width("model", max_width)

        container.remove_children()
        self._model_dropdown_serial += 1
        serial = self._model_dropdown_serial
        self._model_button_values = {}
        self._model_group_button_keys = {}
        self._model_group_button_list_ids = {}
        option_index = 0

        for group_index, group in enumerate(groups):
            if group_index > 0:
                container.mount(Static("", classes="model-group-gap"))
            title = str(group.get("title") or "") or t("input.model_group.other")
            group_key = str(group.get("provider") or "")
            button_id = f"model-group-toggle-{serial}-{group_index}"
            list_id = f"model-group-list-{serial}-{group_index}"
            self._model_group_button_keys[button_id] = group_key
            self._model_group_button_list_ids[button_id] = list_id
            container.mount(
                ModelGroupToggle(title, id=button_id, classes="model-group-toggle")
            )

            list_classes = "model-group-list"
            if group_key in self._collapsed_model_groups:
                list_classes += " hidden"
            group_list = Vertical(id=list_id, classes=list_classes)
            container.mount(group_list)

            for label, value in list(group.get("options") or []):
                item_id = f"model-option-{serial}-{option_index}"
                self._model_button_values[item_id] = value
                classes = "model-option-item"
                if value == selected_value:
                    classes += " selected"
                group_list.mount(Button(label, id=item_id, classes=classes))
                option_index += 1

        trigger.label = selected_label
        self._fit_trigger_to_label("model")

    @staticmethod
    def _sync_dropdown_option_labels(prefix, container, normalized) -> None:
        """Refresh mounted option labels in place, matching on widget id."""
        by_id = {str(child.id): child for child in container.children if child.id}
        for label, value in normalized:
            child = by_id.get(f"{prefix}-{value}")
            if child is not None and str(getattr(child, "label", "")) != label:
                child.label = label

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

    def input_placeholder(self, text_area: MessageTextArea | None = None) -> str:
        if self.prompt_active and self._prompt_allow_custom:
            return self._prompt_custom_placeholder
        if self._suggested_input:
            return self._suggested_input
        return t("input.placeholder")

    def input_revision(self) -> int:
        return self._input_revision

    def suggested_input(self) -> str:
        return self._suggested_input

    def set_suggested_input(
        self,
        suggestion: str,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        if threading.current_thread() is not threading.main_thread():
            if not self.is_mounted:
                return False
            try:
                self.app.call_from_thread(
                    partial(
                        self.set_suggested_input,
                        suggestion,
                        expected_revision=expected_revision,
                    )
                )
            except Exception:
                return False
            return False
        normalized = " ".join(
            line.strip()
            for line in str(suggestion or "").splitlines()
            if line.strip()
        )
        if not normalized or self.prompt_active:
            return False
        if (
            expected_revision is not None
            and self._input_revision != expected_revision
        ):
            return False
        text_area = self._message_input()
        if str(text_area.text or "") or text_area.pending_message_id is not None:
            return False
        self._suggested_input = normalized
        text_area.refresh()
        return True

    def clear_suggested_input(self) -> None:
        if not self._ensure_ui_thread(self.clear_suggested_input):
            return
        self._clear_suggested_input_state()

    def _clear_suggested_input_state(self) -> None:
        if not self._suggested_input:
            return
        self._suggested_input = ""
        if self.is_mounted:
            self._message_input().refresh()

    def _accept_suggested_input(self, text_area: MessageTextArea) -> bool:
        if (
            self.prompt_active
            or text_area is not self._message_input()
            or str(text_area.text or "")
            or not self._suggested_input
        ):
            return False
        suggestion = self._suggested_input
        self._suggested_input = ""
        text_area.load_text(suggestion)
        lines = suggestion.split("\n")
        text_area.move_cursor((len(lines) - 1, len(lines[-1])))
        self.call_after_refresh(self._update_input_height)
        return True

    def set_chat_busy(self, busy: bool) -> None:
        if not self._ensure_ui_thread(self.set_chat_busy, busy):
            return
        self._chat_busy = bool(busy)
        if self._chat_busy:
            self._clear_suggested_input_state()
        self._update_pending_shell()

    def has_pending_messages(self) -> bool:
        return bool(self._pending_messages)

    def pending_message_count(self) -> int:
        return len(self._pending_messages)

    def clear_pending_messages(self) -> None:
        if not self._ensure_ui_thread(self.clear_pending_messages):
            return
        self._pending_messages = []
        self._editing_pending_message_id = None
        self._update_pending_shell()

    def enqueue_pending_message(
        self, content: str, display_content: str | None = None
    ) -> None:
        if not self._ensure_ui_thread(
            self.enqueue_pending_message,
            content,
            display_content,
        ):
            return
        normalized_content = str(content or "").strip()
        normalized_display = (
            normalized_content
            if display_content is None
            else str(display_content or "").strip()
        )
        if not normalized_content:
            return
        if len(self._pending_messages) >= MAX_PENDING_MESSAGES:
            self._notify_pending_limit_reached()
            return
        self._pending_messages.append(
            PendingMessageEntry(
                message_id=self._next_pending_message_id,
                content=normalized_content,
                display_content=normalized_display,
            )
        )
        self._next_pending_message_id += 1
        self._editing_pending_message_id = None
        self._update_pending_shell()

    def pop_next_pending_message(self) -> tuple[str, str] | None:
        self._commit_pending_edit()
        if not self._pending_messages:
            self._update_pending_shell()
            return None
        entry = self._pending_messages.pop(0)
        if self._editing_pending_message_id == entry.message_id:
            self._editing_pending_message_id = None
        self._update_pending_shell()
        return entry.content, entry.display_content

    def _remove_pending_message(self, message_id: int) -> tuple[str, str] | None:
        self._commit_pending_edit()
        for index, entry in enumerate(self._pending_messages):
            if entry.message_id != message_id:
                continue
            removed = self._pending_messages.pop(index)
            if self._editing_pending_message_id == removed.message_id:
                self._editing_pending_message_id = None
            self._update_pending_shell()
            return removed.content, removed.display_content
        self._update_pending_shell()
        return None

    def _notify_pending_limit_reached(self) -> None:
        try:
            self.app.add_status_message(
                "[!]",
                t("input.pending_limit", limit=MAX_PENDING_MESSAGES),
            )
        except Exception:
            pass

    def set_prompt_state(
        self,
        *,
        active: bool,
        current_index: int = 1,
        total: int = 1,
        question: str = "",
        options: list[tuple[str, str, bool]] | None = None,
        allow_custom: bool = False,
        separate_options: bool = False,
        selected_option_index: int | None = None,
        custom_selected: bool = False,
        custom_value: str = "",
        custom_label: str = "",
        custom_placeholder: str = "",
    ) -> None:
        msg_input = self._message_input()
        if active and not self.prompt_active:
            self._prompt_saved_text = str(msg_input.text or "")
        if not active:
            self.prompt_active = False
            self.remove_class("prompt-mode")
            self.remove_class("prompt-separated-options")
            self.remove_class("prompt-no-input")
            self._prompt_question = ""
            self._prompt_options = []
            self._prompt_allow_custom = False
            self._prompt_selected_option_index = None
            self._prompt_custom_selected = False
            self._prompt_syncing = True
            msg_input.load_text(self._prompt_saved_text)
            self._prompt_syncing = False
            self.query_one("#prompt-progress", Static).update("")
            self.query_one("#prompt-question", Static).update("")
            self.query_one("#prompt-options", Vertical).remove_children()
            self._update_pending_shell()
            self.call_after_refresh(self._update_input_height)
            return

        self.prompt_active = True
        self.add_class("prompt-mode")
        self.set_class(bool(separate_options), "prompt-separated-options")
        self._close_all_dropdowns()
        self._hide_command_menu()
        self._prompt_current_index = max(1, int(current_index or 1))
        self._prompt_total = max(self._prompt_current_index, int(total or 1))
        self._prompt_question = str(question or "")
        self._prompt_options = [
            (
                str(title or ""),
                str(detail or ""),
                bool(recommended),
            )
            for title, detail, recommended in (options or [])
        ]
        self._prompt_allow_custom = bool(allow_custom)
        self._prompt_custom_label = prompt_custom_label(custom_label)
        self._prompt_custom_placeholder = prompt_custom_placeholder(custom_placeholder)
        recommended_index = next(
            (
                index
                for index, (_, _, recommended) in enumerate(self._prompt_options)
                if recommended
            ),
            None,
        )
        if selected_option_index is not None and 0 <= int(selected_option_index) < len(
            self._prompt_options
        ):
            self._prompt_selected_option_index = int(selected_option_index)
            self._prompt_custom_selected = False
        elif recommended_index is not None:
            self._prompt_selected_option_index = recommended_index
            self._prompt_custom_selected = False
        else:
            self._prompt_selected_option_index = None
            self._prompt_custom_selected = bool(
                self._prompt_allow_custom
                and (custom_selected or not self._prompt_options)
            )

        self.query_one("#prompt-progress", Static).update(
            t(
                "input.prompt_progress",
                current=self._prompt_current_index,
                total=self._prompt_total,
            )
        )
        self.query_one("#prompt-question", Static).update(self._prompt_question)
        self._rebuild_prompt_options()

        self._prompt_syncing = True
        msg_input.load_text(str(custom_value or ""))
        self._prompt_syncing = False
        if self._prompt_allow_custom:
            self.remove_class("prompt-no-input")
        else:
            self.add_class("prompt-no-input")
        self._update_pending_shell()
        self.call_after_refresh(self._update_input_height)
        self.post_message(self.PromptStateChanged(self.prompt_can_submit()))

    def _rebuild_prompt_options(self) -> None:
        container = self.query_one("#prompt-options", Vertical)
        container.remove_children()
        for index, (title, detail, recommended) in enumerate(self._prompt_options):
            row = PromptOptionRow(
                title,
                detail,
                index=index,
                recommended=recommended,
            )
            row.set_selected(index == self._prompt_selected_option_index)
            container.mount(row)
        if self._prompt_allow_custom:
            custom_row = PromptOptionRow(
                self._prompt_custom_label,
                "",
                index=None,
                is_custom=True,
            )
            custom_row.set_selected(self._prompt_custom_selected)
            container.mount(custom_row)

    def _select_prompt_option(self, index: int | None) -> None:
        if index is None:
            return
        self._prompt_selected_option_index = int(index)
        self._prompt_custom_selected = False
        self._update_prompt_option_selection()
        self.post_message(self.PromptStateChanged(self.prompt_can_submit()))

    def _select_prompt_custom(self, focus: bool = False) -> None:
        if not self._prompt_allow_custom:
            return
        self._prompt_selected_option_index = None
        self._prompt_custom_selected = True
        self._update_prompt_option_selection()
        if focus:
            self.focus_prompt_input()
        self.post_message(self.PromptStateChanged(self.prompt_can_submit()))

    def _update_prompt_option_selection(self) -> None:
        for row in self.query("#prompt-options PromptOptionRow"):
            if row.is_custom:
                row.set_selected(self._prompt_custom_selected)
            else:
                row.set_selected(row.index == self._prompt_selected_option_index)

    def focus_prompt_input(self) -> None:
        self._message_input().focus()

    def prompt_uses_custom_input(self) -> bool:
        return bool(self._prompt_allow_custom and self._prompt_custom_selected)

    def prompt_can_submit(self) -> bool:
        if not self.prompt_active:
            return False
        if self._prompt_selected_option_index is not None:
            return True
        if self._prompt_allow_custom and self._prompt_custom_selected:
            return bool(str(self._message_input().text or "").strip())
        return False

    def get_prompt_answer(self) -> tuple[int | None, str]:
        if self._prompt_selected_option_index is not None:
            return self._prompt_selected_option_index, ""
        return None, str(self._message_input().text or "").strip()


def _windows_key_down(virtual_key: int) -> bool:
    if os.name != "nt" or ctypes is None:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)
    except Exception:
        return False
