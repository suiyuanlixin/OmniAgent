from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Input, Static
from textual.screen import ModalScreen

from tui.theme import render_css


from tui.widgets.chat_input import HalfRowSpacer


class SettingsModal(ModalScreen[None]):
    """Settings modal window centered on screen."""

    def __init__(self, settings_rows=None):
        super().__init__()
        self.settings_rows = list(settings_rows or [])

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

    .settings-name {
        width: 1fr;
        text-align: left;
        color: $TEXT_PRIMARY;
    }

    .settings-value {
        width: auto;
        color: $TEXT_MUTED;
        text-align: right;
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
        if event.control.id == "settings-close-btn":
            self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "settings-search":
            self._render_settings(event.value)

    def action_dismiss_result(self, result: None = None) -> None:
        self.dismiss(result)

    def _render_settings(self, query):
        query = str(query or "").strip().lower()
        settings_list = self.query_one("#settings-list", Vertical)
        settings_list.remove_children()
        visible_rows = []
        for row in self.settings_rows:
            name = str(row.get("name") or "")
            value = str(row.get("value") or "")
            keywords = " ".join([name, value, str(row.get("keywords") or "")]).lower()
            if query and query not in keywords:
                continue
            visible_rows.append((name, value))

        if not visible_rows:
            settings_list.mount(Static("No matching settings", classes="settings-name"))
            return

        for name, value in visible_rows:
            row = Horizontal(
                Static(name, classes="settings-name"),
                Static(value, classes="settings-value"),
                classes="settings-row",
            )
            settings_list.mount(row)
