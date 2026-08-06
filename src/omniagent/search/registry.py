from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .formatter import format_search_response
from .models import SearchResponse, WebSearchError


@dataclass(frozen=True)
class ProviderConfigField:
    key: str
    default: str = ""
    choices: tuple[str, ...] = ()
    secret: bool = False


class SearchProvider(Protocol):
    name: str
    label: str
    config_fields: tuple[ProviderConfigField, ...]
    tool_definition: dict

    def search(
        self,
        tool_input: dict,
        config: dict,
        timeout: float,
        max_results_ceiling: int,
    ) -> SearchResponse: ...


_PROVIDERS: dict[str, SearchProvider] = {}


def register_provider(provider):
    name = str(getattr(provider, "name", "") or "").strip().lower()
    if not name:
        raise ValueError("Web search provider name cannot be empty.")
    if name in _PROVIDERS:
        raise ValueError(f"Web search provider is already registered: {name}")
    _PROVIDERS[name] = provider
    return provider


def provider_names():
    return tuple(sorted(_PROVIDERS))


def get_provider(name):
    normalized = str(name or "").strip().lower()
    try:
        return _PROVIDERS[normalized]
    except KeyError as error:
        raise WebSearchError(
            f"Unsupported web search provider: {normalized or name}"
        ) from error


def provider_config_fields(name):
    return get_provider(name).config_fields


def provider_tool_definition(name):
    definition = get_provider(name).tool_definition
    return {
        "name": definition["name"],
        "description": definition["description"],
        "input_schema": dict(definition["input_schema"]),
    }


def default_provider_configs():
    return {
        name: {field.key: field.default for field in provider.config_fields}
        for name, provider in sorted(_PROVIDERS.items())
    }


def normalize_provider_config(name, value, *, strict=False):
    provider = get_provider(name)
    raw = value if isinstance(value, dict) else {}
    normalized = {}
    for field in provider.config_fields:
        field_value = str(raw.get(field.key, field.default) or "").strip()
        if field.choices:
            matched = next(
                (choice for choice in field.choices if choice.lower() == field_value.lower()),
                "",
            )
            if matched:
                field_value = matched
            elif strict:
                choices = ", ".join(field.choices)
                raise ValueError(
                    f"web_search.providers.{provider.name}.{field.key} "
                    f"must be one of: {choices}."
                )
            else:
                field_value = field.default
        normalized[field.key] = field_value
    return normalized


def normalize_provider_configs(value):
    raw = value if isinstance(value, dict) else {}
    return {
        name: normalize_provider_config(name, raw.get(name, {}))
        for name in provider_names()
    }


def is_provider_configured(name, config):
    provider = get_provider(name)
    keys = {field.key for field in provider.config_fields}
    if "api_key" not in keys:
        return True
    return bool(str((config or {}).get("api_key") or "").strip())


def run_web_search(name, tool_input, config, timeout, max_results_ceiling):
    provider = get_provider(name)
    normalized_config = normalize_provider_config(provider.name, config)
    if not is_provider_configured(provider.name, normalized_config):
        raise WebSearchError(
            f"{provider.label} API key is missing. Add "
            f"web_search.providers.{provider.name}.api_key in config.json."
        )
    try:
        response = provider.search(
            dict(tool_input or {}),
            normalized_config,
            timeout,
            max_results_ceiling,
        )
    except WebSearchError:
        raise
    except Exception as error:
        raise WebSearchError(f"{provider.label} search failed: {error}") from error
    return format_search_response(response, provider.label)
