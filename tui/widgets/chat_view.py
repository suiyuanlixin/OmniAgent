from __future__ import annotations

from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual.widget import Widget

from tui.theme import PAGE_BACKGROUND, SURFACE_BACKGROUND, render_css


class ChatView(Widget):
    DEFAULT_CSS = render_css(
        """
    ChatView {
        width: 100%;
        height: 1fr;
        background: $PAGE_BACKGROUND;
    }

    ChatView #chat-log {
        width: 100%;
        height: 1fr;
        background: $PAGE_BACKGROUND;
        padding: 0;
        scrollbar-size: 0 0;
    }

    .message-row {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
    }
    .message-row-user {
        align-horizontal: right;
    }
    .message-row-assistant,
    .message-row-status {
        align-horizontal: left;
    }

    .message-bubble {
        width: auto;
        max-width: 100%;
        height: auto;
        margin: 0;
    }
    .message-half {
        width: 100%;
        height: 1;
        background: $PAGE_BACKGROUND;
    }
    .message-half-user {
        color: $SURFACE_BACKGROUND;
    }
    .message-half-assistant {
        color: $PAGE_BACKGROUND;
    }

    .message-bubble-content {
        width: auto;
        max-width: 100%;
        height: auto;
        min-width: 1;
        min-height: 1;
        padding: 0 1;
        margin: 0;
    }
    .message-bubble-user {
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
    }
    .message-bubble-assistant {
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
    }
    .message-bubble-status {
        background: transparent;
        color: $TEXT_MUTED;
        padding: 0;
    }
    .message-row-assistant .message-bubble-content,
    .message-row-status .message-bubble-content {
        padding: 0;
    }

    .message-spacer {
        width: 100%;
        height: 1;
    }

    ThoughtBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    ThoughtBlock > .thought-toggle {
        width: auto;
        height: 1;
        min-width: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
    }
    ThoughtBlock > .thought-toggle:hover,
    ThoughtBlock > .thought-toggle:focus-within {
        background: transparent;
        color: $TEXT_MUTED;
    }

    ThoughtBlock > .thought-content {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 0 0 0 2;
        color: $TEXT_MUTED;
        background: transparent;
    }
    ThoughtBlock > .thought-content.hidden {
        display: none;
    }

    ExploredBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    ExploredBlock > .explored-toggle {
        width: auto;
        height: 1;
        min-width: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
    }
    ExploredBlock > .explored-toggle:hover,
    ExploredBlock > .explored-toggle:focus-within {
        background: transparent;
        color: $TEXT_MUTED;
    }

    ExploredBlock > .explored-content {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 0 0 0 2;
        color: $TEXT_MUTED;
        background: transparent;
    }
    ExploredBlock > .explored-content.hidden {
        display: none;
    }

    QuestionsBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    QuestionsBlock > .questions-toggle {
        width: auto;
        height: 1;
        min-width: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
    }
    QuestionsBlock > .questions-toggle:hover,
    QuestionsBlock > .questions-toggle:focus-within {
        background: transparent;
        color: $TEXT_MUTED;
    }

    QuestionsBlock > .questions-content {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 0 0 0 2;
        color: $TEXT_MUTED;
        background: transparent;
    }
    QuestionsBlock > .questions-content.hidden {
        display: none;
    }

    .web-summary-entry {
        width: auto;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
    }
    """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._thought_stream_target: ThoughtBlock | None = None
        self._thought_stream_content = ""
        self._explored_block: ExploredBlock | None = None
        self._questions_block: QuestionsBlock | None = None

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-log")

    def add_message(self, role: str, content: str) -> None:
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        if role == "user":
            self.query_one("#chat-log", VerticalScroll).mount(
                Static("", classes="message-spacer")
            )
        row, content_widget = _build_message_widgets(role, content)
        self.query_one("#chat-log", VerticalScroll).mount(row)
        self.call_after_refresh(self._scroll_end)
        self.messages.append((role, content, datetime.now().isoformat()))
        if role == "assistant":
            self._stream_target = content_widget
            self._stream_role = role
            self._stream_content = str(content or "")

    def add_status(self, content: str) -> None:
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        row, _ = _build_message_widgets("status", content)
        self.query_one("#chat-log", VerticalScroll).mount(row)
        self.call_after_refresh(self._scroll_end)

    def start_stream(self, role: str = "assistant", prefix: str = "") -> None:
        if self._stream_target is not None and self._stream_role == role:
            return
        if role == "status":
            row, content_widget = _build_message_widgets("status", prefix)
            self.query_one("#chat-log", VerticalScroll).mount(row)
            self.call_after_refresh(self._scroll_end)
            self._stream_target = content_widget
            self._stream_role = role
            self._stream_content = str(prefix or "")
            return
        self.add_message(role, prefix)
        self._stream_role = role
        self._stream_content = str(prefix or "")

    def append_stream(
        self, content: str, role: str = "assistant", prefix: str = ""
    ) -> None:
        self.start_stream(role=role, prefix=prefix)
        self._stream_content += str(content or "")
        self._stream_target.update(self._stream_content)
        self.call_after_refresh(self._scroll_end)

    def remove_last_messages(self, count: int = 1) -> None:
        count = max(1, int(count or 1))
        log = self.query_one("#chat-log", VerticalScroll)
        children = list(log.children)
        if not children:
            return
        for child in children[-count:]:
            child.remove()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""

    def clear(self) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        log.remove_children()
        self.messages.clear()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._explored_block = None
        self._questions_block = None

    def _scroll_end(self) -> None:
        self.query_one("#chat-log", VerticalScroll).scroll_end(animate=False)

    def add_thought(self, content: str, elapsed_seconds: float = 0.0) -> None:
        block = ThoughtBlock(content=content, elapsed_seconds=elapsed_seconds)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self.call_after_refresh(self._scroll_end)

    def start_thought_stream(self, elapsed_seconds: float = 0.0) -> None:
        if self._thought_stream_target is not None:
            return
        if self._stream_role == "assistant":
            # GLM may interleave thinking and visible text multiple times in one turn.
            # Once a new thought block starts, the next assistant text must mount into
            # a fresh response block instead of reusing the first one.
            self._stream_target = None
            self._stream_role = None
            self._stream_content = ""
        block = ThoughtBlock(content="", elapsed_seconds=elapsed_seconds)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self.call_after_refresh(self._scroll_end)
        self._thought_stream_target = block
        self._thought_stream_content = ""

    def append_thought_stream(self, content: str) -> None:
        self.start_thought_stream()
        self._thought_stream_content += str(content or "")
        if self._thought_stream_target is not None:
            self._thought_stream_target.set_content(self._thought_stream_content)
            self.call_after_refresh(self._scroll_end)

    def finish_thought_stream(self, elapsed_seconds: float = 0.0) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_target.set_elapsed_seconds(elapsed_seconds)
        self._thought_stream_target = None
        self._thought_stream_content = ""

    def update_thought_stream_elapsed(self, elapsed_seconds: float) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_target.set_elapsed_seconds(elapsed_seconds)

    def replace_thought_stream(self, content: str, elapsed_seconds: float) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_content = str(content or "")
        self._thought_stream_target.set_content(self._thought_stream_content)
        self._thought_stream_target.set_elapsed_seconds(
            max(0.0, float(elapsed_seconds or 0.0))
        )
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self.call_after_refresh(self._scroll_end)

    def add_explored_entry(self, tool_name: str, description: str) -> None:
        if self._explored_block is None:
            block = ExploredBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._explored_block = block
        self._explored_block.add_entry(tool_name, description)
        self.call_after_refresh(self._scroll_end)

    def reset_explored(self) -> None:
        self._explored_block = None

    def add_question_entry(self, question: str, answer: str) -> None:
        if self._questions_block is None:
            block = QuestionsBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._questions_block = block
        self._questions_block.add_entry(question, answer)
        self.call_after_refresh(self._scroll_end)

    def _reset_message_stream(self) -> None:
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""

    def add_web_fetch_entry(self, url: str) -> None:
        self._reset_message_stream()
        content = f"→ [white]Webfetch[/white] [gray]{_escape_markup(url)}[/gray]"
        self.query_one("#chat-log", VerticalScroll).mount(
            Static(content, classes="web-summary-entry", markup=True)
        )
        self.call_after_refresh(self._scroll_end)

    def add_web_search_entry(self, content: str) -> None:
        self._reset_message_stream()
        summary = _escape_markup(content)
        self.query_one("#chat-log", VerticalScroll).mount(
            Static(
                f"→ [white]Websearch[/white] [gray]{summary}[/gray]",
                classes="web-summary-entry",
                markup=True,
            )
        )
        self.call_after_refresh(self._scroll_end)

    def reset_turn_summaries(self) -> None:
        self._explored_block = None
        self._questions_block = None


def _build_message_widgets(role: str, content: str):
    row_classes = "message-row"
    bubble_classes = "message-bubble"
    content_classes = "message-bubble-content"
    half_classes = "message-half"
    if role == "user":
        row_classes += " message-row-user"
        bubble_classes += " message-bubble-user"
        content_classes += " message-bubble-user"
        half_classes += " message-half-user"
    elif role == "status":
        row_classes += " message-row-status"
        bubble_classes += " message-bubble-status"
        content_classes += " message-bubble-status"
        half_classes += " message-half-assistant"
    else:
        row_classes += " message-row-assistant"
        bubble_classes += " message-bubble-assistant"
        content_classes += " message-bubble-assistant"
        half_classes += " message-half-assistant"
    content_widget: Static
    if role in {"user", "assistant"}:
        content_widget = SelectableMessageStatic(
            content,
            classes=content_classes,
            markup=False,
            expand=False,
        )
    else:
        content_widget = Static(
            content,
            classes=content_classes,
            markup=False,
            expand=False,
        )
    if role == "user":
        bubble = Vertical(
            TopHalfSpacer(classes=half_classes),
            content_widget,
            BottomHalfSpacer(classes=half_classes),
            classes=bubble_classes,
        )
    else:
        bubble = Vertical(
            TopHalfSpacer(classes=half_classes),
            content_widget,
            classes=bubble_classes,
        )
    return Horizontal(bubble, classes=row_classes), content_widget


class TopHalfSpacer(Static):
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


class BottomHalfSpacer(Static):
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


class SelectableMessageStatic(Static, can_focus=True):
    BINDINGS = [
        Binding("ctrl+c", "copy_selection", show=False, priority=True),
        Binding("ctrl+a", "select_all", show=False, priority=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selection_anchor = 0
        self._selection_focus = 0
        self._drag_selecting = False

    def render(self):
        start, end = self._selection_range()
        if start == end:
            return super().render()
        content = self._plain_content()
        text = Text(content)
        text.stylize("reverse", start, end)
        return text

    def update(self, content="") -> None:
        super().update(content)
        self.clear_selection(refresh=False)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        try:
            self.screen.set_focus(self, scroll_visible=False)
        except Exception:
            self.focus(scroll_visible=False)
        self._drag_selecting = True
        index = self._index_from_event(event)
        self._selection_anchor = index
        self._selection_focus = index
        self.capture_mouse()
        self.refresh()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._drag_selecting:
            return
        self._selection_focus = self._index_from_event(event)
        self.refresh()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._drag_selecting:
            return
        self._selection_focus = self._index_from_event(event)
        self._drag_selecting = False
        self.release_mouse()
        self.refresh()
        event.stop()

    def on_focus(self) -> None:
        return

    def on_blur(self) -> None:
        if self._drag_selecting:
            self._drag_selecting = False
            self.release_mouse()

    def action_copy_selection(self) -> None:
        selected = self.selected_text or self._plain_content()
        if not selected:
            return
        self.app.copy_to_clipboard(selected)

    def action_select_all(self) -> None:
        content = self._plain_content()
        self._selection_anchor = 0
        self._selection_focus = len(content)
        self.refresh()

    @property
    def selected_text(self) -> str:
        start, end = self._selection_range()
        return self._plain_content()[start:end]

    def clear_selection(self, refresh: bool = True) -> None:
        self._selection_anchor = 0
        self._selection_focus = 0
        if refresh:
            self.refresh()

    def _plain_content(self) -> str:
        return str(getattr(self, "content", "") or "")

    def _selection_range(self) -> tuple[int, int]:
        start = max(0, min(self._selection_anchor, self._selection_focus))
        end = max(0, max(self._selection_anchor, self._selection_focus))
        limit = len(self._plain_content())
        return min(start, limit), min(end, limit)

    def _index_from_event(self, event: events.MouseEvent) -> int:
        lines = self._wrapped_line_ranges()
        if not lines:
            return 0
        top_padding = self.styles.padding.top
        left_padding = self.styles.padding.left
        line_index = min(max(0, event.y - top_padding), len(lines) - 1)
        raw_start, raw_end = lines[line_index]
        column = max(0, event.x - left_padding)
        line_length = raw_end - raw_start
        return raw_start + min(column, line_length)

    def _wrapped_line_ranges(self) -> list[tuple[int, int]]:
        content = self._plain_content()
        if not content:
            return [(0, 0)]
        width = max(1, self.content_region.width)
        lines: list[tuple[int, int]] = []
        offset = 0
        raw_lines = content.split("\n")
        for line_number, raw_line in enumerate(raw_lines):
            wrapped = Text(raw_line).wrap(
                self.app.console,
                width,
                no_wrap=False,
                overflow="fold",
            )
            if not wrapped:
                wrapped = [Text("")]
            for visual_line in wrapped:
                line_text = visual_line.plain
                line_start = offset
                line_end = offset + len(line_text)
                lines.append((line_start, line_end))
                offset = line_end
            if line_number != len(raw_lines) - 1:
                offset += 1
        return lines or [(0, 0)]


class ThoughtBlock(Vertical):
    def __init__(self, content: str = "", elapsed_seconds: float = 0.0):
        super().__init__()
        self.thought_content = str(content or "")
        self.elapsed_seconds = float(elapsed_seconds or 0.0)
        self.expanded = False
        self._toggle_widget: Static | None = None
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._toggle_widget = Static(self._header_label(), classes="thought-toggle")
        self._content_widget = Static(
            self.thought_content, classes="thought-content hidden", markup=False
        )
        yield self._toggle_widget
        yield self._content_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if not hasattr(control, "has_class"):
            return
        if control.has_class("thought-toggle") or control.has_class("thought-content"):
            self.expanded = not self.expanded
            self._refresh()

    def set_content(self, content) -> None:
        if content is None:
            content = ""
        self.thought_content = content
        self._refresh()

    def set_elapsed_seconds(self, elapsed_seconds: float) -> None:
        self.elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
        self._refresh()

    def _header_label(self) -> str:
        marker = "+" if not self.expanded else "-"
        return f"{marker} Thought: {self.elapsed_seconds:.1f}s"

    def _refresh(self) -> None:
        toggle = self._toggle_widget
        content = self._content_widget
        if toggle is None or content is None:
            return
        toggle.update(self._header_label())
        content.update(self.thought_content)
        if self.expanded and self.thought_content:
            content.remove_class("hidden")
        else:
            content.add_class("hidden")


class ExploredBlock(Vertical):
    READ_TOOLS = frozenset({"read_file", "read_program_docs"})
    SEARCH_TOOLS = frozenset({"grep", "glob", "list_dir"})

    def __init__(self):
        super().__init__()
        self.entries: list[tuple[str, str]] = []
        self.expanded = False
        self._toggle_widget: Static | None = None
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._toggle_widget = Static(
            self._header_label(), classes="explored-toggle", markup=True
        )
        self._content_widget = Static(
            "", classes="explored-content hidden", markup=True
        )
        yield self._toggle_widget
        yield self._content_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if not hasattr(control, "has_class"):
            return
        if control.has_class("explored-toggle") or control.has_class(
            "explored-content"
        ):
            self.expanded = not self.expanded
            self._refresh()

    def add_entry(self, tool_name: str, description: str) -> None:
        self.entries.append((str(tool_name), str(description)))
        self._refresh()

    def _header_label(self) -> str:
        reads = sum(1 for name, _ in self.entries if name in self.READ_TOOLS)
        searches = sum(1 for name, _ in self.entries if name in self.SEARCH_TOOLS)
        parts = []
        if reads:
            parts.append(f"{reads} read" if reads == 1 else f"{reads} reads")
        if searches:
            parts.append(
                f"{searches} search" if searches == 1 else f"{searches} searches"
            )
        if not parts:
            parts.append("0 reads, 0 searches")
        counts = ", ".join(parts)
        return f"→ [white]Explored[/white] [gray]{counts}[/gray]"

    def _refresh(self) -> None:
        toggle = self._toggle_widget
        content = self._content_widget
        if toggle is None or content is None:
            return
        toggle.update(self._header_label())
        content.update("\n".join(desc for _, desc in self.entries))
        if self.expanded and self.entries:
            content.remove_class("hidden")
        else:
            content.add_class("hidden")


class QuestionsBlock(Vertical):
    def __init__(self):
        super().__init__()
        self.entries: list[tuple[str, str]] = []
        self.expanded = False
        self._toggle_widget: Static | None = None
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._toggle_widget = Static(
            self._header_label(), classes="questions-toggle", markup=True
        )
        self._content_widget = Static(
            "", classes="questions-content hidden", markup=True
        )
        yield self._toggle_widget
        yield self._content_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if not hasattr(control, "has_class"):
            return
        if control.has_class("questions-toggle") or control.has_class(
            "questions-content"
        ):
            self.expanded = not self.expanded
            self._refresh()

    def add_entry(self, question: str, answer: str) -> None:
        self.entries.append((str(question or ""), str(answer or "")))
        self._refresh()

    def _header_label(self) -> str:
        count = len(self.entries)
        suffix = "answered" if count == 1 else "answered"
        return f"[white]Questions[/white] [gray]{count} {suffix}[/gray]"

    def _content_text(self) -> str:
        parts = []
        for question, answer in self.entries:
            parts.append(
                f"[gray]{_escape_markup(question)}[/gray]\n"
                f"[white]{_escape_markup(answer)}[/white]"
            )
        return "\n\n".join(parts)

    def _refresh(self) -> None:
        toggle = self._toggle_widget
        content = self._content_widget
        if toggle is None or content is None:
            return
        toggle.update(self._header_label())
        content.update(self._content_text())
        if self.expanded and self.entries:
            content.remove_class("hidden")
        else:
            content.add_class("hidden")


def _escape_markup(text: str) -> str:
    return str(text or "").replace("[", r"\[")
