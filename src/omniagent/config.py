import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .persistence import atomic_write_text
from .paths import APP_HOME
from .i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language

from .search import (
    DEFAULT_WEB_SEARCH_DEPTH,
    DEFAULT_WEB_SEARCH_ENABLE,
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_PROVIDER,
    DEFAULT_WEB_SEARCH_TOPIC,
    TAVILY_SEARCH_DEPTHS,
    TAVILY_TOPICS,
    WEB_SEARCH_PROVIDERS,
)

CONFIG_FILE = APP_HOME / "config.json"
API_TYPE_GLM = "glm"
API_TYPE_ANTHROPIC = "anthropic"
API_TYPE_OPENAI = "openai"
API_TYPE_GEMINI = "gemini"
API_TYPE_OLLAMA = "ollama"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_API_TYPE = API_TYPE_GLM
DEFAULT_BASE_URL = ""
DEFAULT_MODEL = "glm-4.7"
DEFAULT_MODEL_ALIAS = "Default"
DEFAULT_PROVIDER = "Default"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_STREAM_MODE = False
DEFAULT_THINKING_MODE = False
DEFAULT_REASONING_EFFORT = ""
DEFAULT_MULTIMODAL_LIMIT = 100
DEFAULT_FILE_INLINE_CHARS = 50000
EXTRA_MODALITY_AUDIO = "audio"
EXTRA_MODALITY_IMAGE = "image"
EXTRA_MODALITY_VIDEO = "video"
SUPPORTED_EXTRA_MODALITIES = (
    EXTRA_MODALITY_AUDIO,
    EXTRA_MODALITY_IMAGE,
    EXTRA_MODALITY_VIDEO,
)
DEFAULT_EXTRA_MODALITY_LIMITS = {
    EXTRA_MODALITY_AUDIO: 50,
    EXTRA_MODALITY_IMAGE: 10,
    EXTRA_MODALITY_VIDEO: 50,
}
DEFAULT_AGENT_MODE = False
DEFAULT_MAX_AGENT_ROUNDS = 12
DEFAULT_MAX_AGENT_TOOL_CALLS = 40
DEFAULT_AGENT_APPROVAL_MODE = "confirm"
AGENT_APPROVAL_CONFIRM = "confirm"
AGENT_APPROVAL_APPROVE = "approve"
AGENT_APPROVAL_FULL = "full"
DEFAULT_AGENT_PLAN_ENABLE = True
DEFAULT_AGENT_TEAM_ENABLE = False
DEFAULT_SKILLS_ENABLE = True
DEFAULT_SKILLS_SOURCE_APP = True
DEFAULT_SKILLS_SOURCE_WORKSPACE = False
DEFAULT_SKILLS_AUTO_CATALOG = True
DEFAULT_COMPACTION_ENABLE = True
DEFAULT_CONTEXT_WINDOW_TOKENS = 128000
AUTO_MODEL_SELECTION = "auto"
DEFAULT_COMPACTION_COMPACT_MODEL = AUTO_MODEL_SELECTION
DEFAULT_MEMORY_MODEL = AUTO_MODEL_SELECTION
DEFAULT_RENDER_MARKDOWN = True
AGENT_APPROVAL_MODES = {
    AGENT_APPROVAL_CONFIRM,
    AGENT_APPROVAL_APPROVE,
    AGENT_APPROVAL_FULL,
}
REASONING_EFFORT_VALUES = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
REASONING_EFFORTS_BY_API = {
    API_TYPE_OPENAI: ("low", "medium", "high", "xhigh", "max"),
    API_TYPE_ANTHROPIC: ("low", "medium", "high", "xhigh", "max"),
    API_TYPE_GLM: ("low", "medium", "high", "xhigh", "max"),
    API_TYPE_GEMINI: ("minimal", "low", "medium", "high"),
    API_TYPE_OLLAMA: ("low", "medium", "high"),
}
SUPPORTED_API_TYPES = {
    API_TYPE_GLM,
    API_TYPE_ANTHROPIC,
    API_TYPE_OPENAI,
    API_TYPE_GEMINI,
    API_TYPE_OLLAMA,
}
MODEL_FIELD_KEYS = {
    "api_type",
    "base_url",
    "model",
    "api_key",
    "max_tokens",
    "temperature",
    "stream_mode",
    "thinking_mode",
    "reasoning_effort",
    "extra_modalities",
    "multimodal_limit",
    "context_window_tokens",
}
GLOBAL_FIELD_KEYS = {
    "current_model",
    "max_agent_rounds",
    "max_agent_tool_calls",
    "file_inline_chars",
    "agent_approval_mode",
    "agent_plan_enable",
    "agent_team_enable",
    "skills_enable",
    "skills_source_app",
    "skills_source_workspace",
    "skills_auto_catalog",
    "compaction_enable",
    "compaction_compact_model",
    "memory_model",
    "render_markdown",
    "language",
    "web_search_enable",
    "web_search_provider",
    "web_search_api_key",
    "web_search_max_results",
    "web_search_depth",
    "web_search_topic",
}


