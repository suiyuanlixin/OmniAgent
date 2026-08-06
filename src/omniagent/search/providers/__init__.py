"""Importing this package registers every built-in search provider."""

from .brave import BRAVE_PROVIDER, BraveSearchProvider
from .tavily import TAVILY_PROVIDER, TavilySearchProvider
from .zhipu import ZHIPU_PROVIDER, ZhipuSearchProvider

__all__ = [
    "BRAVE_PROVIDER",
    "TAVILY_PROVIDER",
    "ZHIPU_PROVIDER",
    "BraveSearchProvider",
    "TavilySearchProvider",
    "ZhipuSearchProvider",
]
