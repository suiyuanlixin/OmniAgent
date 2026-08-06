from __future__ import annotations

from ..models import SearchHit, SearchResponse, WebSearchError
from .base import (
    ProviderConfigField,
    api_key,
    bounded_tool_count,
    optional_string,
    register_provider,
    reject_unknown_fields,
    require_string,
)
from ._http import request_json


ZHIPU_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
ZHIPU_ENGINES = ("search_std", "search_pro", "search_pro_sogou", "search_pro_quark")
ZHIPU_CONTENT_SIZES = ("medium", "high")
ZHIPU_RECENCY = ("noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear")


class ZhipuSearchProvider:
    name = "zhipu"
    label = "Zhipu"
    config_fields = (
        ProviderConfigField(key="api_key", secret=True),
        ProviderConfigField(key="engine", default="search_std", choices=ZHIPU_ENGINES),
        ProviderConfigField(key="content_size", default="medium", choices=ZHIPU_CONTENT_SIZES),
    )
    tool_definition = {
        "name": "web_search",
        "description": (
            "Search the public web with Zhipu using Zhipu's native request fields. "
            "The user controls the search engine and default content size; do not provide those settings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search_query": {"type": "string", "description": "The Zhipu web search query."},
                "count": {
                    "type": "integer",
                    "description": "Optional result count; values above the user's ceiling are capped.",
                },
                "search_recency_filter": {
                    "type": "string",
                    "enum": list(ZHIPU_RECENCY),
                    "description": "Optional Zhipu recency filter.",
                },
                "search_domain_filter": {
                    "type": "string",
                    "description": "Optional single domain filter supported by Zhipu.",
                },
            },
            "required": ["search_query"],
            "additionalProperties": False,
        },
    }

    def search(self, tool_input, config, timeout, max_results_ceiling):
        reject_unknown_fields(
            tool_input, self.tool_definition["input_schema"]["properties"]
        )
        query = require_string(tool_input, "search_query")
        max_results = bounded_tool_count(
            tool_input.get("count"), max_results_ceiling, field="count"
        )
        engine = config["engine"]
        payload = {
            "search_engine": engine,
            "search_query": query,
            "search_intent": False,
            "content_size": config["content_size"],
        }
        if engine == "search_pro_sogou":
            payload["count"] = 10 if max_results <= 10 else 20
        elif engine != "search_pro_quark":
            payload["count"] = max_results
        if "search_recency_filter" in tool_input:
            recency = optional_string(tool_input, "search_recency_filter")
            if recency not in ZHIPU_RECENCY:
                raise WebSearchError(
                    "search_recency_filter must be one of: noLimit, oneDay, oneWeek, oneMonth, oneYear."
                )
            payload["search_recency_filter"] = recency
        if "search_domain_filter" in tool_input:
            domain = optional_string(tool_input, "search_domain_filter")
            if domain and engine != "search_pro_quark":
                payload["search_domain_filter"] = domain

        data = request_json(
            "POST",
            ZHIPU_SEARCH_URL,
            label=self.label,
            headers={
                "Authorization": f"Bearer {api_key(config)}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )

        hits = []
        for item in _as_list(data.get("search_result"))[:max_results]:
            if not isinstance(item, dict):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("link") or "").strip(),
                    content=str(item.get("content") or ""),
                    published_date=str(item.get("publish_date") or "").strip(),
                    source=str(item.get("media") or "").strip(),
                )
            )

        intent = next(
            (item for item in _as_list(data.get("search_intent")) if isinstance(item, dict)),
            {},
        )
        return SearchResponse(
            provider=self.name,
            query=query,
            hits=tuple(hits),
            request_id=str(data.get("request_id") or data.get("id") or ""),
            metadata={
                "intent": intent.get("intent"),
                "optimized_query": intent.get("query"),
            },
        )


def _as_list(value):
    if value is None:
        return ()
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


ZHIPU_PROVIDER = register_provider(ZhipuSearchProvider())
