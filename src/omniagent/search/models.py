from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_WEB_SEARCH_MAX_RESULTS = 5
DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS = 15
MAX_WEB_SEARCH_MAX_RESULTS = 20


class WebSearchError(Exception):
    """Raised for every web search failure, regardless of provider."""


def bounded_max_results(value):
    if isinstance(value, bool):
        return DEFAULT_WEB_SEARCH_MAX_RESULTS
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_WEB_SEARCH_MAX_RESULTS
    return min(max(parsed, 1), MAX_WEB_SEARCH_MAX_RESULTS)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str = ""
    raw_content: str = ""
    score: float | int | None = None
    published_date: str = ""
    source: str = ""


@dataclass(frozen=True)
class SearchResponse:
    provider: str
    query: str
    hits: tuple[SearchHit, ...] = ()
    answer: str = ""
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
