"""Compatibility exports for the provider-based web search package."""

from .search import (
    DEFAULT_WEB_SEARCH_ENABLE,
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_PROVIDER,
    DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS,
    MAX_WEB_SEARCH_MAX_RESULTS,
    TAVILY_SEARCH_DEPTHS,
    TAVILY_TOPICS,
    WEB_SEARCH_PROVIDERS,
    ProviderConfigField,
    SearchHit,
    SearchResponse,
    WebSearchError,
    bounded_max_results,
    default_provider_configs,
    format_search_response,
    get_provider,
    is_web_search_configured,
    normalize_provider_config,
    normalize_provider_configs,
    normalize_web_search_provider,
    provider_config_fields,
    provider_tool_definition,
    search_web,
)
from .search.providers.tavily import TAVILY_SEARCH_DEPTHS, TAVILY_TOPICS

__all__ = [
    "DEFAULT_WEB_SEARCH_DEPTH",
    "DEFAULT_WEB_SEARCH_ENABLE",
    "DEFAULT_WEB_SEARCH_MAX_RESULTS",
    "DEFAULT_WEB_SEARCH_PROVIDER",
    "DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS",
    "MAX_WEB_SEARCH_MAX_RESULTS",
    "TAVILY_SEARCH_DEPTHS",
    "TAVILY_TOPICS",
    "WEB_SEARCH_PROVIDERS",
    "ProviderConfigField",
    "SearchHit",
    "SearchResponse",
    "WebSearchError",
    "bounded_max_results",
    "default_provider_configs",
    "format_search_response",
    "get_provider",
    "is_web_search_configured",
    "normalize_provider_config",
    "normalize_provider_configs",
    "normalize_web_search_provider",
    "provider_config_fields",
    "provider_tool_definition",
    "search_web",
]

# Tavily's own search_depth vocabulary, kept so persisted legacy config values
# can be migrated onto the per-provider search_depth setting.
DEFAULT_WEB_SEARCH_DEPTH = "basic"
