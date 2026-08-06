from __future__ import annotations

from ..models import SearchHit, SearchResponse, WebSearchError
from .base import (
    ProviderConfigField,
    api_key,
    bounded_int,
    bounded_tool_count,
    optional_string,
    register_provider,
    reject_unknown_fields,
    require_string,
)
from ._http import request_json


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_EXTRA_SNIPPETS = ("true", "false")
BRAVE_SAFESEARCH = "moderate"
BRAVE_FRESHNESS = ("pd", "pw", "pm", "py")


class BraveSearchProvider:
    name = "brave"
    label = "Brave"
    config_fields = (
        ProviderConfigField(key="api_key", secret=True),
        ProviderConfigField(key="extra_snippets", default="false", choices=BRAVE_EXTRA_SNIPPETS),
    )
    tool_definition = {
        "name": "web_search",
        "description": (
            "Search the public web with Brave using Brave's native query parameters. "
            "The user controls extra snippets and the result ceiling; do not provide that setting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "The Brave web search query."},
                "count": {
                    "type": "integer",
                    "description": "Optional result count; values above the user's ceiling are capped.",
                },
                "freshness": {
                    "type": "string",
                    "description": (
                        "Optional Brave freshness code (pd, pw, pm, py) or native "
                        "custom date range such as 2022-04-01to2022-07-30."
                    ),
                },
                "country": {"type": "string", "description": "Optional two-letter country code."},
                "search_lang": {"type": "string", "description": "Optional search language code."},
                "ui_lang": {
                    "type": "string",
                    "description": "Optional language tag for response metadata, such as en-US.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Optional result page offset from 0 through 9.",
                },
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    }

    def search(self, tool_input, config, timeout, max_results_ceiling):
        reject_unknown_fields(
            tool_input, self.tool_definition["input_schema"]["properties"]
        )
        query = require_string(tool_input, "q")
        max_results = bounded_tool_count(
            tool_input.get("count"), max_results_ceiling, field="count"
        )
        params = {
            "q": query,
            "count": max_results,
            "safesearch": BRAVE_SAFESEARCH,
            "extra_snippets": config["extra_snippets"],
        }
        if "freshness" in tool_input:
            freshness = optional_string(tool_input, "freshness")
            if freshness:
                params["freshness"] = freshness.lower() if freshness.lower() in BRAVE_FRESHNESS else freshness
        if "country" in tool_input:
            country = optional_string(tool_input, "country")
            if country:
                params["country"] = country.upper()
        if "search_lang" in tool_input:
            language = optional_string(tool_input, "search_lang")
            if language:
                params["search_lang"] = language.lower()
        if "ui_lang" in tool_input:
            ui_language = optional_string(tool_input, "ui_lang")
            if ui_language:
                params["ui_lang"] = ui_language
        if "offset" in tool_input:
            params["offset"] = bounded_int(
                tool_input.get("offset"), field="offset", minimum=0, maximum=9
            )

        data = request_json(
            "GET",
            BRAVE_SEARCH_URL,
            label=self.label,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key(config),
            },
            params=params,
            timeout=timeout,
        )

        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        hits = []
        for item in (web.get("results") or [])[:max_results]:
            if not isinstance(item, dict):
                continue
            profile = item.get("profile")
            profile = profile if isinstance(profile, dict) else {}
            hits.append(
                SearchHit(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    content=_content(item),
                    published_date=str(item.get("page_age") or item.get("age") or "").strip(),
                    source=str(profile.get("long_name") or "").strip(),
                )
            )

        query_meta = data.get("query")
        query_meta = query_meta if isinstance(query_meta, dict) else {}
        return SearchResponse(
            provider=self.name,
            query=query,
            hits=tuple(hits),
            metadata={"altered_query": query_meta.get("altered")},
        )


def _content(item):
    description = str(item.get("description") or "")
    snippets = item.get("extra_snippets")
    snippets = snippets if isinstance(snippets, (list, tuple)) else ()
    extra = "\n".join(str(value) for value in snippets if str(value).strip())
    if not extra:
        return description
    return description + ("\n" if description else "") + extra


BRAVE_PROVIDER = register_provider(BraveSearchProvider())
