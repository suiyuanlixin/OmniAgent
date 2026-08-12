from __future__ import annotations

from .registry import API_TYPE_OLLAMA_CHAT, ModelProviderSpec, register_provider
from .base import MODEL_DISCOVERY_TIMEOUT_SECONDS, model_names


def create_client(api_key: str, base_url: str):
    try:
        from ollama import Client
    except ImportError as error:
        raise RuntimeError("Ollama SDK is not installed. Run: pip install ollama") from error
    kwargs = {}
    if base_url:
        kwargs["host"] = base_url
    if api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
    return Client(**kwargs)


def fetch_models(api_key: str, base_url: str) -> list[str]:
    from ollama import Client
    kwargs = {"timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS}
    if base_url:
        kwargs["host"] = base_url
    if api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
    client = Client(**kwargs)
    try:
        return model_names(client.list())
    finally:
        client.close()


OLLAMA_CHAT_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_OLLAMA_CHAT,
    label="Ollama Chat",
    create_client=create_client,
    fetch_models=fetch_models,
    reasoning_efforts=("low", "medium", "high"),
    requires_api_key=False,
    tool_schema_style="ollama",
))
