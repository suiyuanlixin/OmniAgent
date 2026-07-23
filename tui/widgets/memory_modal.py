from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer
from tui.widgets.chat_view import MarkdownMessageStatic


class _MemoryNavItem(Static):
    can_focus = True


class MemoryModal(ModalScreen[None]):
    DEFAULT_CSS = render_css(
        """
    MemoryModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #memory-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #memory-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    .memory-outer-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    #memory-wrapper {
        width: 100%;
        height: auto;
        min-height: 10;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #memory-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #memory-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #memory-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #memory-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
    }

    #memory-title {
        width: 1fr;
        text-align: left;
        text-style: bold;
        padding: 0;
    }

    #memory-close-btn {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #memory-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 0;
    }

    #memory-panel {
        width: 100%;
        height: auto;
        min-width: 0;
    }

    #memory-sidebar {
        width: 24;
        height: auto;
        padding: 0 1 0 0;
    }

    #memory-nav {
        width: 100%;
        height: auto;
    }

    #memory-nav-scroll,
    #memory-detail-scroll {
        width: 100%;
        min-width: 0;
        height: auto;
        min-height: 0;
        overflow-y: auto;
        scrollbar-size: 0 0;
    }

    #memory-detail-wrap {
        width: 1fr;
        min-width: 0;
        height: auto;
        padding: 0;
    }

    #memory-detail-content {
        width: 100%;
        min-width: 0;
        height: auto;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 1;
    }

    .memory-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    .memory-nav-item,
    .memory-nav-item:focus,
    .memory-nav-item.-active {
        width: 100%;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 1;
        margin: 0 0 0 1;
    }

    .memory-nav-item:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .memory-nav-item.selected,
    .memory-nav-item.selected:hover,
    .memory-nav-item.selected:focus,
    .memory-nav-item.selected.-active {
        color: $TEXT_PRIMARY;
        text-style: bold;
    }

    .memory-nav-item.selected:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Close"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(self, sections: list[dict], title: str = "Memory") -> None:
        super().__init__()
        self.sections = [dict(section) for section in sections or []]
        self.title = str(title or "Memory")
        self._selected_section_id = str(
            (self.sections[0].get("id") if self.sections else "") or ""
        )

    def compose(self) -> ComposeResult:
        with Container(id="memory-frame"):
            with Vertical(id="memory-stack"):
                yield Static("", classes="memory-outer-gap")
                with Container(id="memory-wrapper"):
                    yield HalfRowSpacer(id="memory-top-edge")
                    with Vertical(id="memory-dialog"):
                        with Horizontal(id="memory-header"):
                            yield Static(self.title, id="memory-title")
                            yield Static("esc", id="memory-close-btn")
                        with Vertical(id="memory-body"):
                            yield Static(classes="memory-gap")
                            with Horizontal(id="memory-panel"):
                                with Vertical(id="memory-sidebar"):
                                    with Vertical(id="memory-nav-scroll"):
                                        yield Vertical(id="memory-nav")
                                with Vertical(id="memory-detail-wrap"):
                                    with Vertical(id="memory-detail-scroll"):
                                        yield MarkdownMessageStatic(
                                            "", id="memory-detail-content"
                                        )
                    yield HalfRowSpacer(id="memory-bottom-edge")
                yield Static("", classes="memory-outer-gap")

    def on_mount(self) -> None:
        self._render_sections()
        self._refresh_nav_selection()
        self._update_detail()
        self.call_after_refresh(self._update_layout_constraints)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_click(self, event: events.Click) -> None:
        control_id = self._click_target_id(event)
        if not control_id:
            return
        if control_id == "memory-close-btn":
            self.dismiss(None)
            return
        if control_id.startswith("memory-nav-item-"):
            self._select_section(control_id.removeprefix("memory-nav-item-"))

    def action_dismiss_result(self, result: None = None) -> None:
        self.dismiss(result)

    def _click_target_id(self, event: events.Click) -> str:
        control = getattr(event, "control", None) or getattr(event, "widget", None)
        while control is not None:
            control_id = getattr(control, "id", None)
            if control_id:
                return str(control_id)
            control = getattr(control, "parent", None)
        return ""

    def _render_sections(self) -> None:
        nav = self.query_one("#memory-nav", Vertical)
        for child in list(nav.children):
            child.remove()
        for section in self.sections:
            section_id = str(section.get("id") or "")
            classes = "memory-nav-item"
            if section_id == self._selected_section_id:
                classes += " selected"
            nav.mount(
                _MemoryNavItem(
                    str(section.get("label") or ""),
                    id=f"memory-nav-item-{section_id}",
                    classes=classes,
                )
            )

    def _select_section(self, section_id: str) -> None:
        self._selected_section_id = str(section_id or "")
        self._refresh_nav_selection()
        self._update_detail()
        self.call_after_refresh(self._update_layout_constraints)

    def _refresh_nav_selection(self) -> None:
        for section in self.sections:
            section_id = str(section.get("id") or "")
            try:
                item = self.query_one(f"#memory-nav-item-{section_id}", _MemoryNavItem)
            except Exception:
                continue
            if section_id == self._selected_section_id:
                item.add_class("selected")
            else:
                item.remove_class("selected")

    def _update_detail(self) -> None:
        content_widget = self.query_one("#memory-detail-content", MarkdownMessageStatic)
        selected = next(
            (
                section
                for section in self.sections
                if str(section.get("id") or "") == self._selected_section_id
            ),
            self.sections[0] if self.sections else {"content": ""},
        )
        content = str(selected.get("content") or "").strip()
        content_widget.update(content)

    def _update_layout_constraints(self) -> None:
        try:
            memory_stack = self.query_one("#memory-stack", Vertical)
            nav_scroll = self.query_one("#memory-nav-scroll", Vertical)
            detail_scroll = self.query_one("#memory-detail-scroll", Vertical)
        except Exception:
            return
        available_width = max(1, self.size.width - 8)
        memory_stack.styles.width = available_width
        available_height = max(3, self.size.height - 6)
        nav_scroll.styles.max_height = available_height
        detail_scroll.styles.max_height = available_height

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