@dataclass
class ModelConfig:
    provider: str = DEFAULT_PROVIDER
    profile_name: str = DEFAULT_MODEL_ALIAS
    api_type: str = DEFAULT_API_TYPE
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    stream_mode: bool = DEFAULT_STREAM_MODE
    thinking_mode: bool = DEFAULT_THINKING_MODE
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    extra_modalities: dict[str, int] = field(default_factory=dict)
    multimodal_limit: int | None = None
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS

    def to_dict(self):
        data = {
            "api_type": self.api_type,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream_mode": self.stream_mode,
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "extra_modalities": dict(self.extra_modalities),
            "context_window_tokens": self.context_window_tokens,
        }
        if self.api_type == API_TYPE_GLM:
            data.pop("base_url", None)
        if self.extra_modalities:
            data["multimodal_limit"] = self.multimodal_limit
        return data


@dataclass
class AppConfig:
    current_model: str = ""
    model_list: dict[str, ModelConfig] = field(default_factory=dict)
    max_agent_rounds: int = DEFAULT_MAX_AGENT_ROUNDS
    max_agent_tool_calls: int = DEFAULT_MAX_AGENT_TOOL_CALLS
    file_inline_chars: int = DEFAULT_FILE_INLINE_CHARS
    agent_approval_mode: str = DEFAULT_AGENT_APPROVAL_MODE
    agent_plan_enable: bool = DEFAULT_AGENT_PLAN_ENABLE
    agent_team_enable: bool = DEFAULT_AGENT_TEAM_ENABLE
    skills_enable: bool = DEFAULT_SKILLS_ENABLE
    skills_source_app: bool = DEFAULT_SKILLS_SOURCE_APP
    skills_source_workspace: bool = DEFAULT_SKILLS_SOURCE_WORKSPACE
    skills_auto_catalog: bool = DEFAULT_SKILLS_AUTO_CATALOG
    compaction_enable: bool = DEFAULT_COMPACTION_ENABLE
    compaction_compact_model: str = DEFAULT_COMPACTION_COMPACT_MODEL
    memory_model: str = DEFAULT_MEMORY_MODEL
    render_markdown: bool = DEFAULT_RENDER_MARKDOWN
    language: str = DEFAULT_LANGUAGE
    web_search_enable: bool = DEFAULT_WEB_SEARCH_ENABLE
    web_search_provider: str = DEFAULT_WEB_SEARCH_PROVIDER
    web_search_api_key: str = ""
    web_search_max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS
    web_search_depth: str = DEFAULT_WEB_SEARCH_DEPTH
    web_search_topic: str = DEFAULT_WEB_SEARCH_TOPIC

    @property
    def active_model_name(self):
        if self.current_model in self.model_list:
            return self.current_model
        return next(iter(self.model_list.keys()), "")

    @property
    def active_model(self):
        active_name = self.active_model_name
        if active_name and active_name in self.model_list:
            return self.model_list[active_name]
        return _model_defaults()

    @property
    def api_type(self):
        return self.active_model.api_type

    @property
    def base_url(self):
        return self.active_model.base_url

    @property
    def model(self):
        return self.active_model.model

    @property
    def api_key(self):
        return self.active_model.api_key

    @property
    def max_tokens(self):
        return self.active_model.max_tokens

    @property
    def temperature(self):
        return self.active_model.temperature

    @property
    def stream_mode(self):
        return self.active_model.stream_mode

    @property
    def thinking_mode(self):
        return self.active_model.thinking_mode

    @property
    def reasoning_effort(self):
        return self.active_model.reasoning_effort

    @property
    def extra_modalities(self):
        return self.active_model.extra_modalities

    @property
    def context_window_tokens(self):
        return self.active_model.context_window_tokens

    @property
    def active_model_label(self):
        return str(self.active_model.profile_name or "").strip()

    def model_label(self, key):
        profile = self.model_list.get(str(key or ""))
        return str(profile.profile_name or "").strip() if profile else ""

    def model_backend_id(self, key):
        profile = self.model_list.get(str(key or ""))
        return str(profile.model or "").strip() if profile else ""

    def selected_backend_model(self, value):
        if normalize_optional_model_selection(value) == AUTO_MODEL_SELECTION:
            return self.active_model.model
        return self.model_backend_id(value) or self.active_model.model

    def selected_model_label(self, value):
        if normalize_optional_model_selection(value) == AUTO_MODEL_SELECTION:
            return self.active_model_label
        return self.model_label(value) or self.active_model_label

    def _nested_model_list(self):
        nested = {}
        for model in self.model_list.values():
            nested.setdefault(model.provider, {})[model.profile_name] = model.to_dict()
        return nested

    def to_dict(self):
        return {
            "general": {
                "language": self.language,
                "render_markdown": self.render_markdown,
            },
            "model_list": self._nested_model_list(),
            "current_model": model_profile_reference(
                self.model_list.get(self.active_model_name)
            ),
            "agent_mode": {
                "max_rounds": self.max_agent_rounds,
                "max_tool_calls": self.max_agent_tool_calls,
                "file_inline_chars": self.file_inline_chars,
                "approve": self.agent_approval_mode,
                "plan_mode": self.agent_plan_enable,
                "agent_team": {
                    "enable": self.agent_team_enable,
                },
            },
            "skills": {
                "enable": self.skills_enable,
                "sources": {
                    "app": self.skills_source_app,
                    "workspace": self.skills_source_workspace,
                },
                "auto_catalog": self.skills_auto_catalog,
            },
            "auto_compact": {
                "enable": self.compaction_enable,
                "compact_model": _optional_model_reference(
                    self.compaction_compact_model, self.model_list
                ),
            },
            "memory_system": {
                "memory_model": _optional_model_reference(
                    self.memory_model, self.model_list
                ),
            },
            "web_search": {
                "enable": self.web_search_enable,
                "provider": self.web_search_provider,
                "api_key": self.web_search_api_key,
                "max_results": self.web_search_max_results,
                "search_depth": self.web_search_depth,
                "topic": self.web_search_topic,
            },
        }

    def to_flat_dict(self):
        values = {
            "current_model": self.active_model_name,
            "max_agent_rounds": self.max_agent_rounds,
            "max_agent_tool_calls": self.max_agent_tool_calls,
            "file_inline_chars": self.file_inline_chars,
            "agent_approval_mode": self.agent_approval_mode,
            "agent_plan_enable": self.agent_plan_enable,
            "agent_team_enable": self.agent_team_enable,
            "skills_enable": self.skills_enable,
            "skills_source_app": self.skills_source_app,
            "skills_source_workspace": self.skills_source_workspace,
            "skills_auto_catalog": self.skills_auto_catalog,
            "compaction_enable": self.compaction_enable,
            "compaction_compact_model": self.compaction_compact_model,
            "memory_model": self.memory_model,
            "render_markdown": self.render_markdown,
            "language": self.language,
            "web_search_enable": self.web_search_enable,
            "web_search_provider": self.web_search_provider,
            "web_search_api_key": self.web_search_api_key,
            "web_search_max_results": self.web_search_max_results,
            "web_search_depth": self.web_search_depth,
            "web_search_topic": self.web_search_topic,
        }
        values.update(self.active_model.to_dict())
        return values


