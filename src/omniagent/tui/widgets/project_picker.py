from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from rich.cells import cell_len
from textual.widgets import Button, Input, Static
from textual.widget import Widget
from textual.message import Message
from textual.reactive import reactive

from ..theme import render_css
from ..widgets.chat_input import HalfRowSpacer

OPTION_HORIZONTAL_PADDING = 1
_MORE_LABELS = ["New project", "Without project"]
_SEARCH_PLACEHOLDER = "Search projects"


class ProjectOptionButton(Button, can_focus=False):
    """Flat option button without Textual's built-in press effect."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.active_effect_duration = 0


class ProjectPicker(Widget):
    """Project selector dropdown (overlay style, matches model/thinking dropdowns)."""

    DEFAULT_CSS = render_css(
        """
    ProjectPicker {
        width: auto;
        height: 1;
    }

    #project-drop {
        width: auto;
        height: 1;
        min-width: 0;
        margin: 0;
    }

    #project-trigger {
        width: auto;
        height: 1;
        background: transparent;
        border: none;
        color: $TEXT_PRIMARY;
        margin: 0;
        padding: 0 0;
        text-align: left;
        content-align: left middle;
    }

    #project-options {
        display: none;
        width: auto;
        min-width: 0;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
        padding: 0;
        overlay: screen;
        align-horizontal: left;
    }
    #project-options.open {
        display: block;
    }

    #project-top-edge {
        color: $INFO_BAR_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #project-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #project-search-input {
        width: 100%;
        height: 1;
        background: transparent;
        border: none;
        color: $TEXT_PRIMARY;
        padding: 0 1;
    }

    #project-list {
        width: 100%;
        height: auto;
        padding: 0;
    }

    #project-options Button {
        width: 100%;
        height: 1;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        border: none;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
        padding: 0 0;
        margin: 0;
    }
    #add-project-btn,
    #no-project-btn {
        width: 100%;
        height: 1;
        padding: 0 1;
        margin: 0;
        background: transparent;
        color: $TEXT_PRIMARY;
        text-align: left;
        content-align: left middle;
    }
    #project-options Button:hover,
    #project-options Button:focus,
    #project-options Button.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: $TEXT_PRIMARY;
        background-tint: transparent;
        tint: transparent;
        color: $PAGE_BACKGROUND;
    }
    #add-project-btn:hover,
    #add-project-btn:focus,
    #add-project-btn.-active,
    #no-project-btn:hover,
    #no-project-btn:focus,
    #no-project-btn.-active {
        padding: 0 1;
        margin: 0;
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }

    #project-separator {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_MUTED;
        margin: 0;
        padding: 0 1;
    }
    #project-separator-line {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: $SURFACE_BACKGROUND;
        padding: 0;
        margin: 0;
    }
    """
    )

    current_project = reactive("")
    _all_projects: list[str] = []

    class ProjectSelected(Message):
        def __init__(self, project: str) -> None:
            super().__init__()
            self.project = project

    class NoProject(Message):
        pass

    class AddProject(Message):
        pass

    def on_mount(self) -> None:
        options = self.query_one("#project-options", Container)
        width = self._measure_dropdown_width()
        options.styles.width = width
        options.styles.min_width = width
        self._fit_trigger()
        self.set_projects(self._all_projects)

    def compose(self) -> ComposeResult:
        with Container(id="project-drop"):
            yield Button("Choose project", id="project-trigger")
            with Container(id="project-options"):
                yield HalfRowSpacer(id="project-top-edge")
                yield Input(placeholder=_SEARCH_PLACEHOLDER, id="project-search-input")
                yield Container(id="project-list")
                with Container(id="project-separator"):
                    yield Static(
                        "\u2500" * max(1, self._measure_dropdown_width() - 2),
                        id="project-separator-line",
                    )
                yield Static("New project", id="add-project-btn")
                yield Static("Without project", id="no-project-btn")
                yield HalfRowSpacer(id="project-bottom-edge")

    def _fit_trigger(self) -> None:
        drop = self.query_one("#project-drop", Container)
        trigger = self.query_one("#project-trigger", Button)
        label_width = cell_len(str(trigger.label)) + 2
        drop.styles.width = label_width
        trigger.styles.width = label_width

    def _measure_dropdown_width(self) -> int:
        labels = [*_MORE_LABELS, _SEARCH_PLACEHOLDER, *self._all_projects]
        return max(cell_len(label) for label in labels) + (
            OPTION_HORIZONTAL_PADDING * 2
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "project-trigger":
            self._toggle_dropdown()
            event.stop()
            return

        if btn_id and btn_id.startswith("project-item-"):
            proj_name = str(event.button.label)
            self.current_project = proj_name
            trigger = self.query_one("#project-trigger", Button)
            trigger.label = proj_name
            self._fit_trigger()
            self._close_dropdown()
            self.post_message(self.ProjectSelected(proj_name))
            event.stop()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "project-search-input":
            query = event.value.lower()
            project_items = self.query("#project-list Button")
            for item in project_items:
                label = str(item.label).lower()
                item.display = query in label if query else True

    def on_click(self, event) -> None:
        control = getattr(event, "control", None)
        control_id = getattr(control, "id", None)
        if control_id == "add-project-btn":
            self._close_dropdown()
            self.post_message(self.AddProject())
        elif control_id == "no-project-btn":
            self._close_dropdown()
            self.current_project = ""
            trigger = self.query_one("#project-trigger", Button)
            trigger.label = "Choose project"
            self._fit_trigger()
            self.post_message(self.NoProject())

    def _toggle_dropdown(self) -> None:
        options = self.query_one("#project-options", Container)
        if options.has_class("open"):
            options.remove_class("open")
        else:
            self._close_chat_input_dropdowns()
            options.add_class("open")

    def _close_chat_input_dropdowns(self) -> None:
        try:
            chat_input = self.app.query_one("#chat-input")
            chat_input._close_all_dropdowns()
        except Exception:
            pass

    def _close_dropdown(self) -> None:
        options = self.query_one("#project-options", Container)
        options.remove_class("open")

    def set_projects(self, project_names):
        self._all_projects = [
            str(name) for name in project_names or [] if str(name).strip()
        ]
        width = self._measure_dropdown_width()
        options = self.query_one("#project-options", Container)
        options.styles.width = width
        options.styles.min_width = width
        separator = self.query_one("#project-separator-line", Static)
        separator.update("\u2500" * max(1, width - 2))
        container = self.query_one("#project-list", Container)
        container.remove_children()
        self._project_serial = getattr(self, "_project_serial", 0) + 1
        serial = self._project_serial
        for index, project in enumerate(self._all_projects):
            container.mount(
                ProjectOptionButton(
                    project, id=f"project-item-{serial}-{index}", classes="project-item"
                )
            )

    def set_current_project(self, project_name):
        self.current_project = str(project_name or "")
        trigger = self.query_one("#project-trigger", Button)
        trigger.label = self.current_project or "Choose project"
        self._fit_trigger()
