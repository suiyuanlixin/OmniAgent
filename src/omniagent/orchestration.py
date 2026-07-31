from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class NormalTurn:
    assistant_message: Any
    thinking: str
    text: str
    tool_calls: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class NormalLoopResult:
    thinking: str
    response: str
    thinking_rendered: bool
    response_rendered: bool
    limit_reached: bool


class NormalToolCoordinator:
    """Coordinate complete-response tool rounds across supported API types."""

    def __init__(
        self,
        *,
        max_rounds: int,
        run_turn: Callable[[], NormalTurn],
        append_assistant: Callable[[Any], None],
        execute_tools: Callable[[Sequence[Mapping[str, Any]]], None],
        render_turn: Callable[[str, str], tuple[bool, bool]],
    ) -> None:
        self.max_rounds = max(1, int(max_rounds))
        self.run_turn = run_turn
        self.append_assistant = append_assistant
        self.execute_tools = execute_tools
        self.render_turn = render_turn

    def run(self) -> NormalLoopResult:
        thinking = ""
        response = ""
        thinking_rendered = False
        response_rendered = False

        for _round in range(self.max_rounds):
            turn = self.run_turn()
            self.append_assistant(turn.assistant_message)
            thinking += str(turn.thinking or "")
            response += str(turn.text or "")
            rendered_thinking, rendered_response = self.render_turn(
                turn.thinking,
                turn.text,
            )
            thinking_rendered = thinking_rendered or rendered_thinking
            response_rendered = response_rendered or rendered_response
            if not turn.tool_calls:
                return NormalLoopResult(
                    thinking=thinking,
                    response=response,
                    thinking_rendered=thinking_rendered,
                    response_rendered=response_rendered,
                    limit_reached=False,
                )
            self.execute_tools(turn.tool_calls)

        return NormalLoopResult(
            thinking=thinking,
            response=response,
            thinking_rendered=thinking_rendered,
            response_rendered=response_rendered,
            limit_reached=True,
        )
