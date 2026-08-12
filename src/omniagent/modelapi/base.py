from __future__ import annotations

from collections.abc import Iterable

MODEL_DISCOVERY_TIMEOUT_SECONDS = 20.0


def model_value(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("id", "model", "name"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return ""
    for key in ("id", "model", "name"):
        value = str(getattr(item, key, "") or "").strip()
        if value:
            return value
    return ""


def page_items(page: object) -> Iterable[object]:
    if isinstance(page, dict):
        values = page.get("data")
        if values is None:
            values = page.get("models")
    else:
        values = getattr(page, "data", None)
        if values is None:
            values = getattr(page, "models", None)
    if values is None and isinstance(page, (list, tuple)):
        values = page
    return values or ()


def model_names(response: object) -> list[str]:
    iter_pages = getattr(response, "iter_pages", None)
    pages = iter_pages() if callable(iter_pages) else (response,)
    names = {
        value
        for page in pages
        for item in page_items(page)
        if (value := model_value(item))
    }
    return sorted(names, key=str.casefold)