def normalize_api_type(api_type):
    return str(api_type or DEFAULT_API_TYPE).strip().lower()


def normalize_provider(provider):
    normalized = str(provider or "").strip()
    if not normalized:
        raise ValueError("Provider cannot be empty.")
    return normalized


def model_profile_key(provider, model_name):
    provider_name = str(provider or "").strip()
    profile_name = str(model_name or "").strip()
    if not provider_name or not profile_name:
        return ""
    return json.dumps([provider_name, profile_name], ensure_ascii=False, separators=(",", ":"))


def model_profile_reference(model_config):
    if model_config is None:
        return None
    return {
        "provider": str(model_config.provider or "").strip(),
        "model_name": str(model_config.profile_name or "").strip(),
    }


def _model_reference_key(value, model_list):
    if not isinstance(value, dict):
        return ""
    candidate = model_profile_key(value.get("provider"), value.get("model_name"))
    return candidate if candidate in model_list else ""


def _runtime_model_key(value, model_list):
    candidate = str(value or "").strip()
    if candidate in model_list:
        return candidate
    return _model_reference_key(value, model_list)


def _optional_model_reference(value, model_list):
    if normalize_optional_model_selection(value) == AUTO_MODEL_SELECTION:
        return AUTO_MODEL_SELECTION
    key = _runtime_model_key(value, model_list)
    if not key:
        raise ValueError(f"Unknown model profile: {value}")
    return model_profile_reference(model_list[key])


def _config_optional_model_key(value, model_list, field_name):
    if value is None or (
        isinstance(value, str) and value.strip().lower() == AUTO_MODEL_SELECTION
    ):
        return AUTO_MODEL_SELECTION
    key = _model_reference_key(value, model_list)
    if not key:
        raise ValueError(
            f"{field_name} must be auto or contain provider and model_name "
            "for an existing model."
        )
    return key


def requires_api_key(api_type):
    return normalize_api_type(api_type) != API_TYPE_OLLAMA


def _normalize_base_url(api_type, base_url):
    api_type = normalize_api_type(api_type)
    if api_type == API_TYPE_GLM:
        return ""
    if api_type == API_TYPE_GEMINI:
        return str(base_url or "").strip() or GEMINI_OPENAI_BASE_URL
    return str(base_url or "").strip()


