"""Provider-based web search: neutral request/response models plus a registry."""

from .models import (
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS,
    MAX_WEB_SEARCH_MAX_RESULTS,
    SearchHit,
    SearchResponse,
    WebSearchError,
    bounded_max_results,
)
from .formatter import format_search_response
from .registry import (
    ProviderConfigField,
    default_provider_configs,
    get_provider,
    is_provider_configured,
    normalize_provider_config,
    normalize_provider_configs,
    provider_config_fields,
    provider_names,
    provider_tool_definition,
    register_provider,
    run_web_search,
)

# Importing the providers package registers every built-in provider. This must
# run before WEB_SEARCH_PROVIDERS is computed below.
from . import providers as _providers  # noqa: F401
from .providers.tavily import TAVILY_SEARCH_DEPTHS, TAVILY_TOPICS


DEFAULT_WEB_SEARCH_DEPTH = "basic"
DEFAULT_WEB_SEARCH_ENABLE = True
DEFAULT_WEB_SEARCH_PROVIDER = "tavily"
WEB_SEARCH_PROVIDERS = frozenset(provider_names())

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
    "is_provider_configured",
    "is_web_search_configured",
    "normalize_provider_config",
    "normalize_provider_configs",
    "normalize_web_search_provider",
    "provider_config_fields",
    "provider_names",
    "provider_tool_definition",
    "register_provider",
    "run_web_search",
    "search_web",
]


def normalize_web_search_provider(value):
    provider = str(value or DEFAULT_WEB_SEARCH_PROVIDER).strip().lower()
    if provider in WEB_SEARCH_PROVIDERS:
        return provider
    return DEFAULT_WEB_SEARCH_PROVIDER


def is_web_search_configured(provider=DEFAULT_WEB_SEARCH_PROVIDER, providers=None):
    selected = normalize_web_search_provider(provider)
    configs = normalize_provider_configs(providers)
    return is_provider_configured(selected, configs.get(selected, {}))


def search_web(
    provider,
    tool_input,
    *,
    provider_config=None,
    max_results_ceiling=DEFAULT_WEB_SEARCH_MAX_RESULTS,
    timeout=DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS,
):
    if not isinstance(tool_input, dict):
        raise WebSearchError("Search input must be an object.")
    return run_web_search(
        normalize_web_search_provider(provider),
        tool_input,
        provider_config or {},
        float(timeout or DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS),
        max_results_ceiling,
    )
