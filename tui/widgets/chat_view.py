from __future__ import annotations

from copy import deepcopy
import re
from datetime import datetime

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.strip import Strip
from textual.widgets import Static
from textual.widget import Widget

from tui.theme import (
    DIFF_ADD_BG,
    DIFF_ADD_FG,
    DIFF_DEL_BG,
    DIFF_DEL_FG,
    INFO_BAR_BACKGROUND,
    PAGE_BACKGROUND,
    SURFACE_BACKGROUND,
    TEXT_MUTED,
    TEXT_PRIMARY,
    render_css,
)
from tui.widgets.chat_input import HalfRowSpacer, BottomHalfRowSpacer


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = []
        self._transcript: list[dict] = []
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

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-log")

    def add_message(self, role: str, content: str) -> None:
        self._activate_message_output()
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None
        if role == "user":
            self.query_one("#chat-log", VerticalScroll).mount(
                Static("", classes="message-spacer")
            )
        row, content_widget = _build_message_widgets(role, content)
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
        row, _ = _build_message_widgets("status", content)
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
            row, content_widget = _build_message_widgets("status", prefix)
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
            entry = self._transcript.pop()

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
        self, file_path: str, additions: int, deletions: int, diff: str
    ) -> None:
        self._activate_aux_output("edit")
        if self._edited_block is None:
            block = EditedBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._edited_block = block
        self._edited_block.add_entry(file_path, additions, deletions, diff)
        self._append_transcript_entry({
            "kind": "edit",
            "file_path": str(file_path or ""),
            "additions": int(additions or 0),
            "deletions": int(deletions or 0),
            "diff": str(diff or ""),
        })
        self.call_after_refresh(self._scroll_end)

    def add_write_entry(
        self, file_path: str, additions: int, deletions: int, diff: str
    ) -> None:
        self._activate_aux_output("write")
        if self._write_block is None:
            block = WrittenBlock()
            self.query_one("#chat-log", VerticalScroll).mount(block)
            self.call_after_refresh(self._scroll_end)
            self._write_block = block
        self._write_block.add_entry(file_path, additions, deletions, diff)
        self._append_transcript_entry({
            "kind": "write",
            "file_path": str(file_path or ""),
            "additions": int(additions or 0),
            "deletions": int(deletions or 0),
            "diff": str(diff or ""),
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

    def _reset_message_stream(self) -> None:
        self._stream_target = None
        self._stream_role = None
        self._stream_content = ""
        self._stream_transcript_index = None

    def get_transcript(self) -> list[dict]:
        return deepcopy(self._transcript)

    def load_transcript(self, transcript: list[dict]) -> None:
        self.clear()
        for entry in list(transcript or []):
            self._replay_transcript_entry(entry)
        self._reset_message_stream()
        self._thought_stream_target = None
        self._thought_stream_content = ""
        self._thought_stream_transcript_index = None

    def _append_transcript_entry(self, entry: dict) -> None:
        self._transcript.append(deepcopy(entry))

    def _update_transcript_entry(self, index: int | None, **changes) -> None:
        if index is None or index < 0 or index >= len(self._transcript):
            return
        entry = dict(self._transcript[index])
        entry.update(changes)
        self._transcript[index] = deepcopy(entry)

    def _replay_transcript_entry(self, entry: dict) -> None:
        if not isinstance(entry, dict):
            return
        kind = str(entry.get("kind") or "")
        if kind == "message":
            role = str(entry.get("role") or "")
            content = str(entry.get("content") or "")
            if role == "status":
                self.add_status(content)
            elif role:
                self.add_message(role, content)
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
            )
            return
        if kind == "write":
            self.add_write_entry(
                str(entry.get("file_path") or ""),
                int(entry.get("additions", 0) or 0),
                int(entry.get("deletions", 0) or 0),
                str(entry.get("diff") or ""),
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
        line_text = self._plain_content()[raw_start:raw_end]
        return raw_start + self._index_from_column(line_text, column)

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


class EditedBlock(Vertical):
    def __init__(self):
        super().__init__()

    def add_entry(
        self, file_path: str, additions: int, deletions: int, diff: str
    ) -> None:
        row = DiffFileRow(
            "[gray]#[/] Edit", file_path, additions, deletions, diff, show_stats=True
        )
        self.mount(row)


class WrittenBlock(Vertical):
    def __init__(self):
        super().__init__()

    def add_entry(
        self, file_path: str, additions: int, deletions: int, diff: str
    ) -> None:
        row = DiffFileRow(
            "[gray]#[/] Write", file_path, additions, deletions, diff, show_stats=False
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
    ):
        super().__init__()
        self.label = str(label or "")
        self.file_path = str(file_path or "")
        self.additions = int(additions or 0)
        self.deletions = int(deletions or 0)
        self.diff = str(diff or "")
        self.show_stats = bool(show_stats)
        self._row_expanded = False
        self._row_container: Vertical | None = None
        self._file_row: ChangedFileRow | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="diff-row-header"):
            yield Static(
                self.label, classes="diff-row-label", markup=True, expand=False
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
        parts = []
        if self.additions:
            parts.append(f"[#7fd97f]+{self.additions}[/]")
        if self.deletions:
            parts.append(f"[#d97f7f]-{self.deletions}[/]")
        return " ".join(parts)


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
        self._content_widget = DiffContent(self.diff)
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

    def __init__(self, diff_text: str, **kwargs):
        self._diff_lines = _parse_diff_lines(diff_text)
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
        return _build_diff_strip(line_type, line_num, content, width, self._num_width)


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


def _build_diff_strip(
    line_type: str, line_num: int, content: str, width: int, num_width: int = 3
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
        display = content[:content_width]
        pad_count = content_width - cell_len(display)
        if pad_count > 0:
            display = display + " " * pad_count
        content_style = Style(color=fg, bgcolor=bg)
        segments.append(Segment(display, content_style))

    return Strip(segments)


def _escape_markup(text: str) -> str:
    return str(text or "").replace("[", r"\[")