def normalize_optional_model_selection(value):
    if isinstance(value, dict):
        provider = str(value.get("provider") or "").strip()
        model_name = str(value.get("model_name") or "").strip()
        return model_profile_key(provider, model_name) or AUTO_MODEL_SELECTION
    normalized = str(value or "").strip()
    if not normalized:
        return AUTO_MODEL_SELECTION
    if normalized.lower() in {"none", AUTO_MODEL_SELECTION}:
        return AUTO_MODEL_SELECTION
    return normalized


def normalize_extra_modalities(value):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.lower() == "none":
            return ()
        tokens = re.split(r"[\s,，]+", stripped)
    elif isinstance(value, dict):
        tokens = [str(item or "").strip() for item in value]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(item or "").strip() for item in value]
    elif value is None:
        tokens = []
    else:
        tokens = [str(value or "").strip()]
    normalized = {
        token.lower()
        for token in tokens
        if str(token or "").strip().lower() in SUPPORTED_EXTRA_MODALITIES
    }
    return tuple(
        modality for modality in SUPPORTED_EXTRA_MODALITIES if modality in normalized
    )


def parse_extra_modalities_input(value, *, required=False):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            if required:
                raise ValueError(
                    "Extra modalities is required. Use none or a comma-separated "
                    "list of audio, image, video."
                )
            return ()
        if stripped.lower() == "none":
            return ()
        tokens = [token.strip().lower() for token in re.split(r"[\s,，]+", stripped)]
        invalid = [
            token
            for token in tokens
            if token and token not in SUPPORTED_EXTRA_MODALITIES
        ]
        if invalid:
            raise ValueError(
                "Unsupported extra modalities: "
                + ", ".join(invalid)
                + ". Use none or a comma-separated list of audio, image, video."
            )
    return normalize_extra_modalities(value)


def format_extra_modalities(extra_modalities):
    normalized = normalize_extra_modalities(extra_modalities)
    return ", ".join(normalized) if normalized else "none"


def supported_reasoning_efforts(api_type):
    normalized = normalize_api_type(api_type)
    return REASONING_EFFORTS_BY_API.get(
        normalized, REASONING_EFFORTS_BY_API[DEFAULT_API_TYPE]
    )


def normalize_reasoning_effort_for_api(api_type, effort):
    parsed = parse_reasoning_effort(effort)
    if parsed in {"", "none"}:
        return ""
    if parsed in supported_reasoning_efforts(api_type):
        return parsed
    normalized = normalize_api_type(api_type)
    if normalized in {API_TYPE_OPENAI, API_TYPE_ANTHROPIC, API_TYPE_GLM}:
        if parsed == "minimal":
            return "low"
    elif normalized == API_TYPE_GEMINI:
        if parsed in {"xhigh", "max"}:
            return "high"
    elif normalized == API_TYPE_OLLAMA:
        if parsed == "minimal":
            return "low"
        if parsed in {"xhigh", "max"}:
            return "high"
    supported = supported_reasoning_efforts(normalized)
    return supported[-1] if supported else ""


def _parse_positive_integer(value, label):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an integer.") from error
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return parsed


def parse_max_tokens(value):
    return _parse_positive_integer(value, "Max tokens")


def parse_context_window_tokens(value):
    return _parse_positive_integer(value, "Model context window tokens")


def parse_file_inline_chars(value):
    return _parse_positive_integer(value, "File inline chars")


def parse_extra_modalities_config(value):
    if not isinstance(value, dict):
        raise ValueError(
            "Extra modalities must be an object mapping modality names to limits."
        )
    unknown = sorted(
        str(key) for key in value if str(key) not in SUPPORTED_EXTRA_MODALITIES
    )
    if unknown:
        raise ValueError(
            "Unsupported extra modalities: " + ", ".join(unknown)
        )
    return {
        modality: _parse_positive_integer(
            value[modality], f"{modality.title()} limit (MB)"
        )
        for modality in SUPPORTED_EXTRA_MODALITIES
        if modality in value
    }


def parse_multimodal_limit(value):
    return _parse_positive_integer(value, "Multimodal total limit (MB)")


def parse_agent_rounds(value):
    return _parse_positive_integer(value, "Agent max rounds")


def parse_agent_tool_calls(value):
    return _parse_positive_integer(value, "Agent max tool calls")


def parse_web_search_max_results(value):
    parsed = _parse_positive_integer(value, "Web search max results")
    if parsed > 20:
        raise ValueError("Web search max results must be between 1 and 20.")
    return parsed


def parse_web_search_provider(value):
    provider = str(value or DEFAULT_WEB_SEARCH_PROVIDER).strip().lower()
    if provider not in WEB_SEARCH_PROVIDERS:
        raise ValueError("Web search provider must be tavily.")
    return provider


def parse_web_search_depth(value):
    depth = str(value or DEFAULT_WEB_SEARCH_DEPTH).strip().lower()
    if depth not in TAVILY_SEARCH_DEPTHS:
        raise ValueError(
            "Web search depth must be basic, fast, ultra-fast, or advanced."
        )
    return depth


