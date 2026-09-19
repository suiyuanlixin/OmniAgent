from __future__ import annotations

import json
from collections.abc import Iterable


def serialize_for_estimate(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def estimate_text_tokens(value: object) -> int:
    text = str(value or "")
    ascii_chars = 0
    non_ascii_tokens = 0
    for character in text:
        if character.isspace():
            continue
        if ord(character) <= 0x7F:
            ascii_chars += 1
        else:
            non_ascii_tokens += 1
    return (ascii_chars + 3) // 4 + non_ascii_tokens


def estimate_history_chars(history: Iterable[object]) -> int:
    return sum(len(serialize_for_estimate(message)) for message in history)


def estimate_history_tokens(history: Iterable[object]) -> int:
    return sum(
        estimate_text_tokens(serialize_for_estimate(message)) + 4
        for message in history
    )


TOOL_RESULT_TRUNCATION = (
    "\n[Truncated for model context; full result retained in the worker transcript.]"
)


def bound_tool_results(results: list[str], token_budget: int) -> list[str]:
    """Share an estimated payload budget per round, keeping small results first."""
    remaining = max(0, int(token_budget))
    bounded = [""] * len(results)
    sizes = [estimate_text_tokens(result) for result in results]
    pending = sorted(range(len(results)), key=sizes.__getitem__)
    for position, index in enumerate(pending):
        allocation = remaining // (len(pending) - position)
        text = results[index]
        if sizes[index] <= allocation:
            bounded[index] = text
        else:
            marker = TOOL_RESULT_TRUNCATION
            # Include the marker in the budget, including tiny/zero budgets.
            if estimate_text_tokens(marker) > allocation:
                marker = "[truncated]" if allocation >= 3 else "." * allocation
            prefix_budget = max(0, allocation - estimate_text_tokens(marker))
            units = 0
            end = 0
            for end, character in enumerate(text):
                if not character.isspace():
                    units += 1 if ord(character) <= 0x7F else 4
                if units > prefix_budget * 4:
                    break
            else:
                end = len(text)
            bounded[index] = text[:end].rstrip() + marker
        remaining -= estimate_text_tokens(bounded[index])
    return bounded
