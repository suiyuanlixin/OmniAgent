from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer


class _ReferenceOptionItem(Static):
    can_focus = True


class _ReferenceValueTrigger(Static):
    can_focus = True


class _ReferenceAction(Static):
    can_focus = True


class ReferenceModal(ModalScreen[dict | None]):
    TYPE_OPTIONS = (("File", "file"), ("Folder", "folder"))

    DEFAULT_CSS = render_css(
        """
    ReferenceModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #reference-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #reference-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    .reference-outer-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    .reference-outer-gap.hidden,
    .hidden {
        display: none;
    }

    #reference-wrapper {
        width: 100%;
        height: auto;
        min-height: 8;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #reference-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #reference-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #reference-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #reference-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
    }

    #reference-title {
        width: 1fr;
        text-align: left;
        text-style: bold;
        padding: 0;
    }

    #reference-close-hint {
        width: auto;
        height: 1;
        dock: right;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #reference-body,
    #reference-list {
        width: 100%;
        height: auto;
    }

    #reference-body {
        padding: 0 1 0 2;
    }

    .reference-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    .reference-row {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        margin: 0;
    }

    .reference-name {
        width: 1fr;
        text-align: left;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    .reference-control-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
    }

    .reference-control-trigger,
    .reference-control-trigger:hover,
    .reference-control-trigger:focus,
    .reference-control-trigger.-active {
        width: auto;
        min-width: 7;
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

    .reference-control-trigger.placeholder,
    .reference-control-trigger.placeholder:hover,
    .reference-control-trigger.placeholder:focus,
    .reference-control-trigger.placeholder.-active {
        color: $TEXT_MUTED;
    }

    .reference-options {
        display: none;
        width: auto;
        min-width: 0;
        height: auto;
        background: $INFO_BAR_BACKGROUND;
        border: none;
        padding: 0;
        overlay: screen;
        constrain: none inside;
        align-horizontal: right;
    }

    .reference-options.open {
        display: block;
    }

    .reference-option-btn {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        background-tint: $INFO_BAR_BACKGROUND;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        text-align: right;
        content-align: right middle;
        padding: 0 1;
        margin: 0;
    }

    .reference-option-btn:hover,
    .reference-option-btn:focus,
    .reference-option-btn.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $PAGE_BACKGROUND;
    }

    #reference-edit-input {
        width: auto;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        margin: 0;
    }

    .reference-action-row,
    .reference-action-row:hover,
    .reference-action-row:focus,
    .reference-action-row.-active {
        width: 100%;
        background: transparent;
        color: $TEXT_PRIMARY;
    }

    .reference-action-row:hover,
    .reference-action-row:focus,
    .reference-action-row.-active {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .reference-action-row:hover .reference-name,
    .reference-action-row:focus .reference-name,
    .reference-action-row.-active .reference-name,
    .reference-action-row:hover .reference-action,
    .reference-action-row:focus .reference-action,
    .reference-action-row.-active .reference-action {
        color: $PAGE_BACKGROUND;
        background: transparent;
    }

    .reference-action,
    .reference-action:hover,
    .reference-action:focus,
    .reference-action.-active {
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

    #reference-overlay {
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        border: none;
    }

    #reference-overlay .option--highlighted {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    """
    )

    BINDINGS = [("escape", "dismiss_result(None)", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._draft: dict[str, str] = {"type": "file", "path": ""}
        self._select_open = False
        self._editing_path = False

    def compose(self) -> ComposeResult:
        with Container(id="reference-frame"):
            with Vertical(id="reference-stack"):
                yield Static(
                    "", id="reference-outer-gap-top", classes="reference-outer-gap"
                )
                with Container(id="reference-wrapper"):
                    yield HalfRowSpacer(id="reference-top-edge")
                    with Vertical(id="reference-dialog"):
                        with Horizontal(id="reference-header"):
                            yield Static("Add reference", id="reference-title")
                            yield Static("esc", id="reference-close-hint")
                        with Vertical(id="reference-body"):
                            yield Static(classes="reference-gap")
                            with Vertical(id="reference-list"):
                                with Horizontal(
                                    id="reference-type-row", classes="reference-row"
                                ):
                                    yield Static("Type", classes="reference-name")
                                    yield Container(
                                        _ReferenceValueTrigger(
                                            self._display_type(),
                                            id="reference-type-trigger",
                                            classes="reference-control-trigger",
                                        ),
                                        Vertical(
                                            *[
                                                _ReferenceOptionItem(
                                                    label,
                                                    id=f"reference-type-option-{value}",
                                                    classes="reference-option-btn",
                                                )
                                                for label, value in self.TYPE_OPTIONS
                                            ],
                                            id="reference-type-options",
                                            classes="reference-options",
                                        ),
                                        classes="reference-control-drop",
                                        id="reference-type-drop",
                                    )
                                with Horizontal(
                                    id="reference-path-row", classes="reference-row"
                                ):
                                    yield Static("Path", classes="reference-name")
                                    yield _ReferenceValueTrigger(
                                        self._display_path(),
                                        markup=False,
                                        id="reference-path-trigger",
                                        classes=self._path_trigger_classes(),
                                    )
                                yield Static(classes="reference-gap")
                                with Horizontal(
                                    id="reference-add-row",
                                    classes="reference-row reference-action-row",
                                ):
                                    yield Static("", classes="reference-name")
                                    yield _ReferenceAction(
                                        "Add",
                                        id="reference-add-action",
                                        classes="reference-action",
                                    )
                    yield HalfRowSpacer(id="reference-bottom-edge")
                yield Static(
                    "", id="reference-outer-gap-bottom", classes="reference-outer-gap"
                )

    def on_mount(self) -> None:
        self.call_after_refresh(self._update_layout_constraints)
        self.call_after_refresh(self._update_type_dropdown_metrics)
        self.query_one("#reference-path-trigger", _ReferenceValueTrigger).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)
        self.call_after_refresh(self._update_type_dropdown_metrics)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "reference-edit-input":
            self._finish_path_edit(event.value)
            event.stop()

    def on_click(self, event) -> None:
        target_id = self._click_target_id(event)
        if not target_id:
            return
        if self._editing_path and target_id not in {
            "reference-path-row",
            "reference-path-trigger",
            "reference-edit-input",
        }:
            self._finish_path_edit()
        if target_id == "reference-close-hint":
            self.dismiss(None)
            return
        if target_id in {"reference-add-row", "reference-add-action"}:
            self._submit()
            return
        if target_id in {"reference-type-row", "reference-type-trigger"}:
            self._toggle_type_options()
            return
        if target_id.startswith("reference-type-option-"):
            self._commit_type(target_id.rsplit("-", 1)[-1])
            return
        if target_id in {"reference-path-row", "reference-path-trigger"}:
            self._start_path_edit()
            return
        self._close_type_options()

    def on_key(self, event: Key) -> None:
        focused = self.focused
        focused_id = getattr(focused, "id", "")
        if event.key == "escape" and self._select_open:
            self._close_type_options()
            event.stop()
            return
        if event.key != "enter":
            return
        if focused_id == "reference-add-action":
            self._submit()
            event.stop()
            return
        if focused_id == "reference-type-trigger":
            self._toggle_type_options()
            event.stop()
            return
        if focused_id == "reference-path-trigger":
            self._start_path_edit()
            event.stop()

    def _click_target_id(self, event) -> str:
        widget = getattr(event, "widget", None)
        while widget is not None:
            widget_id = getattr(widget, "id", "") or ""
            if widget_id:
                return widget_id
            widget = getattr(widget, "parent", None)
        return ""

    def _display_type(self) -> str:
        current = str(self._draft.get("type") or "file")
        for label, value in self.TYPE_OPTIONS:
            if value == current:
                return label
        return "File"

    def _display_path(self) -> str:
        value = str(self._draft.get("path") or "")
        return value

    def _path_trigger_classes(self) -> str:
        classes = "reference-control-trigger"
        if not str(self._draft.get("path") or ""):
            classes += " placeholder"
        return classes

    def _toggle_type_options(self) -> None:
        if self._editing_path:
            self._finish_path_edit()
        options = self.query_one("#reference-type-options", Vertical)
        if self._select_open:
            options.remove_class("open")
            self._select_open = False
        else:
            options.add_class("open")
            self._select_open = True

    def _close_type_options(self) -> None:
        if not self._select_open:
            return
        try:
            self.query_one("#reference-type-options", Vertical).remove_class("open")
        except Exception:
            pass
        self._select_open = False

    def _commit_type(self, value: str) -> None:
        if value not in {"file", "folder"}:
            return
        self._draft["type"] = value
        trigger = self.query_one("#reference-type-trigger", _ReferenceValueTrigger)
        trigger.update(self._display_type())
        self._close_type_options()
        self.call_after_refresh(self._update_type_dropdown_metrics)
        trigger.focus()

    def _start_path_edit(self) -> None:
        self._close_type_options()
        if self._editing_path:
            try:
                self.query_one("#reference-edit-input", Input).focus()
                return
            except Exception:
                self._editing_path = False
        row = self.query_one("#reference-path-row", Horizontal)
        trigger = row.query_one("#reference-path-trigger", _ReferenceValueTrigger)
        trigger.display = False
        current_value = str(self._draft.get("path") or "")
        input_widget = Input(value=current_value, id="reference-edit-input")
        input_widget.styles.width = max(len(current_value) + 3, 20)
        row.mount(input_widget)
        input_widget.focus()
        self._editing_path = True

    def _finish_path_edit(self, value: str | None = None) -> None:
        if not self._editing_path:
            return
        row = self.query_one("#reference-path-row", Horizontal)
        trigger = row.query_one("#reference-path-trigger", _ReferenceValueTrigger)
        try:
            input_widget = row.query_one("#reference-edit-input", Input)
        except Exception:
            input_widget = None
        if value is None and input_widget is not None:
            value = input_widget.value
        self._draft["path"] = str(value or "").strip()
        if input_widget is not None:
            input_widget.remove()
        trigger.update(self._display_path())
        trigger.classes = self._path_trigger_classes()
        trigger.display = True
        trigger.focus()
        self._editing_path = False

    def _update_type_dropdown_metrics(self) -> None:
        try:
            trigger = self.query_one("#reference-type-trigger", _ReferenceValueTrigger)
            options = self.query_one("#reference-type-options", Vertical)
            drop = self.query_one("#reference-type-drop", Container)
        except Exception:
            return
        display_value = self._display_type()
        trigger_width = max(len(display_value) + 2, 7)
        option_width = (
            max((len(label) for label, _ in self.TYPE_OPTIONS), default=0) + 2
        )
        option_width = max(option_width, len(display_value) + 2)
        trigger.styles.width = trigger_width
        trigger.styles.min_width = trigger_width
        options.styles.width = option_width
        options.styles.min_width = option_width
        options.styles.offset = (trigger_width - option_width, 0)
        drop.styles.width = trigger_width
        drop.styles.min_width = trigger_width

    def _submit(self) -> None:
        if self._editing_path:
            self._finish_path_edit()
        self._close_type_options()
        path = str(self._draft.get("path") or "").strip()
        reference_type = str(self._draft.get("type") or "")
        if path and reference_type in {"file", "folder"}:
            self.dismiss({"type": reference_type, "path": path})

    def _update_layout_constraints(self) -> None:
        try:
            reference_stack = self.query_one("#reference-stack", Vertical)
            outer_top_gap = self.query_one("#reference-outer-gap-top", Static)
            outer_bottom_gap = self.query_one("#reference-outer-gap-bottom", Static)
        except Exception:
            return
        available_width = max(1, self.size.width - 8)
        reference_stack.styles.width = min(96, max(44, available_width))
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