def parse_web_search_topic(value):
    topic = str(value or DEFAULT_WEB_SEARCH_TOPIC).strip().lower()
    if topic not in TAVILY_TOPICS:
        raise ValueError("Web search topic must be general, news, or finance.")
    return topic


def parse_language(value):
    if value is None:
        return DEFAULT_LANGUAGE
    if isinstance(value, bool):
        raise ValueError(
            "Language must be one of: " + ", ".join(SUPPORTED_LANGUAGES) + "."
        )
    return normalize_language(value)


def parse_agent_approval_mode(value):
    if value is None:
        mode = DEFAULT_AGENT_APPROVAL_MODE
    elif isinstance(value, bool):
        raise ValueError("Agent approval mode must be confirm, approve, or full.")
    else:
        mode = str(value).strip().lower() or DEFAULT_AGENT_APPROVAL_MODE
    if mode not in AGENT_APPROVAL_MODES:
        raise ValueError("Agent approval mode must be confirm, approve, or full.")
    return mode


def parse_reasoning_effort(value):
    if value is None:
        return DEFAULT_REASONING_EFFORT
    if isinstance(value, bool):
        return "medium" if value else "none"
    effort = str(value or "").strip().lower()
    if effort in {"", "default", "auto"}:
        return DEFAULT_REASONING_EFFORT
    if effort in {"false", "0", "no", "off", "disable", "disabled"}:
        return "none"
    if effort in {"true", "ture", "1", "yes", "on"}:
        return "medium"
    if effort not in REASONING_EFFORT_VALUES:
        raise ValueError(
            "Reasoning effort must be empty, none, minimal, low, medium, high, xhigh, or max."
        )
    return effort


def parse_temperature(value):
    try:
        temperature = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError("Temperature must be a number.") from error
    if temperature < 0 or temperature > 2:
        raise ValueError("Temperature must be between 0 and 2.")
    return temperature


def _parse_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "ture", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _model_defaults():
    return ModelConfig()


def _sanitize_model_config(data, *, provider, profile_name):
    data = dict(data or {})
    if "provider" in data or "profile_name" in data:
        raise ValueError(
            "Provider and model name must be declared by model_list.<provider>.<model_name>."
        )
    provider = normalize_provider(provider)
    profile_name = str(profile_name or "").strip()
    if not profile_name:
        raise ValueError("Model profile name cannot be empty.")
    api_type = normalize_api_type(data.get("api_type", DEFAULT_API_TYPE))
    if api_type not in SUPPORTED_API_TYPES:
        api_type = DEFAULT_API_TYPE
    base_url = _normalize_base_url(api_type, data.get("base_url", DEFAULT_BASE_URL))
    model_name = str(data.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        max_tokens = parse_max_tokens(data.get("max_tokens", DEFAULT_MAX_TOKENS))
    except ValueError:
        max_tokens = DEFAULT_MAX_TOKENS
    try:
        temperature = parse_temperature(data.get("temperature", DEFAULT_TEMPERATURE))
    except ValueError:
        temperature = DEFAULT_TEMPERATURE
    try:
        context_window_tokens = parse_context_window_tokens(
            data.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)
        )
    except ValueError:
        context_window_tokens = DEFAULT_CONTEXT_WINDOW_TOKENS
    try:
        reasoning_effort = parse_reasoning_effort(
            data.get("reasoning_effort", DEFAULT_REASONING_EFFORT)
        )
    except ValueError:
        reasoning_effort = DEFAULT_REASONING_EFFORT
    thinking_mode = _parse_bool(data.get("thinking_mode"), DEFAULT_THINKING_MODE)
    if reasoning_effort:
        reasoning_effort = normalize_reasoning_effort_for_api(
            api_type, reasoning_effort
        )
    if "multimodal_limits" in data:
        raise ValueError(
            "Model config does not support multimodal_limits. "
            "Put per-modality limits inside extra_modalities."
        )
    if "extra_modalities" not in data:
        raise ValueError("Model config requires extra_modalities.")
    extra_modalities = parse_extra_modalities_config(data.get("extra_modalities"))
    if extra_modalities:
        if "multimodal_limit" not in data:
            raise ValueError(
                "Model config requires multimodal_limit when extra modalities are enabled."
            )
        multimodal_limit = parse_multimodal_limit(data.get("multimodal_limit"))
    else:
        if "multimodal_limit" in data:
            raise ValueError(
                "Model config must omit multimodal_limit when extra_modalities is empty."
            )
        multimodal_limit = None
    return ModelConfig(
        provider=provider,
        profile_name=profile_name,
        api_type=api_type,
        base_url=base_url,
        model=model_name,
        api_key=str(data.get("api_key") or "").strip(),
        max_tokens=max_tokens,
        temperature=temperature,
        stream_mode=_parse_bool(data.get("stream_mode"), DEFAULT_STREAM_MODE),
        thinking_mode=thinking_mode,
        reasoning_effort=reasoning_effort,
        extra_modalities=extra_modalities,
        multimodal_limit=multimodal_limit,
        context_window_tokens=context_window_tokens,
    )


