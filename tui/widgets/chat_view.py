from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import re
import time
from datetime import datetime

from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from rich import box
from rich.cells import cell_len
from rich.console import Console
import rich.markdown as rich_markdown
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.strip import Strip
from textual.widgets import Static
from textual.widget import Widget

from references import resolve_references
from tui.theme import (
    DIFF_ADD_BG,
    DIFF_ADD_FG,
    DIFF_DEL_BG,
    DIFF_DEL_FG,
    INFO_BAR_BACKGROUND,
    PAGE_BACKGROUND,
    REFERENCE_BACKGROUND,
    SURFACE_BACKGROUND,
    TEXT_PRIMARY,
    TEXT_MUTED,
    render_css,
)
from tui.widgets.chat_input import HalfRowSpacer, BottomHalfRowSpacer
from tui.widgets.todos_panel import TodoLine


def _patch_rich_markdown_tables() -> None:
    if getattr(rich_markdown.TableElement, "_omniagent_fold_patch", False):
        return

    def _render_table(self, console, options):
        table = Table(
            box=box.SIMPLE,
            pad_edge=False,
            style="markdown.table.border",
            show_edge=True,
            collapse_padding=True,
        )

        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                heading = column.content.copy()
                heading.stylize("markdown.table.header")
                table.add_column(heading, overflow="fold", no_wrap=False)

        if self.body is not None:
            if not table.columns and self.body.rows:
                for _ in range(max(len(row.cells) for row in self.body.rows)):
                    table.add_column(overflow="fold", no_wrap=False)
            for row in self.body.rows:
                row_content = [element.content for element in row.cells]
                table.add_row(*row_content)

        yield table

    rich_markdown.TableElement.__rich_console__ = _render_table
    rich_markdown.TableElement._omniagent_fold_patch = True


def _patch_rich_markdown_headings() -> None:
    # Keep h1 aligned with the rest of the Markdown content.
    rich_markdown.Heading.LEVEL_ALIGN["h1"] = "left"


