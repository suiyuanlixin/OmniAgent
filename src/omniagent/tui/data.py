from __future__ import annotations

from ..config import supported_reasoning_efforts
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


REASONING_LABEL_VALUES = frozenset(
    {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
)


def reasoning_label(value: str, *, title_case: bool = False) -> str:
    text = str(value or "").strip().lower()
    key = "off" if text == "none" else text
    label = t(f"app.reasoning.{key}") if key in REASONING_LABEL_VALUES else text
    if title_case or not label.isascii():
        return label
    return label.lower()


def reasoning_levels_for_api(
    api_type: str,
    *,
    include_off: bool = False,
    title_case: bool = False,
) -> list[tuple[str, str]]:
    choices = [
        (reasoning_label(value, title_case=title_case), value)
        for value in supported_reasoning_efforts(api_type)
    ]
    if include_off:
        return [
            (reasoning_label("none", title_case=title_case), "none"),
            *choices,
        ]
    return choices


PROJECT_NAME = "OmniAgent"
PROJECT_LOGO = (
    f"[{TEXT_MUTED} bold]█▀▀█ █▄▄█ █▀▀█ ▀▜▛▀[/][{TEXT_PRIMARY} bold] █▀▀█ █▀▀▀ █▀▀▀ █▀▀█ ▀▜▛▀[/]\n"
    f"[{TEXT_MUTED} bold]█  █ █  █ █  █  ▐▌ [/][{TEXT_PRIMARY} bold] █▀▀█ █  █ █▀▀▀ █  █  ▐▌ [/]\n"
    f"[{TEXT_MUTED} bold]▀▀▀▀ ▀  ▀ ▀  ▀ ▀▀▀▀[/][{TEXT_PRIMARY} bold] ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀  ▀  ▝▘ [/]"
)
