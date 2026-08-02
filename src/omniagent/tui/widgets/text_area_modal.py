from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

from ...i18n import t
from ..theme import render_css
from ..widgets.chat_input import HalfRowSpacer


class TextAreaModal(ModalScreen[str | None]):
    def __init__(self, title: str, value: str = ""):
        super().__init__()
        self.title = str(title or "") or t("common.edit")
        self.value = str(value or "")

    DEFAULT_CSS = render_css(
        """
    TextAreaModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #text-area-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #text-area-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    .text-area-outer-gap {
        width: 100%;
        height: 1;
        background: transparent;
    }

    .text-area-outer-gap.hidden,
    .hidden {
        display: none;
    }

    #text-area-modal-wrap {
        width: 100%;
        height: auto;
        min-height: 10;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #text-area-modal-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #text-area-modal-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #text-area-modal-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #text-area-modal-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
    }

    #text-area-modal-title {
        width: 1fr;
        text-style: bold;
        padding: 0;
    }

    #text-area-modal-close {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #text-area-modal-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
    }

    .text-area-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    #text-area-modal-field {
        width: 100%;
        height: 16;
        min-height: 4;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
        scrollbar-size: 0 0;
    }

    #text-area-modal-footer {
        width: 100%;
        height: 1;
        align-horizontal: right;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
        margin-top: 1;
    }

    #text-area-modal-save,
    #text-area-modal-save:hover,
    #text-area-modal-save:focus,
    #text-area-modal-save.-active {
        width: auto;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Close"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="text-area-frame"):
            with Vertical(id="text-area-stack"):
                yield Static(
                    "", id="text-area-outer-gap-top", classes="text-area-outer-gap"
                )
                with Container(id="text-area-modal-wrap"):
                    yield HalfRowSpacer(id="text-area-modal-top-edge")
                    with Vertical(id="text-area-modal-dialog"):
                        with Horizontal(id="text-area-modal-header"):
                            yield Static(self.title, id="text-area-modal-title")
                            yield Static("esc", id="text-area-modal-close")
                        with Vertical(id="text-area-modal-body"):
                            yield Static(classes="text-area-gap")
                            yield TextArea(self.value, id="text-area-modal-field")
                        with Horizontal(id="text-area-modal-footer"):
                            yield Static(
                                t("common.save"), id="text-area-modal-save"
                            )
                    yield HalfRowSpacer(id="text-area-modal-bottom-edge")
                yield Static(
                    "", id="text-area-outer-gap-bottom", classes="text-area-outer-gap"
                )

    def on_mount(self) -> None:
        self.query_one("#text-area-modal-field", TextArea).focus()
        self.call_after_refresh(self._update_layout_constraints)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_text_area_changed(self, event) -> None:
        if (
            getattr(getattr(event, "text_area", None), "id", None)
            == "text-area-modal-field"
        ):
            self.call_after_refresh(self._update_layout_constraints)

    def on_click(self, event: events.Click) -> None:
        target = self._click_target_id(event)
        if target == "text-area-modal-close":
            self.dismiss(None)
            return
        if target == "text-area-modal-save":
            self._save()

    def action_dismiss_result(self, result: str | None = None) -> None:
        self.dismiss(result)

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()

    def action_save(self) -> None:
        self._save()

    def _save(self) -> None:
        value = self.query_one("#text-area-modal-field", TextArea).text
        self.dismiss(value)

    def _update_layout_constraints(self) -> None:
        stack = self.query_one("#text-area-stack", Vertical)
        wrap = self.query_one("#text-area-modal-wrap", Container)
        field = self.query_one("#text-area-modal-field", TextArea)
        wrap_width = min(100, max(56, self.size.width - 8))
        wrap.styles.width = wrap_width
        stack.styles.width = wrap_width
        content_lines = max(1, len(str(field.text or "").splitlines()))
        chrome_height = 6
        min_wrap_height = 10
        max_wrap_height = max(min_wrap_height, self.size.height - 2)
        desired_wrap_height = max(min_wrap_height, content_lines + chrome_height)
        wrap_height = min(desired_wrap_height, max_wrap_height)
        field_height = max(4, wrap_height - chrome_height)
        field.styles.height = field_height
        wrap.styles.height = wrap_height
        outer_gap = max(0, (self.size.height - wrap_height) // 2)
        top_gap = self.query_one("#text-area-outer-gap-top", Static)
        bottom_gap = self.query_one("#text-area-outer-gap-bottom", Static)
        top_gap.styles.height = outer_gap
        bottom_gap.styles.height = outer_gap

    @staticmethod
    def _click_target_id(event: events.Click) -> str | None:
        node = event.widget
        while node is not None:
            node_id = getattr(node, "id", None)
            if node_id:
                return str(node_id)
            node = getattr(node, "parent", None)
        return None


class PromptFileModal(ModalScreen[str | None]):
    def __init__(self, title: str, value: str = ""):
        super().__init__()
        self.title = str(title or "") or t("settings.page.system_prompt")
        self.value = str(value or "")

    DEFAULT_CSS = render_css(
        """
    PromptFileModal {
        align: center middle;
        background: $OVERLAY_BACKGROUND;
    }

    #prompt-file-frame {
        width: 100%;
        height: 100%;
        padding: 0 4;
        align: center middle;
        background: transparent;
    }

    #prompt-file-stack {
        width: auto;
        height: auto;
        max-height: 100%;
        background: transparent;
    }

    #prompt-file-wrap {
        width: 100%;
        height: auto;
        min-height: 10;
        padding: 0;
        margin: 0;
        background: transparent;
    }

    #prompt-file-dialog {
        width: 100%;
        height: auto;
        background: $SURFACE_BACKGROUND;
        border: none;
    }

    #prompt-file-top-edge {
        color: $PAGE_BACKGROUND;
        background: $SURFACE_BACKGROUND;
    }

    #prompt-file-bottom-edge {
        color: $SURFACE_BACKGROUND;
        background: $PAGE_BACKGROUND;
    }

    #prompt-file-header {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
    }

    #prompt-file-title {
        width: 1fr;
        text-style: bold;
        padding: 0;
    }

    #prompt-file-close {
        width: auto;
        height: 1;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }

    #prompt-file-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 2;
    }

    .prompt-file-gap {
        width: 100%;
        height: 1;
        background: $SURFACE_BACKGROUND;
    }

    #prompt-file-field {
        width: 100%;
        height: 16;
        min-height: 4;
        border: none;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
        scrollbar-size: 0 0;
    }

    #prompt-file-footer {
        width: 100%;
        height: 1;
        align-horizontal: right;
        background: $SURFACE_BACKGROUND;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 2;
        margin-top: 0;
    }

    #prompt-file-save,
    #prompt-file-save:hover,
    #prompt-file-save:focus,
    #prompt-file-save.-active {
        width: auto;
        background: transparent;
        color: $TEXT_PRIMARY;
        padding: 0 1 0 0;
        text-align: right;
        content-align: right middle;
    }
    """
    )

    BINDINGS = [
        ("escape", "dismiss_result(None)", "Close"),
        ("ctrl+c", "quit_attempt", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="prompt-file-frame"):
            with Vertical(id="prompt-file-stack"):
                with Container(id="prompt-file-wrap"):
                    yield HalfRowSpacer(id="prompt-file-top-edge")
                    with Vertical(id="prompt-file-dialog"):
                        with Horizontal(id="prompt-file-header"):
                            yield Static(self.title, id="prompt-file-title")
                            yield Static("esc", id="prompt-file-close")
                        yield Static(classes="prompt-file-gap")
                        with Vertical(id="prompt-file-body"):
                            yield TextArea(self.value, id="prompt-file-field")
                        yield Static(classes="prompt-file-gap")
                        with Horizontal(id="prompt-file-footer"):
                            yield Static(t("common.save"), id="prompt-file-save")
                    yield HalfRowSpacer(id="prompt-file-bottom-edge")

    def on_mount(self) -> None:
        self.query_one("#prompt-file-field", TextArea).focus()
        self.call_after_refresh(self._update_layout_constraints)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._update_layout_constraints)

    def on_text_area_changed(self, event) -> None:
        if (
            getattr(getattr(event, "text_area", None), "id", None)
            == "prompt-file-field"
        ):
            self.call_after_refresh(self._update_layout_constraints)

    def on_click(self, event: events.Click) -> None:
        target = self._click_target_id(event)
        if target == "prompt-file-close":
            self.dismiss(None)
            return
        if target == "prompt-file-save":
            self._save()

    def action_dismiss_result(self, result: str | None = None) -> None:
        self.dismiss(result)

    def action_save(self) -> None:
        self._save()

    def action_quit_app(self) -> None:
        if self.app is not None:
            self.app.exit()

    def action_quit_attempt(self) -> None:
        if self.app is not None and hasattr(self.app, "action_quit_attempt"):
            self.app.action_quit_attempt()

    def _save(self) -> None:
        value = self.query_one("#prompt-file-field", TextArea).text
        self.dismiss(value)

    def _update_layout_constraints(self) -> None:
        stack = self.query_one("#prompt-file-stack", Vertical)
        wrap = self.query_one("#prompt-file-wrap", Container)
        field = self.query_one("#prompt-file-field", TextArea)
        wrap_width = min(100, max(56, self.size.width - 8))
        wrap.styles.width = wrap_width
        stack.styles.width = wrap_width
        content_lines = max(1, len(str(field.text or "").splitlines()))
        chrome_height = 6
        min_wrap_height = 10
        max_wrap_height = max(min_wrap_height, self.size.height)
        desired_wrap_height = max(min_wrap_height, content_lines + chrome_height)
        wrap_height = min(desired_wrap_height, max_wrap_height)
        field_height = max(4, wrap_height - chrome_height)
        field.styles.height = field_height
        wrap.styles.height = wrap_height

    @staticmethod
    def _click_target_id(event: events.Click) -> str | None:
        node = event.widget
        while node is not None:
            node_id = getattr(node, "id", None)
            if node_id:
                return str(node_id)
            node = getattr(node, "parent", None)
        return None
