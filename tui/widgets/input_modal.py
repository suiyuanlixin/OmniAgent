from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer


class InputModal(ModalScreen[str | None]):
    def __init__(self, title: str, multiline: bool = False):
        super().__init__()
        self.title = str(title or "Input")
        self.multiline = bool(multiline)

    DEFAULT_CSS = render_css(
        """
    InputModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #input-modal-wrap {
        width: 100%;
        min-width: 48;
        max-width: 86;
        height: auto;
        background: transparent;
    }

    #input-modal-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0 2 1 2;
    }

    #input-modal-title {
        width: 100%;
        text-style: bold;
    }

    #input-modal-field {
        width: 100%;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        margin-top: 1;
    }

    #input-modal-actions {
        width: 100%;
        align-horizontal: right;
        margin-top: 1;
    }

    #input-modal-actions Button {
        width: auto;
        margin-left: 1;
        border: none;
        background: transparent;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result('')", "Cancel"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="input-modal-wrap"):
            yield HalfRowSpacer(id="input-modal-top")
            with Vertical(id="input-modal-dialog"):
                yield Static(self.title, id="input-modal-title")
                yield Input(id="input-modal-field")
                with Horizontal(id="input-modal-actions"):
                    yield Button("Cancel", id="input-modal-cancel")
                    yield Button("OK", id="input-modal-ok")
            yield HalfRowSpacer(id="input-modal-bottom")

    def on_mount(self) -> None:
        self.query_one("#input-modal-field", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "input-modal-ok":
            value = self.query_one("#input-modal-field", Input).value
            self.dismiss(value)
            return
        self.dismiss("")

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-modal-field":
            self.dismiss(event.value)

    def action_dismiss_result(self, result: str | None = None) -> None:
        self.dismiss(result if result is not None else "")
