from __future__ import annotations

from rich.markup import escape as escape_markup
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...i18n import display_width, t
from ..theme import render_css
from .chat_input import BottomHalfRowSpacer, HalfRowSpacer


class AlertModal(ModalScreen[None]):
    def __init__(self, title: str, detail: str = ""):
        super().__init__()
        self.title = str(title or "") or t("model_config.error_title")
        self.detail = str(detail or "").strip()

    DEFAULT_CSS = render_css(
        """
    AlertModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #alert-wrap {
        width: 100%;
        min-width: 48;
        max-width: 86;
        height: auto;
        background: transparent;
    }

    #alert-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0 1 0 2;
    }

    #alert-title {
        width: 100%;
        text-style: bold;
    }

    #alert-detail {
        width: 100%;
        color: $TEXT_MUTED;
        margin-top: 1;
    }

    #alert-actions {
        width: 100%;
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #alert-actions Button {
        width: auto;
        min-width: 0;
        margin-left: 1;
        border: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
    }
    #alert-actions Button:hover,
    #alert-actions Button:focus,
    #alert-actions Button.-active {
        background: transparent;
        background-tint: transparent;
        border: none;
        border-top: none;
        border-bottom: none;
        tint: transparent;
        text-style: bold;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_modal", "Close"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="alert-wrap"):
            yield BottomHalfRowSpacer(id="alert-top")
            with Vertical(id="alert-dialog"):
                yield Static(escape_markup(self.title), id="alert-title")
                if self.detail:
                    yield Static(escape_markup(self.detail), id="alert-detail")
                with Horizontal(id="alert-actions"):
                    yield Button(t("modal.ok"), id="alert-ok")
            yield HalfRowSpacer(id="alert-bottom")

    def on_mount(self) -> None:
        ok_lbl = t("modal.ok")
        LINE_PAD = 2
        ok_w = display_width(ok_lbl) + LINE_PAD
        self.query_one("#alert-ok", Button).styles.width = max(ok_w, 4)
        self.query_one("#alert-ok", Button).styles.min_width = max(ok_w, 4)
        self.query_one("#alert-ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
