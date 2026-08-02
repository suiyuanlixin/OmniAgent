from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static
from textual import events
from textual.message import Message

from ...i18n import display_width, t
from ..theme import render_css


class SidebarActionButton(Button, can_focus=False):
    """Flat sidebar button without Textual's focus/press visuals."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.active_effect_duration = 0


class SidebarEntryHeader(Horizontal):
    class HoverChanged(Message):
        def __init__(self, header: "SidebarEntryHeader", hovered: bool) -> None:
            super().__init__()
            self.header = header
            self.hovered = hovered

    def on_enter(self, event: events.Enter) -> None:
        self.post_message(self.HoverChanged(self, True))

    def on_leave(self, event: events.Leave) -> None:
        self.post_message(self.HoverChanged(self, False))


class Sidebar(Vertical):
    """Left sidebar with flat project/chat lists and action buttons."""

    class SessionSelected(Message):
        def __init__(self, session_path: str) -> None:
            super().__init__()
            self.session_path = session_path

    class SessionActionRequested(Message):
        def __init__(self, session_path: str, action: str, value: str = "") -> None:
            super().__init__()
            self.session_path = session_path
            self.action = action
            self.value = value

    class ProjectActionRequested(Message):
        def __init__(
            self,
            project_slug: str,
            project_name: str,
            action: str,
            value: str = "",
        ) -> None:
            super().__init__()
            self.project_slug = project_slug
            self.project_name = project_name
            self.action = action
            self.value = value

    class SettingsRequested(Message):
        pass

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._render_serial = 0
        self._open_groups: set[str] = set()
        self._pinned_projects: list[dict] = []
        self._project_sessions: list[dict] = []
        self._pinned_sessions: list[dict] = []
        self._orphan_sessions: list[dict] = []
        self._editing_target: dict[str, str] | None = None
        self._hovered_header = None

    DEFAULT_CSS = render_css(
        """
    Sidebar {
        width: 100%;
        height: 1fr;
        background: $SURFACE_BACKGROUND;
        padding: 0;
        display: none;
    }
    Sidebar.sidebar-visible {
        display: block;
    }
    Sidebar.sidebar-hidden {
        display: none;
    }

    Sidebar > #sidebar-content {
        width: 100%;
        height: 1fr;
        background: $SURFACE_BACKGROUND;
        padding: 0;
        overflow-y: auto;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
        scrollbar-color: transparent;
        scrollbar-background: transparent;
        scrollbar-color-active: transparent;
        scrollbar-color-hover: transparent;
        scrollbar-background-active: transparent;
        scrollbar-background-hover: transparent;
    }

    Sidebar Button.sidebar-action {
        width: 100%;
        min-width: 1;
        height: 1;
        margin: 0;
        border: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
        padding: 0;
        text-align: left;
        content-align: left middle;
    }
    Sidebar Button.sidebar-action:hover,
    Sidebar Button.sidebar-action:focus,
    Sidebar Button.sidebar-action.-active {
        border: none;
        border-top: none;
        border-bottom: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }

    #side-new-chat {
        width: 100%;
        margin: 1 1 1 1;
        background: $SURFACE_BACKGROUND;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }
    #side-new-chat:hover,
    #side-new-chat:focus,
    #side-new-chat.-active,
    #side-new-chat:focus-within {
        background: $SURFACE_BACKGROUND;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }

    .sidebar-section-title {
        width: 100%;
        height: 1;
        color: $TEXT_MUTED;
        background: transparent;
        padding: 0 0 0 2;
        margin: 0;
        content-align: left middle;
    }
    .sidebar-section-title.hidden {
        display: none;
    }
    .sidebar-section-title:hover {
        color: $TEXT_PRIMARY;
    }
    .sidebar-section-title {
        margin-top: 1;
    }
    .sidebar-section-title.no-top-gap {
        margin-top: 0;
    }
    #chats-list {
        padding-bottom: 1;
    }

    .sidebar-list {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .sidebar-list.hidden {
        display: none;
    }

    .sidebar-item {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 0 0 1;
        margin: 0 0 0 1;
        content-align: left middle;
    }
    .sidebar-item:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    .sidebar-chat-item {
        padding: 0 0 0 3;
    }
    .sidebar-empty-item {
        color: $TEXT_MUTED;
    }
    .sidebar-empty-item:hover {
        background: transparent;
        color: $TEXT_MUTED;
    }

    .sidebar-entry {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .sidebar-entry-header {
        width: 100%;
        height: 1;
        padding: 0;
        margin: 0;
    }
    .sidebar-entry-title {
        width: 1fr;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 0 0 1;
        margin: 0 0 0 1;
        content-align: left middle;
    }
    .sidebar-entry-title.sidebar-chat-item {
        padding: 0 0 0 3;
    }
    #sidebar-edit-input {
        border: none;
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
        width: auto;
        height: 1;
        margin: 0 0 0 1;
        padding: 0 0 0 1;
    }
    #sidebar-edit-input.sidebar-chat-item {
        padding: 0 0 0 3;
    }
    #sidebar-edit-input:focus {
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }
    .sidebar-entry-menu-trigger {
        width: 4;
        min-width: 4;
        height: 1;
        color: transparent;
        background: transparent;
        padding: 0 1 0 0;
        margin: 0;
        content-align: center middle;
    }
    .sidebar-entry-menu-trigger.editing {
        display: none;
    }
    .sidebar-entry-title.row-hover,
    .sidebar-entry-title.menu-open,
    .sidebar-entry-menu-trigger.row-hover,
    .sidebar-entry-menu-trigger.menu-open {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    #sidebar-edit-input.row-hover {
        background: transparent;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
    }
    .sidebar-action-menu {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .sidebar-action-menu.hidden {
        display: none;
    }
    .sidebar-action-menu-item {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 0 0 3;
        margin: 0 0 0 1;
        content-align: left middle;
    }
    .sidebar-action-menu-item:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    .sidebar-action-menu-item.sidebar-chat-item {
        padding: 0 0 0 5;
    }

    #side-settings {
        dock: bottom;
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
        border: none;
        background: $SURFACE_BACKGROUND;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
        text-style: bold;
    }
    #side-settings:hover,
    #side-settings:focus,
    #side-settings.-active {
        border: none;
        background: $SURFACE_BACKGROUND;
        background-tint: transparent;
        tint: transparent;
        color: $TEXT_PRIMARY;
        text-style: bold;
    }
    """
    )

    def compose(self) -> ComposeResult:
        new_chat = SidebarActionButton(
            t("sidebar.new_chat"), id="side-new-chat", classes="sidebar-action"
        )
        yield new_chat
        with Vertical(id="sidebar-content"):
            yield Static(
                t("sidebar.pinned"), id="pinned-title", classes="sidebar-section-title"
            )
            yield Vertical(id="pinned-list", classes="sidebar-list")
            yield Static(
                t("sidebar.projects"),
                id="projects-title",
                classes="sidebar-section-title",
            )
            yield Vertical(id="projects-list", classes="sidebar-list")
            yield Static(
                t("sidebar.chats"), id="chats-title", classes="sidebar-section-title"
            )
            yield Vertical(id="chats-list", classes="sidebar-list")

        settings = SidebarActionButton(
            f"= {t('sidebar.settings')}", id="side-settings", classes="sidebar-action"
        )
        yield settings

    def relabel_for_language(self) -> None:
        """Re-resolve the static labels compose() baked in at mount time."""
        if not self.is_mounted:
            return
        labels = {
            "#side-new-chat": t("sidebar.new_chat"),
            "#pinned-title": t("sidebar.pinned"),
            "#projects-title": t("sidebar.projects"),
            "#chats-title": t("sidebar.chats"),
        }
        for selector, label in labels.items():
            try:
                widget = self.query_one(selector)
            except Exception:
                continue
            if isinstance(widget, SidebarActionButton):
                widget.label = label
            else:
                widget.update(label)
        try:
            self.query_one("#side-settings", SidebarActionButton).label = (
                f"= {t('sidebar.settings')}"
            )
        except Exception:
            pass

    def on_click(self, event: events.Click) -> None:
        if not event.control or not event.control.id:
            self._close_action_menus()
            return

        control = event.control
        control_id = control.id

        if control_id == "projects-title":
            self._close_action_menus()
            lst = self.query_one("#projects-list", Vertical)
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
            else:
                lst.add_class("hidden")
        elif control_id == "pinned-title":
            self._close_action_menus()
            lst = self.query_one("#pinned-list", Vertical)
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
            else:
                lst.add_class("hidden")
        elif control_id == "chats-title":
            self._close_action_menus()
            lst = self.query_one("#chats-list", Vertical)
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
            else:
                lst.add_class("hidden")
        elif control_id == "side-settings":
            self._close_action_menus()
            self.post_message(self.SettingsRequested())
        elif control_id.startswith("session-label-"):
            self._close_action_menus()
            self.post_message(
                self.SessionSelected(str(getattr(control, "data_path", "")))
            )
        elif control_id.startswith("session-menu-trigger-"):
            menu_id = str(getattr(control, "data_menu_id", ""))
            if menu_id:
                self._toggle_action_menu(menu_id)
        elif control_id.startswith("session-action-"):
            action = str(getattr(control, "data_action", ""))
            if action == "rename":
                self._begin_inline_edit(
                    "session", str(getattr(control, "data_path", ""))
                )
                return
            self._close_action_menus()
            self.post_message(
                self.SessionActionRequested(
                    str(getattr(control, "data_path", "")),
                    action,
                )
            )
        elif control_id.startswith("project-label-"):
            self._close_action_menus()
            group_id = str(getattr(control, "data_group_id", ""))
            group_key = str(getattr(control, "data_group_key", ""))
            if not group_id or not group_key:
                return
            lst = self.query_one(f"#{group_id}", Vertical)
            self._set_project_group_open(group_id, group_key, lst.has_class("hidden"))
        elif control_id.startswith("project-menu-trigger-"):
            menu_id = str(getattr(control, "data_menu_id", ""))
            group_id = str(getattr(control, "data_group_id", ""))
            group_key = str(getattr(control, "data_group_key", ""))
            if group_id and group_key:
                self._set_project_group_open(group_id, group_key, False)
            if menu_id:
                self._toggle_action_menu(menu_id)
        elif control_id.startswith("project-action-"):
            action = str(getattr(control, "data_action", ""))
            if action == "rename":
                self._begin_inline_edit(
                    "project", str(getattr(control, "data_slug", ""))
                )
                return
            self._close_action_menus()
            self.post_message(
                self.ProjectActionRequested(
                    str(getattr(control, "data_slug", "")),
                    str(getattr(control, "data_name", "")),
                    action,
                )
            )
        else:
            self._close_action_menus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "sidebar-edit-input":
            return
        item_kind = str(getattr(event.input, "data_item_kind", "")).strip()
        original_value = str(getattr(event.input, "data_original_value", "")).strip()
        new_value = str(event.value or "").strip()
        if not new_value:
            event.stop()
            return
        if new_value == original_value:
            self._clear_inline_edit()
            event.stop()
            return
        event.input.data_submitted = True
        if item_kind == "session":
            self.post_message(
                self.SessionActionRequested(
                    str(getattr(event.input, "data_path", "")),
                    "rename",
                    new_value,
                )
            )
        elif item_kind == "project":
            self.post_message(
                self.ProjectActionRequested(
                    str(getattr(event.input, "data_slug", "")),
                    str(getattr(event.input, "data_name", "")),
                    "rename",
                    new_value,
                )
            )
        event.stop()

    def on_blur(self, event: events.Blur) -> None:
        if getattr(event.control, "id", "") == "sidebar-edit-input":
            self._clear_inline_edit()

    def on_key(self, event: events.Key) -> None:
        focused = getattr(self.app, "focused", None)
        if getattr(focused, "id", "") != "sidebar-edit-input":
            return
        if event.key == "escape":
            focused.data_cancelled = True
            self._clear_inline_edit()
            event.stop()

    def on_sidebar_entry_header_hover_changed(
        self, event: SidebarEntryHeader.HoverChanged
    ) -> None:
        if event.hovered:
            self._set_hovered_header(event.header)
        elif event.header is self._hovered_header:
            self._set_hovered_header(None)
        event.stop()

    def _close_action_menus(self) -> None:
        for menu in self.query(".sidebar-action-menu"):
            menu.add_class("hidden")
        for trigger in self.query(".sidebar-entry-menu-trigger"):
            trigger.remove_class("menu-open")
        for title in self.query(".sidebar-entry-title"):
            title.remove_class("menu-open")

    def _toggle_action_menu(self, menu_id: str) -> None:
        if not menu_id:
            return
        target = None
        target_trigger = None
        target_title = None
        for menu in self.query(".sidebar-action-menu"):
            if menu.id == menu_id:
                target = menu
                target_trigger = menu.parent.query_one(
                    ".sidebar-entry-menu-trigger", Static
                )
                try:
                    target_title = menu.parent.query_one(".sidebar-entry-title", Static)
                except Exception:
                    target_title = None
                continue
            menu.add_class("hidden")
            try:
                menu.parent.query_one(
                    ".sidebar-entry-menu-trigger", Static
                ).remove_class("menu-open")
            except Exception:
                pass
            try:
                menu.parent.query_one(".sidebar-entry-title", Static).remove_class(
                    "menu-open"
                )
            except Exception:
                pass
        if target is None:
            return
        if target.has_class("hidden"):
            target.remove_class("hidden")
            if target_trigger is not None:
                target_trigger.add_class("menu-open")
            if target_title is not None:
                target_title.add_class("menu-open")
        else:
            target.add_class("hidden")
            if target_trigger is not None:
                target_trigger.remove_class("menu-open")
            if target_title is not None:
                target_title.remove_class("menu-open")

    def _is_editing(self, item_kind: str, item_key: str) -> bool:
        return self._editing_target == {"kind": item_kind, "key": item_key}

    def _set_header_hover(self, header, hovered: bool) -> None:
        if header is None:
            return
        for selector in (".sidebar-entry-title",):
            try:
                widget = header.query_one(selector)
            except Exception:
                continue
            widget.set_class(hovered, "row-hover")
        try:
            widget = header.query_one("#sidebar-edit-input", Input)
            widget.set_class(hovered, "row-hover")
        except Exception:
            pass
        try:
            trigger = header.query_one(".sidebar-entry-menu-trigger", Static)
        except Exception:
            return
        trigger.set_class(hovered, "row-hover")

    def _set_project_group_open(
        self, group_id: str, group_key: str, open_state: bool
    ) -> None:
        if not group_id or not group_key:
            return
        lst = self.query_one(f"#{group_id}", Vertical)
        if open_state:
            lst.remove_class("hidden")
            self._open_groups.add(group_key)
        else:
            lst.add_class("hidden")
            self._open_groups.discard(group_key)

    def _set_hovered_header(self, header) -> None:
        if header is self._hovered_header:
            return
        self._set_header_hover(self._hovered_header, False)
        self._hovered_header = header
        self._set_header_hover(self._hovered_header, True)

    def _begin_inline_edit(self, item_kind: str, item_key: str) -> None:
        if not item_key:
            return
        self._close_action_menus()
        self._editing_target = {"kind": item_kind, "key": item_key}
        self._render_sessions()
        try:
            editor = self.query_one("#sidebar-edit-input", Input)
        except Exception:
            return
        editor.focus()
        editor.cursor_position = len(editor.value)

    def _clear_inline_edit(self) -> None:
        if self._editing_target is None:
            return
        self._editing_target = None
        self._render_sessions()

    def _session_header(
        self,
        title: str,
        session_path: str,
        item_id: str,
        chat_item: bool = False,
    ) -> Horizontal:
        title_classes = "sidebar-entry-title"
        input_classes = ""
        if chat_item:
            title_classes += " sidebar-chat-item"
            input_classes = "sidebar-chat-item"

        if self._is_editing("session", session_path):
            title_widget = Input(
                value=title,
                id="sidebar-edit-input",
                classes=input_classes,
                placeholder=t("sidebar.chat_title_placeholder"),
            )
            title_widget.styles.width = max(display_width(title) + 3, 8)
            title_widget.data_item_kind = "session"
            title_widget.data_original_value = title
            title_widget.data_path = session_path
        else:
            title_widget = Static(
                title,
                id=f"session-label-{item_id}",
                classes=title_classes,
            )
            title_widget.data_path = session_path

        trigger_classes = "sidebar-entry-menu-trigger"
        if self._is_editing("session", session_path):
            trigger_classes += " editing"

        menu_trigger = Static(
            "⋯",
            id=f"session-menu-trigger-{item_id}",
            classes=trigger_classes,
        )
        menu_trigger.data_menu_id = f"session-menu-{item_id}"

        return SidebarEntryHeader(
            title_widget,
            menu_trigger,
            classes="sidebar-entry-header",
        )

    def _mount_session_item(
        self,
        container: Vertical,
        session: dict,
        item_id: str,
        chat_item: bool = False,
    ) -> None:
        title = str(session.get("title") or t("sidebar.new_chat"))
        session_path = str(session.get("session_path") or "")
        is_pinned = bool(session.get("_pinned"))
        action_name = "unpin" if is_pinned else "pin"
        action_label = (
            t("sidebar.unpin_chat") if is_pinned else t("sidebar.pin_chat")
        )
        menu_item_classes = "sidebar-action-menu-item"
        if chat_item:
            menu_item_classes += " sidebar-chat-item"

        menu_id = f"session-menu-{item_id}"

        pin_item = Static(
            action_label,
            id=f"session-action-{action_name}-{item_id}",
            classes=menu_item_classes,
        )
        pin_item.data_action = action_name
        pin_item.data_path = session_path

        rename_item = Static(
            t("sidebar.rename_chat"),
            id=f"session-action-rename-{item_id}",
            classes=menu_item_classes,
        )
        rename_item.data_action = "rename"
        rename_item.data_path = session_path

        delete_item = Static(
            t("sidebar.archive_chat"),
            id=f"session-action-archive-{item_id}",
            classes=menu_item_classes,
        )
        delete_item.data_action = "archive"
        delete_item.data_path = session_path

        entry = Vertical(
            self._session_header(title, session_path, item_id, chat_item=chat_item),
            Vertical(
                pin_item,
                rename_item,
                delete_item,
                id=menu_id,
                classes="sidebar-action-menu hidden",
            ),
            classes="sidebar-entry",
        )
        container.mount(entry)

    def _mount_project_item(
        self,
        container: Vertical,
        project: dict,
        item_id: str,
    ) -> None:
        name = str(project.get("name") or "")
        slug = str(project.get("slug") or "")
        sessions = list(project.get("sessions") or [])
        is_pinned = bool(project.get("_pinned"))
        action_name = "unpin" if is_pinned else "pin"
        action_label = (
            t("sidebar.unpin_project") if is_pinned else t("sidebar.pin_project")
        )
        menu_id = f"project-menu-{item_id}"
        group_id = f"project-chats-{item_id}"
        group_key = f"project:{slug}"
        input_classes = ""

        if self._is_editing("project", slug):
            title_widget = Input(
                value=name,
                id="sidebar-edit-input",
                classes=input_classes,
                placeholder=t("sidebar.project_name_placeholder"),
            )
            title_widget.styles.width = max(display_width(name) + 3, 8)
            title_widget.data_item_kind = "project"
            title_widget.data_original_value = name
            title_widget.data_slug = slug
            title_widget.data_name = name
        else:
            title_widget = Static(
                name,
                id=f"project-label-{item_id}",
                classes="sidebar-entry-title",
            )
            title_widget.data_group_id = group_id
            title_widget.data_group_key = group_key

        trigger_classes = "sidebar-entry-menu-trigger"
        if self._is_editing("project", slug):
            trigger_classes += " editing"

        menu_trigger = Static(
            "⋯",
            id=f"project-menu-trigger-{item_id}",
            classes=trigger_classes,
        )
        menu_trigger.data_menu_id = menu_id
        menu_trigger.data_group_id = group_id
        menu_trigger.data_group_key = group_key

        pin_item = Static(
            action_label,
            id=f"project-action-{action_name}-{item_id}",
            classes="sidebar-action-menu-item",
        )
        pin_item.data_action = action_name
        pin_item.data_slug = slug
        pin_item.data_name = name

        rename_item = Static(
            t("sidebar.rename_project"),
            id=f"project-action-rename-{item_id}",
            classes="sidebar-action-menu-item",
        )
        rename_item.data_action = "rename"
        rename_item.data_slug = slug
        rename_item.data_name = name

        archive_item = Static(
            t("sidebar.archive_chats"),
            id=f"project-action-archive-{item_id}",
            classes="sidebar-action-menu-item",
        )
        archive_item.data_action = "archive"
        archive_item.data_slug = slug
        archive_item.data_name = name

        remove_item = Static(
            t("common.remove"),
            id=f"project-action-remove-{item_id}",
            classes="sidebar-action-menu-item",
        )
        remove_item.data_action = "remove"
        remove_item.data_slug = slug
        remove_item.data_name = name

        entry = Vertical(
            SidebarEntryHeader(
                title_widget,
                menu_trigger,
                classes="sidebar-entry-header",
            ),
            Vertical(
                pin_item,
                rename_item,
                archive_item,
                remove_item,
                id=menu_id,
                classes="sidebar-action-menu hidden",
            ),
            classes="sidebar-entry",
        )
        container.mount(entry)

        group_classes = "sidebar-list project-chat-list"
        if group_key not in self._open_groups:
            group_classes += " hidden"
        session_group = Vertical(id=group_id, classes=group_classes)
        container.mount(session_group)
        if not sessions:
            no_chats = Static(
                t("sidebar.no_chats"),
                id=f"project-empty-{item_id}",
                classes="sidebar-item sidebar-chat-item sidebar-empty-item",
            )
            session_group.mount(no_chats)
            return
        for session_index, session in enumerate(sessions):
            self._mount_session_item(
                session_group,
                session,
                item_id=f"{item_id}-{session_index}",
                chat_item=True,
            )

    def _render_sessions(self) -> None:
        self._render_serial += 1
        self._hovered_header = None
        serial = self._render_serial
        pinned_title = self.query_one("#pinned-title", Static)
        pinned_list = self.query_one("#pinned-list", Vertical)
        projects_title = self.query_one("#projects-title", Static)
        projects_list = self.query_one("#projects-list", Vertical)
        chats_title = self.query_one("#chats-title", Static)
        chats_list = self.query_one("#chats-list", Vertical)
        pinned_title.add_class("hidden")
        pinned_list.add_class("hidden")
        pinned_list.remove_children()
        projects_title.add_class("hidden")
        projects_list.add_class("hidden")
        projects_list.remove_children()
        chats_title.add_class("hidden")
        chats_list.add_class("hidden")
        chats_list.remove_children()

        for index, project in enumerate(self._pinned_projects):
            pinned_title.remove_class("hidden")
            pinned_list.remove_class("hidden")
            self._mount_project_item(
                pinned_list,
                project,
                item_id=f"pinned-project-{serial}-{index}",
            )

        for index, session in enumerate(self._pinned_sessions):
            pinned_title.remove_class("hidden")
            pinned_list.remove_class("hidden")
            self._mount_session_item(
                pinned_list,
                session,
                item_id=f"pinned-chat-{serial}-{index}",
            )

        for index, project in enumerate(self._project_sessions):
            projects_title.remove_class("hidden")
            projects_list.remove_class("hidden")
            self._mount_project_item(
                projects_list,
                project,
                item_id=f"project-{serial}-{index}",
            )

        for index, session in enumerate(self._orphan_sessions):
            chats_title.remove_class("hidden")
            chats_list.remove_class("hidden")
            self._mount_session_item(
                chats_list,
                session,
                item_id=f"orphan-{serial}-{index}",
            )

        self._fix_section_gaps()

    def set_sessions(
        self,
        project_sessions,
        pinned_projects,
        pinned_sessions,
        orphan_sessions,
    ):
        self._editing_target = None
        self._pinned_projects = list(pinned_projects or [])
        self._project_sessions = list(project_sessions or [])
        self._pinned_sessions = list(pinned_sessions or [])
        self._orphan_sessions = list(orphan_sessions or [])
        self._render_sessions()

    def _fix_section_gaps(self) -> None:
        titles = list(self.query(".sidebar-section-title"))
        first_visible = None
        for title in titles:
            title.remove_class("no-top-gap")
            if first_visible is None and not title.has_class("hidden"):
                first_visible = title
        if first_visible is not None:
            first_visible.add_class("no-top-gap")
