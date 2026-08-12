from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable

from .registry import API_TYPE_OPENAI_RESPONSES, ModelProviderSpec, register_provider
from .openai_chat_completions import create_openai_client, fetch_openai_models


class OpenAIResponsesClient:
    """Adapt the native Responses API to OmniAgent's shared chat loop."""

    def __init__(self, api_key: str, base_url: str = ""):
        self._client = create_openai_client(api_key, base_url)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_chat_completion)
        )
        self.last_response_items: list[dict[str, Any]] = []

    def close(self):
        self._client.close()

    def _create_chat_completion(self, **kwargs):
        response_kwargs = self._response_kwargs(kwargs)
        self.last_response_items = []
        if kwargs.get("stream"):
            response_kwargs["stream"] = True
            return self._stream_chunks(self._client.responses.create(**response_kwargs))
        response = self._client.responses.create(**response_kwargs)
        return self._completion(response)

    def _response_kwargs(self, kwargs):
        messages = list(kwargs.get("messages") or [])
        instructions, items = self._input_items(messages)
        response_kwargs: dict[str, Any] = {
            "model": kwargs.get("model"),
            "input": items,
            "max_output_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
            "store": False,
        }
        if instructions:
            response_kwargs["instructions"] = instructions
        effort = str(kwargs.get("reasoning_effort") or "").strip()
        if effort:
            response_kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
            response_kwargs["include"] = ["reasoning.encrypted_content"]
        tools = self._tools(kwargs.get("tools") or [])
        if tools:
            response_kwargs["tools"] = tools
        return {key: value for key, value in response_kwargs.items() if value is not None}

    def _input_items(self, messages):
        instructions = []
        items = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role in {"system", "developer"}:
                text = self._content_text(message.get("content"))
                if text:
                    instructions.append(text)
                continue
            if role == "assistant":
                native_items = message.get("response_items")
                if not isinstance(native_items, list) or not native_items:
                    raise ValueError(
                        "OpenAI Responses history is missing response_items for "
                        "an assistant message. This conversation cannot be "
                        "replayed with OpenAI Responses API."
                    )
                items.extend(native_items)
                continue
            if role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": str(message.get("content") or ""),
                })
                continue
            if role not in {"user", "assistant"}:
                continue
            items.append({
                "role": role,
                "content": self._message_content(message.get("content"), role),
            })
        return "\n\n".join(instructions), items

    def _message_content(self, content, role):
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or "")
        if role == "assistant":
            return self._content_text(content)
        parts = []
        for item in content:
            if not isinstance(item, dict):
                text = str(item or "")
                if text:
                    parts.append({"type": "input_text", "text": text})
                continue
            item_type = str(item.get("type") or "")
            if item_type == "text":
                parts.append({"type": "input_text", "text": str(item.get("text") or "")})
            elif item_type == "image_url":
                image = item.get("image_url") or {}
                parts.append({
                    "type": "input_image",
                    "image_url": str(image.get("url") or ""),
                    "detail": self._image_detail(image.get("detail")),
                })
            elif item_type == "video_url":
                video = item.get("video_url") or {}
                parts.append({
                    "type": "input_file",
                    "file_data": str(video.get("url") or ""),
                    "filename": "video",
                })
            elif item_type == "input_audio":
                audio = item.get("input_audio") or {}
                parts.append({
                    "type": "input_file",
                    "file_data": self._audio_data_url(audio),
                    "filename": f"audio.{str(audio.get('format') or 'bin')}",
                })
        return parts if role == "user" else self._content_text(content)

    @staticmethod
    def _image_detail(value):
        return value if value in {"low", "high", "auto", "original"} else "auto"

    @staticmethod
    def _audio_data_url(audio):
        audio_format = str(audio.get("format") or "").lower()
        mime_type = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac",
            "ogg": "audio/ogg", "webm": "audio/webm", "m4a": "audio/mp4",
        }.get(audio_format, "application/octet-stream")
        return f"data:{mime_type};base64,{str(audio.get('data') or '')}"

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
                "parameters": function.get("parameters") or function.get("input_schema") or {"type": "object"},
                "strict": False,
            })
        return converted

    def _completion(self, response):
        message = self._message(response)
        return SimpleNamespace(
            id=str(getattr(response, "id", "") or ""),
            model=str(getattr(response, "model", "") or ""),
            choices=[SimpleNamespace(index=0, message=message, finish_reason=self._finish_reason(response))],
            usage=getattr(response, "usage", None),
        )

    def _stream_chunks(self, events: Iterable[Any]):
        calls_by_index: dict[int, dict[str, str]] = {}
        for event in events:
            event_type = str(getattr(event, "type", "") or "")
            content = ""
            reasoning = ""
            tool_calls = []
            usage = None
            if event_type == "response.output_text.delta":
                content = str(getattr(event, "delta", "") or "")
            elif event_type in {
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            }:
                reasoning = str(getattr(event, "delta", "") or "")
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if str(getattr(item, "type", "") or "") == "function_call":
                    index = int(getattr(event, "output_index", 0) or 0)
                    calls_by_index[index] = {
                        "id": str(
                            getattr(item, "call_id", "")
                            or getattr(item, "id", "")
                            or ""
                        ),
                        "name": str(getattr(item, "name", "") or ""),
                    }
                    tool_calls = [
                        self._tool_call_namespace(item, index, arguments="")
                    ]
            elif event_type == "response.function_call_arguments.delta":
                index = int(getattr(event, "output_index", 0) or 0)
                call = calls_by_index.get(index, {})
                tool_calls = [
                    SimpleNamespace(
                        index=index,
                        id=call.get("id", str(getattr(event, "item_id", "") or "")),
                        type="function",
                        function=SimpleNamespace(
                            name=call.get("name", ""),
                            arguments=str(getattr(event, "delta", "") or ""),
                        ),
                    )
                ]
            elif event_type == "response.function_call_arguments.done":
                index = int(getattr(event, "output_index", 0) or 0)
                call = calls_by_index.get(index, {})
                tool_calls = [
                    SimpleNamespace(
                        index=index,
                        id=call.get("id", str(getattr(event, "item_id", "") or "")),
                        type="function",
                        complete=True,
                        function=SimpleNamespace(
                            name=str(getattr(event, "name", "") or call.get("name", "")),
                            arguments=str(getattr(event, "arguments", "") or ""),
                        ),
                    )
                ]
            elif event_type == "response.completed":
                completed_response = getattr(event, "response", None)
                usage = getattr(completed_response, "usage", None)
                self.last_response_items = self._output_items(completed_response)
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
                    usage=usage,
                )

    def _message(self, response):
        text = []
        reasoning = []
        tool_calls = []
        response_items = self._output_items(response)
        self.last_response_items = response_items
        for index, item in enumerate(list(getattr(response, "output", None) or [])):
            item_type = str(getattr(item, "type", "") or "")
            if item_type == "message":
                for part in list(getattr(item, "content", None) or []):
                    if str(getattr(part, "type", "") or "") == "output_text":
                        text.append(str(getattr(part, "text", "") or ""))
            elif item_type == "reasoning":
                reasoning.extend(self._reasoning_text(item))
            elif item_type == "function_call":
                tool_calls.append(self._tool_call_namespace(item, index))
        return SimpleNamespace(
            role="assistant", content="".join(text), reasoning_content="".join(reasoning),
            tool_calls=tool_calls, response_items=response_items,
        )

    def _output_items(self, response):
        items = []
        for item in list(getattr(response, "output", None) or []):
            plain_item = self._plain_data(item)
            if isinstance(plain_item, dict):
                items.append(plain_item)
        return items

    @staticmethod
    def _reasoning_text(item):
        parts = []
        for summary in list(getattr(item, "summary", None) or []):
            parts.append(str(getattr(summary, "text", "") or ""))
        for content in list(getattr(item, "content", None) or []):
            parts.append(str(getattr(content, "text", "") or ""))
        return parts

    @staticmethod
    def _tool_call_namespace(item, index, arguments=None):
        return SimpleNamespace(
            index=int(index or 0),
            id=str(
                getattr(item, "call_id", "")
                or getattr(item, "id", "")
                or ""
            ),
            type="function",
            function=SimpleNamespace(
                name=str(getattr(item, "name", "") or ""),
                arguments=(
                    str(getattr(item, "arguments", "") or "")
                    if arguments is None
                    else str(arguments)
                ),
            ),
        )

    @staticmethod
    def _finish_reason(response):
        status = str(getattr(response, "status", "") or "")
        return "stop" if status == "completed" else status or None

    @staticmethod
    def _plain_data(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [OpenAIResponsesClient._plain_data(item) for item in value]
        if isinstance(value, dict):
            return {key: OpenAIResponsesClient._plain_data(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return OpenAIResponsesClient._plain_data(value.model_dump(exclude_none=True))
        return value

    @staticmethod
    def _content_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or "") if isinstance(item, dict) else str(item or "")
                for item in content
            )
        return str(content or "")


def create_client(api_key: str, base_url: str):
    return OpenAIResponsesClient(api_key, base_url)


OPENAI_RESPONSES_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_OPENAI_RESPONSES,
    label="OpenAI Responses",
    create_client=create_client,
    fetch_models=fetch_openai_models,
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    supported_modalities=("image",),
    requires_native_history=True,
    tool_schema_style="openai",
))
