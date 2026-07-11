from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    add_model_profile_with_config,
)
from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer


_EDIT_NONE = "none"
_EDIT_TOGGLE = "toggle"
_EDIT_SELECT = "select"
_EDIT_INPUT = "input"
_EDIT_NAV = "nav"
_EDIT_ACTION = "action"

_LAYOUT_LIST = "list"
_LAYOUT_MODEL_LIST = "model_list"


class _OptionItem(Static):
    can_focus = True


class _ValueTrigger(Static):
    can_focus = True


class _ModelItem(Static):
    can_focus = True


class _ModelAction(Static):
    can_focus = True


class _ModelGroupTitle(Static):
    can_focus = False


class _FooterAction(Static):
    can_focus = True


class SettingsModal(ModalScreen[None]):
    """Interactive settings modal with homepage + nested setting pages."""

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

    .settings-outer-gap.hidden,
    .hidden {
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

    #settings-back-btn {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_MUTED;
        padding: 0 1 0 0;
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
    .settings-row,
    #settings-list-panel,
    #settings-model-detail-list {
        width: 100%;
        height: auto;
    }

    #settings-list-scroll,
    #settings-model-items-scroll,
    #settings-model-detail-scroll {
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
    .settings-row-stacked {
        height: auto;
    }
    .settings-row-stacked-header {
        width: 100%;
        height: 1;
    }

    .settings-row-button,
    .settings-row-button:hover,
    .settings-row-button:focus,
    .settings-row-button.-active {
        width: 100%;
        background: transparent;
        color: $TEXT_PRIMARY;
    }

    .settings-row-button:hover,
    .settings-row-button:focus,
    .settings-row-button.-active {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .settings-row-button:hover .settings-name,
    .settings-row-button:focus .settings-name,
    .settings-row-button.-active .settings-name,
    .settings-row-button:hover .settings-control-trigger,
    .settings-row-button:focus .settings-control-trigger,
    .settings-row-button.-active .settings-control-trigger,
    .settings-row-button:hover .settings-long-value,
    .settings-row-button:focus .settings-long-value,
    .settings-row-button.-active .settings-long-value {
        color: $PAGE_BACKGROUND;
        background: transparent;
    }
    .settings-row-disabled,
    .settings-row-disabled:hover,
    .settings-row-disabled:focus,
    .settings-row-disabled.-active {
        background: transparent;
        color: $TEXT_MUTED;
    }
    .settings-row-disabled .settings-name,
    .settings-row-disabled .settings-control-trigger,
    .settings-row-disabled .settings-long-value,
    .settings-row-disabled .settings-value {
        color: $TEXT_MUTED;
        background: transparent;
    }

    .settings-row-indented .settings-name {
        padding-left: 2;
    }

    .settings-name {
        width: 1fr;
        text-align: left;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    .settings-name-editing {
        color: $TEXT_PRIMARY;
    }
    .settings-long-value {
        width: 100%;
        height: auto;
        color: $TEXT_MUTED;
        padding: 0 1 0 2;
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

    .settings-nav-trigger,
    .settings-nav-trigger:hover,
    .settings-nav-trigger:focus,
    .settings-nav-trigger.-active {
        min-width: 3;
        color: $TEXT_MUTED;
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

    #settings-model-panel {
        width: 100%;
        height: auto;
    }

    #settings-model-sidebar {
        width: 24;
        height: auto;
        padding: 0 1 0 0;
    }

    #settings-model-detail-wrap {
        width: 1fr;
        height: auto;
        padding: 0 0 0 0;
    }
    #settings-model-detail-footer {
        display: none;
        width: 100%;
        height: 1;
        align-horizontal: right;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
        margin-top: 1;
    }
    #settings-model-detail-footer.open {
        display: block;
    }
    .settings-footer-action,
    .settings-footer-action:hover,
    .settings-footer-action:focus,
    .settings-footer-action.-active {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
        margin-left: 2;
        text-align: right;
        content-align: right middle;
    }
    .settings-footer-action.disabled,
    .settings-footer-action.disabled:hover,
    .settings-footer-action.disabled:focus,
    .settings-footer-action.disabled.-active {
        color: $TEXT_MUTED;
        background: transparent;
    }

    .settings-model-add,
    .settings-model-add:hover,
    .settings-model-add:focus,
    .settings-model-add.-active {
        width: 100%;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 2;
    }

    .settings-model-group {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        padding: 0 0 0 2;
        content-align: left middle;
    }
    .settings-model-group:hover {
        background: transparent;
        color: $TEXT_PRIMARY;
    }

    .settings-model-group-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    .settings-model-group-list {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .settings-model-group-list.hidden {
        display: none;
    }

    #settings-model-items {
        width: 100%;
        height: auto;
    }

    .settings-model-item,
    .settings-model-item:focus,
    .settings-model-item.-active {
        width: 100%;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 0 0 1;
        margin: 0 0 0 1;
    }
    .settings-model-item.inactive,
    .settings-model-item.inactive:focus,
    .settings-model-item.inactive.-active {
        color: $TEXT_MUTED;
    }
    .settings-model-item:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .settings-model-item.selected,
    .settings-model-item.selected:hover,
    .settings-model-item.selected:focus,
    .settings-model-item.selected.-active {
        color: $TEXT_PRIMARY;
        text-style: bold;
    }
    .settings-model-item.selected:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    """
    )

    BINDINGS = [("escape", "dismiss_result(None)", "Close")]

    def __init__(self, pages=None, app=None, page_id: str = "root"):
        super().__init__()
        self.pages = dict(pages or {})
        if page_id not in self.pages and self.pages:
            page_id = next(iter(self.pages.keys()))
        self.app_ref = app
        self._page_stack = [page_id]
        self._current_rows: list[dict] = []
        self._current_model_names: list[str] = []
        self._selected_model_name: str = ""
        self._model_groups: list[dict] = []
        self._model_sidebar_content_rows: int = 0
        self._show_model_group_titles: bool = True
        self._collapsed_model_api_types: set[str] = set()
        self._add_model_draft: dict[str, object] = {}
        self._editing_row_index: int | None = None
        self._select_open_index: int | None = None
        self._render_generation: int = 0
        self._current_footer_actions: list[dict] = []

        self.pages.setdefault(
            "add_model",
            {
                "title": "Add model",
                "layout": "list",
                "show_search": False,
                "rows": self._add_model_rows,
            },
        )

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
                            yield Static("<", id="settings-back-btn", classes="hidden")
                            yield Static("Settings", id="settings-title")
                            yield Static("esc", id="settings-close-btn")
                        with Vertical(id="settings-body"):
                            yield Static(classes="settings-gap")
                            with Horizontal(id="settings-search-row"):
                                yield Input(
                                    placeholder="Search settings...",
                                    id="settings-search",
                                )
                            yield Static(
                                id="settings-search-gap", classes="settings-gap"
                            )
                            with Vertical(id="settings-list-panel"):
                                with VerticalScroll(id="settings-list-scroll"):
                                    yield Vertical(id="settings-list")
                            with Horizontal(
                                id="settings-model-panel", classes="hidden"
                            ):
                                with Vertical(id="settings-model-sidebar"):
                                    yield _ModelAction(
                                        "Add model",
                                        id="settings-model-add-top",
                                        classes="settings-model-add",
                                    )
                                    yield Static(classes="settings-gap")
                                    with VerticalScroll(
                                        id="settings-model-items-scroll"
                                    ):
                                        yield Vertical(id="settings-model-items")
                                with Vertical(id="settings-model-detail-wrap"):
                                    with VerticalScroll(
                                        id="settings-model-detail-scroll"
                                    ):
                                        yield Vertical(id="settings-model-detail-list")
                                    with Horizontal(id="settings-model-detail-footer"):
                                        pass
                    yield HalfRowSpacer(id="settings-bottom-edge")
                yield Static(
                    "", id="settings-outer-gap-bottom", classes="settings-outer-gap"
                )

    def on_mount(self) -> None:
        self._render_current_page("")
        self.call_after_refresh(self._update_layout_constraints)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_click(self, event: events.Click) -> None:
        control_id = self._click_target_id(event)
        if not control_id:
            return

        if control_id == "settings-close-btn":
            if len(self._page_stack) > 1:
                self._go_back()
            else:
                self.dismiss(None)
            return

        if control_id == "settings-back-btn":
            self._go_back()
            return

        if control_id == "settings-model-add-top":
            page = self._current_page()
            on_add_item = page.get("on_add_item")
            if callable(on_add_item):
                created_name = on_add_item(self._selected_model_name)
                if created_name:
                    self._selected_model_name = str(created_name)
                self._render_current_page("")
                return
            self._begin_add_model(self._selected_model_name)
            self._push_page(str(page.get("add_page") or "add_model"))
            return

        if control_id.startswith("settings-model-group-"):
            group_index = self._parse_row_index(control_id, "settings-model-group-")
            if group_index is None or group_index >= len(self._model_groups):
                return
            group = self._model_groups[group_index]
            if not bool(group.get("allow_collapse", True)):
                return
            api_type = str(group.get("api_type") or "")
            list_id = str(group.get("list_id") or "")
            if not list_id:
                return
            try:
                lst = self.query_one(f"#{list_id}", Vertical)
            except Exception:
                return
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
                self._collapsed_model_api_types.discard(api_type)
            else:
                lst.add_class("hidden")
                self._collapsed_model_api_types.add(api_type)
            visible = 0
            for g in self._model_groups:
                if str(g.get("api_type") or "") not in self._collapsed_model_api_types:
                    visible += int(g.get("count") or 0)
            header_rows = (
                len(self._model_groups) if self._show_model_group_titles else 0
            )
            group_gap_rows = max(0, len(self._model_groups) - 1)
            self._model_sidebar_content_rows = (
                header_rows + group_gap_rows + max(0, visible)
            )
            self.call_after_refresh(self._update_layout_constraints)
            return

        if control_id.startswith("settings-model-item-"):
            index = self._parse_row_index(control_id, "settings-model-item-")
            if index is None or index >= len(self._current_model_names):
                return
            model_name = self._current_model_names[index]
            self._select_model(model_name)
            return

        if control_id.startswith("settings-footer-action-"):
            index = self._parse_row_index(control_id, "settings-footer-action-")
            if index is None or index >= len(self._current_footer_actions):
                return
            action = self._current_footer_actions[index]
            if bool(action.get("disabled")):
                return
            on_activate = action.get("on_activate")
            if callable(on_activate):
                on_activate()
            self._render_current_page(self._current_query())
            return

        if control_id.startswith("settings-row-"):
            row_index = self._parse_row_index(control_id, "settings-row-")
            if row_index is None:
                return
            self._activate_row(row_index)
            return

        if control_id.startswith("settings-trigger-"):
            row_index = self._parse_row_index(control_id, "settings-trigger-")
            if row_index is None:
                return
            self._activate_row(row_index)
            return

        if control_id.startswith("settings-opt-"):
            parsed = self._parse_option_indices(control_id)
            if parsed is None:
                return
            row_index, option_index = parsed
            rows = self._visible_rows()
            if row_index < 0 or row_index >= len(rows):
                return
            row = rows[row_index]
            options = list(row.get("options") or [])
            if 0 <= option_index < len(options):
                self._commit_select(row_index, str(options[option_index][1]))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "settings-search":
            self._editing_row_index = None
            self._select_open_index = None
            self._render_current_page(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if (
            event.input.id == "settings-edit-input"
            and self._editing_row_index is not None
        ):
            self._commit_input(self._editing_row_index, event.value)

    def action_dismiss_result(self, result: None = None) -> None:
        if len(self._page_stack) > 1:
            self._go_back()
            return
        self.dismiss(result)

    def _current_page(self) -> dict:
        return self.pages.get(self._page_stack[-1], {})

    def _current_layout(self) -> str:
        return str(self._current_page().get("layout") or _LAYOUT_LIST)

    def _current_query(self) -> str:
        try:
            return self.query_one("#settings-search", Input).value
        except Exception:
            return ""

    def _push_page(self, page_id: str) -> None:
        if not page_id or page_id not in self.pages:
            return
        self._page_stack.append(page_id)
        self._selected_model_name = ""
        self._reset_search()
        self._render_current_page("")

    def _go_back(self) -> None:
        if len(self._page_stack) <= 1:
            self.dismiss(None)
            return
        self._page_stack.pop()
        self._selected_model_name = ""
        self._reset_search()
        self._render_current_page("")

    def _reset_search(self) -> None:
        try:
            search_input = self.query_one("#settings-search", Input)
            search_input.value = ""
        except Exception:
            pass

    def _render_current_page(self, query: str) -> None:
        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()
        self._update_chrome()
        if self._current_layout() == _LAYOUT_MODEL_LIST:
            self._render_model_page()
        else:
            self._render_list_page(query)
        self.call_after_refresh(self._update_layout_constraints)

    def _update_chrome(self) -> None:
        page = self._current_page()
        title = self.query_one("#settings-title", Static)
        back_button = self.query_one("#settings-back-btn", Static)
        close_button = self.query_one("#settings-close-btn", Static)
        add_button = self.query_one("#settings-model-add-top", _ModelAction)
        body = self.query_one("#settings-body", Vertical)
        search_row = self.query_one("#settings-search-row", Horizontal)
        search_gap = self.query_one("#settings-search-gap", Static)
        list_panel = self.query_one("#settings-list-panel", Vertical)
        model_panel = self.query_one("#settings-model-panel", Horizontal)

        title.update(str(page.get("title") or "Settings"))
        back_button.add_class("hidden")
        close_button.update("esc")
        add_button.update(str(page.get("add_label") or "Add model"))

        show_search = bool(page.get("show_search", True)) and (
            self._current_layout() == _LAYOUT_LIST
        )
        search_row.display = show_search
        search_gap.display = show_search
        list_panel.display = self._current_layout() == _LAYOUT_LIST
        model_panel.display = self._current_layout() == _LAYOUT_MODEL_LIST
        body.styles.padding = (
            (0, 1, 0, 0)
            if self._current_layout() == _LAYOUT_MODEL_LIST
            else (0, 1, 0, 2)
        )

    def _page_rows(self) -> list[dict]:
        rows = self._current_page().get("rows") or []
        if callable(rows):
            rows = rows()
        return [dict(row) for row in list(rows or [])]

    def _model_state(self) -> dict:
        state = self._current_page().get("state") or {}
        if callable(state):
            state = state(self._selected_model_name)
        return dict(state or {})

    def _visible_rows(self) -> list[dict]:
        return [row for row in self._current_rows if row.get("_visible", True)]

    def _row_widget_id(self, row_index: int) -> str:
        return f"settings-row-{self._render_generation}-{row_index}"

    def _trigger_id(self, row_index: int) -> str:
        return f"settings-trigger-{self._render_generation}-{row_index}"

    def _options_id(self, row_index: int) -> str:
        return f"settings-options-{self._render_generation}-{row_index}"

    def _option_id(self, row_index: int, option_index: int) -> str:
        return f"settings-opt-{self._render_generation}-{row_index}-{option_index}"

    def _model_item_id(self, item_index: int) -> str:
        return f"settings-model-item-{self._render_generation}-{item_index}"

    def _model_group_id(self, group_index: int) -> str:
        return f"settings-model-group-{self._render_generation}-{group_index}"

    def _model_group_list_id(self, group_index: int) -> str:
        return f"settings-model-group-list-{self._render_generation}-{group_index}"

    def _footer_action_id(self, action_index: int) -> str:
        return f"settings-footer-action-{self._render_generation}-{action_index}"

    def _parse_row_index(self, control_id: str, prefix: str) -> int | None:
        if not control_id.startswith(prefix):
            return None
        try:
            return int(control_id.rsplit("-", 1)[1])
        except (TypeError, ValueError):
            return None

    def _parse_option_indices(self, control_id: str) -> tuple[int, int] | None:
        prefix = "settings-opt-"
        if not control_id.startswith(prefix):
            return None
        payload = control_id[len(prefix) :]
        try:
            _generation, row_text, option_text = payload.split("-", 2)
            return int(row_text), int(option_text)
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
        if edit_type in {_EDIT_NAV, _EDIT_ACTION}:
            if bool(row.get("show_value", False)):
                return value
            return ""
        if edit_type == _EDIT_SELECT:
            for label, opt_value in row.get("options") or []:
                if str(opt_value) == value:
                    return str(label)
        return value

    def _activate_row(self, row_index: int) -> None:
        row = self._visible_rows()[row_index]
        if bool(row.get("disabled")):
            return
        edit_type = row.get("edit_type", _EDIT_NONE)
        if edit_type == _EDIT_NAV:
            self._push_page(str(row.get("target_page") or ""))
        elif edit_type == _EDIT_ACTION:
            on_activate = row.get("on_activate")
            if callable(on_activate):
                result = on_activate()
                if result == "model_list":
                    while (
                        len(self._page_stack) > 1
                        and self._page_stack[-1] != "model_list"
                    ):
                        self._page_stack.pop()
                elif result == "back":
                    self._go_back()
                self._render_current_page(self._current_query())
        elif edit_type == _EDIT_TOGGLE:
            self._commit_toggle(row_index)
        elif edit_type == _EDIT_SELECT:
            self._toggle_select_options(row_index)
        elif edit_type == _EDIT_INPUT:
            self._start_input_edit(row_index)

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
            list_scroll = self.query_one("#settings-list-scroll", VerticalScroll)
            model_items_scroll = self.query_one(
                "#settings-model-items-scroll", VerticalScroll
            )
            model_detail_scroll = self.query_one(
                "#settings-model-detail-scroll", VerticalScroll
            )
            detail_footer = self.query_one("#settings-model-detail-footer", Horizontal)
            outer_top_gap = self.query_one("#settings-outer-gap-top", Static)
            outer_bottom_gap = self.query_one("#settings-outer-gap-bottom", Static)
            search_row = self.query_one("#settings-search-row", Horizontal)
        except Exception:
            return
        available_width = max(1, self.size.width - 8)
        settings_stack.styles.width = min(96, max(44, available_width))
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

        show_search = bool(getattr(search_row, "display", True))
        reserved = 4 + (2 if show_search else 0)
        available_height = max(1, self.size.height - outer_gap_height - reserved)

        if self._current_layout() == _LAYOUT_MODEL_LIST:
            footer_rows = 2 if detail_footer.has_class("open") else 0
            models_needed = max(1, int(self._model_sidebar_content_rows or 0))
            detail_needed = max(
                1,
                sum(self._estimated_row_height(row) for row in self._current_rows) or 0,
            )
            panel_needed = max(detail_needed + footer_rows, models_needed + 2)
            panel_height = min(max(1, panel_needed), available_height)
            detail_height = max(1, panel_height - footer_rows)
            model_items_height = max(1, panel_height - 2)
            model_detail_scroll.styles.height = detail_height
            model_detail_scroll.styles.max_height = max(
                1, available_height - footer_rows
            )
            model_items_scroll.styles.height = model_items_height
            model_items_scroll.styles.max_height = max(1, available_height - 2)
            list_scroll.styles.height = 1
            list_scroll.styles.max_height = 1
        else:
            visible_rows = self._visible_rows()
            list_needed = max(1, len(visible_rows) or 0)
            list_height = min(list_needed, available_height)
            list_scroll.styles.height = list_height
            list_scroll.styles.max_height = available_height
            model_items_scroll.styles.height = 1
            model_items_scroll.styles.max_height = 1
            model_detail_scroll.styles.height = 1
            model_detail_scroll.styles.max_height = 1

    def _estimated_row_height(self, row: dict) -> int:
        height = 1
        long_value = str(row.get("long_value") or "")
        if long_value:
            height += max(1, len(long_value.splitlines()))
        return height

    def _render_list_page(self, query: str) -> None:
        query = str(query or "").strip().lower()
        settings_list = self.query_one("#settings-list", Vertical)
        try:
            detail_footer = self.query_one("#settings-model-detail-footer", Horizontal)
            for child in list(detail_footer.children):
                child.remove()
            detail_footer.remove_class("open")
        except Exception:
            pass
        self._current_footer_actions = []
        self._render_generation += 1
        self._current_rows = self._page_rows()
        for child in list(settings_list.children):
            child.remove()

        visible_count = 0
        for row in self._current_rows:
            name = str(row.get("name") or "")
            value = str(row.get("value") or "")
            keywords = " ".join([name, value, str(row.get("keywords") or "")]).lower()
            if query and query not in keywords:
                row["_visible"] = False
                continue
            row["_visible"] = True
            row["_render_index"] = visible_count
            settings_list.mount(self._build_row_widget(row, visible_count))
            visible_count += 1

        if visible_count == 0:
            settings_list.mount(Static("No matching settings", classes="settings-name"))

    def _render_model_page(self) -> None:
        state = self._model_state()
        self._current_rows = [dict(row) for row in list(state.get("rows") or [])]
        self._current_footer_actions = [
            dict(action) for action in list(state.get("footer_actions") or [])
        ]
        all_model_names = [str(name) for name in list(state.get("models") or [])]
        groups = list(state.get("groups") or [])
        selected_model = str(state.get("selected_model") or "")
        item_labels = dict(state.get("item_labels") or {})
        item_classes = dict(state.get("item_classes") or {})
        show_group_titles = bool(state.get("show_group_titles", True))
        self._show_model_group_titles = show_group_titles
        allow_group_collapse = bool(state.get("allow_group_collapse", True))
        if selected_model in all_model_names:
            self._selected_model_name = selected_model
        elif all_model_names:
            self._selected_model_name = all_model_names[0]
        else:
            self._selected_model_name = ""

        model_items = self.query_one("#settings-model-items", Vertical)
        detail_list = self.query_one("#settings-model-detail-list", Vertical)
        detail_footer = self.query_one("#settings-model-detail-footer", Horizontal)
        self._render_generation += 1

        for child in list(model_items.children):
            child.remove()
        for child in list(detail_list.children):
            child.remove()
        for child in list(detail_footer.children):
            child.remove()

        if not groups:
            groups = [{"api_type": "", "title": "Models", "models": all_model_names}]

        selected_api_type = ""
        for group in groups:
            api_type = str(group.get("api_type") or "")
            if self._selected_model_name in list(group.get("models") or []):
                selected_api_type = api_type
                break
        if selected_api_type:
            self._collapsed_model_api_types.discard(selected_api_type)

        self._model_groups = []
        self._current_model_names = []
        visible_model_count = 0
        header_count = 0

        for group_index, group in enumerate(groups):
            api_type = str(group.get("api_type") or "")
            title = str(group.get("title") or "") or (api_type or "Other")
            group_models = [str(name) for name in list(group.get("models") or [])]
            if show_group_titles:
                header_count += 1

            if group_index > 0:
                model_items.mount(Static("", classes="settings-model-group-gap"))

            if show_group_titles:
                model_items.mount(
                    _ModelGroupTitle(
                        title,
                        id=self._model_group_id(group_index),
                        classes="settings-model-group",
                    )
                )
            group_list_id = self._model_group_list_id(group_index)
            group_list_classes = "settings-model-group-list"
            if allow_group_collapse and api_type in self._collapsed_model_api_types:
                group_list_classes += " hidden"
            group_list = Vertical(id=group_list_id, classes=group_list_classes)
            self._model_groups.append({
                "api_type": api_type,
                "list_id": group_list_id,
                "count": len(group_models),
                "allow_collapse": allow_group_collapse,
            })
            model_items.mount(group_list)

            for model_name in group_models:
                classes = "settings-model-item"
                extra_classes = str(item_classes.get(model_name) or "").strip()
                if extra_classes:
                    classes += f" {extra_classes}"
                if model_name == self._selected_model_name:
                    classes += " selected"
                if (not allow_group_collapse) or (
                    api_type not in self._collapsed_model_api_types
                ):
                    visible_model_count += 1
                flat_index = len(self._current_model_names)
                self._current_model_names.append(model_name)
                group_list.mount(
                    _ModelItem(
                        str(item_labels.get(model_name) or model_name),
                        id=self._model_item_id(flat_index),
                        classes=classes,
                    )
                )

        if not all_model_names:
            model_items.mount(Static("No models", classes="settings-name"))
            self._model_sidebar_content_rows = 1
        else:
            group_gap_rows = max(0, len(groups) - 1)
            self._model_sidebar_content_rows = (
                header_count + group_gap_rows + visible_model_count
            )

        for row_index, row in enumerate(self._current_rows):
            row["_visible"] = True
            row["_render_index"] = row_index
            detail_list.mount(self._build_row_widget(row, row_index))

        if not self._current_rows:
            detail_list.mount(Static("No model settings", classes="settings-name"))

        if self._current_footer_actions:
            detail_footer.add_class("open")
            for action_index, action in enumerate(self._current_footer_actions):
                classes = "settings-footer-action"
                if bool(action.get("disabled")):
                    classes += " disabled"
                detail_footer.mount(
                    _FooterAction(
                        str(action.get("label") or ""),
                        id=self._footer_action_id(action_index),
                        classes=classes,
                    )
                )
        else:
            detail_footer.remove_class("open")

    def _build_row_widget(self, row: dict, row_index: int):
        edit_type = row.get("edit_type", _EDIT_NONE)
        name = str(row.get("name") or "")
        header_children = [Static(name, classes="settings-name")]

        if edit_type == _EDIT_NONE:
            header_children.append(
                Static(
                    self._display_value(row),
                    classes="settings-value settings-value-static",
                )
            )
        elif edit_type == _EDIT_SELECT:
            option_buttons = []
            display_value = self._display_value(row)
            trigger_width = max(len(display_value) + 2, 7)
            option_width = max(
                (len(str(label)) for label, _ in row.get("options") or []),
                default=0,
            )
            option_width = max(option_width, len(display_value)) + 2
            for option_index, (label, opt_value) in enumerate(row.get("options") or []):
                option_buttons.append(
                    _OptionItem(
                        str(label),
                        id=self._option_id(row_index, option_index),
                        classes="settings-option-btn",
                    )
                )
            options_container = Vertical(
                *option_buttons,
                id=self._options_id(row_index),
                classes="settings-options",
            )
            options_container.styles.width = option_width
            options_container.styles.min_width = option_width
            options_container.styles.offset = (trigger_width - option_width, 0)
            trigger = _ValueTrigger(
                display_value,
                id=self._trigger_id(row_index),
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
            header_children.append(drop_container)
        elif edit_type == _EDIT_TOGGLE:
            display_value = self._display_value(row)
            trigger = _ValueTrigger(
                display_value,
                markup=False,
                id=self._trigger_id(row_index),
                classes="settings-control-trigger settings-toggle-trigger",
            )
            trigger.styles.width = max(len(display_value) + 2, 7)
            trigger.styles.min_width = max(len(display_value) + 2, 7)
            if self._is_toggle_enabled(str(row.get("value") or "")):
                trigger.add_class("toggle-on")
            else:
                trigger.add_class("toggle-off")
            header_children.append(trigger)
        else:
            trigger_classes = "settings-control-trigger"
            if edit_type == _EDIT_NAV:
                trigger_classes += " settings-nav-trigger"
            header_children.append(
                _ValueTrigger(
                    self._display_value(row),
                    markup=False,
                    id=self._trigger_id(row_index),
                    classes=trigger_classes,
                )
            )

        row_classes = ["settings-row"]
        if edit_type in {_EDIT_NAV, _EDIT_ACTION}:
            row_classes.append("settings-row-button")
        if bool(row.get("indented")):
            row_classes.append("settings-row-indented")
        if bool(row.get("disabled")):
            row_classes.append("settings-row-disabled")
        long_value = str(row.get("long_value") or "")
        if long_value:
            row_classes.append("settings-row-stacked")
            return Vertical(
                Horizontal(*header_children, classes="settings-row-stacked-header"),
                Static(long_value, classes="settings-long-value"),
                id=self._row_widget_id(row_index),
                classes=" ".join(row_classes),
            )
        return Horizontal(
            *header_children,
            id=self._row_widget_id(row_index),
            classes=" ".join(row_classes),
        )

    def _toggle_select_options(self, row_index: int) -> None:
        if self._select_open_index == row_index:
            self._close_select_options()
            return

        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._select_open_index = row_index
        options_container = self.query_one(f"#{self._options_id(row_index)}", Vertical)
        options_container.add_class("open")

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
        self._close_select_options()
        if self._editing_row_index == row_index:
            try:
                row_widget = self.query_one(
                    f"#{self._row_widget_id(row_index)}", Horizontal
                )
                input_widget = row_widget.query_one("#settings-edit-input", Input)
                input_widget.focus()
                return
            except Exception:
                pass
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._editing_row_index = row_index
        row = self._visible_rows()[row_index]
        current_value = str(row.get("value") or "")

        row_widget = self.query_one(f"#{self._row_widget_id(row_index)}", Horizontal)
        value_button = row_widget.query_one(".settings-control-trigger", _ValueTrigger)
        value_button.display = False

        input_widget = Input(value=current_value, id="settings-edit-input")
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
        self._render_current_page(self._current_query())

    def _select_model(self, model_name: str) -> None:
        callback = self._current_page().get("on_select_model")
        if callable(callback):
            callback(model_name)
        self._selected_model_name = model_name
        self._render_current_page("")

    def _begin_add_model(self, source_name: str = "") -> None:
        self._add_model_draft = {
            "name": "",
            "api_type": API_TYPE_OLLAMA,
            "base_url": "",
            "model": "",
            "api_key": "",
            "max_tokens": "0",
            "temperature": "0",
            "stream_mode": "false",
            "thinking_mode": "false",
            "reasoning_effort": "none",
            "context_window_tokens": "0",
        }

    def _set_add_model_field(self, key: str, value: str) -> None:
        if not self._add_model_draft:
            self._add_model_draft = {}
        self._add_model_draft[key] = value

    def _add_model_rows(self) -> list[dict]:
        draft = dict(self._add_model_draft or {})
        bool_choices = [("true", "true"), ("false", "false")]
        api_type_choices = [
            ("Ollama", API_TYPE_OLLAMA),
            ("OpenAI", API_TYPE_OPENAI),
            ("Anthropic", API_TYPE_ANTHROPIC),
            ("Gemini", API_TYPE_GEMINI),
            ("GLM", API_TYPE_GLM),
        ]
        reasoning_choices = [
            ("none", "none"),
            ("minimal", "minimal"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
        ]
        thinking_enabled = self._is_toggle_enabled(
            str(draft.get("thinking_mode") or "false")
        )
        rows = [
            {
                "name": "Name",
                "value": str(draft.get("name") or ""),
                "keywords": "name",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("name", str(v)),
            },
            {
                "name": "API type",
                "value": str(draft.get("api_type") or API_TYPE_OLLAMA),
                "keywords": "api_type",
                "edit_type": "select",
                "options": api_type_choices,
                "on_change": lambda v: self._set_add_model_field("api_type", str(v)),
            },
            {
                "name": "Base URL",
                "value": str(draft.get("base_url") or ""),
                "keywords": "base_url",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("base_url", str(v)),
            },
            {
                "name": "Model",
                "value": str(draft.get("model") or ""),
                "keywords": "model",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("model", str(v)),
            },
            {
                "name": "API key",
                "value": str(draft.get("api_key") or ""),
                "keywords": "api_key",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("api_key", str(v)),
            },
            {
                "name": "Max tokens",
                "value": str(draft.get("max_tokens") or ""),
                "keywords": "max_tokens",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("max_tokens", str(v)),
            },
            {
                "name": "Temperature",
                "value": str(draft.get("temperature") or ""),
                "keywords": "temperature",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field("temperature", str(v)),
            },
            {
                "name": "Stream",
                "value": str(draft.get("stream_mode") or "false"),
                "keywords": "stream_mode stream",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._set_add_model_field("stream_mode", str(v)),
            },
            {
                "name": "Thinking",
                "value": str(draft.get("thinking_mode") or "false"),
                "keywords": "thinking_mode thinking",
                "edit_type": "toggle",
                "options": bool_choices,
                "on_change": lambda v: self._set_add_model_field(
                    "thinking_mode", str(v)
                ),
            },
            {
                "name": "Context",
                "value": str(draft.get("context_window_tokens") or ""),
                "keywords": "context_window_tokens context",
                "edit_type": "input",
                "on_change": lambda v: self._set_add_model_field(
                    "context_window_tokens", str(v)
                ),
            },
        ]
        if thinking_enabled:
            rows.insert(
                -1,
                {
                    "name": "Reasoning effort",
                    "value": str(draft.get("reasoning_effort") or "none"),
                    "keywords": "reasoning_effort",
                    "edit_type": "select",
                    "options": reasoning_choices,
                    "on_change": lambda v: self._set_add_model_field(
                        "reasoning_effort", str(v)
                    ),
                },
            )
        rows.append({"name": "", "value": "", "edit_type": "none"})
        rows.append({
            "name": "",
            "value": "Add",
            "keywords": "add create",
            "edit_type": "action",
            "show_value": True,
            "on_activate": self._create_model_from_draft,
        })
        return rows

    def _create_model_from_draft(self) -> str:
        if self.app_ref is None:
            return ""
        draft = dict(self._add_model_draft or {})
        name = str(draft.get("name") or "").strip()
        if not name:
            self.app_ref.add_status_message("[!]", "Model name cannot be empty.")
            return ""
        max_tokens = str(draft.get("max_tokens") or "").strip()
        context_tokens = str(draft.get("context_window_tokens") or "").strip()
        temperature = str(draft.get("temperature") or "").strip()
        payload = {
            "api_type": str(draft.get("api_type") or API_TYPE_OLLAMA),
            "base_url": str(draft.get("base_url") or ""),
            "model": str(draft.get("model") or ""),
            "api_key": str(draft.get("api_key") or ""),
            "temperature": temperature,
            "stream_mode": draft.get("stream_mode"),
            "thinking_mode": draft.get("thinking_mode"),
            "reasoning_effort": draft.get("reasoning_effort"),
        }
        if max_tokens and max_tokens != "0":
            payload["max_tokens"] = max_tokens
        if context_tokens and context_tokens != "0":
            payload["context_window_tokens"] = context_tokens
        if payload.get("temperature", "") == "":
            payload.pop("temperature", None)
        try:
            created = add_model_profile_with_config(name, payload)
        except Exception as error:
            self.app_ref.add_status_message("[✗]", f"新增模型失败: {error}")
            return ""
        self.app_ref._reload_config()
        self.app_ref._sync_chat_from_active_model()
        self.app_ref._apply_config_to_controls()
        self._selected_model_name = str(created)
        return "model_list"
