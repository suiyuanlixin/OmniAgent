from __future__ import annotations

from io import StringIO

from rich.console import Console


_bridge = None


def set_bridge(bridge) -> None:
    global _bridge
    _bridge = bridge


def clear_bridge() -> None:
    global _bridge
    _bridge = None


def get_bridge():
    return _bridge


def render_console_text(*objects, **kwargs) -> str:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=100,
        highlight=False,
    )
    console.print(*objects, **kwargs)
    return output.getvalue()