def _default_config():
    return AppConfig()


def _sanitize_config(data):
    data = dict(data or {})
    raw_models = data.get("model_list", {})
    if not isinstance(raw_models, dict):
        raise ValueError("model_list must be an object grouped by Provider.")
    model_list = {}
    for provider, provider_models in raw_models.items():
        provider = normalize_provider(provider)
        if not isinstance(provider_models, dict):
            raise ValueError(f"model_list.{provider} must be an object.")
        for profile_name, profile_data in provider_models.items():
            profile_name = str(profile_name or "").strip()
            if not profile_name:
                raise ValueError(f"model_list.{provider} contains an empty model name.")
            if not isinstance(profile_data, dict):
                raise ValueError(
                    f"model_list.{provider}.{profile_name} must be an object."
                )
            profile = _sanitize_model_config(
                profile_data,
                provider=provider,
                profile_name=profile_name,
            )
            key = model_profile_key(provider, profile_name)
            model_list[key] = profile

    raw_current_model = data.get("current_model")
    current_model = _model_reference_key(raw_current_model, model_list)
    if raw_current_model is not None and model_list and not current_model:
        raise ValueError(
            "current_model must contain provider and model_name for an existing model."
        )
    if not current_model:
        current_model = next(iter(model_list.keys()), "")

    agent_config = data.get("agent_mode", {})
    if not isinstance(agent_config, dict):
        agent_config = {}
    agent_team = agent_config.get("agent_team", {})
    if not isinstance(agent_team, dict):
        agent_team = {}
    skills_config = data.get("skills", {})
    if not isinstance(skills_config, dict):
        skills_config = {}
    skill_sources = skills_config.get("sources", {})
    if not isinstance(skill_sources, dict):
        skill_sources = {}
    compaction_config = data.get("auto_compact", {})
    if not isinstance(compaction_config, dict):
        compaction_config = {}
    memory_config = data.get("memory_system", {})
    if not isinstance(memory_config, dict):
        memory_config = {}
    general_config = data.get("general", {})
    if not isinstance(general_config, dict):
        general_config = {}
    web_search = data.get("web_search", {})
    if not isinstance(web_search, dict):
        web_search = {}

    try:
        max_agent_rounds = parse_agent_rounds(
            agent_config.get("max_rounds", DEFAULT_MAX_AGENT_ROUNDS)
        )
    except ValueError:
        max_agent_rounds = DEFAULT_MAX_AGENT_ROUNDS
    try:
        max_agent_tool_calls = parse_agent_tool_calls(
            agent_config.get("max_tool_calls", DEFAULT_MAX_AGENT_TOOL_CALLS)
        )
    except ValueError:
        max_agent_tool_calls = DEFAULT_MAX_AGENT_TOOL_CALLS
    try:
        file_inline_chars = parse_file_inline_chars(
            agent_config.get("file_inline_chars", DEFAULT_FILE_INLINE_CHARS)
        )
    except ValueError:
        file_inline_chars = DEFAULT_FILE_INLINE_CHARS
    try:
        agent_approval_mode = parse_agent_approval_mode(
            agent_config.get("approve", DEFAULT_AGENT_APPROVAL_MODE)
        )
    except ValueError:
        agent_approval_mode = DEFAULT_AGENT_APPROVAL_MODE
    try:
        web_search_provider = parse_web_search_provider(
            web_search.get("provider", DEFAULT_WEB_SEARCH_PROVIDER)
        )
    except ValueError:
        web_search_provider = DEFAULT_WEB_SEARCH_PROVIDER
    try:
        web_search_max_results = parse_web_search_max_results(
            web_search.get("max_results", DEFAULT_WEB_SEARCH_MAX_RESULTS)
        )
    except ValueError:
        web_search_max_results = DEFAULT_WEB_SEARCH_MAX_RESULTS
    try:
        web_search_depth = parse_web_search_depth(
            web_search.get("search_depth", DEFAULT_WEB_SEARCH_DEPTH)
        )
    except ValueError:
        web_search_depth = DEFAULT_WEB_SEARCH_DEPTH
    try:
        web_search_topic = parse_web_search_topic(
            web_search.get("topic", DEFAULT_WEB_SEARCH_TOPIC)
        )
    except ValueError:
        web_search_topic = DEFAULT_WEB_SEARCH_TOPIC

    return AppConfig(
        current_model=current_model,
        model_list=model_list,
        max_agent_rounds=max_agent_rounds,
        max_agent_tool_calls=max_agent_tool_calls,
        file_inline_chars=file_inline_chars,
        agent_approval_mode=agent_approval_mode,
        agent_plan_enable=_parse_bool(
            agent_config.get("plan_mode"), DEFAULT_AGENT_PLAN_ENABLE
        ),
        agent_team_enable=_parse_bool(
            agent_team.get("enable"), DEFAULT_AGENT_TEAM_ENABLE
        ),
        skills_enable=_parse_bool(skills_config.get("enable"), DEFAULT_SKILLS_ENABLE),
        skills_source_app=_parse_bool(
            skill_sources.get("app"), DEFAULT_SKILLS_SOURCE_APP
        ),
        skills_source_workspace=_parse_bool(
            skill_sources.get("workspace"), DEFAULT_SKILLS_SOURCE_WORKSPACE
        ),
        skills_auto_catalog=_parse_bool(
            skills_config.get("auto_catalog"), DEFAULT_SKILLS_AUTO_CATALOG
        ),
        compaction_enable=_parse_bool(
            compaction_config.get("enable"), DEFAULT_COMPACTION_ENABLE
        ),
        compaction_compact_model=_config_optional_model_key(
            compaction_config.get("compact_model"),
            model_list,
            "auto_compact.compact_model",
        ),
        memory_model=_config_optional_model_key(
            memory_config.get("memory_model"),
            model_list,
            "memory_system.memory_model",
        ),
        render_markdown=_parse_bool(
            general_config.get("render_markdown"), DEFAULT_RENDER_MARKDOWN
        ),
        language=normalize_language(general_config.get("language")),
        web_search_enable=_parse_bool(
            web_search.get("enable"), DEFAULT_WEB_SEARCH_ENABLE
        ),
        web_search_provider=web_search_provider,
        web_search_api_key=str(web_search.get("api_key") or "").strip(),
        web_search_max_results=web_search_max_results,
        web_search_depth=web_search_depth,
        web_search_topic=web_search_topic,
    )


