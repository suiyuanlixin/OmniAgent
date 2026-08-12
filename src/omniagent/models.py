from __future__ import annotations

from .modelapi import fetch_models, get_provider, normalize_api_type


def fetch_available_models(api_type: str, base_url: str, api_key: str) -> list[str]:
    """Fetch model identifiers through the selected model API provider."""
    normalized_api_type = normalize_api_type(api_type)
    provider = get_provider(normalized_api_type)
    normalized_api_key = str(api_key or "").strip()
    if provider.requires_api_key and not normalized_api_key:
        raise ValueError("API key cannot be empty.")
    return fetch_models(
        normalized_api_type,
        normalized_api_key,
        str(base_url or "").strip(),
    )
