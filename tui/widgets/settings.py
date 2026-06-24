from __future__ import annotations

import json
import traceback
import time
import urllib.request

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Input, Static
from textual.screen import ModalScreen

from tui.theme import render_css


from tui.widgets.chat_input import HalfRowSpacer


_EDIT_NONE = "none"
_EDIT_TOGGLE = "toggle"
_EDIT_SELECT = "select"
_EDIT_INPUT = "input"


# #region debug-point A:report-helper
def _debug_report(
    hypothesis_id: str, location: str, msg: str, data: dict | None = None
) -> None:
    _path = ".dbg/settings-click-input.env"
    _url = "http://127.0.0.1:7777/event"
    _session = "settings-click-input"
    try:
        with open(_path, encoding="utf-8") as _env_file:
            for _line in _env_file.read().splitlines():
                if _line.startswith("DEBUG_SERVER_URL="):
                    _url = _line.split("=", 1)[1].strip() or _url
                elif _line.startswith("DEBUG_SESSION_ID="):
                    _session = _line.split("=", 1)[1].strip() or _session
        urllib.request.urlopen(
            urllib.request.Request(
                _url,
                data=json.dumps({
                    "sessionId": _session,
                    "runId": "pre-fix",
                    "hypothesisId": hypothesis_id,
                    "location": location,
                    "msg": f"[DEBUG] {msg}",
                    "data": data or {},
                    "ts": int(time.time() * 1000),
                }).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=0.3,
        ).read()
    except Exception:
        pass


# #endregion


class _OptionItem(Static):
    can_focus = True
    pass


class _ValueTrigger(Static):
    can_focus = True
    pass


class SettingsModal(ModalScreen[None]):
    """Interactive settings modal window centered on screen."""

    def __init__(self, settings_rows=None, app=None):
        super().__init__()
        self.settings_rows = list(settings_rows or [])
        self.app_ref = app
        self._editing_row_index: int | None = None
        self._select_open_index: int | None = None
        self._render_generation: int = 0

    DEFAULT_CSS = render_css(
        """
    SettingsModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #settings-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #settings-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    .settings-outer-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    .settings-outer-gap.hidden {
        display: none;
    }

    #settings-wrapper {
        width: 100%;
        height: auto;
        min-height: 10;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #settings-dialog {
        width: 100%;
        height: auto;
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
        padding: 0 1 0 2;
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
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #settings-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
    }

    #settings-search-row,
    #settings-list-scroll,
    #settings-list,
    .settings-row {
        width: 100%;
        height: auto;
    }

    #settings-list-scroll {
        min-height: 0;
        overflow-y: auto;
        scrollbar-size: 0 0;
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
        padding: 0 1;
    }

    .settings-value-static {
        padding: 0 1 0 0;
    }

    .settings-control-trigger,
    .settings-control-trigger:hover,
    .settings-control-trigger:focus,
    .settings-control-trigger.-active {
        width: auto;
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

    .settings-toggle-trigger.toggle-off,
    .settings-toggle-trigger.toggle-off:hover,
    .settings-toggle-trigger.toggle-off:focus,
    .settings-toggle-trigger.toggle-off.-active {
        color: $TEXT_MUTED;
    }

    .settings-control-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
    }

    .settings-options {
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

    .settings-options.open {
        display: block;
    }

    .settings-option-btn {
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
    .settings-option-btn:hover,
    .settings-option-btn:focus,
    .settings-option-btn.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $PAGE_BACKGROUND;
    }

    #settings-edit-input {
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
    ]

    def compose(self) -> ComposeResult:
        with Container(id="settings-frame"):
            with Vertical(id="settings-stack"):
                yield Static(
                    "", id="settings-outer-gap-top", classes="settings-outer-gap"
                )
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
                                    placeholder="Search settings...",
                                    id="settings-search",
                                )
                            yield Static(classes="settings-gap")
                            with Vertical(id="settings-list-scroll"):
                                yield Vertical(id="settings-list")
                    yield HalfRowSpacer(id="settings-bottom-edge")
                yield Static(
                    "", id="settings-outer-gap-bottom", classes="settings-outer-gap"
                )

    def on_mount(self) -> None:
        self._render_settings("")
        self.call_after_refresh(self._update_layout_constraints)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_click(self, event: events.Click) -> None:
        try:
            control_id = self._click_target_id(event)
            # #region debug-point A:on-click
            _debug_report(
                "A",
                "settings.py:on_click",
                "settings click received",
                {
                    "control_id": control_id,
                    "raw_control_id": getattr(
                        getattr(event, "control", None), "id", None
                    ),
                    "editing_row_index": self._editing_row_index,
                    "select_open_index": self._select_open_index,
                },
            )
            # #endregion
            if not control_id:
                return

            if control_id == "settings-close-btn":
                self.dismiss(None)
                return

            if control_id.startswith("settings-trigger-"):
                row_index = self._parse_row_index(control_id, "settings-trigger-")
                if row_index is None:
                    return
                row = self._visible_rows()[row_index]
                edit_type = row.get("edit_type", _EDIT_NONE)
                if edit_type == _EDIT_TOGGLE:
                    self._commit_toggle(row_index)
                elif edit_type == _EDIT_SELECT:
                    self._toggle_select_options(row_index)
                elif edit_type == _EDIT_INPUT:
                    self._start_input_edit(row_index)
                return

            if control_id.startswith("settings-opt-"):
                payload = control_id[len("settings-opt-") :]
                opt_value, sep, row_text = payload.rpartition("-")
                if sep:
                    row_index = int(row_text)
                    self._commit_select(row_index, opt_value)
                return
        except Exception as error:
            # #region debug-point A:on-click-error
            _debug_report(
                "A",
                "settings.py:on_click",
                "settings click failed",
                {"error": repr(error), "traceback": traceback.format_exc()},
            )
            # #endregion
            raise

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "settings-search":
            self._editing_row_index = None
            self._select_open_index = None
            self._render_settings(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            # #region debug-point B:on-input-submitted
            _debug_report(
                "B",
                "settings.py:on_input_submitted",
                "settings input submitted",
                {
                    "input_id": getattr(event.input, "id", ""),
                    "value": getattr(event, "value", ""),
                    "editing_row_index": self._editing_row_index,
                },
            )
            # #endregion
            if (
                event.input.id == "settings-edit-input"
                and self._editing_row_index is not None
            ):
                self._commit_input(self._editing_row_index, event.value)
        except Exception as error:
            # #region debug-point B:on-input-submitted-error
            _debug_report(
                "B",
                "settings.py:on_input_submitted",
                "settings input submit failed",
                {"error": repr(error), "traceback": traceback.format_exc()},
            )
            # #endregion
            raise

    def action_dismiss_result(self, result: None = None) -> None:
        self.dismiss(result)

    def _visible_rows(self) -> list[dict]:
        return [r for r in self.settings_rows if r.get("_visible", True)]

    def _row_widget_id(self, row_index: int) -> str:
        return f"settings-row-{self._render_generation}-{row_index}"

    def _trigger_id(self, row_index: int) -> str:
        return f"settings-trigger-{self._render_generation}-{row_index}"

    def _options_id(self, row_index: int) -> str:
        return f"settings-options-{self._render_generation}-{row_index}"

    def _parse_row_index(self, control_id: str, prefix: str) -> int | None:
        if not control_id.startswith(prefix):
            return None
        try:
            return int(control_id.rsplit("-", 1)[1])
        except (TypeError, ValueError):
            return None

    def _click_target_id(self, event: events.Click) -> str:
        control = getattr(event, "control", None) or getattr(event, "widget", None)
        while control is not None:
            control_id = getattr(control, "id", None)
            if control_id:
                return str(control_id)
            control = getattr(control, "parent", None)
        return ""

    def _display_value(self, row: dict) -> str:
        value = str(row.get("value") or "")
        edit_type = row.get("edit_type", _EDIT_NONE)
        if edit_type == _EDIT_TOGGLE:
            return self._toggle_display_value(row)
        if edit_type in {_EDIT_SELECT, _EDIT_TOGGLE}:
            for label, opt_value in row.get("options") or []:
                if str(opt_value) == value:
                    return str(label)
        return value

    def _is_toggle_enabled(self, value: str) -> bool:
        return str(value or "").strip().lower() in {"true", "on", "yes", "1"}

    def _toggle_display_value(self, row: dict) -> str:
        return (
            "true" if self._is_toggle_enabled(str(row.get("value") or "")) else "false"
        )

    def _toggle_next_value(self, row: dict) -> str:
        options = [
            (str(label), str(value)) for label, value in row.get("options") or []
        ]
        truthy_value = next(
            (value for _, value in options if self._is_toggle_enabled(value)),
            "true",
        )
        falsey_value = next(
            (value for _, value in options if not self._is_toggle_enabled(value)),
            "false",
        )
        current_value = str(row.get("value") or "")
        return falsey_value if self._is_toggle_enabled(current_value) else truthy_value

    def _update_layout_constraints(self) -> None:
        try:
            settings_stack = self.query_one("#settings-stack", Vertical)
            list_scroll = self.query_one("#settings-list-scroll", Vertical)
            outer_top_gap = self.query_one("#settings-outer-gap-top", Static)
            outer_bottom_gap = self.query_one("#settings-outer-gap-bottom", Static)
        except Exception:
            return
        available_width = max(1, self.size.width - 8)
        settings_stack.styles.width = min(78, max(44, available_width))
        wrapper_min_height = 10
        show_outer_gaps = self.size.height >= (wrapper_min_height + 2)
        if show_outer_gaps:
            outer_top_gap.remove_class("hidden")
            outer_bottom_gap.remove_class("hidden")
            outer_gap_height = 2
        else:
            outer_top_gap.add_class("hidden")
            outer_bottom_gap.add_class("hidden")
            outer_gap_height = 0
        # Total reserved height inside the wrapper:
        # - half-row spacers top/bottom: 2
        # - header: 1
        # - body chrome (gap + search + gap): 3
        list_scroll.styles.max_height = max(1, self.size.height - outer_gap_height - 6)

    def _render_settings(self, query):
        query = str(query or "").strip().lower()
        settings_list = self.query_one("#settings-list", Vertical)
        self._render_generation += 1
        for child in list(settings_list.children):
            child.remove()
        self._editing_row_index = None
        self._select_open_index = None
        # #region debug-point D:render-settings
        _debug_report(
            "D",
            "settings.py:_render_settings",
            "render settings list",
            {"query": query, "rows_total": len(self.settings_rows)},
        )
        # #endregion

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
            row_children = [Static(name, classes="settings-name")]
            if edit_type == _EDIT_NONE:
                row_children.append(
                    Static(
                        self._display_value(row),
                        classes="settings-value settings-value-static",
                    )
                )
            elif edit_type == _EDIT_SELECT:
                option_buttons = []
                display_value = self._display_value(row)
                trigger_width = len(display_value) + 2
                option_width = max(
                    (len(str(label)) for label, _ in row.get("options") or []),
                    default=0,
                )
                option_width = max(option_width, len(display_value)) + 2
                for label, opt_value in row.get("options") or []:
                    label = str(label)
                    opt_value = str(opt_value)
                    btn_classes = "settings-option-btn"
                    option_buttons.append(
                        _OptionItem(
                            label,
                            id=f"settings-opt-{opt_value}-{visible_count}",
                            classes=btn_classes,
                        )
                    )
                options_container = Vertical(
                    *option_buttons,
                    id=self._options_id(visible_count),
                    classes="settings-options",
                )
                options_container.styles.width = option_width
                options_container.styles.min_width = option_width
                options_container.styles.offset = (trigger_width - option_width, 0)
                trigger = _ValueTrigger(
                    display_value,
                    id=self._trigger_id(visible_count),
                    classes="settings-control-trigger",
                )
                trigger.styles.width = trigger_width
                trigger.styles.min_width = trigger_width
                drop_container = Container(
                    trigger,
                    options_container,
                    classes="settings-control-drop",
                )
                drop_container.styles.width = trigger_width
                drop_container.styles.min_width = trigger_width
                row_children.append(drop_container)
            elif edit_type == _EDIT_TOGGLE:
                display_value = self._display_value(row)
                trigger = _ValueTrigger(
                    display_value,
                    markup=False,
                    id=self._trigger_id(visible_count),
                    classes="settings-control-trigger settings-toggle-trigger",
                )
                trigger.styles.width = max(len(display_value) + 2, 7)
                trigger.styles.min_width = max(len(display_value) + 2, 7)
                if self._is_toggle_enabled(str(row.get("value") or "")):
                    trigger.add_class("toggle-on")
                else:
                    trigger.add_class("toggle-off")
                row_children.append(trigger)
            else:
                row_children.append(
                    _ValueTrigger(
                        self._display_value(row),
                        id=self._trigger_id(visible_count),
                        classes="settings-control-trigger",
                    )
                )
            row_widget = Horizontal(
                *row_children,
                id=self._row_widget_id(visible_count),
                classes="settings-row",
            )
            settings_list.mount(row_widget)
            visible_count += 1

        if visible_count == 0:
            settings_list.mount(Static("No matching settings", classes="settings-name"))

    def _toggle_select_options(self, row_index: int) -> None:
        # #region debug-point C:toggle-select-options
        _debug_report(
            "C",
            "settings.py:_toggle_select_options",
            "toggle select options",
            {
                "row_index": row_index,
                "select_open_index_before": self._select_open_index,
                "visible_rows": len(self._visible_rows()),
            },
        )
        # #endregion
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
        options_container = self.query_one(f"#{self._options_id(row_index)}", Vertical)
        options_container.add_class("open")
        # #region debug-point C:options-mounted
        _debug_report(
            "C",
            "settings.py:_toggle_select_options",
            "options container opened",
            {
                "row_index": row_index,
                "options_count": len(options),
                "current_value": current_value,
                "styles_width": str(options_container.styles.width),
                "styles_min_width": str(options_container.styles.min_width),
                "display": bool(options_container.display),
            },
        )
        # #endregion

    def _close_select_options(self) -> None:
        if self._select_open_index is not None:
            try:
                options = self.query_one(
                    f"#{self._options_id(self._select_open_index)}", Vertical
                )
                options.remove_class("open")
            except Exception:
                pass
            self._select_open_index = None

    def _commit_select(self, row_index: int, new_value: str) -> None:
        self._close_select_options()
        row = self._visible_rows()[row_index]
        self._apply_change(row, new_value)

    def _commit_toggle(self, row_index: int) -> None:
        row = self._visible_rows()[row_index]
        self._apply_change(row, self._toggle_next_value(row))

    def _start_input_edit(self, row_index: int) -> None:
        # #region debug-point B:start-input-edit
        _debug_report(
            "B",
            "settings.py:_start_input_edit",
            "start input edit",
            {
                "row_index": row_index,
                "editing_row_index_before": self._editing_row_index,
                "visible_rows": len(self._visible_rows()),
            },
        )
        # #endregion
        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._editing_row_index = row_index
        row = self._visible_rows()[row_index]
        current_value = str(row.get("value") or "")

        row_widget = self.query_one(f"#{self._row_widget_id(row_index)}", Horizontal)
        name_static = row_widget.query_one(".settings-name", Static)
        name_static.add_class("settings-name-editing")
        value_button = row_widget.query_one(".settings-control-trigger", _ValueTrigger)
        value_button.display = False

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
                f"#{self._row_widget_id(self._editing_row_index)}", Horizontal
            )
            name_static = row_widget.query_one(".settings-name", Static)
            name_static.remove_class("settings-name-editing")
            value_button = row_widget.query_one(
                ".settings-control-trigger", _ValueTrigger
            )
            value_button.display = True
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
        # #region debug-point B:commit-input
        _debug_report(
            "B",
            "settings.py:_commit_input",
            "commit input",
            {
                "row_index": row_index,
                "new_value": new_value,
                "editing_row_index": self._editing_row_index,
                "visible_rows": len(self._visible_rows()),
            },
        )
        # #endregion
        if not new_value:
            self._finish_input_edit()
            return
        row = self._visible_rows()[row_index]
        self._finish_input_edit()
        self._apply_change(row, new_value)

    def _apply_change(self, row: dict, new_value: str) -> None:
        try:
            # #region debug-point E:apply-change
            _debug_report(
                "E",
                "settings.py:_apply_change",
                "apply change",
                {
                    "row_name": str(row.get("name") or ""),
                    "old_value": str(row.get("value") or ""),
                    "new_value": str(new_value),
                    "editing_row_index": self._editing_row_index,
                    "select_open_index": self._select_open_index,
                },
            )
            # #endregion
            row["value"] = str(new_value)
            on_change = row.get("on_change")
            if on_change:
                on_change(new_value)
            self._close_select_options()
            if self._editing_row_index is not None:
                self._finish_input_edit()
            search_input = self.query_one("#settings-search", Input)
            self._render_settings(search_input.value)
        except Exception as error:
            # #region debug-point E:apply-change-error
            _debug_report(
                "E",
                "settings.py:_apply_change",
                "apply change failed",
                {"error": repr(error), "traceback": traceback.format_exc()},
            )
            # #endregion
            raise
