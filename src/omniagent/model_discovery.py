from __future__ import annotations

from collections.abc import Iterable

from .config import (
    API_TYPE_ANTHROPIC,
    API_TYPE_GEMINI,
    API_TYPE_GLM,
    API_TYPE_OLLAMA,
    API_TYPE_OPENAI,
    GEMINI_OPENAI_BASE_URL,
    normalize_api_type,
)


MODEL_DISCOVERY_TIMEOUT_SECONDS = 20.0


def _model_value(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("id", "model", "name"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return ""
    for key in ("id", "model", "name"):
        value = str(getattr(item, key, "") or "").strip()
        if value:
            return value
    return ""


def _page_items(page: object) -> Iterable[object]:
    if isinstance(page, dict):
        values = page.get("data")
        if values is None:
            values = page.get("models")
    else:
        values = getattr(page, "data", None)
        if values is None:
            values = getattr(page, "models", None)
    if values is None and isinstance(page, (list, tuple)):
        values = page
    if values is None:
        return ()
    return values


def _model_names(response: object) -> list[str]:
    iter_pages = getattr(response, "iter_pages", None)
    pages = iter_pages() if callable(iter_pages) else (response,)
    names: set[str] = set()
    for page in pages:
        for item in _page_items(page):
            value = _model_value(item)
            if value:
                names.add(value)
    return sorted(names, key=str.casefold)


def _openai_models(api_key: str, base_url: str) -> list[str]:
    from openai import OpenAI

    kwargs: dict[str, object] = {
        "api_key": api_key,
        "timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    try:
        return _model_names(client.models.list())
    finally:
        client.close()


def _anthropic_models(api_key: str, base_url: str) -> list[str]:
    import anthropic

    kwargs: dict[str, object] = {
        "api_key": api_key,
        "timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    try:
        return _model_names(client.models.list())
    finally:
        client.close()


def _ollama_models(api_key: str, base_url: str) -> list[str]:
    from ollama import Client

    kwargs: dict[str, object] = {"timeout": MODEL_DISCOVERY_TIMEOUT_SECONDS}
    if base_url:
        kwargs["host"] = base_url
    if api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
    client = Client(**kwargs)
    try:
        return _model_names(client.list())
    finally:
        client.close()


def _glm_models(api_key: str) -> list[str]:
    import httpx
    from zai import ZhipuAiClient

    sdk_client = ZhipuAiClient(api_key=api_key)
    try:
        url = f"{str(sdk_client.base_url).rstrip('/')}/models"
        headers = dict(sdk_client.auth_headers)
    finally:
        sdk_client.close()

    with httpx.Client(timeout=MODEL_DISCOVERY_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return _model_names(response.json())


def fetch_available_models(api_type: str, base_url: str, api_key: str) -> list[str]:
    """Fetch model identifiers using the same provider settings as chat runtime."""

    normalized_api_type = normalize_api_type(api_type)
    normalized_base_url = str(base_url or "").strip()
    normalized_api_key = str(api_key or "").strip()

    if normalized_api_type == API_TYPE_OLLAMA:
        return _ollama_models(normalized_api_key, normalized_base_url)
    if not normalized_api_key:
        raise ValueError("API key cannot be empty.")
    if normalized_api_type == API_TYPE_ANTHROPIC:
        return _anthropic_models(normalized_api_key, normalized_base_url)
    if normalized_api_type == API_TYPE_GLM:
        return _glm_models(normalized_api_key)
    if normalized_api_type == API_TYPE_GEMINI:
        normalized_base_url = normalized_base_url or GEMINI_OPENAI_BASE_URL
        return _openai_models(normalized_api_key, normalized_base_url)
    if normalized_api_type == API_TYPE_OPENAI:
        return _openai_models(normalized_api_key, normalized_base_url)
    raise ValueError(f"Unsupported API type: {normalized_api_type}")
