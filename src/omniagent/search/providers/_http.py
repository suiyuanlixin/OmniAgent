from __future__ import annotations

import httpx

from ..models import WebSearchError


def request_json(method, url, *, label, **kwargs):
    """Perform an HTTP request and return a JSON object, or raise WebSearchError."""
    try:
        response = httpx.request(method, url, **kwargs)
    except httpx.TimeoutException as error:
        raise WebSearchError(f"{label} search timed out.") from error
    except httpx.HTTPError as error:
        raise WebSearchError(f"{label} search request failed: {error}") from error
    if response.status_code >= 400:
        raise WebSearchError(_error_message(response, label))
    try:
        data = response.json()
    except ValueError as error:
        raise WebSearchError(f"{label} returned a non-JSON response.") from error
    if not isinstance(data, dict):
        raise WebSearchError(f"{label} returned an unexpected response.")
    return data


def _error_message(response, label):
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("detail") or ""
        else:
            detail = payload.get("detail") or error or payload.get("message") or ""
    if not detail:
        detail = str(getattr(response, "text", "") or "").strip()
    if not detail:
        detail = str(getattr(response, "reason_phrase", "") or "Request failed")
    return f"{label} search failed ({response.status_code}): {detail}"
