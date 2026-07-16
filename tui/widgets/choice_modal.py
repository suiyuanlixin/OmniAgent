from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer


class ChoiceModal(ModalScreen[int]):
    def __init__(self, question: str, options):
        super().__init__()
        self.question = str(question or "Choose one")
        self.options = [str(option) for option in options or []]

    DEFAULT_CSS = render_css(
        """
    ChoiceModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #choice-wrap {
        width: 100%;
        min-width: 48;
        max-width: 86;
        height: auto;
        background: transparent;
    }

    #choice-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0 2 1 2;
    }

    #choice-title {
        width: 100%;
        text-style: bold;
    }

    .choice-button {
        width: 100%;
        border: none;
        background: transparent;
        text-align: left;
        margin-top: 1;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(0)", "Cancel"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="choice-wrap"):
            yield HalfRowSpacer(id="choice-top")
            with Vertical(id="choice-dialog"):
                yield Static(self.question, id="choice-title")
                for index, option in enumerate(self.options, 1):
                    yield Button(
                        f"{index}. {option}",
                        id=f"choice-{index}",
                        classes="choice-button",
                    )
            yield HalfRowSpacer(id="choice-bottom")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            index = int(str(event.button.id).split("-", 1)[1])
        except (IndexError, ValueError):
            index = 0
        self.dismiss(index)

    def action_dismiss_result(self, result: int = 0) -> None:
        self.dismiss(int(result or 0))

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()
