from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ...config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    DEFAULT_EXTRA_MODALITY_LIMITS,
    DEFAULT_MULTIMODAL_LIMIT,
    SUPPORTED_EXTRA_MODALITIES,
    add_model_profile_with_config,
    format_extra_modalities,
    parse_extra_modalities_config,
    parse_extra_modalities_input,
    parse_multimodal_limit,
    normalize_reasoning_effort_for_api,
    supported_reasoning_efforts,
)
from ..theme import render_css
from ..widgets.chat_input import HalfRowSpacer


_EDIT_NONE = "none"
_EDIT_TOGGLE = "toggle"
_EDIT_SELECT = "select"
_EDIT_INPUT = "input"
_EDIT_AUTOCOMPLETE = "autocomplete"
_EDIT_MODALITIES = "modalities"
_EDIT_NAV = "nav"
_EDIT_ACTION = "action"

_LAYOUT_LIST = "list"
_LAYOUT_MODEL_LIST = "model_list"
_LAYOUT_ARCHIVED_CHATS = "archived_chats"


class _OptionItem(Static):
    can_focus = True


class _ValueTrigger(Static):
    can_focus = True


class _SelectGroupToggle(Static):
    can_focus = False


class _ModelItem(Static):
    can_focus = True


class _ModelAction(Static):
    can_focus = True


class _ModelGroupTitle(Static):
    can_focus = False


class _FooterAction(Static):
    can_focus = True


class _ArchivedChatAction(Static):
    can_focus = True


class _ArchivedBulkAction(Static):
    can_focus = True


class _ModalitiesChip(Static):
    can_focus = True


