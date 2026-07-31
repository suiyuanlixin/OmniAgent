from .ui import print_error, print_info, print_success

COMMANDS = {
    "/help": "Open command help",
    "/quit": "Exit OmniAgent",
    "/clear": "Clear current chat",
    "/comp": "Compact the current conversation context immediately",
    "/memory": "Open memory page",
    "/search": "Open web search settings",
    "/skills": "Open skills settings",
    "/agent": "Open agent mode page",
    "/team": "Open team page",
}


def process_command(user_input, chat):
    parts = user_input.split(maxsplit=1)
    base = parts[0].lower()
    args = parts[1] if len(parts) > 1 else None

    handler = COMMAND_HANDLERS.get(base)
    if handler:
        return handler(chat, args)
    print_error(f"Unknown command: {base}. Use /help to see available commands.")
    return True


def handle_help(chat, args):
    command_list = "\n".join(f"{cmd:<8} {desc}" for cmd, desc in COMMANDS.items())
    print_info(f"Commands:\n{command_list}")
    return True


def handle_quit(chat, args):
    print_success("Goodbye!")
    return False


def handle_clear(chat, args):
    if chat is None:
        print_info("No active conversation to clear.")
        return True
    chat.clear_history()
    print_success("Conversation history cleared.")
    return True


def handle_comp(chat, args):
    if args:
        print_error("Usage: /comp")
        return True
    if chat is None:
        print_info("No active conversation to compact.")
        return True

    result = chat.compact_context(manual=True)
    if result.get("compacted"):
        return True

    reason = result.get("reason") or "Context compaction was cancelled."
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
