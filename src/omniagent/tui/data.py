from __future__ import annotations

from .theme import TEXT_MUTED, TEXT_PRIMARY

APPROVAL_LEVELS: list[tuple[str, str]] = [
    ("Ask for approval", "confirm"),
    ("Approve for me", "approve"),
    ("Full access", "full"),
]

THINKING_LEVELS: list[tuple[str, str]] = [
    ("Off", "none"),
    ("Minimal", "minimal"),
    ("Low", "low"),
    ("Medium", "medium"),
    ("High", "high"),
    ("Max", "max"),
]

PROJECT_NAME = "OmniAgent"
PROJECT_LOGO = (
    f"[{TEXT_MUTED} bold]█▀▀█ █▄▄█ █▀▀█ ▀▜▛▀[/][{TEXT_PRIMARY} bold] █▀▀█ █▀▀▀ █▀▀▀ █▀▀█ ▀▜▛▀[/]\n"
    f"[{TEXT_MUTED} bold]█  █ █  █ █  █  ▐▌ [/][{TEXT_PRIMARY} bold] █▀▀█ █  █ █▀▀▀ █  █  ▐▌ [/]\n"
    f"[{TEXT_MUTED} bold]▀▀▀▀ ▀  ▀ ▀  ▀ ▀▀▀▀[/][{TEXT_PRIMARY} bold] ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀  ▀  ▝▘ [/]"
)
