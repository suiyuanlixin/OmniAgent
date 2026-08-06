from __future__ import annotations

from ..models import SearchHit, SearchResponse, WebSearchError
from .base import (
    ProviderConfigField,
    api_key,
    bounded_int,
    bounded_tool_count,
    optional_string,
    optional_string_list,
    register_provider,
    reject_unknown_fields,
    require_string,
)
from ._http import request_json


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_SEARCH_DEPTHS = ("basic", "fast", "ultra-fast", "advanced")
TAVILY_TOPICS = ("general", "news", "finance")
TAVILY_TIME_RANGES = ("day", "week", "month", "year", "d", "w", "m", "y")
TAVILY_ANSWER_LEVELS = ("basic", "advanced")
TAVILY_RAW_CONTENT = ("markdown", "text")


class TavilySearchProvider:
    name = "tavily"
    label = "Tavily"
    config_fields = (
        ProviderConfigField(key="api_key", secret=True),
        ProviderConfigField(key="search_depth", default="basic", choices=TAVILY_SEARCH_DEPTHS),
    )
    tool_definition = {
        "name": "web_search",
        "description": (
            "Search the public web with Tavily using Tavily's native search fields. "
            "Use this for current or external information. The user controls the "
            "search depth and result ceiling; do not provide those settings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The Tavily search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Optional result count; values above the user's ceiling are capped.",
                },
                "topic": {
                    "type": "string",
                    "enum": list(TAVILY_TOPICS),
                    "description": "Tavily search topic.",
                },
                "time_range": {
                    "type": "string",
                    "enum": list(TAVILY_TIME_RANGES),
                    "description": "Optional Tavily time range.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Optional start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end date in YYYY-MM-DD format.",
                },
                "chunks_per_source": {
                    "type": "integer",
                    "description": "Optional number of content chunks per source.",
                },
                "include_answer": {
                    "oneOf": [
                        {"type": "boolean"},
                        {"type": "string", "enum": list(TAVILY_ANSWER_LEVELS)},
                    ],
                    "description": "Whether Tavily should return a basic or advanced answer summary.",
                },
                "include_raw_content": {
                    "oneOf": [
                        {"type": "boolean"},
                        {"type": "string", "enum": list(TAVILY_RAW_CONTENT)},
                    ],
                    "description": "Whether to include raw page content, optionally as Markdown or text.",
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional domains to include.",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional domains to exclude.",
                },
                "country": {
                    "type": "string",
                    "description": "Optional country boost for general searches.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }

    def search(self, tool_input, config, timeout, max_results_ceiling):
        reject_unknown_fields(
            tool_input, self.tool_definition["input_schema"]["properties"]
        )
        query = require_string(tool_input, "query")
        payload = {"query": query}
        max_results = bounded_tool_count(
            tool_input.get("max_results"), max_results_ceiling, field="max_results"
        )
        payload["max_results"] = max_results
        if "topic" in tool_input:
            topic = optional_string(tool_input, "topic").lower()
            if topic not in TAVILY_TOPICS:
                raise WebSearchError("topic must be one of: general, news, finance.")
            payload["topic"] = topic
        if "time_range" in tool_input:
            time_range = optional_string(tool_input, "time_range").lower()
            if time_range not in TAVILY_TIME_RANGES:
                raise WebSearchError(
                    "time_range must be one of: day, week, month, year, d, w, m, y."
                )
            payload["time_range"] = time_range
        for field in ("start_date", "end_date"):
            if field in tool_input:
                value = optional_string(tool_input, field)
                if value:
                    payload[field] = value
        if "chunks_per_source" in tool_input:
            payload["chunks_per_source"] = bounded_int(
                tool_input.get("chunks_per_source"),
                field="chunks_per_source",
                minimum=1,
                maximum=3,
            )
        if "include_answer" in tool_input:
            include_answer = tool_input["include_answer"]
            if isinstance(include_answer, bool):
                payload["include_answer"] = include_answer
            elif (
                isinstance(include_answer, str)
                and include_answer.strip().lower() in TAVILY_ANSWER_LEVELS
            ):
                payload["include_answer"] = include_answer.strip().lower()
            else:
                raise WebSearchError(
                    "include_answer must be boolean, basic, or advanced."
                )
        if "include_raw_content" in tool_input:
            raw_content = tool_input["include_raw_content"]
            if isinstance(raw_content, bool):
                payload["include_raw_content"] = raw_content
            elif isinstance(raw_content, str) and raw_content.strip().lower() in TAVILY_RAW_CONTENT:
                payload["include_raw_content"] = raw_content.strip().lower()
            else:
                raise WebSearchError("include_raw_content must be boolean, markdown, or text.")
        for field in ("include_domains", "exclude_domains"):
            if field in tool_input:
                payload[field] = list(optional_string_list(tool_input, field))
        if "country" in tool_input:
            country = optional_string(tool_input, "country")
            if country and payload.get("topic", "general") == "general":
                payload["country"] = country.lower()

        payload.update(
            {
                "search_depth": config["search_depth"],
                "include_images": False,
                "include_usage": True,
            }
        )
        data = request_json(
            "POST",
            TAVILY_SEARCH_URL,
            label=self.label,
            headers={
                "Authorization": f"Bearer {api_key(config)}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )

        hits = []
        for item in (data.get("results") or [])[:max_results]:
            if not isinstance(item, dict):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or "(untitled)").strip(),
                    url=str(item.get("url") or "").strip(),
                    content=str(item.get("content") or ""),
                    raw_content=str(item.get("raw_content") or ""),
                    score=item.get("score"),
                    published_date=str(item.get("published_date") or "").strip(),
                )
            )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        response_time = data.get("response_time")
        return SearchResponse(
            provider=self.name,
            query=query,
            hits=tuple(hits),
            answer=str(data.get("answer") or ""),
            request_id=str(data.get("request_id") or ""),
            metadata={
                "credits": usage.get("credits"),
                "response_time": f"{response_time}s" if response_time is not None else None,
            },
        )


TAVILY_PROVIDER = register_provider(TavilySearchProvider())
