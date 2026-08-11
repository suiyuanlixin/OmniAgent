from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...i18n import display_width, t
from ..theme import render_css
from ..widgets.chat_input import BottomHalfRowSpacer, HalfRowSpacer


class ConfirmModal(ModalScreen[bool]):
    def __init__(self, title: str, detail: str = ""):
        super().__init__()
        self.title = str(title or "") or t("common.confirm")
        self.detail = str(detail or "").strip()

    DEFAULT_CSS = render_css(
        """
    ConfirmModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #confirm-wrap {
        width: 100%;
        min-width: 48;
        max-width: 86;
        height: auto;
        background: transparent;
    }

    #confirm-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0 2 0 2;
    }

    #confirm-title {
        width: 100%;
        text-style: bold;
    }

    #confirm-detail {
        width: 100%;
        color: $TEXT_MUTED;
        margin-top: 1;
    }

    #confirm-actions {
        width: 100%;
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #confirm-actions Button {
        width: auto;
        min-width: 0;
        margin-left: 1;
        border: none;
        background: transparent;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(False)", "Cancel"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="confirm-wrap"):
            yield BottomHalfRowSpacer(id="confirm-top")
            with Vertical(id="confirm-dialog"):
                yield Static(self.title, id="confirm-title")
                if self.detail:
                    yield Static(self.detail, id="confirm-detail")
                with Horizontal(id="confirm-actions"):
                    yield Button(t("common.cancel"), id="confirm-cancel")
                    yield Button(t("modal.ok"), id="confirm-ok")
            yield HalfRowSpacer(id="confirm-bottom")

    def on_mount(self) -> None:
        # Textual's default Button min-width is 16, which ignores content width.
        # Override here after compose so we can compute exact label cell widths.
        cancel_lbl = t("common.cancel")
        ok_lbl = t("modal.ok")
        # line-pad adds 2 cells of horizontal padding inside the button label.
        LINE_PAD = 2
        cancel_w = display_width(cancel_lbl) + LINE_PAD
        ok_w = display_width(ok_lbl) + LINE_PAD
        self.query_one("#confirm-cancel", Button).styles.width = max(cancel_w, 4)
        self.query_one("#confirm-cancel", Button).styles.min_width = max(cancel_w, 4)
        self.query_one("#confirm-ok", Button).styles.width = max(ok_w, 4)
        self.query_one("#confirm-ok", Button).styles.min_width = max(ok_w, 4)
        self.query_one("#confirm-ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-ok")

    def action_dismiss_result(self, result: bool = False) -> None:
        self.dismiss(bool(result))

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
