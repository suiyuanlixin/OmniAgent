from __future__ import annotations

from ..output import ToolOutputValue
from .models import SearchResponse


def format_search_response(response: SearchResponse, label: str = "") -> ToolOutputValue:
    provider_label = str(label or "").strip() or response.provider.title()
    header = [f"{provider_label} web search results for: {response.query}"]
    for key, value in response.metadata.items():
        if value is not None and str(value) != "":
            header.append(f"{key}: {value}")
    if response.request_id:
        header.append(f"request_id: {response.request_id}")

    leading_sections = ["\n".join(header)]
    if response.answer:
        leading_sections.append("Answer:\n" + response.answer)

    if not response.hits:
        leading_sections.append("No results found.")
        text = "\n\n".join(leading_sections)
        return ToolOutputValue(text=text, records=(text,), record_mode="search")

    result_records = []
    for index, hit in enumerate(response.hits, 1):
        block = [f"[{index}] {hit.title or '(untitled)'}"]
        if hit.url:
            block.append(f"URL: {hit.url}")
        if hit.source:
            block.append(f"Source: {hit.source}")
        if hit.published_date:
            block.append(f"Published: {hit.published_date}")
        if hit.score is not None:
            block.append(f"Score: {hit.score}")
        if hit.content:
            block.append("Content:\n" + hit.content)
        if hit.raw_content:
            block.append("Raw content:\n" + hit.raw_content)
        result_records.append("\n".join(block))

    leading = "\n\n".join(leading_sections + ["Results:"])
    text = leading + "\n" + "\n\n".join(result_records)
    return ToolOutputValue(
        text=text,
        records=(leading, *result_records),
        record_mode="search",
    )
