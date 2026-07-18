import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from search import (
    DEFAULT_WEB_SEARCH_DEPTH,
    DEFAULT_WEB_SEARCH_ENABLE,
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_PROVIDER,
    DEFAULT_WEB_SEARCH_TOPIC,
    TAVILY_SEARCH_DEPTHS,
    TAVILY_TOPICS,
    WEB_SEARCH_PROVIDERS,
)

CONFIG_FILE = "config.json"
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
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_STREAM_MODE = False
DEFAULT_THINKING_MODE = False
DEFAULT_REASONING_EFFORT = ""
EXTRA_MODALITY_AUDIO = "audio"
EXTRA_MODALITY_IMAGE = "image"
EXTRA_MODALITY_VIDEO = "video"
SUPPORTED_EXTRA_MODALITIES = (
    EXTRA_MODALITY_AUDIO,
    EXTRA_MODALITY_IMAGE,
    EXTRA_MODALITY_VIDEO,
)
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
DEFAULT_SKILLS_MAX_CHARS = 12000
DEFAULT_COMPACTION_ENABLE = True
DEFAULT_CONTEXT_WINDOW_TOKENS = 128000
DEFAULT_COMPACTION_TRIGGER_RATIO = 0.75
DEFAULT_COMPACTION_KEEP_RECENT_MESSAGES = 12
AUTO_MODEL_SELECTION = "auto"
DEFAULT_COMPACTION_COMPACT_MODEL = AUTO_MODEL_SELECTION
DEFAULT_MEMORY_MODEL = AUTO_MODEL_SELECTION
DEFAULT_DEBUG = False
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
    API_TYPE_OLLAMA: ("low", "medium", "high", "max"),
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
    "context_window_tokens",
}
GLOBAL_FIELD_KEYS = {
    "current_model",
    "max_agent_rounds",
    "max_agent_tool_calls",
    "agent_approval_mode",
    "agent_plan_enable",
    "agent_team_enable",
    "skills_enable",
    "skills_source_app",
    "skills_source_workspace",
    "skills_auto_catalog",
    "skills_max_chars",
    "compaction_enable",
    "compaction_trigger_ratio",
    "compaction_keep_recent_messages",
    "compaction_compact_model",
    "memory_model",
    "render_markdown",
    "debug",
    "web_search_enable",
    "web_search_provider",
    "web_search_api_key",
    "web_search_max_results",
    "web_search_depth",
    "web_search_topic",
}


@dataclass
class ModelConfig:
    api_type: str = DEFAULT_API_TYPE
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    stream_mode: bool = DEFAULT_STREAM_MODE
    thinking_mode: bool = DEFAULT_THINKING_MODE
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    extra_modalities: tuple[str, ...] = field(default_factory=tuple)
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS

    def to_dict(self):
        return {
            "api_type": self.api_type,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream_mode": self.stream_mode,
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "extra_modalities": list(self.extra_modalities),
            "context_window_tokens": self.context_window_tokens,
        }