_patch_rich_markdown_tables()
_patch_rich_markdown_headings()


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
    .message-row-assistant > .message-bubble {
        width: 100%;
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
    .message-row-assistant .message-bubble-content {
        width: 100%;
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

    CompactionBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    CompactionBlock > .compaction-line {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        content-align: center middle;
        text-align: center;
    }

    CompactionBlock > .compaction-details {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 0;
        color: $TEXT_MUTED;
        background: transparent;
        content-align: center middle;
        text-align: center;
    }
    CompactionBlock > .compaction-details.hidden {
        display: none;
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

    TodosBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    TodosBlock > .todos-toggle {
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
    TodosBlock > .todos-toggle:hover,
    TodosBlock > .todos-toggle:focus-within {
        background: transparent;
        color: $TEXT_MUTED;
    }

    TodosBlock > .todos-content {
        width: 100%;
        height: auto;
        padding: 0;
        color: $TEXT_MUTED;
        background: transparent;
    }
    TodosBlock > .todos-content > .todos-top-spacer {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }
    TodosBlock > .todos-content > .todos-panel {
        width: 100%;
        height: auto;
        padding: 0;
        background: $SURFACE_BACKGROUND;
    }
    TodosBlock > .todos-content > .todos-panel > .todos-summary {
        width: 1fr;
        height: 1;
        margin: 0 2;
        color: $TEXT_PRIMARY;
        background: $SURFACE_BACKGROUND;
    }
    TodosBlock > .todos-content > .todos-panel > .todos-list {
        width: 1fr;
        height: auto;
        margin: 0 2;
        background: $SURFACE_BACKGROUND;
    }
    TodosBlock > .todos-content > .todos-panel > .todos-list > TodoLine {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        background: $SURFACE_BACKGROUND;
    }
    TodosBlock > .todos-content > .todos-bottom-spacer {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }
    TodosBlock > .todos-content.hidden {
        display: none;
    }

    SubagentBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }
    SubagentBlock > .subagent-toggle {
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
    SubagentBlock > .subagent-content {
        width: 100%;
        height: auto;
        margin-top: 0;
        padding: 0 0 0 2;
        background: transparent;
    }
    SubagentBlock > .subagent-content.hidden {
        display: none;
    }
    SubagentBlock ChatView,
    SubagentBlock ChatView #chat-log {
        width: 100%;
        height: auto;
        background: transparent;
    }

    .web-summary-entry {
        width: auto;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
    }

    EditedBlock {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }

    WrittenBlock {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }

    DiffFileRow {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    DiffFileRow > .diff-row-header {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    DiffFileRow > .diff-row-header > .diff-row-label {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
    }
    DiffFileRow > .diff-row-header > .diff-row-path {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0 0 0 1;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
        overflow: hidden;
    }
    DiffFileRow > .diff-row-header > .diff-row-stats {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0 0 0 1;
        background: transparent;
        text-align: left;
        content-align: left middle;
    }

    DiffFileRow > DiffContent {
        width: 100%;
        height: auto;
        margin-top: 0;
        padding: 0;
        background: $INFO_BAR_BACKGROUND;
    }
    DiffFileRow > DiffContent.hidden {
        display: none;
    }

    DiffFileRow > .diff-file-row-wrap {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    DiffFileRow > .diff-file-row-wrap.hidden {
        display: none;
    }
    DiffFileRow > .diff-file-row-wrap > .diff-file-row-top-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }
    DiffFileRow > .diff-file-row-wrap > .diff-file-row-container {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0 1;
        background: $INFO_BAR_BACKGROUND;
    }
    DiffFileRow > .diff-file-row-wrap > .diff-file-row-container > ChangedFileRow {
        background: $INFO_BAR_BACKGROUND;
    }
    DiffFileRow > .diff-file-row-wrap > .diff-file-row-bottom-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }

    ShellBlock {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }

    ShellRow {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    ShellRow > .shell-row-header {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    ShellRow > .shell-row-header > .shell-row-label {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
    }
    ShellRow > .shell-row-header > .shell-row-shell-label {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0 0 0 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
    }
    ShellRow > .shell-row-header > .shell-row-command {
        width: 1fr;
        height: 1;
        margin: 0;
        padding: 0 0 0 1;
        background: transparent;
        color: $TEXT_MUTED;
        text-align: left;
        content-align: left middle;
        overflow: hidden;
    }
    ShellRow > .shell-row-header > .shell-row-command.hidden {
        display: none;
    }

    ShellRow > .shell-row-wrap {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    ShellRow > .shell-row-wrap.hidden {
        display: none;
    }
    ShellRow > .shell-row-wrap > .shell-row-top-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }
    ShellRow > .shell-row-wrap > .shell-row-container {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0 1;
        background: $INFO_BAR_BACKGROUND;
    }
    ShellRow > .shell-row-wrap > .shell-row-container > .shell-command-display {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        color: $TEXT_PRIMARY;
        background: transparent;
    }
    ShellRow > .shell-row-wrap > .shell-row-container > .shell-output-display {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 0;
        color: $TEXT_MUTED;
        background: transparent;
    }
    ShellRow > .shell-row-wrap > .shell-row-bottom-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }

    ChangedFilesBlock {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: transparent;
    }

    ChangedFilesBlock > .changed-files-toggle {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
    }

    ChangedFilesBlock > .changed-files-top-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }

    ChangedFilesBlock > .changed-files-rows {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0 1;
        background: $INFO_BAR_BACKGROUND;
    }
    ChangedFilesBlock > .changed-files-rows.hidden {
        display: none;
    }

    ChangedFilesBlock > .changed-files-bottom-spacer {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $PAGE_BACKGROUND;
    }

    ChangedFileRow {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }

    ChangedFileRow > .changed-file-row-header {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    ChangedFileRow > .changed-file-row-header > .changed-file-row-path {
        width: 1fr;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
        overflow: hidden;
    }
    ChangedFileRow > .changed-file-row-header > .changed-file-row-stats {
        width: auto;
        height: 1;
        margin: 0;
        padding: 0 0 0 1;
        background: transparent;
        text-align: right;
        content-align: right middle;
    }

    ChangedFileRow > DiffContent {
        width: 100%;
        height: auto;
        margin-top: 0;
        padding: 0;
        background: $INFO_BAR_BACKGROUND;
    }
    ChangedFileRow > DiffContent.hidden {
        display: none;
    }
    """
    )

    def __init__(
        self, *args, markdown_enabled: bool = True, user_spacer: bool = True, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.messages = []
        self._transcript: list[dict] = []
        self._assistant_markdown_enabled = bool(markdown_enabled)
        self._user_spacer = bool(user_spacer)
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index: int | None = None
        self._active_output_kind: str | None = None
        self._thought_stream_target: ThoughtBlock | None = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index: int | None = None
        self._explored_block: ExploredBlock | None = None
        self._edited_block: EditedBlock | None = None
        self._write_block: WrittenBlock | None = None
        self._shell_block: ShellBlock | None = None
        self._questions_block: QuestionsBlock | None = None
        self._compaction_blocks: dict[str, CompactionBlock] = {}
        self._compaction_transcript_indices: dict[str, int] = {}
        self._subagent_blocks: dict[str, SubagentBlock] = {}
        self._subagent_transcript_indices: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-log")

    def add_message(self, role: str, content: str, reference_base_dir=None) -> None:
        self._activate_message_output()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None
        if role == "user" and self._user_spacer:
            self.query_one("#chat-log", VerticalScroll).mount(
                Static("", classes="message-spacer")
            )
        row, content_widget = _build_message_widgets(
            role,
            content,
            assistant_markdown_enabled=self._assistant_markdown_enabled,
            reference_base_dir=reference_base_dir,
        )
        self.query_one("#chat-log", VerticalScroll).mount(row)
        self.call_after_refresh(self._scroll_end)
        self.messages.append((role, content, datetime.now().isoformat()))
        self._append_transcript_entry({
            "kind": "message",
            "role": str(role or ""),
            "content": str(content or ""),
        })
        if role == "assistant":
            self._stream_target = content_widget
            self._stream_role = role
            self._stream_content = str(content or "")
            self._stream_transcript_index = len(self._transcript) - 1

    def add_status(self, content: str) -> None:
        self._activate_message_output()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None
        row, _ = _build_message_widgets(
            "status",
            content,
            assistant_markdown_enabled=self._assistant_markdown_enabled,
        )
        self.query_one("#chat-log", VerticalScroll).mount(row)
        self.call_after_refresh(self._scroll_end)
        self._append_transcript_entry({
            "kind": "message",
            "role": "status",
            "content": str(content or ""),
        })

    def start_stream(self, role: str = "assistant", prefix: str = "") -> None:
        self._activate_message_output()
        if self._stream_target is not None and self._stream_role == role:
            return
        if role == "status":
            row, content_widget = _build_message_widgets(
                "status",
                prefix,
                assistant_markdown_enabled=self._assistant_markdown_enabled,
            )
            self.query_one("#chat-log", VerticalScroll).mount(row)
            self.call_after_refresh(self._scroll_end)
            self._stream_target = content_widget
            self._stream_role = role
            self._stream_content = str(prefix or "")
            self._append_transcript_entry({
                "kind": "message",
                "role": str(role or ""),
                "content": str(prefix or ""),
            })
            self._stream_transcript_index = len(self._transcript) - 1
            return
        self.add_message(role, prefix)
        self._stream_role = role
        self._stream_content = str(prefix or "")
        self._stream_transcript_index = len(self._transcript) - 1

    def append_stream(
        self, content: str, role: str = "assistant", prefix: str = ""
    ) -> None:
        self.start_stream(role=role, prefix=prefix)
        self._stream_content += str(content or "")
        self._stream_target.update(self._stream_content)
        self._update_transcript_entry(
            self._stream_transcript_index,
            content=self._stream_content,
        )
        self.call_after_refresh(self._scroll_end)

    def remove_last_messages(self, count: int = 1) -> None:
        count = max(1, int(count or 1))
        remove_count = count
        log = self.query_one("#chat-log", VerticalScroll)
        children = list(log.children)
        if not children:
            return
        for child in children[-count:]:
            child.remove()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None
        self._active_output_kind = None
        while remove_count > 0 and self._transcript:
            remove_count -= 1
            self._transcript.pop()

    def clear(self) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        log.remove_children()
        self.messages.clear()
        self._transcript.clear()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None
        self._active_output_kind = None
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index = None
        self._explored_block = None
        self._edited_block = None
        self._write_block = None
        self._shell_block = None
        self._questions_block = None
        self._compaction_blocks.clear()
        self._compaction_transcript_indices.clear()
        self._subagent_blocks.clear()
        self._subagent_transcript_indices.clear()

    def clear_message_selection(self) -> None:
        widgets = [
            *self.query(SelectableMessageStatic),
            *self.query(MarkdownMessageStatic),
        ]
        for widget in widgets:
            if widget._selection_anchor != widget._selection_focus:
                widget.clear_selection()

    def _scroll_end(self) -> None:
        self.query_one("#chat-log", VerticalScroll).scroll_end(animate=False)

    def add_thought(self, content: str, elapsed_seconds: float = 0.0) -> None:
        self._activate_aux_output("thought")
        block = ThoughtBlock(content=content, elapsed_seconds=elapsed_seconds)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self.call_after_refresh(self._scroll_end)
        self._append_transcript_entry({
            "kind": "thought",
            "content": str(content or ""),
            "elapsed_seconds": float(elapsed_seconds or 0.0),
        })

    def start_thought_stream(self, elapsed_seconds: float = 0.0) -> None:
        self._activate_aux_output("thought")
        if self._thought_stream_target is not None:
            return
        block = ThoughtBlock(content="", elapsed_seconds=elapsed_seconds)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self.call_after_refresh(self._scroll_end)
        self._thought_stream_target = block
        self._thought_stream_content = ""
        self._append_transcript_entry({
            "kind": "thought",
            "content": "",
            "elapsed_seconds": float(elapsed_seconds or 0.0),
        })
        self._thought_stream_transcript_index = len(self._transcript) - 1

    def append_thought_stream(self, content: str) -> None:
        self.start_thought_stream()
        self._thought_stream_content += str(content or "")
        if self._thought_stream_target is not None:
            self._thought_stream_target.set_content(self._thought_stream_content)
            self._update_transcript_entry(
                self._thought_stream_transcript_index,
                content=self._thought_stream_content,
            )
            self.call_after_refresh(self._scroll_end)

    @staticmethod
    def _trim_trailing_blank_lines(content: str) -> str:
        return re.sub(r"(?:\r?\n[ \t]*)+\Z", "", str(content or ""))

    def finish_thought_stream(self, elapsed_seconds: float = 0.0) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_content = self._trim_trailing_blank_lines(
            self._thought_stream_content
        )
        self._thought_stream_target.set_content(self._thought_stream_content)
        self._thought_stream_target.set_elapsed_seconds(elapsed_seconds)
        self._update_transcript_entry(
            self._thought_stream_transcript_index,
            content=self._thought_stream_content,
            elapsed_seconds=max(0.0, float(elapsed_seconds or 0.0)),
        )
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index = None

    def update_thought_stream_elapsed(self, elapsed_seconds: float) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_target.set_elapsed_seconds(elapsed_seconds)
        self._update_transcript_entry(
            self._thought_stream_transcript_index,
            elapsed_seconds=max(0.0, float(elapsed_seconds or 0.0)),
        )

    def replace_thought_stream(self, content: str, elapsed_seconds: float) -> None:
        if self._thought_stream_target is None:
            return
        self._thought_stream_content = self._trim_trailing_blank_lines(content)
        self._thought_stream_target.set_content(self._thought_stream_content)
        self._thought_stream_target.set_elapsed_seconds(
            max(0.0, float(elapsed_seconds or 0.0))
        )
        self._update_transcript_entry(
            self._thought_stream_transcript_index,
            content=self._thought_stream_content,
            elapsed_seconds=max(0.0, float(elapsed_seconds or 0.0)),
        )
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index = None
        self.call_after_refresh(self._scroll_end)

    def add_explored_entry(self, tool_name: str, description: str) -> None:
        self._activate_aux_output("explored")
        if self._explored_block is None:
            block = ExploredBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._explored_block = block
        self._explored_block.add_entry(tool_name, description)
        self._append_transcript_entry({
            "kind": "explored_entry",
            "tool_name": str(tool_name or ""),
            "description": str(description or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def reset_explored(self) -> None:
        self._explored_block = None

    def add_edit_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self._activate_aux_output("edit")
        if self._edited_block is None:
            block = EditedBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._edited_block = block
        self._edited_block.add_entry(
            file_path, additions, deletions, diff, status=status
        )
        self._append_transcript_entry({
            "kind": "edit",
            "file_path": str(file_path or ""),
            "additions": int(additions or 0),
            "deletions": int(deletions or 0),
            "diff": str(diff or ""),
            "status": str(status or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def add_write_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        self._activate_aux_output("write")
        if self._write_block is None:
            block = WrittenBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._write_block = block
        self._write_block.add_entry(
            file_path, additions, deletions, diff, status=status
        )
        self._append_transcript_entry({
            "kind": "write",
            "file_path": str(file_path or ""),
            "additions": int(additions or 0),
            "deletions": int(deletions or 0),
            "diff": str(diff or ""),
            "status": str(status or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def reset_edited(self) -> None:
        self._edited_block = None
        self._write_block = None
        self._shell_block = None

    def add_shell_entry(self, command: str, output: str) -> None:
        self._activate_aux_output("shell")
        if self._shell_block is None:
            block = ShellBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._shell_block = block
        self._shell_block.add_entry(command, output)
        self._append_transcript_entry({
            "kind": "shell",
            "command": str(command or ""),
            "output": str(output or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def add_changed_files_entry(self, files: list[dict]) -> None:
        if not files:
            return
        self._activate_aux_output("changed_files")
        block = ChangedFilesBlock(files)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self._append_transcript_entry({
            "kind": "changed_files",
            "files": [dict(file_info or {}) for file_info in list(files or [])],
        })
        self.call_after_refresh(self._scroll_end)

    def add_question_entry(self, question: str, answer: str) -> None:
        self._activate_aux_output("questions")
        if self._questions_block is None:
            block = QuestionsBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._questions_block = block
        self._questions_block.add_entry(question, answer)
        self._append_transcript_entry({
            "kind": "question",
            "question": str(question or ""),
            "answer": str(answer or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def add_todo_entry(
        self, items: list[dict] | None, summary: dict | None = None
    ) -> None:
        self._activate_aux_output("todo")
        block = TodosBlock(items or [], summary)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self._append_transcript_entry({
            "kind": "todo",
            "items": [dict(item or {}) for item in list(items or [])],
            "summary": dict(summary or {}),
        })
        self.call_after_refresh(self._scroll_end)

    def add_subagent_entry(self, agent_type: str, transcript: list[dict]) -> None:
        self._activate_aux_output("subagent")
        block = SubagentBlock(agent_type, transcript, self._assistant_markdown_enabled)
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self._append_transcript_entry({
            "kind": "subagent",
            "agent_type": str(agent_type or ""),
            "transcript": deepcopy(list(transcript or [])),
        })
        self.call_after_refresh(self._scroll_end)

    def start_subagent_entry(self, entry_id: str, agent_type: str) -> None:
        self._activate_aux_output("subagent")
        block = SubagentBlock(agent_type, [], self._assistant_markdown_enabled)
        entry_id = str(entry_id)
        self._subagent_blocks[entry_id] = block
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self._append_transcript_entry({
            "kind": "subagent",
            "agent_type": str(agent_type or ""),
            "transcript": [],
        })
        self._subagent_transcript_indices[entry_id] = len(self._transcript) - 1
        self.call_after_refresh(self._scroll_end)

    def append_subagent_event(self, entry_id: str, event: dict) -> None:
        entry_id = str(entry_id)
        block = self._subagent_blocks.get(entry_id)
        if block is None or not isinstance(event, dict):
            return
        block.add_event(event)
        transcript_index = self._subagent_transcript_indices.get(entry_id)
        if transcript_index is not None:
            self._update_transcript_entry(
                transcript_index,
                transcript=deepcopy(block.persistent_transcript()),
            )
        self.call_after_refresh(self._scroll_end)

    def start_compaction_entry(
        self,
        entry_id: str,
        status: str,
        mode: str = "auto",
        details: str = "",
    ) -> None:
        self._activate_aux_output("compaction")
        entry_id = str(entry_id or "")
        details = self._normalize_compaction_details(details)
        block = CompactionBlock(status=status, mode=mode, details=details)
        self._compaction_blocks[entry_id] = block
        self.query_one("#chat-log", VerticalScroll).mount(block)
        self._append_transcript_entry({
            "kind": "compaction",
            "status": str(status or ""),
            "mode": str(mode or "auto"),
            "details": str(details or ""),
        })
        self._compaction_transcript_indices[entry_id] = len(self._transcript) - 1
        self.call_after_refresh(self._scroll_end)

    def finish_compaction_entry(
        self,
        entry_id: str,
        status: str,
        mode: str = "auto",
        details: str = "",
    ) -> None:
        entry_id = str(entry_id or "")
        details = self._normalize_compaction_details(details)
        block = self._compaction_blocks.get(entry_id)
        if block is None:
            self.start_compaction_entry(entry_id, status, mode=mode, details=details)
            return
        block.set_state(status=status, mode=mode, details=details)
        transcript_index = self._compaction_transcript_indices.get(entry_id)
        if transcript_index is not None:
            self._update_transcript_entry(
                transcript_index,
                status=str(status or ""),
                mode=str(mode or "auto"),
                details=str(details or ""),
            )
        self.call_after_refresh(self._scroll_end)

    @staticmethod
    def _normalize_compaction_details(details: str) -> str:
        text = str(details or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        message_match = re.search(
            r"\bmessages?\s*:\s*([0-9]+)\s*->\s*([0-9]+)",
            text,
            flags=re.IGNORECASE,
        )
        char_match = re.search(
            r"\bchars?\s*:\s*([0-9]+)\s*->\s*([0-9]+)",
            text,
            flags=re.IGNORECASE,
        )
        model_match = re.search(
            r"\bcompact model\s*:\s*(.+?)(?=\s+Memory updated:|\s+Memory update failed:|\s+Memory update:\s*scheduled|$)",
            text,
            flags=re.IGNORECASE,
        )
        parts: list[str] = []
        if message_match:
            parts.append(
                f"Message: {message_match.group(1)} -> {message_match.group(2)}"
            )
        if char_match:
            parts.append(f"Chars: {char_match.group(1)} -> {char_match.group(2)}")
        if model_match:
            model = str(model_match.group(1) or "").strip()
            if model:
                parts.append(f"Compact model: {model}")
        return "\n".join(parts) if parts else ""

    def _reset_message_stream(self) -> None:
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None

    def get_transcript(self) -> list[dict]:
        return deepcopy(self._transcript)

    def load_transcript(self, transcript: list[dict], reference_base_dir=None) -> None:
        self.clear()
        for entry in list(transcript or []):
            self._replay_transcript_entry(entry, reference_base_dir)
        self._reset_message_stream()
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index = None

    def set_markdown_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._assistant_markdown_enabled == enabled:
            return
        transcript = self.get_transcript()
        self._assistant_markdown_enabled = enabled
        self.load_transcript(transcript)

    def _append_transcript_entry(self, entry: dict) -> None:
        self._transcript.append(deepcopy(entry))

    def _update_transcript_entry(self, index: int | None, **changes) -> None:
        if index is None or index < 0 or index >= len(self._transcript):
            return
        entry = dict(self._transcript[index])
        entry.update(changes)
        self._transcript[index] = deepcopy(entry)

    def _replay_transcript_entry(self, entry: dict, reference_base_dir=None) -> None:
        if not isinstance(entry, dict):
            return
        kind = str(entry.get("kind") or "")
        if kind == "message":
            role = str(entry.get("role") or "")
            content = str(entry.get("content") or "")
            if role == "status":
                self.add_status(content)
            elif role:
                self.add_message(role, content, reference_base_dir)
            return
        if kind == "thought":
            self.add_thought(
                str(entry.get("content") or ""),
                float(entry.get("elapsed_seconds", 0.0) or 0.0),
            )
            return
        if kind == "explored_entry":
            self.add_explored_entry(
                str(entry.get("tool_name") or ""),
                str(entry.get("description") or ""),
            )
            return
        if kind == "question":
            self.add_question_entry(
                str(entry.get("question") or ""),
                str(entry.get("answer") or ""),
            )
            return
        if kind == "todo":
            self.add_todo_entry(
                [dict(item or {}) for item in list(entry.get("items") or [])],
                dict(entry.get("summary") or {}),
            )
            return
        if kind == "web_fetch":
            self.add_web_fetch_entry(str(entry.get("url") or ""))
            return
        if kind == "web_search":
            self.add_web_search_entry(str(entry.get("content") or ""))
            return
        if kind == "edit":
            self.add_edit_entry(
                str(entry.get("file_path") or ""),
                int(entry.get("additions", 0) or 0),
                int(entry.get("deletions", 0) or 0),
                str(entry.get("diff") or ""),
                str(entry.get("status") or ""),
            )
            return
        if kind == "write":
            self.add_write_entry(
                str(entry.get("file_path") or ""),
                int(entry.get("additions", 0) or 0),
                int(entry.get("deletions", 0) or 0),
                str(entry.get("diff") or ""),
                str(entry.get("status") or ""),
            )
            return
        if kind == "shell":
            self.add_shell_entry(
                str(entry.get("command") or ""),
                str(entry.get("output") or ""),
            )
            return
        if kind == "changed_files":
            self.add_changed_files_entry([
                dict(file_info or {}) for file_info in list(entry.get("files") or [])
            ])
            return
        if kind == "subagent":
            self.add_subagent_entry(
                str(entry.get("agent_type") or ""),
                list(entry.get("transcript") or []),
            )
            return
        if kind == "compaction":
            self.start_compaction_entry(
                f"replay-{len(self._transcript)}",
                str(entry.get("status") or "running"),
                str(entry.get("mode") or "auto"),
                str(entry.get("details") or ""),
            )
            return

    def add_web_fetch_entry(self, url: str) -> None:
        self._activate_aux_output("web_fetch")
        content = f"→ [white]Webfetch[/white] [gray]{_escape_markup(url)}[/gray]"
        self.query_one("#chat-log", VerticalScroll).mount(
            Static(content, classes="web-summary-entry", markup=True)
        )
        self._append_transcript_entry({
            "kind": "web_fetch",
            "url": str(url or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def add_web_search_entry(self, content: str) -> None:
        self._activate_aux_output("web_search")
        summary = _escape_markup(content)
        self.query_one("#chat-log", VerticalScroll).mount(
            Static(
                f"→ [white]Websearch[/white] [gray]{summary}[/gray]",
                classes="web-summary-entry",
                markup=True,
            )
        )
        self._append_transcript_entry({
            "kind": "web_search",
            "content": str(content or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def reset_turn_summaries(self) -> None:
        self._explored_block = None
        self._edited_block = None
        self._write_block = None
        self._shell_block = None
        self._questions_block = None
        self._active_output_kind = None

    def _activate_message_output(self) -> None:
        if self._active_output_kind == "message":
            return
        self._clear_auxiliary_group_refs()
        self._active_output_kind = "message"

    def _activate_aux_output(self, kind: str) -> None:
        if self._active_output_kind != kind:
            self._reset_message_stream()
            self._clear_auxiliary_group_refs(except_kind=kind)
            self._active_output_kind = kind

    def _clear_auxiliary_group_refs(self, except_kind: str | None = None) -> None:
        if except_kind != "explored":
            self._explored_block = None
        if except_kind != "edit":
            self._edited_block = None
        if except_kind != "write":
            self._write_block = None
        if except_kind != "shell":
            self._shell_block = None
        if except_kind != "questions":
            self._questions_block = None


class CompactionBlock(Vertical):
    LABELS = {
        ("auto", "running"): "Auto context compaction",
        ("auto", "done"): "Context compact complete",
        ("manual", "running"): "Manual context compaction",
        ("manual", "done"): "Context compact complete",
    }

    def __init__(self, status: str = "running", mode: str = "auto", details: str = ""):
        super().__init__()
        self.status = str(status or "running")
        self.mode = str(mode or "auto")
        self.details = str(details or "")
        self.expanded = False
        self._line_widget: Static | None = None
        self._details_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._line_widget = Static("", classes="compaction-line", markup=True)
        yield self._line_widget
        self._details_widget = Static(
            "", classes="compaction-details hidden", markup=False
        )
        yield self._details_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        if self.status != "done" or not self.details:
            return
        self.expanded = not self.expanded
        self._refresh()
        if self.expanded:
            self.call_after_refresh(
                self.scroll_visible,
                animate=False,
                force=True,
                immediate=True,
            )
        event.stop()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh()

    def set_state(self, status: str, mode: str = "auto", details: str = "") -> None:
        self.status = str(status or "running")
        self.mode = str(mode or "auto")
        self.details = str(details or "")
        if self.status != "done" or not self.details:
            self.expanded = False
        self._refresh()

    def _label(self) -> str:
        return self.LABELS.get(
            (self.mode, self.status),
            self.LABELS[("auto", "running")],
        )

    def _refresh(self) -> None:
        if self._line_widget is None or self._details_widget is None:
            return
        self._line_widget.update(self._line_markup())
        self._details_widget.update(self.details)
        if self.expanded and self.status == "done" and self.details:
            self._details_widget.remove_class("hidden")
        else:
            self._details_widget.add_class("hidden")

    def _line_markup(self) -> str:
        label = self._label()
        width = max(1, self.size.width or self.content_region.width or 1)
        inner_width = max(0, width - 2)
        label_width = cell_len(label)
        side_total = max(0, inner_width - label_width)
        left_width = side_total // 2
        right_width = side_total - left_width
        left = "─" * left_width
        right = "─" * right_width
        return f"[gray]{left} {_escape_markup(label)} {right}[/gray]"


def _build_message_widgets(
    role: str,
    content: str,
    assistant_markdown_enabled: bool = True,
    reference_base_dir=None,
):
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
    if role == "assistant" and assistant_markdown_enabled:
        content_widget = MarkdownMessageStatic(
            content,
            classes=content_classes,
            expand=False,
        )
    elif role in {"user", "assistant"}:
        rendered_content, copy_references = (
            _reference_message_content(content, reference_base_dir)
            if role == "user"
            else (content, [])
        )
        content_widget = SelectableMessageStatic(
            rendered_content,
            copy_content=content,
            copy_references=copy_references,
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


def _reference_message_content(content: str, base_dir=None):
    source = str(content or "")
    references = resolve_references(source, base_dir)
    if not references:
        return Text(source), []
    result = Text()
    copy_references = []
    offset = 0
    style = Style(color=TEXT_PRIMARY, bgcolor=REFERENCE_BACKGROUND)
    for reference in references:
        result.append(source[offset : reference.start])
        display = f" {reference.display} "
        result.append(display, style=style)
        copy_references.append((display, reference.syntax))
        offset = reference.end
    result.append(source[offset:])
    return result, copy_references


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

    def __init__(self, *args, copy_content=None, copy_references=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._copy_content = None if copy_content is None else str(copy_content)
        self._copy_references = list(copy_references or [])
        self._selection_anchor = 0
        self._selection_focus = 0
        self._drag_selecting = False
        self._render_cache_width = 0
        self._render_cache_source = ""
        self._render_cache_text = ""
        self._render_cache_styled: Text | None = None
        self._render_cache_index_map: tuple[int | None, ...] = ()

    def render(self):
        if self._selection_anchor == self._selection_focus:
            return super().render()
        start, end = self._selection_range()
        text = self._rendered_plain_text().copy()
        text.stylize("reverse", start, end)
        return text

    def update(self, content="") -> None:
        super().update(content)
        self._render_cache_width = 0
        self._render_cache_source = ""
        self._render_cache_text = ""
        self._render_cache_styled = None
        self._render_cache_index_map = ()
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
        self._selection_focus = self._selection_index_from_event(event)
        self.refresh()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._drag_selecting:
            return
        self._selection_focus = self._selection_index_from_event(event)
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
        if self._selection_anchor == self._selection_focus:
            selected = self._copy_content or self._raw_content()
        else:
            selected = self._selected_copy_text()
            for display, syntax in self._copy_references:
                selected = selected.replace(display, syntax)
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

    def _selected_copy_text(self) -> str:
        start, end = self._selection_range()
        if start >= end:
            return ""
        self._rendered_plain_text()
        source = self._raw_content()
        copied: list[str] = []
        for source_index in self._render_cache_index_map[start:end]:
            if source_index is None or source_index < 0 or source_index >= len(source):
                continue
            copied.append(source[source_index])
        return "".join(copied)

    def clear_selection(self, refresh: bool = True) -> None:
        self._selection_anchor = 0
        self._selection_focus = 0
        if refresh:
            self.refresh()

    def _raw_content(self) -> str:
        content = getattr(self, "content", "")
        return content.plain if isinstance(content, Text) else str(content or "")

    def _styled_content(self) -> Text:
        content = getattr(self, "content", "")
        return content.copy() if isinstance(content, Text) else Text(str(content or ""))

    def _plain_content(self) -> str:
        self._rendered_plain_text()
        return self._render_cache_text

    def _rendered_plain_text(self) -> Text:
        width = max(1, self.content_region.width)
        source = self._raw_content()
        if (
            self._render_cache_width == width
            and self._render_cache_source == source
            and self._render_cache_styled is not None
        ):
            return self._render_cache_styled
        base_text = self._styled_content()
        raw_lines = base_text.split("\n", include_separator=False)
        source_lines = source.split("\n")
        if not raw_lines:
            raw_lines = [Text("")]
        if not source_lines:
            source_lines = [""]
        rendered = Text()
        plain_lines: list[str] = []
        index_map: list[int | None] = []
        source_offset = 0
        for line_index, raw_line in enumerate(raw_lines):
            source_line = (
                source_lines[line_index] if line_index < len(source_lines) else ""
            )
            source_line_offset = source_offset
            source_line_cursor = 0
            wrapped = raw_line.wrap(
                self.app.console,
                width,
                no_wrap=False,
                overflow="fold",
            )
            if not wrapped:
                wrapped = [Text("")]
            for wrapped_index, visual_line in enumerate(wrapped):
                if rendered:
                    rendered.append("\n")
                    if wrapped_index == 0 and line_index > 0:
                        index_map.append(source_line_offset - 1)
                    else:
                        index_map.append(None)
                rendered.append_text(visual_line)
                plain_lines.append(visual_line.plain)
                visual_text = visual_line.plain
                visual_length = len(visual_text)
                for char_index in range(visual_length):
                    source_index = source_line_offset + source_line_cursor + char_index
                    if source_index < source_line_offset + len(source_line):
                        index_map.append(source_index)
                    else:
                        index_map.append(None)
                source_line_cursor += visual_length
            source_offset = source_line_offset + len(source_line)
            if line_index != len(source_lines) - 1:
                source_offset += 1
        self._render_cache_width = width
        self._render_cache_source = source
        self._render_cache_text = "\n".join(plain_lines)
        self._render_cache_styled = rendered
        self._render_cache_index_map = tuple(index_map)
        return rendered

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
        line_text = self._plain_content()[raw_start:raw_end]
        return raw_start + self._index_from_column(line_text, column)

    def _selection_index_from_event(self, event: events.MouseEvent) -> int:
        lines = self._wrapped_line_ranges()
        if not lines:
            return 0
        top_padding = self.styles.padding.top
        left_padding = self.styles.padding.left
        line_index = min(max(0, event.y - top_padding), len(lines) - 1)
        raw_start, raw_end = lines[line_index]
        column = max(0, event.x - left_padding)
        line_text = self._plain_content()[raw_start:raw_end]
        before = raw_start + self._index_from_column(line_text, column)
        after = raw_start + self._index_after_column(line_text, column)
        return before if before < self._selection_anchor else after

    @staticmethod
    def _index_from_column(line_text: str, column: int) -> int:
        if column <= 0 or not line_text:
            return 0

        used_width = 0
        for index, char in enumerate(line_text):
            char_width = max(1, cell_len(char))
            if column < used_width + char_width:
                return index
            used_width += char_width
        return len(line_text)

    @staticmethod
    def _index_after_column(line_text: str, column: int) -> int:
        if not line_text:
            return 0

        used_width = 0
        for index, char in enumerate(line_text):
            char_width = max(1, cell_len(char))
            if column < used_width + char_width:
                return index + 1
            used_width += char_width
        return len(line_text)

    def _wrapped_line_ranges(self) -> list[tuple[int, int]]:
        content = self._plain_content()
        if not content:
            return [(0, 0)]
        lines: list[tuple[int, int]] = []
        offset = 0
        raw_lines = content.split("\n")
        for line_number, raw_line in enumerate(raw_lines):
            line_start = offset
            line_end = offset + len(raw_line)
            lines.append((line_start, line_end))
            offset = line_end
            if line_number != len(raw_lines) - 1:
                offset += 1
        return lines or [(0, 0)]


class MarkdownMessageStatic(Static, can_focus=True):
    BINDINGS = [
        Binding("ctrl+c", "copy_markdown", show=False, priority=True),
        Binding("ctrl+a", "select_all", show=False, priority=True),
    ]

    def __init__(self, content: str = "", *args, **kwargs):
        super().__init__("", *args, **kwargs)
        self._markdown_source = str(content or "")
        self._selection_anchor = 0
        self._selection_focus = 0
        self._drag_selecting = False
        self._render_cache_width = 0
        self._render_cache_source = ""
        self._render_cache_text = ""
        self._render_cache_styled: Text | None = None

    def render(self):
        start, end = self._selection_range()
        if start == end:
            return self._markdown_renderable()
        text = self._rendered_markdown_text().copy()
        text.stylize("reverse", start, end)
        return text

    def update(self, content="") -> None:
        self._markdown_source = str(content or "")
        self._render_cache_width = 0
        self._render_cache_source = ""
        self._render_cache_text = ""
        self._render_cache_styled = None
        self.clear_selection(refresh=False)
        self.refresh(layout=True)

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
        self._selection_focus = self._selection_index_from_event(event)
        self.refresh()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._drag_selecting:
            return
        self._selection_focus = self._selection_index_from_event(event)
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

    def _markdown_renderable(self):
        return RichMarkdown(self._markdown_source)

    def _plain_content(self) -> str:
        self._rendered_markdown_text()
        return self._render_cache_text

    def _rendered_markdown_text(self) -> Text:
        width = max(1, self.content_region.width)
        if (
            self._render_cache_width == width
            and self._render_cache_source == self._markdown_source
            and self._render_cache_styled is not None
        ):
            return self._render_cache_styled
        console = Console(
            force_terminal=False, color_system=None, width=width, highlight=False
        )
        lines = console.render_lines(
            self._markdown_renderable(),
            console.options.update(width=width),
            pad=False,
        )
        rendered = Text()
        plain_lines: list[str] = []
        for line_index, segments in enumerate(lines):
            line_text = Text()
            preserve_trailing_whitespace = False
            for segment in segments:
                if not segment.text:
                    continue
                if self._segment_has_background(segment.style):
                    preserve_trailing_whitespace = True
                line_text.append(segment.text, segment.style)
            if preserve_trailing_whitespace:
                plain_lines.append(line_text.plain)
            else:
                trim_length = len(line_text.plain.rstrip())
                if trim_length > 0:
                    line_text = line_text[:trim_length]
                plain_lines.append(line_text.plain)
            if not line_text.plain and not preserve_trailing_whitespace:
                line_text = Text("")
            if line_index:
                rendered.append("\n")
            rendered.append_text(line_text)
        self._render_cache_width = width
        self._render_cache_source = self._markdown_source
        self._render_cache_text = "\n".join(plain_lines)
        self._render_cache_styled = rendered
        return rendered

    @staticmethod
    def _segment_has_background(style) -> bool:
        if style is None:
            return False
        bgcolor = getattr(style, "bgcolor", None)
        if bgcolor is not None:
            return True
        link_style = getattr(style, "_link_style", None)
        if link_style is not None:
            linked_bg = getattr(link_style, "bgcolor", None)
            if linked_bg is not None:
                return True
        return False

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
        line_text = self._plain_content()[raw_start:raw_end]
        return raw_start + SelectableMessageStatic._index_from_column(line_text, column)

    def _selection_index_from_event(self, event: events.MouseEvent) -> int:
        lines = self._wrapped_line_ranges()
        if not lines:
            return 0
        top_padding = self.styles.padding.top
        left_padding = self.styles.padding.left
        line_index = min(max(0, event.y - top_padding), len(lines) - 1)
        raw_start, raw_end = lines[line_index]
        column = max(0, event.x - left_padding)
        line_text = self._plain_content()[raw_start:raw_end]
        before = raw_start + SelectableMessageStatic._index_from_column(
            line_text, column
        )
        after = raw_start + SelectableMessageStatic._index_after_column(
            line_text, column
        )
        return before if before < self._selection_anchor else after

    def _wrapped_line_ranges(self) -> list[tuple[int, int]]:
        content = self._plain_content()
        if not content:
            return [(0, 0)]
        lines: list[tuple[int, int]] = []
        offset = 0
        raw_lines = content.split("\n")
        for line_number, raw_line in enumerate(raw_lines):
            line_start = offset
            line_end = offset + len(raw_line)
            lines.append((line_start, line_end))
            offset = line_end
            if line_number != len(raw_lines) - 1:
                offset += 1
        return lines or [(0, 0)]

    def action_copy_markdown(self) -> None:
        selected = self.selected_text
        if selected:
            self.app.copy_to_clipboard(selected)
            return
        if not self._markdown_source:
            return
        self.app.copy_to_clipboard(self._markdown_source)


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
            event.stop()

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
    READ_TOOLS = frozenset({
        "read_file",
        "read_program_docs",
        "read_skill",
    })
    SEARCH_TOOLS = frozenset({"grep", "glob", "list_dir", "list_skills"})

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
            event.stop()

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
            event.stop()

    def add_entry(self, question: str, answer: str) -> None:
        self.entries.append((str(question or ""), str(answer or "")))
        self._refresh()

    def _header_label(self) -> str:
        count = len(self.entries)
        suffix = "answered" if count == 1 else "answered"
        return f"[gray]#[/] [white]Questions[/white] [gray]{count} {suffix}[/gray]"

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


class TodosBlock(Vertical):
    def __init__(self, items: list[dict], summary: dict | None = None):
        super().__init__()
        self.items = [dict(item or {}) for item in list(items or [])]
        self.summary = dict(summary or {})
        self.expanded = False
        self._toggle_widget: Static | None = None
        self._content_widget: Vertical | None = None
        self._summary_widget: Static | None = None
        self._list_widget: Vertical | None = None

    def compose(self) -> ComposeResult:
        self._toggle_widget = Static(
            self._header_label(), classes="todos-toggle", markup=True
        )
        self._summary_widget = Static("", classes="todos-summary")
        self._list_widget = Vertical(classes="todos-list")
        yield self._toggle_widget
        with Vertical(classes="todos-content hidden") as content:
            yield BottomHalfRowSpacer(classes="todos-top-spacer")
            with Vertical(classes="todos-panel"):
                yield self._summary_widget
                yield self._list_widget
            yield HalfRowSpacer(classes="todos-bottom-spacer")
        self._content_widget = content

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        self.expanded = not self.expanded
        self._refresh()
        event.stop()

    def _header_label(self) -> str:
        total = int(self.summary.get("total", len(self.items)) or 0)
        completed = int(self.summary.get("completed", 0) or 0)
        if self.expanded:
            return "[gray]#[/] [white]Todos[/white]"
        return (
            f"[gray]#[/] [white]Todos[/white] "
            f"[gray]{completed} of {total} todos completed[/gray]"
        )

    def _refresh(self) -> None:
        toggle = self._toggle_widget
        content = self._content_widget
        summary = self._summary_widget
        rows = self._list_widget
        if toggle is None or content is None or summary is None or rows is None:
            return
        toggle.update(self._header_label())
        completed = int(self.summary.get("completed", 0) or 0)
        total = int(self.summary.get("total", len(self.items)) or 0)
        summary.update(f"{completed} of {total} todos completed")
        existing = list(rows.children)
        target = len(self.items)
        while len(existing) > target:
            existing.pop().remove()
        while len(existing) < target:
            line = TodoLine()
            rows.mount(line)
            existing.append(line)
        for line, item in zip(existing, self.items):
            if isinstance(line, TodoLine):
                line.set_item(item)
        if self.expanded:
            content.remove_class("hidden")
        else:
            content.add_class("hidden")


class SubagentBlock(Vertical):
    def __init__(
        self,
        agent_type: str,
        transcript: list[dict],
        markdown_enabled: bool,
    ):
        super().__init__()
        self.agent_type = str(agent_type or "subagent")
        self.transcript = deepcopy(list(transcript or []))
        self.markdown_enabled = bool(markdown_enabled)
        self.expanded = False
        self._toggle_widget: Static | None = None
        self._content_widget: Vertical | None = None
        self._chat_view: ChatView | None = None
        self._loaded = False
        self._thinking_started_at: float | None = None
        self._thinking_timer = None

    def compose(self) -> ComposeResult:
        self._toggle_widget = Static(
            self._header_label(), classes="subagent-toggle", markup=True
        )
        self._chat_view = ChatView(
            markdown_enabled=self.markdown_enabled, user_spacer=False
        )
        self._content_widget = Vertical(
            self._chat_view, classes="subagent-content hidden"
        )
        yield self._toggle_widget
        yield self._content_widget

    def on_mount(self) -> None:
        self._refresh()
        self._thinking_timer = self.set_interval(
            0.1, self._refresh_thought_elapsed, pause=False
        )
        self._load_transcript()

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if hasattr(control, "has_class") and control.has_class("subagent-toggle"):
            self.expanded = not self.expanded
            self._refresh()
        else:
            self.expanded = False
            self._refresh()
        event.stop()

    def _header_label(self) -> str:
        marker = "»" if not self.expanded else "«"
        return f"{marker} [white]Subagent[/white] [gray]{_escape_markup(self.agent_type)}[/gray]"

    def _refresh(self) -> None:
        if self._toggle_widget is not None:
            self._toggle_widget.update(self._header_label())
        if self._content_widget is None:
            return
        if self.expanded:
            self._content_widget.remove_class("hidden")
        else:
            self._content_widget.add_class("hidden")

    def _load_transcript(self) -> None:
        if self._chat_view is not None:
            self._chat_view.load_transcript(_subagent_chat_transcript(self.transcript))
            self._loaded = True

    def add_event(self, event: dict) -> None:
        self.transcript.append(deepcopy(event))
        if event.get("_persist_only"):
            return
        if not self._loaded or self._chat_view is None:
            return
        kind = str(event.get("kind") or "")
        content = str(event.get("content") or "")
        if kind == "thought_start":
            return
        if kind == "thought_end":
            self._finish_thought_stream()
            return
        if kind == "thought_delta":
            if self._thinking_started_at is None:
                self._thinking_started_at = time.monotonic()
                self._chat_view.start_thought_stream()
            self._chat_view.append_thought_stream(content)
            return
        if kind == "message_delta":
            self._finish_thought_stream()
            self._chat_view.append_stream(content, role="assistant")
            return
        if kind in {"tool_call", "tool_result"}:
            self._finish_thought_stream()
        for entry in _subagent_chat_transcript([event]):
            self._chat_view._replay_transcript_entry(entry)

    def persistent_transcript(self) -> list[dict]:
        return [
            deepcopy(event)
            for event in self.transcript
            if str(event.get("kind") or "")
            not in {"thought_start", "thought_delta", "message_delta"}
        ]

    def _refresh_thought_elapsed(self) -> None:
        if self._thinking_started_at is None or self._chat_view is None:
            return
        self._chat_view.update_thought_stream_elapsed(
            max(0.0, time.monotonic() - self._thinking_started_at)
        )

    def _finish_thought_stream(self) -> None:
        if self._thinking_started_at is None or self._chat_view is None:
            return
        self._chat_view.finish_thought_stream(
            max(0.0, time.monotonic() - self._thinking_started_at)
        )
        self._thinking_started_at = None


def _subagent_chat_transcript(transcript: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for entry in transcript:
        if not isinstance(entry, dict):
            continue
        if entry.get("_persist_only"):
            entry = dict(entry)
            entry.pop("_persist_only", None)
        kind = str(entry.get("kind") or "")
        if kind in {"thought_start", "thought_delta", "message_delta"}:
            continue
        if kind in {"message", "thought"}:
            entries.append(entry)
            continue
        if kind == "tool_call":
            name = str(entry.get("name") or "")
            arguments = entry.get("arguments", {})
            description = _subagent_explored_description(name, arguments)
            if description:
                entries.append({
                    "kind": "explored_entry",
                    "tool_name": name,
                    "description": description,
                })
            continue
        if kind != "tool_result":
            continue
        display = entry.get("display")
        if isinstance(display, dict):
            display_kind = str(display.get("kind") or "")
            if display_kind == "web_fetch":
                entries.append({"kind": "web_fetch", "url": display.get("url", "")})
                continue
            if display_kind == "web_search":
                entries.append({
                    "kind": "web_search",
                    "content": display.get("content", ""),
                })
                continue
            if display_kind in {"file_edit", "file_write"}:
                entries.append({
                    "kind": "edit" if display_kind == "file_edit" else "write",
                    "file_path": display.get("file_path", ""),
                    "additions": display.get("additions", 0),
                    "deletions": display.get("deletions", 0),
                    "diff": display.get("diff", ""),
                })
                continue
            if display_kind == "shell":
                entries.append({
                    "kind": "shell",
                    "command": display.get("command", ""),
                    "output": display.get("output", ""),
                })
                continue
    return entries


def _subagent_explored_description(name: str, arguments) -> str:
    if not isinstance(arguments, dict):
        return ""
    if name == "read_file":
        parts = ["[white]Read[/white]"]
        file_path = _escape_markup(arguments.get("file_path") or "")
        if file_path:
            parts.append(f"[gray]{file_path}[/gray]")
        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")
        if start_line is not None and end_line is not None:
            parts.append(f"[gray]offset={start_line} limit={end_line}[/gray]")
        elif start_line is not None:
            parts.append(f"[gray]offset={start_line}[/gray]")
        return " ".join(parts)
    if name == "read_program_docs":
        return "[white]Read program docs[/white]"
    if name == "list_skills":
        return "[white]List skills[/white]"
    if name == "read_skill":
        parts = ["[white]Read skill[/white]"]
        skill_name = _escape_markup(arguments.get("name") or "")
        if skill_name:
            parts.append(f"[gray]{skill_name}[/gray]")
        return " ".join(parts)
    if name == "grep":
        parts = ["[white]Grep[/white]"]
        pattern = _escape_markup(arguments.get("pattern") or "")
        if pattern:
            parts.append(f"[gray]{pattern}[/gray]")
        if arguments.get("include"):
            parts.append(f"[gray]include={_escape_markup(arguments['include'])}[/gray]")
        if arguments.get("path"):
            parts.append(f"[gray]path={_escape_markup(arguments['path'])}[/gray]")
        return " ".join(parts)
    if name == "glob":
        return f"[white]Glob[/white] [gray]{_escape_markup(arguments.get('pattern') or '')}[/gray]"
    if name == "list_dir":
        return f"[white]List dir[/white] [gray]{_escape_markup(arguments.get('path') or '.')}[/gray]"
    return ""


class EditedBlock(Vertical):
    def __init__(self):
        super().__init__()

    def add_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        row = DiffFileRow(
            "[gray]#[/] Edit",
            file_path,
            additions,
            deletions,
            diff,
            show_stats=True,
            status=status,
        )
        self.mount(row)


class WrittenBlock(Vertical):
    def __init__(self):
        super().__init__()

    def add_entry(
        self,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        status: str = "",
    ) -> None:
        row = DiffFileRow(
            "[gray]#[/] Write",
            file_path,
            additions,
            deletions,
            diff,
            show_stats=False,
            status=status,
        )
        self.mount(row)


class ShellBlock(Vertical):
    def __init__(self):
        super().__init__()

    def add_entry(self, command: str, output: str) -> None:
        row = ShellRow(command, output)
        self.mount(row)


class ShellRow(Vertical):
    """A shell command row with single-level expansion.
    Collapsed: shows '$ Shell command' (truncated).
    Expanded: shows full command + output in a dark container.
    """

    def __init__(self, command: str, output: str):
        super().__init__()
        self.command = str(command or "")
        self.output = str(output or "")
        self._expanded = False
        self._header_command: Static | None = None
        self._output_widget: Static | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="shell-row-header"):
            yield Static("$", classes="shell-row-label", markup=True, expand=False)
            yield Static(
                "Shell", classes="shell-row-shell-label", markup=True, expand=False
            )
            self._header_command = Static(
                _escape_markup(self.command),
                classes="shell-row-command",
                markup=True,
                expand=False,
            )
            yield self._header_command
        self._output_widget = Static(
            _escape_markup(self.output.rstrip()),
            classes="shell-output-display",
            markup=True,
            expand=False,
        )
        with Vertical(classes="shell-row-wrap hidden"):
            yield HalfRowSpacer(classes="shell-row-top-spacer")
            with Vertical(classes="shell-row-container"):
                yield Static(
                    _escape_markup(self.command),
                    classes="shell-command-display",
                    markup=True,
                    expand=False,
                )
                yield self._output_widget
            yield BottomHalfRowSpacer(classes="shell-row-bottom-spacer")

    def on_mount(self) -> None:
        self._update_state()
        self._refresh_header_command()

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_header_command()

    def on_click(self, event: events.Click) -> None:
        self._expanded = not self._expanded
        self._update_state()
        event.stop()

    def _update_state(self) -> None:
        try:
            wrap = self.query_one(".shell-row-wrap", Vertical)
        except NoMatches:
            return
        if self._expanded:
            wrap.remove_class("hidden")
        else:
            wrap.add_class("hidden")
        hc = self._header_command
        if hc is not None:
            if self._expanded:
                hc.add_class("hidden")
            else:
                hc.remove_class("hidden")
                self._refresh_header_command()

    @staticmethod
    def _truncate_command_for_width(command: str, width: int) -> str:
        text = str(command or "")
        if width <= 0 or not text:
            return ""
        if cell_len(text) <= width:
            return text
        if width <= 3:
            return "." * width

        reserved = width - 3
        result: list[str] = []
        used = 0
        for char in text:
            char_width = cell_len(char)
            if used + char_width > reserved:
                break
            result.append(char)
            used += char_width
        return "".join(result) + "..."

    def _refresh_header_command(self) -> None:
        hc = self._header_command
        if hc is None:
            return
        width = max(0, hc.content_region.width or hc.size.width)
        if width <= 0:
            return
        hc.update(_escape_markup(self._truncate_command_for_width(self.command, width)))


class DiffFileRow(Vertical):
    """A write/edit row with two-level expansion.
    First click shows a file-row container with half-row spacers.
    Second click on the file-row shows the diff.
    """

    def __init__(
        self,
        label: str,
        file_path: str,
        additions: int,
        deletions: int,
        diff: str,
        show_stats: bool = True,
        status: str = "",
    ):
        super().__init__()
        self.label = str(label or "")
        self.file_path = str(file_path or "")
        self.additions = int(additions or 0)
        self.deletions = int(deletions or 0)
        self.diff = str(diff or "")
        self.show_stats = bool(show_stats)
        self.status = str(status or "").strip().lower()
        self._row_expanded = False
        self._row_container: Vertical | None = None
        self._file_row: ChangedFileRow | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="diff-row-header"):
            yield Static(
                self._label_markup(),
                classes="diff-row-label",
                markup=True,
                expand=False,
            )
            yield Static(
                _escape_markup(self.file_path),
                classes="diff-row-path",
                markup=True,
                expand=False,
            )
            if self.show_stats:
                yield Static(
                    self._stats_text(),
                    classes="diff-row-stats",
                    markup=True,
                    expand=False,
                )
        self._file_row = ChangedFileRow({
            "file_path": self.file_path,
            "additions": self.additions,
            "deletions": self.deletions,
            "diff": self.diff,
        })
        with Vertical(classes="diff-file-row-wrap hidden"):
            yield HalfRowSpacer(classes="diff-file-row-top-spacer")
            with Vertical(classes="diff-file-row-container"):
                yield self._file_row
            yield BottomHalfRowSpacer(classes="diff-file-row-bottom-spacer")

    def on_mount(self) -> None:
        pass

    def on_click(self, event: events.Click) -> None:
        if self._file_row is None:
            return
        try:
            wrap = self.query_one(".diff-file-row-wrap", Vertical)
        except NoMatches:
            return
        self._row_expanded = not self._row_expanded
        if self._row_expanded:
            wrap.remove_class("hidden")
        else:
            wrap.add_class("hidden")
            self._file_row.expanded = False
            if self._file_row._content_widget:
                self._file_row._content_widget.add_class("hidden")
        event.stop()

    def _stats_text(self) -> str:
        if self.status == "rejected":
            return ""
        parts = []
        if self.additions:
            parts.append(f"[#7fd97f]+{self.additions}[/]")
        if self.deletions:
            parts.append(f"[#d97f7f]-{self.deletions}[/]")
        return " ".join(parts)

    def _label_markup(self) -> str:
        if self.status == "rejected":
            return f"{self.label} [gray](rejected)[/]"
        return self.label


class ChangedFilesBlock(Vertical):
    def __init__(self, files: list[dict]):
        super().__init__()
        self.files = list(files or [])

    def compose(self) -> ComposeResult:
        yield Static(self._header_label(), classes="changed-files-toggle", markup=True)
        yield HalfRowSpacer(classes="changed-files-top-spacer")
        with Vertical(classes="changed-files-rows"):
            for f in self.files:
                yield ChangedFileRow(f)
        yield BottomHalfRowSpacer(classes="changed-files-bottom-spacer")

    def _header_label(self) -> str:
        count = len(self.files)
        total_add = sum(int(f.get("additions", 0) or 0) for f in self.files)
        total_del = sum(int(f.get("deletions", 0) or 0) for f in self.files)
        label = f"{count} Changed file" if count == 1 else f"{count} Changed files"
        return (
            f"[white]{label}[/white] [#7fd97f]+{total_add}[/] [#d97f7f]-{total_del}[/]"
        )


class ChangedFileRow(Vertical):
    def __init__(self, file_info: dict):
        super().__init__()
        self.file_path = str((file_info or {}).get("file_path") or "")
        self.additions = int((file_info or {}).get("additions", 0) or 0)
        self.deletions = int((file_info or {}).get("deletions", 0) or 0)
        self.diff = str((file_info or {}).get("diff") or "")
        self.expanded = False
        self._path_widget: Static | None = None
        self._stats_widget: Static | None = None
        self._content_widget: DiffContent | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="changed-file-row-header"):
            self._path_widget = Static(
                _escape_markup(self.file_path),
                classes="changed-file-row-path",
                markup=True,
                expand=False,
            )
            self._stats_widget = Static(
                f"[#7fd97f]+{self.additions}[/] [#d97f7f]-{self.deletions}[/]",
                classes="changed-file-row-stats",
                markup=True,
                expand=False,
            )
            yield self._path_widget
            yield self._stats_widget
        self._content_widget = DiffContent(self.diff, self.file_path)
        yield self._content_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        self.expanded = not self.expanded
        self._refresh()
        event.stop()

    def _refresh(self) -> None:
        content = self._content_widget
        if content is None:
            return
        if self.expanded and self.diff:
            content.remove_class("hidden")
        else:
            content.add_class("hidden")


class DiffContent(Static):
    """Renders diff content with full-width colored backgrounds and line numbers."""

    def __init__(self, diff_text: str, file_path: str = "", **kwargs):
        self._diff_lines = _parse_diff_lines(diff_text)
        self._lexer_name = _get_diff_lexer_name(file_path)
        max_num = max((ln for _, ln, _ in self._diff_lines), default=0)
        self._num_width = max(1, len(str(max_num)))
        super().__init__("", markup=False, **kwargs)

    def on_mount(self) -> None:
        self.styles.height = max(1, len(self._diff_lines))

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip.blank(1)
        if y < 0 or y >= len(self._diff_lines):
            return Strip.blank(width)
        line_type, line_num, content = self._diff_lines[y]
        return _build_diff_strip(
            line_type,
            line_num,
            content,
            width,
            self._num_width,
            self._lexer_name,
        )


_DIFF_HUNK_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _parse_diff_lines(diff_text: str) -> list[tuple[str, int, str]]:
    """Parse a unified diff into (type, line_number, content) tuples.

    type is 'add', 'del', or 'ctx'. line_number is the old line for del/ctx,
    new line for add.
    """
    result: list[tuple[str, int, str]] = []
    old_line = 0
    new_line = 0
    for line in (diff_text or "").splitlines():
        m = _DIFF_HUNK_RE.match(line)
        if m:
            old_line = int(m.group(1))
            new_line = int(m.group(2))
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("+"):
            result.append(("add", new_line, line[1:]))
            new_line += 1
        elif line.startswith("-"):
            result.append(("del", old_line, line[1:]))
            old_line += 1
        else:
            content = line[1:] if line.startswith(" ") else line
            result.append(("ctx", old_line, content))
            old_line += 1
            new_line += 1
    return result


@lru_cache(maxsize=128)
def _get_diff_lexer_name(file_path: str) -> str | None:
    try:
        lexer = get_lexer_for_filename(str(file_path or ""))
    except (ClassNotFound, ValueError):
        return None
    aliases = list(getattr(lexer, "aliases", []) or [])
    if aliases:
        return aliases[0]
    return getattr(lexer, "name", None)


@lru_cache(maxsize=4096)
def _highlight_diff_content(
    content: str, lexer_name: str, content_width: int
) -> tuple[Segment, ...]:
    if content_width <= 0:
        return ()
    console = Console(
        force_terminal=False,
        color_system=None,
        width=content_width,
        highlight=False,
    )
    syntax = Syntax(
        content,
        lexer_name,
        line_numbers=False,
        word_wrap=False,
        code_width=content_width,
        background_color="default",
    )
    lines = console.render_lines(
        syntax,
        console.options.update(width=content_width),
        pad=False,
    )
    if not lines:
        return ()
    return tuple(lines[0])


def _build_diff_strip(
    line_type: str,
    line_num: int,
    content: str,
    width: int,
    num_width: int = 3,
    lexer_name: str | None = None,
) -> Strip:
    """Build a single Strip for a diff line with full-width colored background."""
    if width <= 0:
        return Strip.blank(1)

    gap = 1
    content_start = num_width + gap
    content_width = max(0, width - content_start)

    if line_type == "add":
        fg = DIFF_ADD_FG
        bg = DIFF_ADD_BG
    elif line_type == "del":
        fg = DIFF_DEL_FG
        bg = DIFF_DEL_BG
    else:
        fg = TEXT_MUTED
        bg = INFO_BAR_BACKGROUND

    segments: list[Segment] = []

    num_str = str(line_num) if line_num else ""
    num_text = num_str.rjust(num_width)
    num_style = Style(
        color=fg,
        bgcolor=INFO_BAR_BACKGROUND,
    )
    segments.append(Segment(num_text, num_style))

    if gap > 0:
        segments.append(Segment(" " * gap, Style(bgcolor=INFO_BAR_BACKGROUND)))

    if content_width > 0:
        content_style = Style(color=fg, bgcolor=bg)
        display_width = 0
        if lexer_name:
            try:
                highlighted = _highlight_diff_content(
                    content, lexer_name, content_width
                )
            except Exception:
                highlighted = ()
            for segment in highlighted:
                if display_width >= content_width:
                    break
                segment_text = segment.text
                if not segment_text:
                    continue
                if display_width + cell_len(segment_text) > content_width:
                    break
                display_width += cell_len(segment_text)
                merged_style = content_style
                if segment.style is not None:
                    merged_style += segment.style + Style(bgcolor=bg)
                segments.append(Segment(segment_text, merged_style))
        if display_width < content_width:
            plain_content = content
            if display_width > 0:
                consumed = 0
                char_index = 0
                while char_index < len(plain_content) and consumed < display_width:
                    consumed += cell_len(plain_content[char_index])
                    char_index += 1
                plain_content = plain_content[char_index:]
            remaining_width = content_width - display_width
            display = plain_content[:remaining_width]
            pad_count = remaining_width - cell_len(display)
            if pad_count > 0:
                display = display + " " * pad_count
            segments.append(Segment(display, content_style))

    return Strip(segments)


def _escape_markup(text: str) -> str:
    return str(text or "").replace("[", r"\[")
