from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Button, Input, Static
from textual.screen import ModalScreen

from tui.theme import render_css


from tui.widgets.chat_input import HalfRowSpacer


_EDIT_NONE = "none"
_EDIT_TOGGLE = "toggle"
_EDIT_SELECT = "select"
_EDIT_INPUT = "input"


class _OptionButton(Button):
    pass


class SettingsModal(ModalScreen[None]):
    """Interactive settings modal window centered on screen."""

    def __init__(self, settings_rows=None, app=None):
        super().__init__()
        self.settings_rows = list(settings_rows or [])
        self.app_ref = app
        self._editing_row_index: int | None = None
        self._select_open_index: int | None = None

    DEFAULT_CSS = render_css(
        """
    SettingsModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #settings-wrapper {
        width: 100%;
        min-width: 44;
        max-width: 78;
        height: auto;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #settings-dialog {
        width: 100%;
        height: auto;
        min-height: 14;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #settings-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #settings-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #settings-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 2;
    }

    #settings-title {
        width: 1fr;
        text-align: left;
        text-style: bold;
        padding: 0;
    }

    #settings-close-btn {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
        text-align: right;
        content-align: right middle;
    }

    #settings-body {
        width: 100%;
        height: auto;
        padding: 0 2;
    }

    #settings-search-row,
    #settings-list,
    .settings-row {
        width: 100%;
        height: auto;
    }

    .settings-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    #settings-search {
        width: 100%;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    .settings-row {
        height: 1;
        color: $TEXT_PRIMARY;
        margin: 0;
    }
    .settings-row:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .settings-name {
        width: 1fr;
        text-align: left;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    .settings-name-editing {
        color: $TEXT_MUTED;
    }

    .settings-value {
        width: auto;
        color: $TEXT_MUTED;
        text-align: right;
    }

    .settings-options {
        width: 100%;
        height: auto;
        margin: 0 0 0 2;
    }

    .settings-option-btn {
        width: 100%;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 2;
        margin: 0;
        text-align: left;
        content-align: left middle;
    }
    .settings-option-btn:hover,
    .settings-option-btn:focus {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .settings-option-btn.selected {
        color: $PLAN_MODE;
    }

    #settings-edit-input {
        width: auto;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="settings-wrapper"):
            yield HalfRowSpacer(id="settings-top-edge")
            with Vertical(id="settings-dialog"):
                with Horizontal(id="settings-header"):
                    yield Static("Settings", id="settings-title")
                    yield Static("esc", id="settings-close-btn")
                with Vertical(id="settings-body"):
                    yield Static(classes="settings-gap")
                    with Horizontal(id="settings-search-row"):
                        yield Input(
                            placeholder="Search settings...", id="settings-search"
                        )
                    yield Static(classes="settings-gap")
                    yield Vertical(id="settings-list")
            yield HalfRowSpacer(id="settings-bottom-edge")

    def on_mount(self) -> None:
        self._render_settings("")

    def on_click(self, event: events.Click) -> None:
        if not event.control:
            return

        control_id = event.control.id or ""

        if control_id == "settings-close-btn":
            self.dismiss(None)
            return

        if control_id.startswith("settings-row-"):
            row_index = int(control_id[len("settings-row-"):])
            row = self._visible_rows()[row_index]
            edit_type = row.get("edit_type", _EDIT_NONE)
            if edit_type == _EDIT_TOGGLE:
                self._commit_toggle(row_index)
            elif edit_type == _EDIT_SELECT:
                self._toggle_select_options(row_index)
            elif edit_type == _EDIT_INPUT:
                self._start_input_edit(row_index)
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("settings-opt-"):
            parts = btn_id[len("settings-opt-"):].split("-", 1)
            if len(parts) == 2:
                row_index = int(parts[0])
                opt_value = parts[1]
                self._commit_select(row_index, opt_value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "settings-search":
            self._editing_row_index = None
            self._select_open_index = None
            self._render_settings(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "settings-edit-input" and self._editing_row_index is not None:
            self._commit_input(self._editing_row_index, event.value)

    def action_dismiss_result(self, result: None = None) -> None:
        self.dismiss(result)

    def _visible_rows(self) -> list[dict]:
        return [
            r for r in self.settings_rows
            if r.get("_visible", True)
        ]

    def _render_settings(self, query):
        query = str(query or "").strip().lower()
        settings_list = self.query_one("#settings-list", Vertical)
        settings_list.remove_children()
        self._editing_row_index = None
        self._select_open_index = None

        visible_count = 0
        for row in self.settings_rows:
            name = str(row.get("name") or "")
            value = str(row.get("value") or "")
            keywords = " ".join([name, value, str(row.get("keywords") or "")]).lower()
            if query and query not in keywords:
                row["_visible"] = False
                continue
            row["_visible"] = True
            row["_render_index"] = visible_count
            edit_type = row.get("edit_type", _EDIT_NONE)

            value_display = value
            if edit_type == _EDIT_TOGGLE:
                marker = "✓" if value.lower() in ("on", "true", "yes") else "✗"
                value_display = marker

            row_widget = Horizontal(
                Static(name, classes="settings-name"),
                Static(value_display, classes="settings-value"),
                id=f"settings-row-{visible_count}",
                classes="settings-row",
            )
            settings_list.mount(row_widget)
            visible_count += 1

        if visible_count == 0:
            settings_list.mount(
                Static("No matching settings", classes="settings-name")
            )

    def _commit_toggle(self, row_index: int) -> None:
        row = self._visible_rows()[row_index]
        current = str(row.get("value") or "").lower()
        new_value = "off" if current in ("on", "true", "yes") else "on"
        self._apply_change(row, new_value)

    def _toggle_select_options(self, row_index: int) -> None:
        if self._select_open_index == row_index:
            self._close_select_options()
            return

        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._select_open_index = row_index
        row = self._visible_rows()[row_index]
        options = row.get("options") or []
        current_value = str(row.get("value") or "")

        settings_list = self.query_one("#settings-list", Vertical)
        options_container = Vertical(
            id=f"settings-options-{row_index}",
            classes="settings-options",
        )
        for label, opt_value in options:
            label = str(label)
            opt_value = str(opt_value)
            btn_classes = "settings-option-btn"
            if opt_value == current_value:
                btn_classes += " selected"
            btn = _OptionButton(
                label,
                id=f"settings-opt-{row_index}-{opt_value}",
                classes=btn_classes,
            )
            options_container.mount(btn)

        row_widget = self.query_one(f"#settings-row-{row_index}", Horizontal)
        settings_list.mount(options_container, after=row_widget)

    def _close_select_options(self) -> None:
        if self._select_open_index is not None:
            try:
                options = self.query_one(
                    f"#settings-options-{self._select_open_index}", Vertical
                )
                options.remove()
            except Exception:
                pass
            self._select_open_index = None

    def _commit_select(self, row_index: int, new_value: str) -> None:
        self._close_select_options()
        row = self._visible_rows()[row_index]
        self._apply_change(row, new_value)

    def _start_input_edit(self, row_index: int) -> None:
        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._editing_row_index = row_index
        row = self._visible_rows()[row_index]
        current_value = str(row.get("value") or "")

        row_widget = self.query_one(f"#settings-row-{row_index}", Horizontal)
        name_static = row_widget.query_one(".settings-name", Static)
        name_static.add_class("settings-name-editing")
        value_static = row_widget.query_one(".settings-value", Static)
        value_static.display = False

        input_widget = Input(
            value=current_value,
            id="settings-edit-input",
        )
        input_widget.styles.width = max(len(current_value) + 3, 8)
        row_widget.mount(input_widget)
        input_widget.focus()

    def _finish_input_edit(self) -> None:
        if self._editing_row_index is None:
            return
        try:
            row_widget = self.query_one(
                f"#settings-row-{self._editing_row_index}", Horizontal
            )
            name_static = row_widget.query_one(".settings-name", Static)
            name_static.remove_class("settings-name-editing")
            value_static = row_widget.query_one(".settings-value", Static)
            value_static.display = True
            try:
                input_widget = row_widget.query_one("#settings-edit-input", Input)
                input_widget.remove()
            except Exception:
                pass
        except Exception:
            pass
        self._editing_row_index = None

    def _commit_input(self, row_index: int, new_value: str) -> None:
        new_value = str(new_value or "").strip()
        if not new_value:
            self._finish_input_edit()
            return
        row = self._visible_rows()[row_index]
        self._finish_input_edit()
        self._apply_change(row, new_value)

    def _apply_change(self, row: dict, new_value: str) -> None:
        row["value"] = str(new_value)
        on_change = row.get("on_change")
        if on_change:
            on_change(new_value)
        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()
        search_input = self.query_one("#settings-search", Input)
        self._render_settings(search_input.value)
