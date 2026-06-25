from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static
from textual import events
from textual.message import Message

from tui.theme import render_css


class SidebarActionButton(Button, can_focus=False):
    """Flat sidebar button without Textual's focus/press visuals."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.active_effect_duration = 0


class Sidebar(Vertical):
    """Left sidebar with flat project/chat lists and action buttons."""

    class SessionSelected(Message):
        def __init__(self, session_path: str) -> None:
            super().__init__()
            self.session_path = session_path

    class SessionActionRequested(Message):
        def __init__(self, session_path: str, action: str) -> None:
            super().__init__()
            self.session_path = session_path
            self.action = action

    class SettingsRequested(Message):
        pass

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._render_serial = 0
        self._expanded_groups: set[str] = set()

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

    .sidebar-session-entry {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .sidebar-session-label {
        width: 1fr;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 0 0 1;
        margin: 0 0 0 1;
        content-align: left middle;
    }
    .sidebar-session-label.sidebar-chat-item {
        padding: 0 0 0 3;
    }
    .sidebar-session-label:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    .sidebar-session-menu {
        width: 100%;
        height: auto;
        padding: 0;
        margin: 0;
    }
    .sidebar-session-menu.hidden {
        display: none;
    }
    .sidebar-session-menu-item {
        width: 100%;
        height: 1;
        color: $TEXT_PRIMARY;
        background: transparent;
        padding: 0 0 0 3;
        margin: 0 0 0 1;
        content-align: left middle;
    }
    .sidebar-session-menu-item:hover {
        background: $TEXT_PRIMARY;
        color: $PAGE_BACKGROUND;
    }
    .sidebar-session-menu-item.sidebar-chat-item {
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
            "New Chat", id="side-new-chat", classes="sidebar-action"
        )
        yield new_chat
        with Vertical(id="sidebar-content"):
            yield Static("Pinned", id="pinned-title", classes="sidebar-section-title")
            yield Vertical(id="pinned-list", classes="sidebar-list")
            yield Static(
                "Projects", id="projects-title", classes="sidebar-section-title"
            )
            yield Vertical(id="projects-list", classes="sidebar-list")
            yield Static("Chats", id="chats-title", classes="sidebar-section-title")
            yield Vertical(id="chats-list", classes="sidebar-list")

        settings = SidebarActionButton(
            "= Settings", id="side-settings", classes="sidebar-action"
        )
        yield settings

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
            menu_id = str(getattr(control, "data_menu_id", ""))
            if menu_id:
                self._toggle_action_menu(menu_id)
        elif control_id.startswith("session-action-"):
            self._close_action_menus()
            self.post_message(
                self.SessionActionRequested(
                    str(getattr(control, "data_path", "")),
                    str(getattr(control, "data_action", "")),
                )
            )
        elif control_id.startswith("project-") and not control_id.startswith(
            "project-chats-"
        ):
            self._close_action_menus()
            group_id = str(getattr(control, "data_group_id", ""))
            if not group_id:
                return
            lst = self.query_one(f"#{group_id}", Vertical)
            if lst.has_class("hidden"):
                lst.remove_class("hidden")
                self._expanded_groups.discard(group_id)
            else:
                lst.add_class("hidden")
                self._expanded_groups.add(group_id)
        else:
            self._close_action_menus()

    def _close_action_menus(self) -> None:
        for menu in self.query(".sidebar-session-menu"):
            menu.add_class("hidden")

    def _toggle_action_menu(self, menu_id: str) -> None:
        if not menu_id:
            return
        target = None
        for menu in self.query(".sidebar-session-menu"):
            if menu.id == menu_id:
                target = menu
                continue
            menu.add_class("hidden")
        if target is None:
            return
        if target.has_class("hidden"):
            target.remove_class("hidden")
        else:
            target.add_class("hidden")

    def _mount_session_item(
        self,
        container: Vertical,
        session: dict,
        item_id: str,
        chat_item: bool = False,
    ) -> None:
        title = str(session.get("title") or "New Chat")
        session_path = str(session.get("session_path") or "")
        is_pinned = bool(session.get("_pinned"))
        action_name = "unpin" if is_pinned else "pin"
        action_label = "Unpin chat" if is_pinned else "Pin chat"
        label_classes = "sidebar-session-label"
        menu_item_classes = "sidebar-session-menu-item"
        if chat_item:
            label_classes += " sidebar-chat-item"
            menu_item_classes += " sidebar-chat-item"

        menu_id = f"session-menu-{item_id}"

        label = Static(title, id=f"session-label-{item_id}", classes=label_classes)
        label.data_path = session_path
        label.data_menu_id = menu_id

        load_item = Static(
            "Load chat",
            id=f"session-action-load-{item_id}",
            classes=menu_item_classes,
        )
        load_item.data_action = "load"
        load_item.data_path = session_path

        pin_item = Static(
            action_label,
            id=f"session-action-{action_name}-{item_id}",
            classes=menu_item_classes,
        )
        pin_item.data_action = action_name
        pin_item.data_path = session_path

        delete_item = Static(
            "Archive chat",
            id=f"session-action-delete-{item_id}",
            classes=menu_item_classes,
        )
        delete_item.data_action = "delete"
        delete_item.data_path = session_path

        entry = Vertical(
            label,
            Vertical(
                load_item,
                pin_item,
                delete_item,
                id=menu_id,
                classes="sidebar-session-menu hidden",
            ),
            classes="sidebar-session-entry",
        )
        container.mount(entry)

    def set_sessions(self, project_sessions, pinned_sessions, orphan_sessions):
        self._render_serial += 1
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
        chats_list.remove_children()
        chats_title.add_class("hidden")
        chats_list.add_class("hidden")

        for index, session in enumerate(pinned_sessions or []):
            pinned_title.remove_class("hidden")
            pinned_list.remove_class("hidden")
            self._mount_session_item(
                pinned_list,
                session,
                item_id=f"pinned-{serial}-{index}",
            )

        for index, project in enumerate(project_sessions or []):
            name = str(project.get("name") or "")
            sessions = list(project.get("sessions") or [])
            projects_title.remove_class("hidden")
            projects_list.remove_class("hidden")
            group_id = f"project-chats-{serial}-{index}"
            project_item = Static(
                name,
                id=f"project-{serial}-{index}",
                classes="sidebar-item",
            )
            project_item.data_group_id = group_id
            projects_list.mount(project_item)
            group_classes = "sidebar-list project-chat-list"
            if sessions:
                group_classes += " hidden"
            session_group = Vertical(
                id=group_id,
                classes=group_classes,
            )
            projects_list.mount(session_group)
            if not sessions:
                no_chats = Static(
                    "No Chats",
                    id=f"project-empty-{serial}-{index}",
                    classes="sidebar-item sidebar-chat-item sidebar-empty-item",
                )
                session_group.mount(no_chats)
            for session_index, session in enumerate(sessions):
                self._mount_session_item(
                    session_group,
                    session,
                    item_id=f"project-{serial}-{index}-{session_index}",
                    chat_item=True,
                )

        for index, session in enumerate(orphan_sessions or []):
            chats_title.remove_class("hidden")
            chats_list.remove_class("hidden")
            self._mount_session_item(
                chats_list,
                session,
                item_id=f"orphan-{serial}-{index}",
            )

        self._fix_section_gaps()

    def _fix_section_gaps(self) -> None:
        titles = list(self.query(".sidebar-section-title"))
        first_visible = None
        for title in titles:
            title.remove_class("no-top-gap")
            if first_visible is None and not title.has_class("hidden"):
                first_visible = title
        if first_visible is not None:
            first_visible.add_class("no-top-gap")
