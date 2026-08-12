from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Iterable

from .base import model_value
from .registry import API_TYPE_GEMINI_INTERACTIONS, ModelProviderSpec, register_provider


class GeminiInteractionsClient:
    """Adapt the Gemini Interactions API to OmniAgent's shared chat loop."""

    def __init__(self, api_key: str, base_url: str = ""):
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise RuntimeError(
                "Google Gen AI SDK is not installed. Run: pip install google-genai"
            ) from error

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["http_options"] = types.HttpOptions(base_url=base_url)
        self._client = genai.Client(**kwargs)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_chat_completion)
        )
        self.last_interaction_steps: list[dict[str, Any]] = []

    def close(self):
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def _create_chat_completion(self, **kwargs):
        request = self._request_kwargs(kwargs)
        self.last_interaction_steps = []
        if kwargs.get("stream"):
            request["stream"] = True
            return self._stream_chunks(self._client.interactions.create(**request))
        interaction = self._client.interactions.create(**request)
        return self._completion(interaction)

    def _request_kwargs(self, kwargs):
        system_instruction, input_steps = self._input_steps(
            kwargs.get("messages") or []
        )
        request: dict[str, Any] = {
            "model": str(kwargs.get("model") or ""),
            "input": input_steps,
            "store": False,
        }
        if system_instruction:
            request["system_instruction"] = system_instruction
        tools = self._tools(kwargs.get("tools") or [])
        if tools:
            request["tools"] = tools
        generation_config: dict[str, Any] = {}
        max_tokens = kwargs.get("max_tokens")
        if max_tokens is not None:
            generation_config["max_output_tokens"] = int(max_tokens)
        include_thoughts = self._include_thoughts(kwargs)
        effort = str(kwargs.get("reasoning_effort") or "").strip().lower()
        if include_thoughts:
            generation_config["thinking_summaries"] = "auto"
            if effort in {"minimal", "low", "medium", "high"}:
                generation_config["thinking_level"] = effort
        if generation_config:
            request["generation_config"] = generation_config
        return request

    @staticmethod
    def _include_thoughts(kwargs):
        extra_body = kwargs.get("extra_body")
        if not isinstance(extra_body, dict):
            return False
        google = extra_body.get("google")
        if not isinstance(google, dict):
            return False
        thinking = google.get("thinking_config")
        return isinstance(thinking, dict) and bool(thinking.get("include_thoughts"))

    def _input_steps(self, messages):
        system_parts = []
        steps = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role in {"system", "developer"}:
                text = self._content_text(message.get("content"))
                if text:
                    system_parts.append(text)
                continue
            if role == "tool":
                steps.append(self._function_result_step(message))
                continue
            if role == "assistant":
                native_steps = message.get("interaction_steps")
                if not isinstance(native_steps, list) or not native_steps:
                    raise ValueError(
                        "Gemini Interactions history is missing interaction_steps "
                        "for an assistant message. This conversation cannot be "
                        "replayed with Gemini Interactions API."
                    )
                steps.extend(native_steps)
                continue
            if role == "user":
                content = self._content_parts(message.get("content"))
                if content:
                    steps.append({"type": "user_input", "content": content})
                continue
            raise ValueError(
                f"Unsupported role in Gemini Interactions history: {role!r}."
            )
        return "\n\n".join(system_parts), steps

    @staticmethod
    def _arguments(value):
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _function_result_step(message):
        return {
            "type": "function_result",
            "call_id": str(message.get("tool_call_id") or ""),
            "name": str(message.get("tool_name") or message.get("name") or ""),
            "result": [
                {"type": "text", "text": str(message.get("content") or "")}
            ],
            "is_error": bool(message.get("is_error")),
        }

    def _content_parts(self, content):
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        if not isinstance(content, list):
            text = str(content or "")
            return [{"type": "text", "text": text}] if text else []

        parts = []
        for item in content:
            if not isinstance(item, dict):
                text = str(item or "")
                if text:
                    parts.append({"type": "text", "text": text})
                continue
            item_type = str(item.get("type") or "")
            if item_type == "text":
                text = str(item.get("text") or "")
                if text:
                    parts.append({"type": "text", "text": text})
            elif item_type in {"image_url", "video_url"}:
                media = item.get(item_type) or {}
                part = self._data_url_part(str(media.get("url") or ""))
                if part:
                    parts.append(part)
            elif item_type == "input_audio":
                audio = item.get("input_audio") or {}
                audio_format = str(audio.get("format") or "").lower()
                mime_type = {
                    "mp3": "audio/mpeg",
                    "wav": "audio/wav",
                    "flac": "audio/flac",
                    "ogg": "audio/ogg",
                    "webm": "audio/webm",
                    "m4a": "audio/mp4",
                }.get(audio_format, "application/octet-stream")
                data = str(audio.get("data") or "")
                if data:
                    parts.append({
                        "type": "audio",
                        "data": data,
                        "mime_type": mime_type,
                    })
            elif item_type in {"image", "audio", "video"}:
                source = item.get("source") or {}
                data = str(source.get("data") or "")
                if data:
                    parts.append({
                        "type": item_type,
                        "data": data,
                        "mime_type": str(
                            source.get("media_type") or "application/octet-stream"
                        ),
                    })
        return parts

    @staticmethod
    def _data_url_part(value):
        if not value.startswith("data:") or ";base64," not in value:
            return None
        header, data = value.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        if mime_type.startswith("image/"):
            kind = "image"
        elif mime_type.startswith("video/"):
            kind = "video"
        elif mime_type.startswith("audio/"):
            kind = "audio"
        else:
            kind = "document"
        return {"type": kind, "data": data, "mime_type": mime_type}

    @staticmethod
    def _tools(tools):
        converted = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") or tool
            name = str(function.get("name") or "")
            if not name:
                continue
            converted.append({
                "type": "function",
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": (
                    function.get("parameters")
                    or function.get("input_schema")
                    or {"type": "object"}
                ),
            })
        return converted

    def _completion(self, interaction):
        message = self._message(interaction)
        return SimpleNamespace(
            id=str(getattr(interaction, "id", "") or ""),
            model=str(getattr(interaction, "model", "") or ""),
            choices=[
                SimpleNamespace(
                    index=0,
                    message=message,
                    finish_reason=self._finish_reason(interaction),
                )
            ],
            usage=self._usage(interaction),
        )

    def _message(self, interaction):
        steps = list(getattr(interaction, "steps", None) or [])
        interaction_steps = self._output_steps(steps)
        self.last_interaction_steps = interaction_steps
        text = []
        thinking = []
        tool_calls = []
        for index, step in enumerate(steps):
            step_type = str(getattr(step, "type", "") or "")
            if step_type == "model_output":
                text.extend(self._content_texts(getattr(step, "content", None)))
            elif step_type == "thought":
                thinking.extend(self._thought_texts(step))
            elif step_type == "function_call":
                tool_calls.append(self._tool_call_namespace(step, index))
        output_text = str(getattr(interaction, "output_text", "") or "")
        if output_text and not text:
            text.append(output_text)
        return SimpleNamespace(
            role="assistant",
            content="".join(text),
            reasoning_content="".join(thinking),
            tool_calls=tool_calls,
            interaction_steps=interaction_steps,
        )

    def _stream_chunks(self, events: Iterable[Any]):
        step_types: dict[int, str] = {}
        calls: dict[int, dict[str, str]] = {}
        for event in events:
            event_type = str(getattr(event, "event_type", "") or "")
            content = ""
            reasoning = ""
            tool_calls = []
            usage = None
            if event_type == "step.start":
                index = int(getattr(event, "index", 0) or 0)
                step = getattr(event, "step", None)
                step_type = str(getattr(step, "type", "") or "")
                step_types[index] = step_type
                if step_type == "function_call":
                    calls[index] = {
                        "id": str(getattr(step, "id", "") or ""),
                        "name": str(getattr(step, "name", "") or ""),
                    }
                    tool_calls = [self._tool_call_namespace(step, index, arguments="")]
            elif event_type == "step.delta":
                index = int(getattr(event, "index", 0) or 0)
                delta = getattr(event, "delta", None)
                delta_type = str(getattr(delta, "type", "") or "")
                if delta_type == "text":
                    value = str(getattr(delta, "text", "") or "")
                    if step_types.get(index) == "thought":
                        reasoning = value
                    else:
                        content = value
                elif delta_type == "thought_summary":
                    reasoning = "".join(
                        self._content_texts([getattr(delta, "content", None)])
                    )
                elif delta_type == "arguments_delta":
                    call = calls.get(index, {})
                    tool_calls = [SimpleNamespace(
                        index=index,
                        id=call.get("id", ""),
                        type="function",
                        function=SimpleNamespace(
                            name=call.get("name", ""),
                            arguments=str(getattr(delta, "arguments", "") or ""),
                        ),
                    )]
            elif event_type == "step.stop":
                usage = getattr(event, "usage", None) or getattr(
                    event, "step_usage", None
                )
            elif event_type == "interaction.completed":
                interaction = getattr(event, "interaction", None)
                steps = list(getattr(interaction, "steps", None) or [])
                self.last_interaction_steps = self._output_steps(steps)
                usage = getattr(interaction, "usage", None)
                for index, step in enumerate(steps):
                    if str(getattr(step, "type", "") or "") == "function_call":
                        tool_calls.append(
                            self._tool_call_namespace(
                                step, index, complete=True
                            )
                        )
            if content or reasoning or tool_calls or usage is not None:
                delta = SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=tool_calls,
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(index=0, delta=delta, finish_reason=None)
                    ],
                    usage=self._usage_value(usage),
                )

    def _output_steps(self, steps):
        return [
            self._plain_data(step)
            for step in steps
            if str(getattr(step, "type", "") or "")
            not in {"user_input", "function_result"}
        ]

    @staticmethod
    def _tool_call_namespace(step, index, arguments=None, complete=False):
        raw_arguments = getattr(step, "arguments", None) or {}
        return SimpleNamespace(
            index=int(index or 0),
            id=str(getattr(step, "id", "") or ""),
            type="function",
            complete=bool(complete),
            function=SimpleNamespace(
                name=str(getattr(step, "name", "") or ""),
                arguments=(
                    json.dumps(raw_arguments, ensure_ascii=False)
                    if arguments is None
                    else str(arguments)
                ),
            ),
        )

    @staticmethod
    def _thought_texts(step):
        texts = []
        for content in list(getattr(step, "summary", None) or []):
            if str(getattr(content, "type", "") or "") == "text":
                texts.append(str(getattr(content, "text", "") or ""))
        return texts

    @staticmethod
    def _content_texts(contents):
        texts = []
        for content in list(contents or []):
            if content is None:
                continue
            if str(getattr(content, "type", "") or "") == "text":
                texts.append(str(getattr(content, "text", "") or ""))
        return texts

    @staticmethod
    def _finish_reason(interaction):
        status = str(getattr(interaction, "status", "") or "")
        return "stop" if status == "completed" else status or None

    def _usage(self, interaction):
        return self._usage_value(getattr(interaction, "usage", None))

    @staticmethod
    def _usage_value(usage):
        if usage is None:
            return None
        output_tokens = int(getattr(usage, "total_output_tokens", 0) or 0)
        reasoning_tokens = int(getattr(usage, "total_thought_tokens", 0) or 0)
        return SimpleNamespace(
            prompt_tokens=int(getattr(usage, "total_input_tokens", 0) or 0),
            completion_tokens=output_tokens + reasoning_tokens,
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            completion_tokens_details=SimpleNamespace(
                reasoning_tokens=reasoning_tokens
            ),
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=int(getattr(usage, "total_cached_tokens", 0) or 0)
            ),
        )

    @staticmethod
    def _plain_data(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [GeminiInteractionsClient._plain_data(item) for item in value]
        if isinstance(value, tuple):
            return [GeminiInteractionsClient._plain_data(item) for item in value]
        if isinstance(value, dict):
            return {
                key: GeminiInteractionsClient._plain_data(item)
                for key, item in value.items()
            }
        if hasattr(value, "model_dump"):
            return GeminiInteractionsClient._plain_data(
                value.model_dump(exclude_none=True)
            )
        return value

    @staticmethod
    def _content_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or "")
                if isinstance(item, dict)
                else str(item or "")
                for item in content
            )
        return str(content or "")


def create_client(api_key: str, base_url: str):
    return GeminiInteractionsClient(api_key=api_key, base_url=base_url)


def fetch_models(api_key: str, base_url: str) -> list[str]:
    from google import genai
    from google.genai import types

    kwargs: dict[str, object] = {"api_key": api_key}
    if base_url:
        kwargs["http_options"] = types.HttpOptions(base_url=base_url)
    client = genai.Client(**kwargs)
    try:
        names = {
            value.removeprefix("models/")
            for model in client.models.list()
            if (value := model_value(model))
        }
        return sorted(names, key=str.casefold)
    finally:
        client.close()


def normalize_gemini_base_url(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.rstrip("/").endswith("/openai"):
        raise ValueError(
            "Gemini Interactions API does not accept an OpenAI-compatible Base URL. "
            "Clear Base URL or provide a native Gemini Interactions endpoint."
        )
    return normalized


GEMINI_INTERACTIONS_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_GEMINI_INTERACTIONS,
    label="Gemini Interactions",
    create_client=create_client,
    fetch_models=fetch_models,
    reasoning_efforts=("minimal", "low", "medium", "high"),
    supports_temperature=False,
    requires_native_history=True,
    normalize_base_url=normalize_gemini_base_url,
))
