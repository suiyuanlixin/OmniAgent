from .registry import (
    API_TYPE_ANTHROPIC_MESSAGES,
    API_TYPE_GEMINI_INTERACTIONS,
    API_TYPE_OLLAMA_CHAT,
    API_TYPE_OPENAI_CHAT_COMPLETIONS,
    API_TYPE_OPENAI_RESPONSES,
    API_TYPE_ZAI_CHAT_COMPLETIONS,
    ModelProviderSpec,
    create_client,
    fetch_models,
    get_provider,
    normalize_api_type,
    normalize_base_url,
    provider_choices,
    provider_names,
    register_provider,
)

from .ollama_chat import OLLAMA_CHAT_PROVIDER
from .openai_chat_completions import OPENAI_CHAT_COMPLETIONS_PROVIDER
from .openai_responses import OPENAI_RESPONSES_PROVIDER
from .anthropic_messages import ANTHROPIC_MESSAGES_PROVIDER
from .gemini_interactions import GEMINI_INTERACTIONS_PROVIDER
from .zai_chat_completions import ZAI_CHAT_COMPLETIONS_PROVIDER

SUPPORTED_API_TYPES = frozenset(provider_names())

__all__ = [
    "API_TYPE_ANTHROPIC_MESSAGES",
    "API_TYPE_GEMINI_INTERACTIONS",
    "API_TYPE_OLLAMA_CHAT",
    "API_TYPE_OPENAI_CHAT_COMPLETIONS",
    "API_TYPE_OPENAI_RESPONSES",
    "API_TYPE_ZAI_CHAT_COMPLETIONS",
    "ModelProviderSpec",
    "SUPPORTED_API_TYPES",
    "create_client",
    "fetch_models",
    "get_provider",
    "normalize_api_type",
    "normalize_base_url",
    "provider_choices",
    "provider_names",
    "register_provider",
]
