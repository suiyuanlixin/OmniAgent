from collections.abc import Mapping

from .i18n import pad_to_width, t
from .ui import print_error, print_info, print_success

COMMAND_DESCRIPTION_KEYS = {
    "/help": "cmd.help.desc",
    "/quit": "cmd.quit.desc",
    "/clear": "cmd.clear.desc",
    "/comp": "cmd.comp.desc",
    "/memory": "cmd.memory.desc",
    "/search": "cmd.search.desc",
    "/skills": "cmd.skills.desc",
    "/agent": "cmd.agent.desc",
    "/team": "cmd.team.desc",
}


class _CommandCatalog(Mapping):
    """Command token -> description mapping resolved on every read.

    Descriptions are translated lazily instead of being frozen at import
    time, so switching language at runtime is reflected everywhere the
    catalog is consumed (help output, settings page, command menu).
    """

    def __init__(self, description_keys):
        self._description_keys = dict(description_keys)

    def __getitem__(self, command):
        return t(self._description_keys[command])

    def __iter__(self):
        return iter(self._description_keys)

    def __len__(self):
        return len(self._description_keys)


COMMANDS = _CommandCatalog(COMMAND_DESCRIPTION_KEYS)


def process_command(user_input, chat):
    parts = user_input.split(maxsplit=1)
    base = parts[0].lower()
    args = parts[1] if len(parts) > 1 else None

    handler = COMMAND_HANDLERS.get(base)
    if handler:
        return handler(chat, args)
    print_error(t("cli.unknown_command", command=base))
    return True


def handle_help(chat, args):
    command_list = "\n".join(
        f"{pad_to_width(cmd, 8)} {desc}" for cmd, desc in COMMANDS.items()
    )
    print_info(f"{t('cli.commands_header')}\n{command_list}")
    return True


def handle_quit(chat, args):
    print_success(t("cli.goodbye"))
    return False


def handle_clear(chat, args):
    if chat is None:
        print_info(t("cli.no_chat_to_clear"))
        return True
    chat.clear_history()
    print_success(t("cli.history_cleared"))
    return True


def handle_comp(chat, args):
    if args:
        print_error(t("cli.comp_usage"))
        return True
    if chat is None:
        print_info(t("cli.no_chat_to_compact"))
        return True

    result = chat.compact_context(manual=True)
    if result.get("compacted"):
        return True

    reason = result.get("reason") or t("cli.compact_cancelled")
    if result.get("error"):
        print_error(reason)
    else:
        print_info(reason)
    return True


COMMAND_HANDLERS = {
    "/help": handle_help,
    "/quit": handle_quit,
    "/clear": handle_clear,
    "/comp": handle_comp,
}
