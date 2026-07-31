from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ..theme import render_css
from ..widgets.chat_input import HalfRowSpacer


class _ProjectAction(Static):
    can_focus = True


class _ProjectValueTrigger(Static):
    can_focus = True


class ProjectModal(ModalScreen[dict | None]):
    def __init__(self) -> None:
        super().__init__()
        self._draft: dict[str, str] = {"name": "", "path": ""}
        self._editing_key: str | None = None

    DEFAULT_CSS = render_css(
        """
    ProjectModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #project-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #project-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    .project-outer-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    .project-outer-gap.hidden,
    .hidden {
        display: none;
    }

    #project-wrapper {
        width: 100%;
        height: auto;
        min-height: 8;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #project-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #project-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #project-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #project-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
    }

    #project-title {
        width: 1fr;
        text-align: left;
        text-style: bold;
        padding: 0;
    }

    #project-close-hint {
        width: auto;
        height: 1;
        dock: right;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #project-body,
    #project-list {
        width: 100%;
        height: auto;
    }

    #project-body {
        padding: 0 1 0 2;
    }

    .project-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    .project-row {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        margin: 0;
    }

    .project-name {
        width: 1fr;
        text-align: left;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    .project-control-trigger,
    .project-control-trigger:hover,
    .project-control-trigger:focus,
    .project-control-trigger.-active {
        width: auto;
        min-width: 30;
        height: 1;
        background: $SURFACE_BACKGROUND;
        background-tint: $SURFACE_BACKGROUND;
        tint: transparent;
        border: none;
        border-top: none;
        border-bottom: none;
        outline: none;
        color: $TEXT_PRIMARY;
        margin: 0;
        padding: 0 1;
        text-align: right;
        content-align: right middle;
    }

    .project-action-row,
    .project-action-row:hover,
    .project-action-row:focus,
    .project-action-row.-active {
        width: 100%;
        background: transparent;
        color: $TEXT_PRIMARY;
    }

    .project-action-row:hover,
    .project-action-row:focus,
    .project-action-row.-active {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .project-action-row:hover .project-name,
    .project-action-row:focus .project-name,
    .project-action-row.-active .project-name,
    .project-action-row:hover .project-action,
    .project-action-row:focus .project-action,
    .project-action-row.-active .project-action {
        color: $PAGE_BACKGROUND;
        background: transparent;
    }

    .project-action,
    .project-action:hover,
    .project-action:focus,
    .project-action.-active {
        width: auto;
        height: 1;
        min-width: 5;
        background: $SURFACE_BACKGROUND;
        background-tint: $SURFACE_BACKGROUND;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        margin: 0;
        padding: 0 1;
        text-align: right;
        content-align: right middle;
    }

    #project-edit-input {
        width: auto;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Close"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="project-frame"):
            with Vertical(id="project-stack"):
                yield Static(
                    "", id="project-outer-gap-top", classes="project-outer-gap"
                )
                with Container(id="project-wrapper"):
                    yield HalfRowSpacer(id="project-top-edge")
                    with Vertical(id="project-dialog"):
                        with Horizontal(id="project-header"):
                            yield Static("New project", id="project-title")
                            yield Static("esc", id="project-close-hint")
                        with Vertical(id="project-body"):
                            yield Static(classes="project-gap")
                            with Vertical(id="project-list"):
                                with Horizontal(
                                    id="project-name-row", classes="project-row"
                                ):
                                    yield Static("Project name", classes="project-name")
                                    yield _ProjectValueTrigger(
                                        self._draft.get("name", ""),
                                        id="project-trigger-name",
                                        classes="project-control-trigger",
                                    )
                                with Horizontal(
                                    id="project-path-row", classes="project-row"
                                ):
                                    yield Static("Project path", classes="project-name")
                                    yield _ProjectValueTrigger(
                                        self._draft.get("path", ""),
                                        id="project-trigger-path",
                                        classes="project-control-trigger",
                                    )
                                yield Static(classes="project-gap")
                                with Horizontal(
                                    id="project-add-row",
                                    classes="project-row project-action-row",
                                ):
                                    yield Static("", classes="project-name")
                                    yield _ProjectAction(
                                        "Add",
                                        id="project-add-action",
                                        classes="project-action",
                                    )
                    yield HalfRowSpacer(id="project-bottom-edge")
                yield Static(
                    "", id="project-outer-gap-bottom", classes="project-outer-gap"
                )

    def on_mount(self) -> None:
        self.call_after_refresh(self._update_layout_constraints)
        self.query_one("#project-trigger-name", _ProjectValueTrigger).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "project-edit-input":
            self._finish_input_edit(event.value)
            return

    def on_click(self, event) -> None:
        target_id = self._click_target_id(event)
        if not target_id:
            return
        if target_id == "project-close-hint":
            self.dismiss(None)
            return
        if target_id in {"project-add-row", "project-add-action"}:
            self._submit_project()
            return
        if target_id in {"project-name-row", "project-trigger-name"}:
            self._start_input_edit("name")
            return
        if target_id in {"project-path-row", "project-trigger-path"}:
            self._start_input_edit("path")

    def on_key(self, event: Key) -> None:
        focused = self.focused
        focused_id = getattr(focused, "id", "")
        if event.key != "enter":
            return
        if focused_id == "project-add-action":
            self._submit_project()
            event.stop()
            return
        if focused_id == "project-trigger-name":
            self._start_input_edit("name")
            event.stop()
            return
        if focused_id == "project-trigger-path":
            self._start_input_edit("path")
            event.stop()

    def _submit_project(self) -> None:
        name = str(self._draft.get("name") or "").strip()
        path = str(self._draft.get("path") or "").strip()
        if name and path:
            self.dismiss({"name": name, "path": path})

    def _click_target_id(self, event) -> str:
        widget = getattr(event, "widget", None)
        while widget is not None:
            widget_id = getattr(widget, "id", "") or ""
            if widget_id:
                return widget_id
            widget = getattr(widget, "parent", None)
        return ""

    def _start_input_edit(self, key: str) -> None:
        if key not in {"name", "path"}:
            return
        if self._editing_key is not None:
            self._finish_input_edit()

        self._editing_key = key
        row_id = "project-name-row" if key == "name" else "project-path-row"
        trigger_id = "project-trigger-name" if key == "name" else "project-trigger-path"
        row = self.query_one(f"#{row_id}", Horizontal)
        trigger = row.query_one(f"#{trigger_id}", _ProjectValueTrigger)
        trigger.display = False

        current_value = str(self._draft.get(key) or "")
        input_widget = Input(value=current_value, id="project-edit-input")
        input_widget.styles.width = max(len(current_value) + 3, 12)
        row.mount(input_widget)
        input_widget.focus()

    def _finish_input_edit(self, value: str | None = None) -> None:
        if self._editing_key is None:
            return
        key = self._editing_key
        row_id = "project-name-row" if key == "name" else "project-path-row"
        trigger_id = "project-trigger-name" if key == "name" else "project-trigger-path"
        row = self.query_one(f"#{row_id}", Horizontal)
        trigger = row.query_one(f"#{trigger_id}", _ProjectValueTrigger)
        try:
            input_widget = row.query_one("#project-edit-input", Input)
        except Exception:
            input_widget = None

        if value is None and input_widget is not None:
            value = input_widget.value
        self._draft[key] = str(value or "")

        if input_widget is not None:
            input_widget.remove()

        trigger.update(str(self._draft.get(key) or ""))
        trigger.display = True
        trigger.focus()
        self._editing_key = None

    def _update_layout_constraints(self) -> None:
        try:
            project_stack = self.query_one("#project-stack", Vertical)
            outer_top_gap = self.query_one("#project-outer-gap-top", Static)
            outer_bottom_gap = self.query_one("#project-outer-gap-bottom", Static)
        except Exception:
            return
        available_width = max(1, self.size.width - 8)
        project_stack.styles.width = min(96, max(44, available_width))
        wrapper_min_height = 8
        show_outer_gaps = self.size.height >= (wrapper_min_height + 2)
        if show_outer_gaps:
            outer_top_gap.remove_class("hidden")
            outer_bottom_gap.remove_class("hidden")
        else:
            outer_top_gap.add_class("hidden")
            outer_bottom_gap.add_class("hidden")

    def action_dismiss_result(self, result: dict | None = None) -> None:
        self.dismiss(result)

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
