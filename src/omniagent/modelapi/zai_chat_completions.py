from __future__ import annotations

import httpx

from .registry import API_TYPE_ZAI_CHAT_COMPLETIONS, ModelProviderSpec, register_provider
from .base import MODEL_DISCOVERY_TIMEOUT_SECONDS, model_names


def create_client(api_key: str, base_url: str):
    try:
        from zai import ZhipuAiClient
    except ImportError as error:
        raise RuntimeError("ZhipuAI SDK is not installed. Run: pip install zai-sdk") from error
    return ZhipuAiClient(api_key=api_key)


def fetch_models(api_key: str, base_url: str) -> list[str]:
    sdk_client = create_client(api_key, base_url)
    try:
        url = f"{str(sdk_client.base_url).rstrip('/')}/models"
        headers = dict(sdk_client.auth_headers)
    finally:
        sdk_client.close()
    with httpx.Client(timeout=MODEL_DISCOVERY_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return model_names(response.json())


ZAI_CHAT_COMPLETIONS_PROVIDER = register_provider(ModelProviderSpec(
    api_type=API_TYPE_ZAI_CHAT_COMPLETIONS,
    label="Zai Chat Completions",
    create_client=create_client,
    fetch_models=fetch_models,
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    supports_base_url=False,
    tool_schema_style="glm",
))
