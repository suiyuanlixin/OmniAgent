from __future__ import annotations

from .registry import (
    API_TYPE_OPENAI_CHAT_COMPLETIONS,
    ModelProviderSpec,
    register_provider,
)
from .base import MODEL_DISCOVERY_TIMEOUT_SECONDS, model_names


def create_openai_client(api_key: str, base_url: str):
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("OpenAI SDK is not installed. Run: pip install openai") from error
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def fetch_openai_models(api_key: str, base_url: str) -> list[str]:
    from openai import OpenAI
    kwargs = {
        "api_key": api_key,
        "timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    try:
        return model_names(client.models.list())
    finally:
        client.close()


OPENAI_CHAT_COMPLETIONS_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_OPENAI_CHAT_COMPLETIONS,
    label="OpenAI Chat Completions",
    create_client=create_openai_client,
    fetch_models=fetch_openai_models,
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    tool_schema_style="openai",
))