def _persist_config(config):
    atomic_write_text(
        CONFIG_FILE,
        json.dumps(config.to_dict(), indent=4, ensure_ascii=False) + "\n",
    )


def _load_existing_config():
    path = Path(CONFIG_FILE)
    if not path.exists():
        config = _default_config()
        _persist_config(config)
        return config
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = _default_config()
        _persist_config(config)
        return config
    return _sanitize_config(raw)


def load_config():
    return _load_existing_config()


def reload_config():
    return _load_existing_config()


def update_config():
    return _load_existing_config()


def save_config_field(key, value):
    save_config_fields({key: value})


def save_model_profile_field(name, key, value):
    save_config_fields({key: value}, model_name=name)


def add_model_profile_with_config(name, model_config):
    config = _load_existing_config()
    model_name = str(name or "").strip()
    if not model_name:
        raise ValueError("Model profile name cannot be empty.")
    payload = dict(model_config or {})
    provider = normalize_provider(payload.pop("provider", None))
    key = model_profile_key(provider, model_name)
    if key in config.model_list:
        raise ValueError(f"Model profile already exists: {provider}/{model_name}")

    config.model_list[key] = _sanitize_model_config(
        payload, provider=provider, profile_name=model_name
    )
    config.current_model = key
    _persist_config(_sanitize_config(config.to_dict()))
    return key


def delete_model_profile(name):
    config = _load_existing_config()
    key = _runtime_model_key(name, config.model_list)
    if not key:
        raise ValueError(f"Model profile not found: {name}")
    del config.model_list[key]
    if config.current_model == key:
        config.current_model = next(iter(config.model_list.keys()), "")
    if config.compaction_compact_model == key:
        config.compaction_compact_model = AUTO_MODEL_SELECTION
    if config.memory_model == key:
        config.memory_model = AUTO_MODEL_SELECTION
    _persist_config(_sanitize_config(config.to_dict()))


def rename_model_profile(old_name, new_name):
    config = _load_existing_config()
    old_key = _runtime_model_key(old_name, config.model_list)
    new_profile_name = str(new_name or "").strip()
    if not old_key or not new_profile_name:
        raise ValueError("Model profile name cannot be empty.")
    profile = config.model_list[old_key]
    new_key = model_profile_key(profile.provider, new_profile_name)
    if new_key != old_key and new_key in config.model_list:
        raise ValueError(
            f"Model profile already exists: {profile.provider}/{new_profile_name}"
        )
    if new_key == old_key:
        return new_key

    profile.profile_name = new_profile_name
    config.model_list[new_key] = config.model_list.pop(old_key)
    if config.current_model == old_key:
        config.current_model = new_key
    if config.compaction_compact_model == old_key:
        config.compaction_compact_model = new_key
    if config.memory_model == old_key:
        config.memory_model = new_key
    _persist_config(_sanitize_config(config.to_dict()))
    return new_key

