from __future__ import annotations

from ..i18n import t
from .theme import TEXT_MUTED, TEXT_PRIMARY

# Values are stable identifiers; labels are resolved on every call so a
# language switch re-labels the dropdowns without a restart. Do not cache
# these at module or class level.
APPROVAL_LEVEL_VALUES: tuple[str, ...] = ("confirm", "approve", "full")
THINKING_LEVEL_VALUES: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "max",
)


def approval_levels() -> list[tuple[str, str]]:
    return [(t(f"input.approval.{value}"), value) for value in APPROVAL_LEVEL_VALUES]


def thinking_levels() -> list[tuple[str, str]]:
    return [(t(f"input.thinking.{value}"), value) for value in THINKING_LEVEL_VALUES]


PROJECT_NAME = "OmniAgent"
PROJECT_LOGO = (
    f"[{TEXT_MUTED} bold]█▀▀█ █▄▄█ █▀▀█ ▀▜▛▀[/][{TEXT_PRIMARY} bold] █▀▀█ █▀▀▀ █▀▀▀ █▀▀█ ▀▜▛▀[/]\n"
    f"[{TEXT_MUTED} bold]█  █ █  █ █  █  ▐▌ [/][{TEXT_PRIMARY} bold] █▀▀█ █  █ █▀▀▀ █  █  ▐▌ [/]\n"
    f"[{TEXT_MUTED} bold]▀▀▀▀ ▀  ▀ ▀  ▀ ▀▀▀▀[/][{TEXT_PRIMARY} bold] ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀  ▀  ▝▘ [/]"
)
