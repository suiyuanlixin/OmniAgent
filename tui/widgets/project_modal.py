from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from tui.theme import render_css
from tui.widgets.chat_input import HalfRowSpacer


class ProjectModal(ModalScreen[dict | None]):
    DEFAULT_CSS = render_css(
        """
    ProjectModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #project-modal-wrap {
        width: 100%;
        min-width: 50;
        max-width: 86;
        height: auto;
        background: transparent;
    }

    #project-modal-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        padding: 0 2 1 2;
    }

    #project-modal-header,
    .project-modal-row,
    #project-modal-actions {
        width: 100%;
        height: auto;
    }

    #project-modal-header {
        height: 1;
        padding: 0;
    }

    #project-modal-title {
        width: 1fr;
        text-style: bold;
    }

    #project-modal-close {
        width: auto;
    }

    .project-modal-label {
        width: 100%;
        color: $TEXT_MUTED;
        margin-top: 1;
    }

    .project-modal-input {
        width: 100%;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
    }

    #project-modal-actions {
        align-horizontal: right;
        margin-top: 1;
    }

    #project-modal-save,
    #project-modal-cancel {
        width: auto;
        margin-left: 1;
        border: none;
        background: transparent;
    }
    """
    )

    BINDINGS = [("escape", "dismiss_result(None)", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="project-modal-wrap"):
            yield HalfRowSpacer(id="project-modal-top")
            with Vertical(id="project-modal-dialog"):
                with Horizontal(id="project-modal-header"):
                    yield Static("New Project", id="project-modal-title")
                    yield Static("esc", id="project-modal-close")
                yield Static("Project name", classes="project-modal-label")
                yield Input(placeholder="my-project", id="project-name", classes="project-modal-input")
                yield Static("Project path", classes="project-modal-label")
                yield Input(placeholder="D:\\Code\\MyProject", id="project-path", classes="project-modal-input")
                with Horizontal(id="project-modal-actions"):
                    yield Button("Close", id="project-modal-cancel")
                    yield Button("Save", id="project-modal-save")
            yield HalfRowSpacer(id="project-modal-bottom")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "project-modal-save":
            name = self.query_one("#project-name", Input).value.strip()
            path = self.query_one("#project-path", Input).value.strip()
            if name and path:
                self.dismiss({"name": name, "path": path})
                return
        self.dismiss(None)

    def action_dismiss_result(self, result: dict | None = None) -> None:
        self.dismiss(result)
