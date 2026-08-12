from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

API_TYPE_OLLAMA_CHAT = "ollama_chat"
API_TYPE_OPENAI_RESPONSES = "openai_responses"
API_TYPE_OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
API_TYPE_ANTHROPIC_MESSAGES = "anthropic_messages"
API_TYPE_GEMINI_INTERACTIONS = "gemini_interactions"
API_TYPE_ZAI_CHAT_COMPLETIONS = "zai_chat_completions"


@dataclass(frozen=True)
class ModelProviderSpec:
    api_type: str
    label: str
    create_client: Callable[[str, str], object]
    fetch_models: Callable[[str, str], list[str]]
    reasoning_efforts: tuple[str, ...]
    requires_api_key: bool = True
    supports_base_url: bool = True
    supports_temperature: bool = True
    requires_native_history: bool = False
    supported_modalities: tuple[str, ...] = ("audio", "image", "video")
    tool_schema_style: str = "openai"
    normalize_base_url: Callable[[str], str] = lambda value: str(value or "").strip()


_PROVIDERS: dict[str, ModelProviderSpec] = {}


def register_provider(spec: ModelProviderSpec) -> ModelProviderSpec:
    if spec.api_type in _PROVIDERS:
        raise ValueError(f"Duplicate model API type: {spec.api_type}")
    _PROVIDERS[spec.api_type] = spec
    return spec


def normalize_api_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("Model API type is required.")
    if normalized not in _PROVIDERS:
        supported = ", ".join(_PROVIDERS)
        raise ValueError(
            f"Unsupported model API type: {normalized}. Supported types: {supported}."
        )
    return normalized


def get_provider(api_type: object) -> ModelProviderSpec:
    return _PROVIDERS[normalize_api_type(api_type)]


def provider_names() -> tuple[str, ...]:
    return tuple(_PROVIDERS)


def provider_choices() -> tuple[tuple[str, str], ...]:
    return tuple((spec.label, spec.api_type) for spec in _PROVIDERS.values())


def create_client(api_type: object, api_key: str, base_url: str):
    return get_provider(api_type).create_client(str(api_key or ""), str(base_url or ""))


def fetch_models(api_type: object, api_key: str, base_url: str) -> list[str]:
    return get_provider(api_type).fetch_models(str(api_key or ""), str(base_url or ""))


def normalize_base_url(api_type: object, value: object) -> str:
    return get_provider(api_type).normalize_base_url(str(value or ""))
