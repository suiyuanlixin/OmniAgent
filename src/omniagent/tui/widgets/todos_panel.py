from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static
from textual.widget import Widget

from ..theme import (
    SURFACE_BACKGROUND,
    TEXT_MUTED,
    TEXT_PRIMARY,
    render_css,
)
from ..widgets.chat_input import BottomHalfRowSpacer


def _todo_status_symbol(status: str) -> str:
    status = str(status or "").strip().lower()
    if status in {"completed", "in_progress"}:
        return "■"
    return "□"


class TodoLine(Static):
    def __init__(self, item: dict | None = None, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.item = item or {}

    def set_item(self, item: dict | None) -> None:
        self.item = item or {}
        self.refresh()

    def render(self) -> Text:
        item = self.item or {}
        status = str(item.get("status") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        symbol = _todo_status_symbol(status)
        completed = status == "completed"
        background = (
            self.styles.background.hex
            if self.styles.background is not None
            else SURFACE_BACKGROUND
        )

        text = Text(no_wrap=True, overflow="crop")
        symbol_color = TEXT_MUTED if completed else TEXT_PRIMARY
        text_color = TEXT_MUTED if completed else TEXT_PRIMARY

        text.append(symbol, style=Style(color=symbol_color, bgcolor=background))
        text.append(" ", style=Style(color=text_color, bgcolor=background))
        start = len(text)
        text.append(
            content,
            style=Style(color=text_color, bgcolor=background),
        )
        if completed and len(text) > start:
            text.stylize("strike", start, len(text))
        return text


class TodosPanel(Widget):
    DEFAULT_CSS = render_css(
        """
    TodosPanel {
        display: none;
        width: 100%;
        height: auto;
        min-width: 0;
        padding: 0;
        margin: 0 1;
        align-horizontal: center;
        background: $PAGE_BACKGROUND;
    }
    TodosPanel.visible {
        display: block;
    }
    TodosPanel.prompt-active {
        display: none;
    }

    TodosPanel > #todos-shell {
        width: 100%;
        min-width: 0;
        max-width: 78;
        height: auto;
        background: $PAGE_BACKGROUND;
    }

    TodosPanel > #todos-shell > #todos-top-edge {
        width: 100%;
        height: 1;
        background: $PAGE_BACKGROUND;
        color: $SURFACE_BACKGROUND;
    }

    TodosPanel > #todos-shell > #todos-panel {
        width: 100%;
        height: auto;
        padding: 0;
        background: $SURFACE_BACKGROUND;
    }

    #todos-header {
        width: 1fr;
        height: 1;
        margin: 0 2;
        background: $SURFACE_BACKGROUND;
    }

    #todos-summary {
        width: auto;
        height: 1;
        color: $TEXT_PRIMARY;
        background: $SURFACE_BACKGROUND;
    }

    #todos-current {
        width: 1fr;
        min-width: 0;
        height: 1;
        color: $TEXT_MUTED;
        background: $SURFACE_BACKGROUND;
        margin-left: 1;
        overflow: hidden;
    }
    #todos-current.hidden {
        display: none;
    }

    #todos-header-spacer {
        width: 1fr;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    #todos-toggle {
        width: auto;
        min-width: 1;
        height: 1;
        color: $TEXT_PRIMARY;
        background: $SURFACE_BACKGROUND;
    }

    #todos-list {
        width: 1fr;
        height: auto;
        margin: 1 2 0 2;
        background: $SURFACE_BACKGROUND;
    }
    #todos-list.hidden {
        display: none;
    }

    #todos-list > TodoLine {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        background: $SURFACE_BACKGROUND;
    }
    """
    )

    def __init__(
        self,
        items: list[dict] | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.items: list[dict] = [
            item for item in items or [] if isinstance(item, dict)
        ]
        self.expanded = True
        self._summary_widget: Static | None = None
        self._current_widget: Static | None = None
        self._toggle_widget: Static | None = None
        self._list_widget: Vertical | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="todos-shell"):
            yield BottomHalfRowSpacer(id="todos-top-edge")
            with Vertical(id="todos-panel"):
                with Horizontal(id="todos-header"):
                    self._summary_widget = Static("", id="todos-summary")
                    self._current_widget = Static("", id="todos-current")
                    yield self._summary_widget
                    yield self._current_widget
                    yield Static("", id="todos-header-spacer")
                    self._toggle_widget = Static("=", id="todos-toggle")
                    yield self._toggle_widget
                self._list_widget = Vertical(id="todos-list")
                yield self._list_widget

    def on_mount(self) -> None:
        self._refresh()

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if not hasattr(control, "id"):
            return
        if str(getattr(control, "id", "") or "") == "todos-toggle":
            self.expanded = not self.expanded
            self._refresh()
            event.stop()

    def set_items(self, items: list[dict] | None) -> None:
        had_items = bool(self.items)
        next_items = [item for item in items or [] if isinstance(item, dict)]
        has_items = bool(next_items)
        if had_items and not has_items:
            self.expanded = False
        elif (not had_items) and has_items:
            self.expanded = True
        self.items = next_items
        self._refresh()

    def _refresh(self) -> None:
        summary = self._summary_widget
        current = self._current_widget
        toggle = self._toggle_widget
        rows = self._list_widget
        if summary is None or current is None or toggle is None or rows is None:
            return

        if self.items:
            self.add_class("visible")
        else:
            self.remove_class("visible")

        completed_count = sum(
            1
            for item in self.items
            if str(item.get("status") or "").strip().lower() == "completed"
        )
        total_count = len(self.items)
        summary.update(f"{completed_count} of {total_count} todos completed")
        toggle.update("=")

        active = next(
            (
                str(item.get("content") or "").strip()
                for item in self.items
                if str(item.get("status") or "").strip().lower() == "in_progress"
            ),
            "",
        )
        if self.expanded:
            current.add_class("hidden")
            rows.remove_class("hidden")
        else:
            rows.add_class("hidden")
            if active:
                current.update(active)
                current.remove_class("hidden")
            else:
                current.update("")
                current.add_class("hidden")

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
