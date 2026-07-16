from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Container
from textual.widgets import Button, Input, Label
from textual.screen import ModalScreen

from tui.theme import render_css


class FileInputModal(ModalScreen[str | None]):
    """Modal to input a file path."""

    DEFAULT_CSS = render_css(
        """
    FileInputModal {
        align: center middle;
    }

    FileInputModal > Container {
        width: 50;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
        padding: 1 2;
    }

    FileInputModal #file-modal-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    FileInputModal #file-path-input {
        width: 100%;
        margin-bottom: 1;
    }

    FileInputModal #file-modal-buttons {
        width: 100%;
        align-horizontal: right;
    }

    FileInputModal #file-submit-btn {
        width: 10;
        margin-right: 1;
        background: transparent;
        color: $FULL_ACCESS;
        border: none;
    }

    FileInputModal #file-cancel-btn {
        width: 8;
        border: none;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Cancel"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Enter file path", id="file-modal-title")
            yield Input(placeholder="/path/to/file.py", id="file-path-input")
            with Horizontal(id="file-modal-buttons"):
                yield Button("Submit", id="file-submit-btn")
                yield Button("Cancel", id="file-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-submit-btn":
            path_input = self.query_one("#file-path-input", Input)
            path = path_input.value.strip()
            if path:
                self.dismiss(path)
            else:
                self.dismiss(None)
        elif event.button.id == "file-cancel-btn":
            self.dismiss(None)

    def action_dismiss_result(self, result: str | None = None) -> None:
        self.dismiss(result)

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
