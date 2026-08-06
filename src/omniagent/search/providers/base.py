from __future__ import annotations

from ..models import WebSearchError
from ..registry import ProviderConfigField, register_provider

__all__ = [
    "ProviderConfigField",
    "WebSearchError",
    "api_key",
    "bounded_int",
    "bounded_tool_count",
    "optional_bool",
    "optional_string",
    "optional_string_list",
    "register_provider",
    "reject_unknown_fields",
    "require_string",
]


def api_key(config):
    """Read the provider API key. The registry validates presence before search."""
    return str((config or {}).get("api_key") or "").strip()


def bounded_int(value, *, field, minimum, maximum, default=None):
    if isinstance(value, bool):
        raise WebSearchError(f"{field} must be an integer.")
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise WebSearchError(f"{field} must be an integer.") from error
    if not minimum <= parsed <= maximum:
        raise WebSearchError(f"{field} must be between {minimum} and {maximum}.")
    return parsed


def bounded_tool_count(value, ceiling, *, field="count", maximum=20):
    if isinstance(value, bool):
        raise WebSearchError(f"{field} must be an integer.")
    if value is None or str(value).strip() == "":
        return min(max(int(ceiling), 1), maximum)
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise WebSearchError(f"{field} must be an integer.") from error
    return min(max(parsed, 1), min(int(ceiling), maximum))


def reject_unknown_fields(tool_input, allowed):
    unknown = sorted(set(tool_input or {}) - set(allowed))
    if unknown:
        raise WebSearchError("Unsupported search parameter(s): " + ", ".join(unknown))


def require_string(tool_input, field):
    value = str((tool_input or {}).get(field) or "").strip()
    if not value:
        raise WebSearchError(f"{field} cannot be empty.")
    return value


def optional_string(tool_input, field):
    value = (tool_input or {}).get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WebSearchError(f"{field} must be a string.")
    return value.strip()


def optional_bool(tool_input, field, default=False):
    value = (tool_input or {}).get(field, default)
    if isinstance(value, bool):
        return value
    raise WebSearchError(f"{field} must be a boolean.")


def optional_string_list(tool_input, field):
    value = (tool_input or {}).get(field, ())
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WebSearchError(f"{field} must be an array of strings.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise WebSearchError(f"{field} must be an array of non-empty strings.")
        result.append(item.strip())
    return tuple(result)
