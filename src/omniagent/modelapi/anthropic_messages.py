from __future__ import annotations

from .registry import API_TYPE_ANTHROPIC_MESSAGES, ModelProviderSpec, register_provider
from .base import MODEL_DISCOVERY_TIMEOUT_SECONDS, model_names


def create_client(api_key: str, base_url: str):
    try:
        import anthropic
    except ImportError as error:
        raise RuntimeError("Anthropic SDK is not installed. Run: pip install anthropic") from error
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def fetch_models(api_key: str, base_url: str) -> list[str]:
    import anthropic
    kwargs = {
        "api_key": api_key,
        "timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    try:
        return model_names(client.models.list())
    finally:
        client.close()


ANTHROPIC_MESSAGES_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_ANTHROPIC_MESSAGES,
    label="Anthropic Messages",
    create_client=create_client,
    fetch_models=fetch_models,
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    tool_schema_style="anthropic",
))