class _ModalitiesAddTrigger(Static):
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
        width: 1fr;
        min-width: 0;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
    }

    #settings-search-row {
        height: 1;
    }

    #settings-header-select-wrap {
        display: none;
        width: auto;
        min-width: 0;
        margin-left: 0;
    }
    #settings-header-select-wrap.visible {
        display: block;
    }
    #settings-archived-bulk-wrap {
        display: none;
        width: auto;
        min-width: 0;
        margin-left: 0;
    }
    #settings-archived-bulk-wrap.visible {
        display: block;
    }
    #settings-header-select-drop {
        width: auto;
        min-width: 0;
        height: 1;
    }
    #settings-header-select-trigger,
    #settings-header-select-trigger:hover,
    #settings-header-select-trigger:focus,
    #settings-header-select-trigger.-active {
        width: auto;
        min-width: 12;
        height: 1;
        background: $SURFACE_BACKGROUND;
        background-tint: $SURFACE_BACKGROUND;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        text-align: left;
        content-align: left middle;
    }
    #settings-header-select-options {
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
    #settings-header-select-options.open {
        display: block;
    }
    .settings-header-select-option {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        background-tint: $INFO_BAR_BACKGROUND;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        content-align: left middle;
    }
    .settings-header-select-option.selected {
        text-style: bold;
    }
    .settings-header-select-option:hover,
    .settings-header-select-option:focus,
    .settings-header-select-option.-active {
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $PAGE_BACKGROUND;
    }
    .settings-header-select-separator {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $TEXT_MUTED;
        content-align: center middle;
    }
    #settings-archived-bulk-action {
        width: auto;
        min-width: 10;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 1;
        text-align: center;
        content-align: center middle;
    }
    #settings-archived-bulk-action:hover,
    #settings-archived-bulk-action:focus,
    #settings-archived-bulk-action.-active {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    #settings-archived-bulk-action.disabled,
    #settings-archived-bulk-action.disabled:hover,
    #settings-archived-bulk-action.disabled:focus,
    #settings-archived-bulk-action.disabled.-active {
        background: transparent;
        color: $TEXT_MUTED;
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
    .settings-control-trigger.placeholder,
    .settings-control-trigger.placeholder:hover,
    .settings-control-trigger.placeholder:focus,
    .settings-control-trigger.placeholder.-active {
        color: $TEXT_MUTED;
    }

    .settings-nav-trigger,
    .settings-nav-trigger:hover,
    .settings-nav-trigger:focus,
    .settings-nav-trigger.-active {
        min-width: 3;
        color: $TEXT_MUTED;
    }

    .settings-inline-action,
    .settings-inline-action:hover,
    .settings-inline-action:focus,
    .settings-inline-action.-active {
        min-width: 8;
        color: $TEXT_MUTED;
        padding: 0 0 0 1;
    }

    .settings-toggle-trigger.toggle-off,
    .settings-toggle-trigger.toggle-off:hover,
    .settings-toggle-trigger.toggle-off:focus,
    .settings-toggle-trigger.toggle-off.-active {
        color: $TEXT_MUTED;
    }

    .settings-modalities-control {
        width: auto;
        height: 1;
        min-width: 0;
    }

    .settings-modalities-chip,
    .settings-modalities-chip:hover,
    .settings-modalities-chip:focus,
    .settings-modalities-chip.-active {
        width: auto;
        height: 1;
        min-width: 0;
        background: $INFO_BAR_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        margin: 0 0 0 1;
    }

    .settings-modalities-add,
    .settings-modalities-add:hover,
    .settings-modalities-add:focus,
    .settings-modalities-add.-active {
        width: auto;
        height: 1;
        min-width: 5;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        padding: 0 1;
        margin: 0;
    }

    .settings-modalities-add.disabled,
    .settings-modalities-add.disabled:hover,
    .settings-modalities-add.disabled:focus,
    .settings-modalities-add.disabled.-active {
        background: transparent;
        background-tint: transparent;
        tint: transparent;
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
        text-align: left;
        content-align: left middle;
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

    .settings-option-btn.selected,
    .settings-option-btn.selected:focus,
    .settings-option-btn.selected.-active {
        color: $TEXT_PRIMARY;
        text-style: bold;
    }

    .settings-option-btn.selected:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    .settings-option-btn-disabled,
    .settings-option-btn-disabled:hover,
    .settings-option-btn-disabled:focus,
    .settings-option-btn-disabled.-active {
        background: $INFO_BAR_BACKGROUND;
        color: $TEXT_MUTED;
    }

    .settings-option-group-title {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
        color: $TEXT_MUTED;
        padding: 0 1;
        text-align: left;
        content-align: left middle;
    }

    .settings-option-group-gap {
        width: 100%;
        height: 1;
        background: $INFO_BAR_BACKGROUND;
    }

    .settings-select-group-toggle {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        padding: 0 1 0 1;
        content-align: left middle;
    }

    .settings-select-group-toggle:hover {
        color: $TEXT_PRIMARY;
    }

    .settings-select-group-list {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }

    .settings-select-group-list.hidden {
        display: none;
    }

    #settings-edit-input {
        width: auto;
        height: 1;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1;
    }

    .settings-control-trigger-unit,
    .settings-control-trigger-unit:hover,
    .settings-control-trigger-unit:focus,
    .settings-control-trigger-unit.-active {
        padding-right: 0;
    }

    #settings-edit-input.settings-edit-input-unit {
        padding-right: 0;
    }

    .settings-input-unit {
        width: auto;
        height: 1;
        color: $TEXT_MUTED;
        padding: 0 1 0 0;
        margin: 0;
        content-align: left middle;
    }

    .settings-limit-name {
        width: 1fr;
        height: 1;
        min-width: 0;
        margin: 0;
        padding: 0;
    }

    .settings-limit-selector-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
    }

    .settings-limit-selector-trigger,
    .settings-limit-selector-trigger:hover,
    .settings-limit-selector-trigger:focus,
    .settings-limit-selector-trigger.-active {
        width: auto;
        height: 1;
        min-width: 0;
        background: $SURFACE_BACKGROUND;
        background-tint: $SURFACE_BACKGROUND;
        tint: transparent;
        border: none;
        outline: none;
        color: $TEXT_PRIMARY;
        margin: 0;
        padding: 0 1 0 0;
        text-align: left;
        content-align: left middle;
    }

    .settings-limit-label {
        width: auto;
        height: 1;
        color: $TEXT_PRIMARY;
        margin: 0;
        padding: 0;
        content-align: left middle;
    }

    .settings-limit-selector-options {
        align-horizontal: left;
    }

    .settings-autocomplete-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
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

    .settings-archived-group-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }
    .settings-archived-group-title {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        padding: 0;
        content-align: left middle;
    }
    .settings-archived-row {
        width: 100%;
        height: 1;
        margin: 0;
    }
    .settings-archived-title {
        width: 1fr;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0;
        content-align: left middle;
    }
    .settings-archived-action {
        width: auto;
        min-width: 0;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 1;
        text-align: center;
        content-align: center middle;
    }
    .settings-archived-action:hover,
    .settings-archived-action:focus,
    .settings-archived-action.-active {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    """
    )

    BINDINGS = [
        Binding("escape", "navigate_back", "Back", priority=True),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

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
        self._collapsed_model_groups: set[str] = set()
        self._add_model_draft: dict[str, object] = {}
        self._editing_row_index: int | None = None
        self._autocomplete_filtered_options: list[str] = []
        self._autocomplete_render_generation: int = 0
        self._select_open_index: int | None = None
        self._select_group_toggle_keys: dict[str, str] = {}
        self._select_group_toggle_list_ids: dict[str, str] = {}
        self._collapsed_select_groups: dict[str, set[str]] = {}
        self._render_generation: int = 0
        self._current_footer_actions: list[dict] = []
        self._header_select_options: list[dict] = []
        self._archived_chat_actions: list[dict] = []
        self._archived_bulk_paths: list[str] = []
        self._list_content_rows: int = 0

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
                                    placeholder="Search settings",
                                    id="settings-search",
                                )
                                with Container(id="settings-header-select-wrap"):
                                    with Container(id="settings-header-select-drop"):
                                        yield _ValueTrigger(
                                            "",
                                            id="settings-header-select-trigger",
                                        )
                                        yield Vertical(
                                            id="settings-header-select-options"
                                        )
                                with Container(id="settings-archived-bulk-wrap"):
                                    yield _ArchivedBulkAction(
                                        "",
                                        id="settings-archived-bulk-action",
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
        if control_id != "settings-header-select-trigger" and not control_id.startswith(
            "settings-header-select-option-"
        ):
            self._close_header_select()

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
            group_key = str(group.get("group_key") or "")
            list_id = str(group.get("list_id") or "")
            if not list_id:
                return
            try:
                lst = self.query_one(f"#{list_id}", Vertical)
            except Exception:
                return
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
                self._collapsed_model_groups.discard(group_key)
            else:
                lst.add_class("hidden")
                self._collapsed_model_groups.add(group_key)
            visible = 0
            for g in self._model_groups:
                if str(g.get("group_key") or "") not in self._collapsed_model_groups:
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

        if control_id == "settings-header-select-trigger":
            self._toggle_header_select()
            return

        if control_id.startswith("settings-header-select-option-"):
            index = self._parse_row_index(control_id, "settings-header-select-option-")
            if index is None or index >= len(self._header_select_options):
                return
            option = self._header_select_options[index]
            if (
                bool(option.get("disabled"))
                or str(option.get("type") or "") == "separator"
            ):
                return
            on_change = self._current_page().get("on_header_select_change")
            if callable(on_change):
                on_change(str(option.get("value") or ""))
            self._close_header_select()
            self._render_current_page(self._current_query())
            return

        if control_id.startswith("settings-archived-action-"):
            index = self._parse_row_index(control_id, "settings-archived-action-")
            if index is None or index >= len(self._archived_chat_actions):
                return
            action = self._archived_chat_actions[index]
            on_archived_action = self._current_page().get("on_archived_action")
            if callable(on_archived_action):
                on_archived_action(
                    str(action.get("session_path") or ""),
                    str(action.get("action") or ""),
                )
            self._render_current_page(self._current_query())
            return

        if control_id == "settings-archived-bulk-action":
            if not self._archived_bulk_paths:
                return
            on_bulk_remove = self._current_page().get("on_archived_bulk_remove")
            if callable(on_bulk_remove):
                on_bulk_remove(list(self._archived_bulk_paths))
            self._render_current_page(self._current_query())
            return

        add_row_index = self._parse_row_index(control_id, "settings-modal-add-")
        if add_row_index is not None:
            rows = self._visible_rows()
            if 0 <= add_row_index < len(rows):
                row = rows[add_row_index]
                if self._remaining_modalities(row):
                    self._toggle_select_options(add_row_index)
            return

        parsed_remove = self._parse_modalities_remove(control_id)
        if parsed_remove is not None:
            row_index, modality = parsed_remove
            rows = self._visible_rows()
            if 0 <= row_index < len(rows):
                row = rows[row_index]
                current = list(self._modalities_from_value(str(row.get("value") or "")))
                updated = [item for item in current if item != modality]
                self._close_select_options()
                self._apply_change(row, format_extra_modalities(updated))
            return

        parsed_modal_opt = self._parse_modalities_option_indices(control_id)
        if parsed_modal_opt is not None:
            row_index, option_index = parsed_modal_opt
            rows = self._visible_rows()
            if 0 <= row_index < len(rows):
                row = rows[row_index]
                remaining = self._remaining_modalities(row)
                if 0 <= option_index < len(remaining):
                    current = list(
                        self._modalities_from_value(str(row.get("value") or ""))
                    )
                    current.append(remaining[option_index])
                    self._apply_change(row, format_extra_modalities(current))
            return

        if control_id.startswith("settings-limit-selector-"):
            row_index = self._parse_row_index(
                control_id, "settings-limit-selector-"
            )
            if row_index is not None:
                self._toggle_select_options(row_index)
            return

        if control_id == "settings-edit-input":
            if self._editing_row_index is not None:
                rows = self._visible_rows()
                if 0 <= self._editing_row_index < len(rows):
                    row = rows[self._editing_row_index]
                    if row.get("edit_type") == _EDIT_AUTOCOMPLETE:
                        try:
                            input_widget = self.query_one("#settings-edit-input", Input)
                            self._refresh_autocomplete_options(input_widget.value)
                        except Exception:
                            pass
            return

        if control_id.startswith("settings-autocomplete-opt-"):
            option_index = self._parse_autocomplete_option_index(control_id)
            if (
                option_index is not None
                and self._editing_row_index is not None
                and 0 <= option_index < len(self._autocomplete_filtered_options)
            ):
                self._commit_input(
                    self._editing_row_index,
                    self._autocomplete_filtered_options[option_index],
                )
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

        if control_id.startswith("settings-accessory-"):
            row_index = self._parse_row_index(control_id, "settings-accessory-")
            if row_index is None:
                return
            rows = self._visible_rows()
            if row_index < 0 or row_index >= len(rows):
                return
            row = rows[row_index]
            target_page = str(row.get("accessory_target_page") or "").strip()
            if target_page:
                self._push_page(target_page)
                return
            accessory_action = row.get("accessory_action")
            if callable(accessory_action):
                accessory_action()
                self._render_current_page(self._current_query())
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
            options = self._select_options(row)
            if 0 <= option_index < len(options):
                option_value = str(options[option_index][1])
                if option_value in self._disabled_option_values(row):
                    return
                if bool(row.get("limit_selector")):
                    self._commit_limit_selector(row_index, option_value)
                else:
                    self._commit_select(row_index, option_value)
            return

        if control_id.startswith("settings-select-group-toggle-"):
            group_key = self._select_group_toggle_keys.get(control_id)
            list_id = self._select_group_toggle_list_ids.get(control_id)
            parsed = self._parse_select_group_indices(control_id)
            if group_key is None or list_id is None or parsed is None:
                return
            row_index, _group_index = parsed
            rows = self._visible_rows()
            if row_index < 0 or row_index >= len(rows):
                return
            self._toggle_select_group(rows[row_index], group_key, list_id)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "settings-search":
            self._close_header_select()
            self._editing_row_index = None
            self._autocomplete_filtered_options = []
            self._select_open_index = None
            self._render_current_page(event.value)
            return
        if (
            event.input.id == "settings-edit-input"
            and self._editing_row_index is not None
        ):
            rows = self._visible_rows()
            if 0 <= self._editing_row_index < len(rows):
                row = rows[self._editing_row_index]
                if row.get("edit_type") == _EDIT_AUTOCOMPLETE:
                    self._refresh_autocomplete_options(event.value)

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

    def action_navigate_back(self) -> None:
        self._go_back()

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
        self.set_focus(None)
        self._page_stack.append(page_id)
        self._selected_model_name = ""
        self._reset_search()
        self._render_current_page("")

    def _go_back(self) -> None:
        if len(self._page_stack) <= 1:
            self.dismiss(None)
            return
        self.set_focus(None)
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
        self._close_header_select()
        self._close_select_options()
        if self._editing_row_index is not None:
            self._finish_input_edit()
        self._update_chrome()
        if self._current_layout() == _LAYOUT_MODEL_LIST:
            self._render_model_page()
        elif self._current_layout() == _LAYOUT_ARCHIVED_CHATS:
            self._render_archived_chats_page(query)
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
        search_input = self.query_one("#settings-search", Input)
        search_gap = self.query_one("#settings-search-gap", Static)
        list_panel = self.query_one("#settings-list-panel", Vertical)
        model_panel = self.query_one("#settings-model-panel", Horizontal)
        header_select_wrap = self.query_one("#settings-header-select-wrap", Container)
        archived_bulk_wrap = self.query_one("#settings-archived-bulk-wrap", Container)
        archived_bulk_action = self.query_one(
            "#settings-archived-bulk-action", _ArchivedBulkAction
        )

        title.update(str(page.get("title") or "Settings"))
        back_button.add_class("hidden")
        close_button.update("esc")
        add_button.update(str(page.get("add_label") or "Add model"))
        search_input.placeholder = str(
            page.get("search_placeholder") or "Search settings"
        )

        show_search = bool(page.get("show_search", True)) and (
            self._current_layout() in {_LAYOUT_LIST, _LAYOUT_ARCHIVED_CHATS}
        )
        search_row.display = show_search
        search_gap.display = show_search
        list_panel.display = self._current_layout() in {
            _LAYOUT_LIST,
            _LAYOUT_ARCHIVED_CHATS,
        }
        model_panel.display = self._current_layout() == _LAYOUT_MODEL_LIST
        if self._current_layout() == _LAYOUT_ARCHIVED_CHATS:
            header_select_wrap.add_class("visible")
            archived_bulk_wrap.add_class("visible")
        else:
            header_select_wrap.remove_class("visible")
            archived_bulk_wrap.remove_class("visible")
            self._header_select_options = []
            self._archived_bulk_paths = []
        archived_bulk_action.remove_class("disabled")
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

    def _limit_selector_id(self, row_index: int) -> str:
        return f"settings-limit-selector-{self._render_generation}-{row_index}"

    def _accessory_id(self, row_index: int) -> str:
        return f"settings-accessory-{self._render_generation}-{row_index}"

    def _model_item_id(self, item_index: int) -> str:
        return f"settings-model-item-{self._render_generation}-{item_index}"

    def _model_group_id(self, group_index: int) -> str:
        return f"settings-model-group-{self._render_generation}-{group_index}"

    def _model_group_list_id(self, group_index: int) -> str:
        return f"settings-model-group-list-{self._render_generation}-{group_index}"

    def _select_group_toggle_id(self, row_index: int, group_index: int) -> str:
        return (
            f"settings-select-group-toggle-"
            f"{self._render_generation}-{row_index}-{group_index}"
        )

    def _select_group_list_id(self, row_index: int, group_index: int) -> str:
        return (
            f"settings-select-group-list-"
            f"{self._render_generation}-{row_index}-{group_index}"
        )

    def _footer_action_id(self, action_index: int) -> str:
        return f"settings-footer-action-{self._render_generation}-{action_index}"

    def _archived_action_id(self, action_index: int) -> str:
        return f"settings-archived-action-{self._render_generation}-{action_index}"

    def _modalities_add_id(self, row_index: int) -> str:
        return f"settings-modal-add-{self._render_generation}-{row_index}"

    def _modalities_remove_id(self, row_index: int, modality: str) -> str:
        return f"settings-modal-remove-{self._render_generation}-{row_index}-{modality}"

    def _modalities_option_id(self, row_index: int, option_index: int) -> str:
        return (
            f"settings-modal-opt-{self._render_generation}-{row_index}-{option_index}"
        )

    def _autocomplete_options_id(self, row_index: int) -> str:
        return f"settings-autocomplete-options-{self._render_generation}-{row_index}"

    def _autocomplete_option_id(self, row_index: int, option_index: int) -> str:
        return (
            f"settings-autocomplete-opt-"
            f"{self._render_generation}-{row_index}-"
            f"{self._autocomplete_render_generation}-{option_index}"
        )

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

    def _parse_select_group_indices(self, control_id: str) -> tuple[int, int] | None:
        prefix = "settings-select-group-toggle-"
        if not control_id.startswith(prefix):
            return None
        payload = control_id[len(prefix) :]
        try:
            _generation, row_text, group_text = payload.split("-", 2)
            return int(row_text), int(group_text)
        except (TypeError, ValueError):
            return None

    def _parse_autocomplete_option_index(self, control_id: str) -> int | None:
        prefix = "settings-autocomplete-opt-"
        if not control_id.startswith(prefix):
            return None
        try:
            return int(control_id.rsplit("-", 1)[1])
        except (TypeError, ValueError):
            return None

    def _parse_modalities_remove(self, control_id: str) -> tuple[int, str] | None:
        prefix = "settings-modal-remove-"
        if not control_id.startswith(prefix):
            return None
        payload = control_id[len(prefix) :]
        try:
            _generation, row_text, modality = payload.split("-", 2)
            return int(row_text), str(modality)
        except (TypeError, ValueError):
            return None

    def _parse_modalities_option_indices(
        self,
        control_id: str,
    ) -> tuple[int, int] | None:
        prefix = "settings-modal-opt-"
        if not control_id.startswith(prefix):
            return None
        payload = control_id[len(prefix) :]
        try:
            _generation, row_text, option_text = payload.split("-", 2)
            return int(row_text), int(option_text)
        except (TypeError, ValueError):
            return None

    def _modalities_from_value(self, value: str) -> tuple[str, ...]:
        try:
            return parse_extra_modalities_input(str(value or ""), required=True)
        except ValueError:
            return ()

    def _remaining_modalities(self, row: dict) -> list[str]:
        selected = set(self._modalities_from_value(str(row.get("value") or "")))
        return [
            str(opt_value)
            for _, opt_value in list(row.get("options") or [])
            if str(opt_value) not in selected
        ]

    def _click_target_id(self, event: events.Click) -> str:
        control = getattr(event, "control", None) or getattr(event, "widget", None)
        while control is not None:
            control_id = getattr(control, "id", None)
            if control_id:
                return str(control_id)
            control = getattr(control, "parent", None)
        return ""

    def _header_select_option_id(self, option_index: int) -> str:
        return f"settings-header-select-option-{self._render_generation}-{option_index}"

    def _toggle_header_select(self) -> None:
        if not self._header_select_options:
            return
        options_container = self.query_one("#settings-header-select-options", Vertical)
        if options_container.has_class("open"):
            options_container.remove_class("open")
        else:
            options_container.add_class("open")

    def _close_header_select(self) -> None:
        try:
            options_container = self.query_one(
                "#settings-header-select-options", Vertical
            )
        except Exception:
            return
        options_container.remove_class("open")

    def _set_header_select_state(
        self,
        *,
        label: str,
        options: list[dict],
        selected_value: str = "",
    ) -> None:
        wrap = self.query_one("#settings-header-select-wrap", Container)
        trigger = self.query_one("#settings-header-select-trigger", _ValueTrigger)
        drop = self.query_one("#settings-header-select-drop", Container)
        options_container = self.query_one("#settings-header-select-options", Vertical)
        self._header_select_options = [dict(option) for option in list(options or [])]
        wrap.add_class("visible")
        trigger_label = str(label or "").strip() or "All project"
        trigger.update(trigger_label)
        trigger_width = max(12, len(trigger_label) + 2)
        drop.styles.width = trigger_width
        drop.styles.min_width = trigger_width
        trigger.styles.width = trigger_width
        trigger.styles.min_width = trigger_width

        longest_label = max([
            len(trigger_label),
            *[
                len(str(option.get("label") or ""))
                for option in self._header_select_options
                if str(option.get("type") or "") != "separator"
            ],
        ])
        option_width = max(14, longest_label + 2)
        options_container.styles.width = option_width
        options_container.styles.min_width = option_width
        options_container.styles.offset = (trigger_width - option_width, 0)

        for child in list(options_container.children):
            child.remove()

        separator_text = "\u2500" * max(1, option_width - 2)
        for index, option in enumerate(self._header_select_options):
            if str(option.get("type") or "") == "separator":
                options_container.mount(
                    Static(separator_text, classes="settings-header-select-separator")
                )
                continue
            classes = "settings-header-select-option"
            if str(option.get("value") or "") == selected_value:
                classes += " selected"
            options_container.mount(
                _OptionItem(
                    str(option.get("label") or ""),
                    id=self._header_select_option_id(index),
                    classes=classes,
                )
            )

    def _archived_state(self, query: str) -> dict:
        state = self._current_page().get("state") or {}
        if callable(state):
            state = state(query)
        return dict(state or {})

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
            for label, opt_value in self._select_options(row):
                if str(opt_value) == value:
                    return str(label)
        return value

    def _select_groups(self, row: dict) -> list[dict]:
        groups = list(row.get("option_groups") or [])
        if groups:
            return groups
        options = list(row.get("options") or [])
        if not options:
            return []
        return [{"title": "", "options": options}]

    def _select_options(self, row: dict) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        for group in self._select_groups(row):
            for label, opt_value in list(group.get("options") or []):
                options.append((str(label), str(opt_value)))
        return options

    def _select_group_state_key(self, row: dict) -> str:
        page_id = str(self._page_stack[-1] if self._page_stack else "")
        name = str(row.get("name") or "")
        keywords = str(row.get("keywords") or "")
        return f"{page_id}:{name}:{keywords}"

    def _collapsed_select_group_keys(self, row: dict) -> set[str]:
        key = self._select_group_state_key(row)
        collapsed = self._collapsed_select_groups.setdefault(key, set())
        return set(collapsed)

    def _set_collapsed_select_group_keys(self, row: dict, values: set[str]) -> None:
        key = self._select_group_state_key(row)
        self._collapsed_select_groups[key] = set(values)

    def _toggle_select_group(self, row: dict, group_key: str, list_id: str) -> None:
        try:
            group_list = self.query_one(f"#{list_id}", Vertical)
        except Exception:
            return
        collapsed = self._collapsed_select_group_keys(row)
        if group_list.has_class("hidden"):
            group_list.remove_class("hidden")
            collapsed.discard(group_key)
        else:
            group_list.add_class("hidden")
            collapsed.add(group_key)
        self._set_collapsed_select_group_keys(row, collapsed)

    def _disabled_option_values(self, row: dict) -> set[str]:
        return {str(value) for value in list(row.get("disabled_options") or [])}

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
                if result == "back":
                    self._go_back()
                elif isinstance(result, str) and result in self.pages:
                    while len(self._page_stack) > 1 and self._page_stack[-1] != result:
                        self._page_stack.pop()
                    if self._page_stack[-1] != result:
                        self._page_stack.append(result)
                self._render_current_page(self._current_query())
        elif edit_type == _EDIT_TOGGLE:
            self._commit_toggle(row_index)
        elif edit_type == _EDIT_SELECT:
            self._toggle_select_options(row_index)
        elif edit_type == _EDIT_MODALITIES:
            return
        elif edit_type in {_EDIT_INPUT, _EDIT_AUTOCOMPLETE}:
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
            models_needed = max(0, int(self._model_sidebar_content_rows or 0))
            detail_needed = max(
                0,
                sum(self._estimated_row_height(row) for row in self._current_rows) or 0,
            )
            panel_needed = max(detail_needed + footer_rows, models_needed + 2)
            panel_height = min(max(1, panel_needed), available_height)
            detail_height = (
                max(1, panel_height - footer_rows)
                if detail_needed or footer_rows
                else 0
            )
            model_items_height = max(1, panel_height - 2) if models_needed else 0
            model_detail_scroll.styles.height = detail_height
            model_detail_scroll.styles.max_height = (
                max(1, available_height - footer_rows) if detail_height else 0
            )
            model_items_scroll.styles.height = model_items_height
            model_items_scroll.styles.max_height = (
                max(1, available_height - 2) if model_items_height else 0
            )
            list_scroll.styles.height = 1
            list_scroll.styles.max_height = 1
        else:
            list_needed = max(1, int(self._list_content_rows or 0))
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
        self._list_content_rows = 0
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
            self._list_content_rows += self._estimated_row_height(row)
            visible_count += 1

        if visible_count == 0:
            settings_list.mount(Static("No matching settings", classes="settings-name"))
            self._list_content_rows = 1

    def _render_archived_chats_page(self, query: str) -> None:
        settings_list = self.query_one("#settings-list", Vertical)
        try:
            detail_footer = self.query_one("#settings-model-detail-footer", Horizontal)
            for child in list(detail_footer.children):
                child.remove()
            detail_footer.remove_class("open")
        except Exception:
            pass
        self._current_rows = []
        self._current_footer_actions = []
        self._archived_chat_actions = []
        self._list_content_rows = 0
        self._render_generation += 1
        for child in list(settings_list.children):
            child.remove()

        state = self._archived_state(query)
        self._archived_bulk_paths = [
            str(path or "").strip()
            for path in list(state.get("bulk_remove_paths") or [])
            if str(path or "").strip()
        ]
        self._set_header_select_state(
            label=str(state.get("filter_label") or "All project"),
            options=list(state.get("filter_options") or []),
            selected_value=str(state.get("filter_value") or ""),
        )
        bulk_action = self.query_one(
            "#settings-archived-bulk-action", _ArchivedBulkAction
        )
        bulk_label = str(state.get("bulk_remove_label") or "Remove all")
        bulk_action.update(bulk_label)
        bulk_action.styles.width = max(10, len(bulk_label) + 2)
        bulk_action.styles.min_width = max(10, len(bulk_label) + 2)
        bulk_action.set_class(not self._archived_bulk_paths, "disabled")

        groups = list(state.get("groups") or [])
        if not groups:
            settings_list.mount(
                Static(
                    str(state.get("empty_label") or "No archived chats"),
                    classes="settings-name",
                )
            )
            self._list_content_rows = 1
            return

        for group_index, group in enumerate(groups):
            if group_index > 0:
                settings_list.mount(Static("", classes="settings-archived-group-gap"))
                self._list_content_rows += 1
            settings_list.mount(
                Static(
                    str(group.get("title") or ""),
                    classes="settings-archived-group-title",
                )
            )
            self._list_content_rows += 1
            for session in list(group.get("sessions") or []):
                remove_index = len(self._archived_chat_actions)
                self._archived_chat_actions.append({
                    "action": "remove",
                    "session_path": str(session.get("session_path") or ""),
                })
                unarchive_index = len(self._archived_chat_actions)
                self._archived_chat_actions.append({
                    "action": "unarchive",
                    "session_path": str(session.get("session_path") or ""),
                })
                settings_list.mount(
                    Horizontal(
                        Static(
                            str(session.get("title") or "New Chat"),
                            classes="settings-archived-title",
                        ),
                        _ArchivedChatAction(
                            "Remove",
                            id=self._archived_action_id(remove_index),
                            classes="settings-archived-action",
                        ),
                        _ArchivedChatAction(
                            "Unarchive",
                            id=self._archived_action_id(unarchive_index),
                            classes="settings-archived-action",
                        ),
                        classes="settings-archived-row",
                    )
                )
                self._list_content_rows += 1

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
        empty_list_label = (
            str(state.get("empty_list_label"))
            if "empty_list_label" in state
            else "No items"
        )
        blank_detail_when_empty = bool(state.get("blank_detail_when_empty", False))
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

        if not groups and all_model_names:
            groups = [{"provider": "", "title": "Models", "models": all_model_names}]

        selected_group_key = ""
        for group in groups:
            group_key = str(group.get("provider") or "")
            if self._selected_model_name in list(group.get("models") or []):
                selected_group_key = group_key
                break
        if selected_group_key:
            self._collapsed_model_groups.discard(selected_group_key)

        self._model_groups = []
        self._current_model_names = []
        visible_model_count = 0
        header_count = 0

        for group_index, group in enumerate(groups):
            group_key = str(group.get("provider") or "")
            title = str(group.get("title") or "") or (group_key or "Other")
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
            if allow_group_collapse and group_key in self._collapsed_model_groups:
                group_list_classes += " hidden"
            group_list = Vertical(id=group_list_id, classes=group_list_classes)
            self._model_groups.append({
                "group_key": group_key,
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
                    group_key not in self._collapsed_model_groups
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
            if empty_list_label:
                model_items.mount(Static(empty_list_label, classes="settings-name"))
                self._model_sidebar_content_rows = 1
            else:
                self._model_sidebar_content_rows = 0
        else:
            group_gap_rows = max(0, len(groups) - 1)
            self._model_sidebar_content_rows = (
                header_count + group_gap_rows + visible_model_count
            )

        for row_index, row in enumerate(self._current_rows):
            row["_visible"] = True
            row["_render_index"] = row_index
            detail_list.mount(self._build_row_widget(row, row_index))

        if not self._current_rows and not blank_detail_when_empty:
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
        unit = str(row.get("unit") or "").strip()
        limit_selector = bool(row.get("limit_selector"))
        header_children = [] if limit_selector else [Static(name, classes="settings-name")]
        if limit_selector:
            options = self._select_options(row)
            selected = str(row.get("limit_key") or "")
            selected_label = next(
                (label for label, value in options if value == selected),
                selected.title(),
            )
            trigger_width = max(len(selected_label) + 1, 6)
            option_width = max(
                max((len(label) for label, _value in options), default=0) + 2,
                trigger_width,
            )
            option_widgets = [
                _OptionItem(
                    label,
                    markup=False,
                    id=self._option_id(row_index, option_index),
                    classes=(
                        "settings-option-btn selected"
                        if value == selected
                        else "settings-option-btn"
                    ),
                )
                for option_index, (label, value) in enumerate(options)
            ]
            options_container = Vertical(
                *option_widgets,
                id=self._options_id(row_index),
                classes="settings-options settings-limit-selector-options",
            )
            options_container.styles.width = option_width
            options_container.styles.min_width = option_width
            selector_trigger = _ValueTrigger(
                selected_label,
                markup=False,
                id=self._limit_selector_id(row_index),
                classes="settings-limit-selector-trigger",
            )
            selector_trigger.styles.width = trigger_width
            selector_trigger.styles.min_width = trigger_width
            selector_drop = Container(
                selector_trigger,
                options_container,
                classes="settings-limit-selector-drop",
            )
            selector_drop.styles.width = trigger_width
            selector_drop.styles.min_width = trigger_width
            header_children.append(
                Horizontal(
                    selector_drop,
                    Static("limit", markup=False, classes="settings-limit-label"),
                    classes="settings-limit-name",
                )
            )
        accessory_label = str(row.get("accessory_label") or "").strip()
        accessory_widget = None
        if accessory_label:
            accessory_widget = _ValueTrigger(
                accessory_label,
                markup=False,
                id=self._accessory_id(row_index),
                classes="settings-control-trigger settings-inline-action",
            )

        if edit_type == _EDIT_NONE:
            header_children.append(
                Static(
                    self._display_value(row),
                    classes="settings-value settings-value-static",
                )
            )
        elif edit_type == _EDIT_SELECT:
            option_widgets = []
            display_value = self._display_value(row)
            disabled_options = self._disabled_option_values(row)
            trigger_width = max(len(display_value) + 2, 7)
            select_groups = self._select_groups(row)
            grouped_select = bool(row.get("option_groups"))
            selected_value = str(row.get("value") or "")
            collapsed_group_keys = self._collapsed_select_group_keys(row)
            selected_group_key = ""
            for group in select_groups:
                group_key = str(group.get("provider") or "")
                for _label, opt_value in list(group.get("options") or []):
                    if str(opt_value) == selected_value:
                        selected_group_key = group_key
                        break
                if selected_group_key:
                    break
            if selected_group_key:
                collapsed_group_keys.discard(selected_group_key)
                self._set_collapsed_select_group_keys(row, collapsed_group_keys)
            option_width = max(
                (
                    len(str(label))
                    for group in select_groups
                    for label, _ in list(group.get("options") or [])
                ),
                default=0,
            )
            option_width = max(
                option_width,
                max(
                    (len(str(group.get("title") or "")) for group in select_groups),
                    default=0,
                ),
            )
            option_width = max(option_width, len(display_value)) + 2
            flat_option_index = 0
            self._select_group_toggle_keys = {
                key: value
                for key, value in self._select_group_toggle_keys.items()
                if not key.startswith(
                    f"settings-select-group-toggle-{self._render_generation}-{row_index}-"
                )
            }
            self._select_group_toggle_list_ids = {
                key: value
                for key, value in self._select_group_toggle_list_ids.items()
                if not key.startswith(
                    f"settings-select-group-toggle-{self._render_generation}-{row_index}-"
                )
            }
            for group_index, group in enumerate(select_groups):
                title = str(group.get("title") or "")
                group_key = str(group.get("provider") or "")
                if grouped_select and title:
                    if group_index > 0:
                        option_widgets.append(
                            Static(
                                "",
                                classes="settings-select-group-gap settings-option-group-gap",
                            )
                        )
                    toggle_id = self._select_group_toggle_id(row_index, group_index)
                    list_id = self._select_group_list_id(row_index, group_index)
                    self._select_group_toggle_keys[toggle_id] = group_key
                    self._select_group_toggle_list_ids[toggle_id] = list_id
                    option_widgets.append(
                        _SelectGroupToggle(
                            title,
                            id=toggle_id,
                            classes="settings-select-group-toggle",
                        )
                    )
                    list_classes = "settings-select-group-list"
                    if group_key in collapsed_group_keys:
                        list_classes += " hidden"
                    group_list_children = []
                    for label, opt_value in list(group.get("options") or []):
                        option_classes = "settings-option-btn"
                        if str(opt_value) in disabled_options:
                            option_classes += " settings-option-btn-disabled"
                        if str(opt_value) == selected_value:
                            option_classes += " selected"
                        group_list_children.append(
                            _OptionItem(
                                str(label),
                                id=self._option_id(row_index, flat_option_index),
                                classes=option_classes,
                            )
                        )
                        flat_option_index += 1
                    group_list = Vertical(
                        *group_list_children,
                        id=list_id,
                        classes=list_classes,
                    )
                    option_widgets.append(group_list)
                    continue
                if title:
                    if group_index > 0:
                        option_widgets.append(
                            Static("", classes="settings-option-group-gap")
                        )
                    option_widgets.append(
                        Static(title, classes="settings-option-group-title")
                    )
                for label, opt_value in list(group.get("options") or []):
                    option_classes = "settings-option-btn"
                    if str(opt_value) in disabled_options:
                        option_classes += " settings-option-btn-disabled"
                    if str(opt_value) == selected_value:
                        option_classes += " selected"
                    option_widgets.append(
                        _OptionItem(
                            str(label),
                            id=self._option_id(row_index, flat_option_index),
                            classes=option_classes,
                        )
                    )
                    flat_option_index += 1
            options_container = Vertical(
                *option_widgets,
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
            if accessory_widget is not None:
                header_children.append(accessory_widget)
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
            if accessory_widget is not None:
                header_children.append(accessory_widget)
            header_children.append(trigger)
        elif edit_type == _EDIT_MODALITIES:
            selected_modalities = list(
                self._modalities_from_value(str(row.get("value") or ""))
            )
            remaining_modalities = self._remaining_modalities(row)
            option_width = (
                max((len(item) for item in remaining_modalities), default=0) + 2
            )
            option_width = max(option_width, 7)
            option_buttons = [
                _OptionItem(
                    str(modality).title(),
                    id=self._modalities_option_id(row_index, option_index),
                    classes="settings-option-btn",
                )
                for option_index, modality in enumerate(remaining_modalities)
            ]
            options_container = Vertical(
                *option_buttons,
                id=self._options_id(row_index),
                classes="settings-options",
            )
            add_width = 5
            options_container.styles.width = option_width
            options_container.styles.min_width = option_width
            options_container.styles.offset = (add_width - option_width, 0)
            controls: list = []
            for modality in selected_modalities:
                controls.append(
                    _ModalitiesChip(
                        f"\u00d7 {str(modality).title()}",
                        markup=False,
                        id=self._modalities_remove_id(row_index, modality),
                        classes="settings-modalities-chip",
                    )
                )
            add_classes = "settings-modalities-add"
            if not remaining_modalities:
                add_classes += " disabled"
            add_trigger = _ModalitiesAddTrigger(
                "Add",
                markup=False,
                id=self._modalities_add_id(row_index),
                classes=add_classes,
            )
            add_trigger.styles.width = add_width
            add_trigger.styles.min_width = add_width
            controls.append(
                Container(
                    add_trigger,
                    options_container,
                    classes="settings-modalities-control",
                )
            )
            if accessory_widget is not None:
                header_children.append(accessory_widget)
            header_children.extend(controls)
        else:
            trigger_classes = "settings-control-trigger"
            if unit and edit_type == _EDIT_INPUT:
                trigger_classes += " settings-control-trigger-unit"
            if edit_type == _EDIT_NAV:
                trigger_classes += " settings-nav-trigger"
            display_value = self._display_value(row)
            placeholder_value = str(row.get("placeholder_value") or "")
            if (
                edit_type in {_EDIT_INPUT, _EDIT_AUTOCOMPLETE}
                and not str(row.get("value") or "")
                and placeholder_value
            ):
                display_value = placeholder_value
                trigger_classes += " placeholder"
            if accessory_widget is not None:
                header_children.append(accessory_widget)
            header_children.append(
                _ValueTrigger(
                    display_value,
                    markup=False,
                    id=self._trigger_id(row_index),
                    classes=trigger_classes,
                )
            )
            if unit and edit_type == _EDIT_INPUT:
                header_children.append(
                    Static(unit, markup=False, classes="settings-input-unit")
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

    def _commit_limit_selector(self, row_index: int, new_value: str) -> None:
        self._close_select_options()
        row = self._visible_rows()[row_index]
        on_change = row.get("on_limit_select")
        if callable(on_change):
            on_change(str(new_value))
        self._render_current_page(self._current_query())

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
                row = self._visible_rows()[row_index]
                if row.get("edit_type") == _EDIT_AUTOCOMPLETE:
                    self._refresh_autocomplete_options(input_widget.value)
                return
            except Exception:
                pass
        if self._editing_row_index is not None:
            self._finish_input_edit()

        self._editing_row_index = row_index
        row = self._visible_rows()[row_index]
        current_value = str(row.get("value") or "")
        placeholder_value = str(row.get("placeholder_value") or "")

        row_widget = self.query_one(f"#{self._row_widget_id(row_index)}", Horizontal)
        value_button = row_widget.query_one(
            f"#{self._trigger_id(row_index)}", _ValueTrigger
        )
        value_button.display = False

        input_kwargs = {
            "value": current_value,
            "id": "settings-edit-input",
        }
        if placeholder_value:
            input_kwargs["placeholder"] = placeholder_value
        input_widget = Input(**input_kwargs)
        if row.get("unit"):
            input_widget.add_class("settings-edit-input-unit")
        input_width = max(len(current_value or placeholder_value) + 3, 8)
        input_widget.styles.width = input_width
        if row.get("edit_type") == _EDIT_AUTOCOMPLETE:
            options = self._autocomplete_options(row)
            normalized_query = current_value.strip()
            filtered = [
                option
                for option in options
                if not normalized_query or normalized_query in option
            ]
            self._autocomplete_filtered_options = filtered
            self._autocomplete_render_generation += 1
            option_widgets: list[Static] = []
            if filtered:
                option_widgets.extend(
                    _OptionItem(
                        option,
                        markup=False,
                        id=self._autocomplete_option_id(row_index, option_index),
                        classes="settings-option-btn",
                    )
                    for option_index, option in enumerate(filtered)
                )
                longest_label = max(len(option) for option in filtered)
            else:
                longest_label = input_width
            option_classes = "settings-options settings-autocomplete-options"
            if filtered:
                option_classes += " open"
            options_container = Vertical(
                *option_widgets,
                id=self._autocomplete_options_id(row_index),
                classes=option_classes,
            )
            option_width = max(input_width, longest_label + 2)
            options_container.styles.width = option_width
            options_container.styles.min_width = option_width
            options_container.styles.offset = (input_width - option_width, 0)
            drop_container = Container(
                input_widget,
                options_container,
                classes="settings-control-drop settings-autocomplete-drop",
            )
            drop_container.styles.width = input_width
            drop_container.styles.min_width = input_width
            row_widget.mount(drop_container)
        else:
            if row.get("unit"):
                unit_widget = row_widget.query_one(".settings-input-unit", Static)
                row_widget.mount(input_widget, before=unit_widget)
            else:
                row_widget.mount(input_widget)
        input_widget.focus()

    def _autocomplete_options(self, row: dict) -> list[str]:
        options: list[str] = []
        seen: set[str] = set()
        for option in list(row.get("suggestions") or []):
            value = str(option or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            options.append(value)
        return options

    def _refresh_autocomplete_options(self, query: str) -> None:
        if self._editing_row_index is None:
            return
        rows = self._visible_rows()
        if not (0 <= self._editing_row_index < len(rows)):
            return
        row = rows[self._editing_row_index]
        if row.get("edit_type") != _EDIT_AUTOCOMPLETE:
            return
        try:
            options_container = self.query_one(
                f"#{self._autocomplete_options_id(self._editing_row_index)}", Vertical
            )
            input_widget = self.query_one("#settings-edit-input", Input)
            drop_container = options_container.parent
        except Exception:
            return

        options = self._autocomplete_options(row)
        normalized_query = str(query or "").strip()
        filtered = [
            option
            for option in options
            if not normalized_query or normalized_query in option
        ]
        self._autocomplete_filtered_options = filtered
        self._autocomplete_render_generation += 1
        for child in list(options_container.children):
            child.remove()

        input_width = max(len(str(query or "")) + 3, 8)
        input_widget.styles.width = input_width
        drop_container.styles.width = input_width
        drop_container.styles.min_width = input_width
        if not options:
            options_container.remove_class("open")
            return

        if not filtered:
            options_container.remove_class("open")
            return

        for option_index, option in enumerate(filtered):
            options_container.mount(
                _OptionItem(
                    option,
                    markup=False,
                    id=self._autocomplete_option_id(
                        self._editing_row_index, option_index
                    ),
                    classes="settings-option-btn",
                )
            )
        longest_label = max(len(option) for option in filtered)

        option_width = max(input_width, longest_label + 2)
        options_container.styles.width = option_width
        options_container.styles.min_width = option_width
        options_container.styles.offset = (input_width - option_width, 0)
        options_container.add_class("open")

    def _finish_input_edit(self) -> None:
        if self._editing_row_index is None:
            return
        try:
            row_widget = self.query_one(
                f"#{self._row_widget_id(self._editing_row_index)}", Horizontal
            )
            value_button = row_widget.query_one(
                f"#{self._trigger_id(self._editing_row_index)}", _ValueTrigger
            )
            value_button.display = True
            try:
                autocomplete_drop = row_widget.query_one(
                    ".settings-autocomplete-drop", Container
                )
                autocomplete_drop.display = False
                autocomplete_drop.remove()
            except Exception:
                try:
                    input_widget = row_widget.query_one("#settings-edit-input", Input)
                    input_widget.display = False
                    input_widget.remove()
                except Exception:
                    pass
        except Exception:
            pass
        self._editing_row_index = None
        self._autocomplete_filtered_options = []

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
            "provider": "",
            "name": "",
            "api_type": API_TYPE_OLLAMA,
            "base_url": "",
            "model": "",
            "api_key": "",
            "max_tokens": "0",
            "temperature": "0",
            "stream_mode": "false",
            "thinking_mode": "false",
            "reasoning_effort": "medium",
            "extra_modalities": "none",
            "image_limit": str(DEFAULT_EXTRA_MODALITY_LIMITS["image"]),
            "audio_limit": str(DEFAULT_EXTRA_MODALITY_LIMITS["audio"]),
            "video_limit": str(DEFAULT_EXTRA_MODALITY_LIMITS["video"]),
            "multimodal_limit": str(DEFAULT_MULTIMODAL_LIMIT),
            "selected_limit": "total",
            "context_window_tokens": "0",
        }

    def _existing_model_providers(self) -> list[str]:
        providers: set[str] = set()
        if self.app_ref is not None:
            try:
                model_list = getattr(self.app_ref.config, "model_list", {}) or {}
                for profile in model_list.values():
                    provider = str(getattr(profile, "provider", "") or "").strip()
                    if provider:
                        providers.add(provider)
            except Exception:
                pass
        if not providers:
            for group in self._model_groups:
                provider = str(group.get("provider") or "").strip()
                if provider:
                    providers.add(provider)
        return sorted(providers, key=str.casefold)

    def _set_add_model_field(self, key: str, value: str) -> None:
        if not self._add_model_draft:
            self._add_model_draft = {}
        if key == "api_type":
            value = str(value or API_TYPE_OLLAMA)
            current_effort = self._add_model_draft.get("reasoning_effort") or "medium"
            self._add_model_draft["reasoning_effort"] = (
                normalize_reasoning_effort_for_api(value, current_effort)
            )
            if value == API_TYPE_GLM:
                self._add_model_draft.pop("base_url", None)
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
        draft_api_type = str(draft.get("api_type") or API_TYPE_OLLAMA)
        reasoning_choices = [
            (value, value) for value in supported_reasoning_efforts(draft_api_type)
        ]
        thinking_enabled = self._is_toggle_enabled(
            str(draft.get("thinking_mode") or "false")
        )
        current_effort = normalize_reasoning_effort_for_api(
            draft_api_type,
            draft.get("reasoning_effort") or "medium",
        )
        if current_effort not in {value for _, value in reasoning_choices}:
            current_effort = "medium"
        rows = [
            {
                "name": "Provider",
                "value": str(draft.get("provider") or ""),
                "keywords": "provider",
                "edit_type": "autocomplete",
                "suggestions": self._existing_model_providers(),
                "on_change": lambda v: self._set_add_model_field("provider", str(v)),
            },
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
                "name": "Extra modalities",
                "value": str(draft.get("extra_modalities") or "none"),
                "keywords": "extra_modalities modalities audio image video",
                "edit_type": "modalities",
                "options": [
                    ("audio", "audio"),
                    ("image", "image"),
                    ("video", "video"),
                ],
                "on_change": lambda v: self._set_add_model_field(
                    "extra_modalities", str(v)
                ),
            },
            {
                "name": "Limit",
                "keywords": "extra_modalities multimodal_limit upload size total",
                "edit_type": "input",
                "unit": "MB",
                "limit_selector": True,
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
        if draft_api_type == API_TYPE_GLM:
            rows = [row for row in rows if row.get("name") != "Base URL"]
        selected_modalities = parse_extra_modalities_input(
            str(draft.get("extra_modalities") or "none"), required=True
        )
        if selected_modalities:
            limit_options = [
                (modality.title(), modality)
                for modality in SUPPORTED_EXTRA_MODALITIES
                if modality in selected_modalities
            ]
            limit_options.append(("Total", "total"))
            available_limit_keys = {value for _label, value in limit_options}
            selected_limit = str(draft.get("selected_limit") or "total")
            if selected_limit not in available_limit_keys:
                selected_limit = limit_options[0][1]
                self._add_model_draft["selected_limit"] = selected_limit
            limit_row = next(row for row in rows if row.get("name") == "Limit")
            limit_row.update(
                {
                    "limit_key": selected_limit,
                    "options": limit_options,
                    "value": str(
                        draft.get("multimodal_limit")
                        if selected_limit == "total"
                        else draft.get(f"{selected_limit}_limit")
                    ),
                    "on_limit_select": lambda v: self._set_add_model_field(
                        "selected_limit", str(v)
                    ),
                    "on_change": lambda v, key=selected_limit: (
                        self._set_add_model_field(
                            "multimodal_limit" if key == "total" else f"{key}_limit",
                            str(v),
                        )
                    ),
                }
            )
        else:
            rows = [row for row in rows if row.get("name") != "Limit"]

        if thinking_enabled:
            rows.insert(
                next(
                    index
                    for index, row in enumerate(rows)
                    if row.get("name") == "Extra modalities"
                ),
                {
                    "name": "Reasoning effort",
                    "value": current_effort,
                    "keywords": "reasoning_effort",
                    "edit_type": "select",
                    "options": reasoning_choices,
                    "on_change": lambda v: self._set_add_model_field(
                        "reasoning_effort",
                        normalize_reasoning_effort_for_api(draft_api_type, str(v)),
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
        provider = str(draft.get("provider") or "").strip()
        if not provider:
            self.app_ref.add_status_message("[!]", "Provider cannot be empty.")
            return ""
        name = str(draft.get("name") or "").strip()
        if not name:
            self.app_ref.add_status_message("[!]", "Model name cannot be empty.")
            return ""
        extra_modalities = str(draft.get("extra_modalities") or "").strip()
        try:
            parse_extra_modalities_input(extra_modalities, required=True)
        except ValueError as error:
            self.app_ref.add_status_message("[!]", str(error))
            return ""
        selected_modalities = parse_extra_modalities_input(
            extra_modalities, required=True
        )
        try:
            extra_modalities_config = parse_extra_modalities_config(
                {
                    modality: draft.get(f"{modality}_limit")
                    for modality in selected_modalities
                }
            )
            multimodal_limit = (
                parse_multimodal_limit(draft.get("multimodal_limit"))
                if extra_modalities_config
                else None
            )
        except ValueError as error:
            self.app_ref.add_status_message("[!]", str(error))
            return ""
        max_tokens = str(draft.get("max_tokens") or "").strip()
        context_tokens = str(draft.get("context_window_tokens") or "").strip()
        temperature = str(draft.get("temperature") or "").strip()
        api_type = str(draft.get("api_type") or API_TYPE_OLLAMA)
        payload = {
            "provider": provider,
            "api_type": api_type,
            "model": str(draft.get("model") or ""),
            "api_key": str(draft.get("api_key") or ""),
            "temperature": temperature,
            "stream_mode": draft.get("stream_mode"),
            "thinking_mode": draft.get("thinking_mode"),
            "reasoning_effort": draft.get("reasoning_effort"),
            "extra_modalities": extra_modalities_config,
        }
        if api_type != API_TYPE_GLM:
            payload["base_url"] = str(draft.get("base_url") or "")
        if extra_modalities_config:
            payload["multimodal_limit"] = multimodal_limit
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

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