def save_config_fields(fields, model_name=None):
    config = _load_existing_config()
    active_name = (
        _runtime_model_key(model_name, config.model_list)
        if model_name is not None
        else config.active_model_name
    )
    if model_name is not None and not active_name:
        raise ValueError(f"Model profile not found: {model_name}")
    active_model = config.model_list.get(active_name)
    for key, value in dict(fields or {}).items():
        if key in MODEL_FIELD_KEYS:
            if active_model is None:
                raise ValueError("No model profile selected.")
            if key == "api_type":
                active_model.api_type = normalize_api_type(value)
                active_model.base_url = _normalize_base_url(
                    active_model.api_type, active_model.base_url
                )
                active_model.reasoning_effort = normalize_reasoning_effort_for_api(
                    active_model.api_type, active_model.reasoning_effort
                )
            elif key == "base_url":
                active_model.base_url = _normalize_base_url(
                    active_model.api_type, value
                )
            elif key == "model":
                active_model.model = str(value or "").strip() or DEFAULT_MODEL
            elif key == "api_key":
                active_model.api_key = str(value or "").strip()
            elif key == "max_tokens":
                active_model.max_tokens = parse_max_tokens(value)
            elif key == "temperature":
                active_model.temperature = parse_temperature(value)
            elif key == "stream_mode":
                active_model.stream_mode = _parse_bool(value, active_model.stream_mode)
            elif key == "thinking_mode":
                active_model.thinking_mode = _parse_bool(
                    value, active_model.thinking_mode
                )
            elif key == "reasoning_effort":
                if value:
                    active_model.reasoning_effort = normalize_reasoning_effort_for_api(
                        active_model.api_type, value
                    )
                else:
                    active_model.reasoning_effort = ""
            elif key == "extra_modalities":
                active_model.extra_modalities = parse_extra_modalities_config(value)
                if active_model.extra_modalities:
                    if active_model.multimodal_limit is None:
                        active_model.multimodal_limit = DEFAULT_MULTIMODAL_LIMIT
                else:
                    active_model.multimodal_limit = None
            elif key == "multimodal_limit":
                if not active_model.extra_modalities:
                    raise ValueError(
                        "Cannot set multimodal_limit without extra modalities."
                    )
                active_model.multimodal_limit = parse_multimodal_limit(value)
            elif key == "context_window_tokens":
                active_model.context_window_tokens = parse_context_window_tokens(value)
            continue

        if key not in GLOBAL_FIELD_KEYS:
            continue

        if key == "current_model":
            model_key = _runtime_model_key(value, config.model_list)
            if not model_key:
                raise ValueError(f"Unknown model profile: {value}")
            config.current_model = model_key
        elif key == "max_agent_rounds":
            config.max_agent_rounds = parse_agent_rounds(value)
        elif key == "max_agent_tool_calls":
            config.max_agent_tool_calls = parse_agent_tool_calls(value)
        elif key == "file_inline_chars":
            config.file_inline_chars = parse_file_inline_chars(value)
        elif key == "agent_approval_mode":
            config.agent_approval_mode = parse_agent_approval_mode(value)
        elif key == "agent_plan_enable":
            config.agent_plan_enable = _parse_bool(value, config.agent_plan_enable)
        elif key == "agent_team_enable":
            config.agent_team_enable = _parse_bool(value, config.agent_team_enable)
        elif key == "skills_enable":
            config.skills_enable = _parse_bool(value, config.skills_enable)
        elif key == "skills_source_app":
            config.skills_source_app = _parse_bool(value, config.skills_source_app)
        elif key == "skills_source_workspace":
            config.skills_source_workspace = _parse_bool(
                value, config.skills_source_workspace
            )
        elif key == "skills_auto_catalog":
            config.skills_auto_catalog = _parse_bool(value, config.skills_auto_catalog)
        elif key == "compaction_enable":
            config.compaction_enable = _parse_bool(value, config.compaction_enable)
        elif key == "compaction_compact_model":
            normalized = normalize_optional_model_selection(value)
            config.compaction_compact_model = (
                AUTO_MODEL_SELECTION
                if normalized == AUTO_MODEL_SELECTION
                else _runtime_model_key(value, config.model_list)
            )
            if not config.compaction_compact_model:
                raise ValueError(f"Unknown model profile: {value}")
        elif key == "memory_model":
            normalized = normalize_optional_model_selection(value)
            config.memory_model = (
                AUTO_MODEL_SELECTION
                if normalized == AUTO_MODEL_SELECTION
                else _runtime_model_key(value, config.model_list)
            )
            if not config.memory_model:
                raise ValueError(f"Unknown model profile: {value}")
        elif key == "render_markdown":
            config.render_markdown = _parse_bool(value, config.render_markdown)
        elif key == "language":
            config.language = parse_language(value)
        elif key == "web_search_enable":
            config.web_search_enable = _parse_bool(value, config.web_search_enable)
        elif key == "web_search_provider":
            config.web_search_provider = parse_web_search_provider(value)
        elif key == "web_search_api_key":
            config.web_search_api_key = str(value or "").strip()
        elif key == "web_search_max_results":
            config.web_search_max_results = parse_web_search_max_results(value)
        elif key == "web_search_depth":
            config.web_search_depth = parse_web_search_depth(value)
        elif key == "web_search_topic":
            config.web_search_topic = parse_web_search_topic(value)

    _persist_config(_sanitize_config(config.to_dict()))