@dataclass
class AppConfig:
    current_model: str = ""
    model_list: dict[str, ModelConfig] = field(default_factory=dict)
    max_agent_rounds: int = DEFAULT_MAX_AGENT_ROUNDS
    max_agent_tool_calls: int = DEFAULT_MAX_AGENT_TOOL_CALLS
    agent_approval_mode: str = DEFAULT_AGENT_APPROVAL_MODE
    agent_plan_enable: bool = DEFAULT_AGENT_PLAN_ENABLE
    agent_team_enable: bool = DEFAULT_AGENT_TEAM_ENABLE
    skills_enable: bool = DEFAULT_SKILLS_ENABLE
    skills_source_app: bool = DEFAULT_SKILLS_SOURCE_APP
    skills_source_workspace: bool = DEFAULT_SKILLS_SOURCE_WORKSPACE
    skills_auto_catalog: bool = DEFAULT_SKILLS_AUTO_CATALOG
    skills_max_chars: int = DEFAULT_SKILLS_MAX_CHARS
    compaction_enable: bool = DEFAULT_COMPACTION_ENABLE
    compaction_trigger_ratio: float = DEFAULT_COMPACTION_TRIGGER_RATIO
    compaction_keep_recent_messages: int = DEFAULT_COMPACTION_KEEP_RECENT_MESSAGES
    compaction_compact_model: str = DEFAULT_COMPACTION_COMPACT_MODEL
    memory_model: str = DEFAULT_MEMORY_MODEL
    render_markdown: bool = DEFAULT_RENDER_MARKDOWN
    debug: bool = DEFAULT_DEBUG
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

    def to_dict(self):
        return {
            "general": {
                "render_markdown": self.render_markdown,
            },
            "model_list": {
                name: model.to_dict() for name, model in self.model_list.items()
            },
            "current_model": self.active_model_name,
            "agent_mode": {
                "max_rounds": self.max_agent_rounds,
                "max_tool_calls": self.max_agent_tool_calls,
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
                "max_skill_chars": self.skills_max_chars,
            },
            "auto_compact": {
                "enable": self.compaction_enable,
                "trigger_ratio": self.compaction_trigger_ratio,
                "keep_recent_messages": self.compaction_keep_recent_messages,
                "compact_model": self.compaction_compact_model,
            },
            "memory_system": {
                "memory_model": self.memory_model,
            },
            "web_search": {
                "enable": self.web_search_enable,
                "provider": self.web_search_provider,
                "api_key": self.web_search_api_key,
                "max_results": self.web_search_max_results,
                "search_depth": self.web_search_depth,
                "topic": self.web_search_topic,
            },
            **({"debug": True} if self.debug else {}),
        }

    def to_flat_dict(self):
        values = {
            "current_model": self.active_model_name,
            "max_agent_rounds": self.max_agent_rounds,
            "max_agent_tool_calls": self.max_agent_tool_calls,
            "agent_approval_mode": self.agent_approval_mode,
            "agent_plan_enable": self.agent_plan_enable,
            "agent_team_enable": self.agent_team_enable,
            "skills_enable": self.skills_enable,
            "skills_source_app": self.skills_source_app,
            "skills_source_workspace": self.skills_source_workspace,
            "skills_auto_catalog": self.skills_auto_catalog,
            "skills_max_chars": self.skills_max_chars,
            "compaction_enable": self.compaction_enable,
            "compaction_trigger_ratio": self.compaction_trigger_ratio,
            "compaction_keep_recent_messages": self.compaction_keep_recent_messages,
            "compaction_compact_model": self.compaction_compact_model,
            "memory_model": self.memory_model,
            "render_markdown": self.render_markdown,
            "debug": self.debug,
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
        if parsed == "xhigh":
            return "max"
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


def parse_skill_max_chars(value):
    parsed = _parse_positive_integer(value, "Skill max chars")
    if parsed < 1000:
        raise ValueError("Skill max chars must be at least 1000.")
    return parsed


def parse_agent_rounds(value):
    return _parse_positive_integer(value, "Agent max rounds")


def parse_agent_tool_calls(value):
    return _parse_positive_integer(value, "Agent max tool calls")


def parse_compaction_trigger_ratio(value):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError("Auto compact trigger ratio must be a number.") from error
    if parsed <= 0 or parsed > 1:
        raise ValueError(
            "Auto compact trigger ratio must be greater than 0 and at most 1."
        )
    return parsed


def parse_compaction_keep_recent_messages(value):
    return _parse_positive_integer(value, "Auto compact keep recent messages")


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
    if temperature < 0 or temperature > 1:
        raise ValueError("Temperature must be between 0 and 1.")
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


def _sanitize_model_config(data):
    data = dict(data or {})
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
    if "extra_modalities" not in data:
        raise ValueError("Model config requires extra_modalities.")
    raw_extra_modalities = data.get("extra_modalities")
    if isinstance(raw_extra_modalities, str):
        extra_modalities = parse_extra_modalities_input(
            raw_extra_modalities,
            required=True,
        )
    else:
        extra_modalities = normalize_extra_modalities(raw_extra_modalities)
    return ModelConfig(
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
        context_window_tokens=context_window_tokens,
    )


def _default_config():
    return AppConfig()


def _sanitize_config(data):
    data = dict(data or {})
    raw_models = data.get("model_list", {})
    model_list = {}
    if isinstance(raw_models, dict):
        for name, model_data in raw_models.items():
            model_name = str(name or "").strip()
            if not model_name:
                continue
            model_list[model_name] = _sanitize_model_config(model_data)
    current_model = str(data.get("current_model") or "").strip()
    if current_model not in model_list:
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
        agent_approval_mode = parse_agent_approval_mode(
            agent_config.get("approve", DEFAULT_AGENT_APPROVAL_MODE)
        )
    except ValueError:
        agent_approval_mode = DEFAULT_AGENT_APPROVAL_MODE
    try:
        skills_max_chars = parse_skill_max_chars(
            skills_config.get("max_skill_chars", DEFAULT_SKILLS_MAX_CHARS)
        )
    except ValueError:
        skills_max_chars = DEFAULT_SKILLS_MAX_CHARS
    try:
        compaction_trigger_ratio = parse_compaction_trigger_ratio(
            compaction_config.get("trigger_ratio", DEFAULT_COMPACTION_TRIGGER_RATIO)
        )
    except ValueError:
        compaction_trigger_ratio = DEFAULT_COMPACTION_TRIGGER_RATIO
    try:
        compaction_keep_recent_messages = parse_compaction_keep_recent_messages(
            compaction_config.get(
                "keep_recent_messages", DEFAULT_COMPACTION_KEEP_RECENT_MESSAGES
            )
        )
    except ValueError:
        compaction_keep_recent_messages = DEFAULT_COMPACTION_KEEP_RECENT_MESSAGES
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
        skills_max_chars=skills_max_chars,
        compaction_enable=_parse_bool(
            compaction_config.get("enable"), DEFAULT_COMPACTION_ENABLE
        ),
        compaction_trigger_ratio=compaction_trigger_ratio,
        compaction_keep_recent_messages=compaction_keep_recent_messages,
        compaction_compact_model=normalize_optional_model_selection(
            compaction_config.get("compact_model")
        ),
        memory_model=normalize_optional_model_selection(
            memory_config.get("memory_model")
        ),
        render_markdown=_parse_bool(
            general_config.get("render_markdown"), DEFAULT_RENDER_MARKDOWN
        ),
        debug=_parse_bool(data.get("debug"), DEFAULT_DEBUG),
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
    path = Path(CONFIG_FILE)
    path.write_text(
        json.dumps(config.to_dict(), indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
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


def add_model_profile(name, source_name=""):
    config = _load_existing_config()
    model_name = str(name or "").strip()
    if not model_name:
        raise ValueError("Model profile name cannot be empty.")
    if model_name in config.model_list:
        raise ValueError(f"Model profile already exists: {model_name}")

    source_key = str(source_name or "").strip()
    if source_key and source_key in config.model_list:
        source_model = config.model_list[source_key]
    else:
        source_model = config.active_model

    config.model_list[model_name] = _sanitize_model_config(source_model.to_dict())
    config.current_model = model_name
    _persist_config(_sanitize_config(config.to_dict()))
    return model_name


def add_model_profile_with_config(name, model_config):
    config = _load_existing_config()
    model_name = str(name or "").strip()
    if not model_name:
        raise ValueError("Model profile name cannot be empty.")
    if model_name in config.model_list:
        raise ValueError(f"Model profile already exists: {model_name}")

    config.model_list[model_name] = _sanitize_model_config(dict(model_config or {}))
    config.current_model = model_name
    _persist_config(_sanitize_config(config.to_dict()))
    return model_name


def delete_model_profile(name):
    config = _load_existing_config()
    model_name = str(name or "").strip()
    if not model_name:
        raise ValueError("Model profile name cannot be empty.")
    if model_name not in config.model_list:
        raise ValueError(f"Model profile not found: {model_name}")
    del config.model_list[model_name]
    if config.current_model == model_name:
        config.current_model = next(iter(config.model_list.keys()), "")
    _persist_config(_sanitize_config(config.to_dict()))


def rename_model_profile(old_name, new_name):
    config = _load_existing_config()
    old_key = str(old_name or "").strip()
    new_key = str(new_name or "").strip()
    if not old_key or not new_key:
        raise ValueError("Model profile name cannot be empty.")
    if old_key not in config.model_list:
        raise ValueError(f"Model profile not found: {old_key}")
    if new_key != old_key and new_key in config.model_list:
        raise ValueError(f"Model profile already exists: {new_key}")

    if new_key == old_key:
        return new_key

    config.model_list[new_key] = config.model_list.pop(old_key)
    if config.current_model == old_key:
        config.current_model = new_key
    _persist_config(_sanitize_config(config.to_dict()))
    return new_key


def save_config_fields(fields):
    config = _load_existing_config()
    active_name = config.active_model_name
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
                if isinstance(value, str):
                    active_model.extra_modalities = parse_extra_modalities_input(
                        value,
                        required=True,
                    )
                else:
                    active_model.extra_modalities = normalize_extra_modalities(value)
            elif key == "context_window_tokens":
                active_model.context_window_tokens = parse_context_window_tokens(value)
            continue

        if key not in GLOBAL_FIELD_KEYS:
            raise ValueError(f"Unknown config key: {key}")

        if key == "current_model":
            value = str(value or "").strip()
            if value not in config.model_list:
                raise ValueError(f"Unknown model profile: {value}")
            config.current_model = value
        elif key == "max_agent_rounds":
            config.max_agent_rounds = parse_agent_rounds(value)
        elif key == "max_agent_tool_calls":
            config.max_agent_tool_calls = parse_agent_tool_calls(value)
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
        elif key == "skills_max_chars":
            config.skills_max_chars = parse_skill_max_chars(value)
        elif key == "compaction_enable":
            config.compaction_enable = _parse_bool(value, config.compaction_enable)
        elif key == "compaction_trigger_ratio":
            config.compaction_trigger_ratio = parse_compaction_trigger_ratio(value)
        elif key == "compaction_keep_recent_messages":
            config.compaction_keep_recent_messages = (
                parse_compaction_keep_recent_messages(value)
            )
        elif key == "compaction_compact_model":
            config.compaction_compact_model = normalize_optional_model_selection(value)
        elif key == "memory_model":
            config.memory_model = normalize_optional_model_selection(value)
        elif key == "render_markdown":
            config.render_markdown = _parse_bool(value, config.render_markdown)
        elif key == "debug":
            config.debug = _parse_bool(value, DEFAULT_DEBUG)
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
