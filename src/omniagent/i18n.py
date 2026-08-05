"""Lightweight UI translation layer.

Plain dictionaries instead of gettext so the app needs no .mo compile step.
Lookups never raise: a missing key falls back to English, then to the key
itself, so an untranslated string degrades to English text instead of
crashing the TUI.

Also hosts the display-width helpers. Chinese glyphs occupy two terminal
cells, so ``len()`` reports half the space a CJK label actually needs. Every
layout calculation must use :func:`display_width` instead.
"""

from __future__ import annotations

from rich.cells import cell_len

LANG_EN = "en"
LANG_ZH = "zh"
SUPPORTED_LANGUAGES = (LANG_EN, LANG_ZH)
DEFAULT_LANGUAGE = LANG_EN

LANGUAGE_LABELS = {
    LANG_EN: "English",
    LANG_ZH: "中文",
}

_current_language = DEFAULT_LANGUAGE


def normalize_language(value) -> str:
    """Coerce any input to a supported language code, defaulting to English."""
    text = str(value or "").strip().lower().replace("_", "-")
    if text in SUPPORTED_LANGUAGES:
        return text
    if text.startswith("zh") or text in {"cn", "chinese", "中文"}:
        return LANG_ZH
    if text.startswith("en") or text == "english":
        return LANG_EN
    return DEFAULT_LANGUAGE


def set_language(value) -> str:
    global _current_language
    _current_language = normalize_language(value)
    return _current_language


def get_language() -> str:
    return _current_language


def language_label(value=None) -> str:
    code = normalize_language(value) if value is not None else _current_language
    return LANGUAGE_LABELS.get(code, LANGUAGE_LABELS[DEFAULT_LANGUAGE])


def language_options() -> list[tuple[str, str]]:
    """(label, value) pairs for the settings selector."""
    return [(LANGUAGE_LABELS[code], code) for code in SUPPORTED_LANGUAGES]


def t(key, **kwargs) -> str:
    """Translate ``key`` for the active language.

    Placeholders use named ``str.format`` fields so word order can differ
    between languages. Formatting failures fall back to the raw template
    rather than propagating, keeping a bad key from taking down a render.
    """
    lookup = str(key or "")
    table = TRANSLATIONS.get(_current_language) or {}
    template = table.get(lookup)
    if template is None:
        template = (TRANSLATIONS.get(DEFAULT_LANGUAGE) or {}).get(lookup)
    if template is None:
        template = lookup
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def display_width(text) -> int:
    """Terminal cell width of ``text`` (CJK glyphs count as two)."""
    return cell_len(str(text or ""))


def pad_to_width(text, width: int) -> str:
    """Right-pad ``text`` with spaces to ``width`` terminal cells.

    ``str.ljust`` pads by character count, which under-pads CJK text.
    """
    content = str(text or "")
    padding = int(width) - display_width(content)
    return content + " " * padding if padding > 0 else content


def truncate_to_width(text, width: int, ellipsis: str = "...") -> str:
    """Trim ``text`` so it occupies at most ``width`` terminal cells."""
    content = str(text or "")
    limit = int(width)
    if limit <= 0 or not content:
        return ""
    if display_width(content) <= limit:
        return content
    marker_width = display_width(ellipsis)
    if limit <= marker_width:
        return "." * limit
    reserved = limit - marker_width
    kept: list[str] = []
    used = 0
    for char in content:
        char_width = display_width(char)
        if used + char_width > reserved:
            break
        kept.append(char)
        used += char_width
    return "".join(kept) + ellipsis


def fit_to_width(text, width: int) -> str:
    """Truncate then pad so the result is exactly ``width`` cells wide."""
    return pad_to_width(truncate_to_width(text, width), width)


_EN: dict[str, str] = {}
_ZH: dict[str, str] = {}

TRANSLATIONS = {
    LANG_EN: _EN,
    LANG_ZH: _ZH,
}


def _add(key: str, english: str, chinese: str) -> None:
    _EN[key] = english
    _ZH[key] = chinese


# --- Settings: page titles and chrome ---------------------------------------
_add("settings.title", "Settings", "设置")
_add("settings.close", "esc", "esc")
_add("settings.back", "<", "<")
_add("settings.search_placeholder", "Search settings", "搜索设置")
_add("settings.add_model", "Add model", "添加模型")
_add("settings.page.general", "General", "通用")
_add("settings.page.archived_chats", "Archived chats", "已归档会话")
_add("settings.page.model_list", "Model list", "模型列表")
_add("settings.page.agent_mode", "Agent mode", "智能体模式")
_add("settings.page.skills", "Skills", "技能")
_add("settings.page.installed_skills", "Installed skills", "已安装技能")
_add("settings.page.add_skill", "Install skill", "安装技能")
_add("settings.page.auto_compact", "Auto compact", "自动压缩")
_add("settings.page.memory_system", "Memory system", "记忆系统")
_add("settings.page.web_search", "Web search", "网络搜索")
_add("settings.page.help", "Commands", "命令")
_add("settings.page.team", "Agent team", "智能体团队")
_add("settings.page.system_prompt", "System prompt", "系统提示词")
_add("settings.search_archived", "Search archived chats", "搜索已归档会话")
_add("settings.add_member", "Add member", "添加成员")
_add("settings.install_skill", "Install skill", "安装技能")

# --- Settings: General page -------------------------------------------------
_add("settings.language", "Language", "语言")
_add("settings.use_markdown", "Use markdown", "使用 Markdown")

# --- Common values ----------------------------------------------------------
_add("common.true", "true", "开")
_add("common.false", "false", "关")
_add("common.on", "On", "开")
_add("common.off", "Off", "关")
_add("common.yes", "Yes", "是")
_add("common.no", "No", "否")
_add("common.auto", "Auto", "自动")
_add("common.none", "None", "无")
_add("common.submit", "Submit", "提交")
_add("common.cancel", "Cancel", "取消")
_add("common.confirm", "Confirm", "确认")
_add("common.save", "Save", "保存")
_add("common.remove", "Remove", "移除")
_add("common.unarchive", "Unarchive", "取消归档")
_add("common.delete", "Delete", "删除")
_add("common.rename", "Rename", "重命名")
_add("common.edit", "Edit", "编辑")
_add("common.close", "Close", "关闭")
_add("common.next", "Next", "下一步")
_add("common.dismiss", "Dismiss", "忽略")
_add("common.quit", "Quit", "退出")
_add("common.remove_all", "Remove all", "全部移除")
_add("common.enabled", "Enabled", "已启用")
_add("common.disabled", "Disabled", "已禁用")

# --- app.py: shared row labels ----------------------------------------------
_add("app.row.enable", "Enable", "启用")
_add("app.row.name", "Name", "名称")
_add("app.row.provider", "Provider", "服务商")
_add("app.row.api_key", "API key", "API 密钥")
_add("app.row.source", "Source", "来源")
_add("app.row.target", "Target", "目标")
_add("app.row.version", "Version", "版本")
_add("app.row.registry", "Registry", "Registry")
_add("app.row.path", "Path", "路径")
_add("app.row.description", "Description", "描述")
_add("app.row.role", "Role", "角色")
_add("app.row.tools", "Tools", "工具")
_add("app.row.reset", "Reset", "重置")
_add("app.value.empty", "(empty)", "(空)")
_add("app.value.local", "(local)", "(本地)")
_add("app.value.local_plain", "Local", "本地")
_add("app.value.unknown", "(unknown)", "(未知)")
_add("app.value.total", "Total", "总计")

# --- app.py: model page -----------------------------------------------------
_add("app.model.api_type", "API type", "API 类型")
_add("app.model.name", "Model name", "模型名称")
_add("app.model.base_url", "Base URL", "基础 URL")
_add("app.model.model", "Model", "模型")
_add("app.model.max_tokens", "Max tokens", "最大 Token 数")
_add("app.model.temperature", "Temperature", "温度")
_add("app.model.stream", "Stream", "流式输出")
_add("app.model.thinking", "Thinking", "思考模式")
_add("app.model.extra_modalities", "Extra modalities", "额外模态")
_add("app.model.modality.audio", "Audio", "音频")
_add("app.model.modality.image", "Image", "图像")
_add("app.model.modality.video", "Video", "视频")
_add("app.model.limit", "Limit", "上限")
_add("app.model.context", "Context", "上下文")
_add("app.model.reasoning_effort", "Reasoning effort", "推理强度")

# --- app.py: info bar / sidebar toggle ---------------------------------------
# The context readout is rebuilt on every token update, but it also needs a
# zero-state label for the initial compose pass.
_add(
    "app.info.context",
    "Context: {value} ({percent}%)",
    "上下文：{value} ({percent}%)",
)
_add("app.info.context_initial", "Context: 0.0k (0%)", "上下文：0.0k (0%)")
_add("app.info.interrupt_key", "esc", "esc")
_add("app.info.interrupt_text", "interrupt", "中断")
_add("app.info.sessions", "Sessions", "会话")
_add("app.info.dismiss", "Dismiss", "关闭")
_add("app.info.back", "Back", "上一步")
_add("app.info.next", "Next", "下一步")
_add("app.info.submit", "Submit", "提交")
_add("app.sidebar_toggle", "= Sessions", "= 会话")

# --- app.py: reasoning effort labels ----------------------------------------
_add("app.reasoning.off", "Off", "关闭")
_add("app.reasoning.minimal", "Minimal", "极低")
_add("app.reasoning.low", "Low", "低")
_add("app.reasoning.medium", "Medium", "中")
_add("app.reasoning.high", "High", "高")
_add("app.reasoning.xhigh", "XHigh", "极高")
_add("app.reasoning.max", "Max", "最高")

# --- app.py: agent mode -----------------------------------------------------
_add("app.agent.max_rounds", "Max rounds", "最大轮数")
_add("app.agent.max_tool_calls", "Max tool calls", "最大工具调用数")
_add("app.agent.file_inline_chars", "File inline chars", "文件内联字符数")
_add("app.agent.team_config", "config", "配置")

# --- app.py: skills ---------------------------------------------------------
_add("app.skills.sources", "Sources", "来源")
_add("app.skills.app", "App", "应用")
_add("app.skills.workspace", "Workspace", "工作区")
_add("app.skills.auto_catalog", "Auto catalog", "自动编目")
_add("app.skills.empty", "No skills", "暂无技能")
_add("app.skills.loaded", "Loaded", "已加载")
_add("app.skills.installed_via", "Installed via", "安装方式")
_add("app.skills.slug", "Slug", "标识")
_add("app.skills.installed_at", "Installed at", "安装时间")
_add("app.skills.skill_md", "SKILL.md", "SKILL.md")
_add("app.skills.triggers", "Triggers", "触发词")
_add("app.skills.files", "Files", "文件")
_add("app.skills.force", "Force", "强制覆盖")
_add("app.skills.install", "Install", "安装")
_add("app.skills.version_placeholder", "Latest", "最新版本")

# --- app.py: auto compact / memory ------------------------------------------
_add("app.compact.model", "Compact model", "压缩模型")
_add("app.memory.model", "Memory model", "记忆模型")

# --- app.py: web search -----------------------------------------------------
_add("app.web.max_results", "Max results", "最大结果数")
_add("app.web.search_depth", "Search depth", "搜索深度")
_add("app.web.topic", "Topic", "主题")
_add("app.web.depth.basic", "Basic", "基础")
_add("app.web.depth.fast", "Fast", "快速")
_add("app.web.depth.ultra_fast", "Ultra fast", "极速")
_add("app.web.depth.advanced", "Advanced", "深度")
_add("app.web.topic.general", "General", "通用")
_add("app.web.topic.news", "News", "新闻")
_add("app.web.topic.finance", "Finance", "财经")

# --- app.py: agent team -----------------------------------------------------
_add("app.team.empty", "No members", "暂无成员")
_add("app.team.max_turns", "Max turns", "最大轮次")
_add("app.team.system_prompt", "System prompt", "系统提示词")
_add("app.team.active", "Active", "运行中")
_add("app.team.task_count", "Task count", "任务数")
_add("app.team.runtime_status", "Runtime status", "运行状态")
_add("app.team.runtime", "Runtime", "运行时")
_add("app.team.shutdown", "Shutdown", "关闭")
_add("app.team.source.builtin", "Builtin", "内置")
_add("app.team.source.override", "Override", "覆盖")
_add("app.team.source.custom", "Custom", "自定义")
_add("app.team.edit_prompt_title", "Edit prompt: {name}", "编辑提示词: {name}")
_add(
    "app.team.edit_description_title",
    "Edit description: {name}",
    "编辑描述: {name}",
)
_add("app.team.edit_tools_title", "Edit tools: {name}", "编辑工具: {name}")

# --- app.py: archived chats -------------------------------------------------
_add("app.archived.all_projects", "All project", "全部项目")
_add("app.archived.without_project", "Without project", "无项目")
_add("app.archived.empty", "No archived chats", "暂无已归档会话")

# --- app.py: quit hint ------------------------------------------------------
_add("app.quit.title", "Quit", "退出")
_add("app.quit.hint", "Press Ctrl+Q to quit", "按 Ctrl+Q 退出")

# --- app.py: toasts (session / project) -------------------------------------
_add(
    "app.toast.chat_init_failed",
    "Failed to initialize chat: {error}",
    "初始化对话失败: {error}",
)
_add(
    "app.toast.reference_invalid",
    "Reference path does not exist or type mismatch.",
    "引用路径不存在或类型不匹配。",
)
_add(
    "app.toast.busy_switch_session",
    "Busy right now, cannot switch chats.",
    "当前正在处理中，暂时不能切换会话。",
)
_add(
    "app.toast.session_read_failed",
    "Cannot read the selected chat.",
    "无法读取所选会话。",
)
_add(
    "app.toast.busy_session_action",
    "Busy right now, cannot act on chats.",
    "当前正在处理中，暂时不能操作会话。",
)
_add("app.toast.session_pinned", "Chat pinned.", "已置顶对话。")
_add("app.toast.session_unpinned", "Chat unpinned.", "已取消置顶。")
_add("app.toast.session_archived", "Chat archived.", "已归档对话。")
_add("app.toast.session_renamed", "Chat renamed.", "已重命名对话。")
_add(
    "app.toast.session_action_failed",
    "Chat action failed: {error}",
    "会话操作失败: {error}",
)
_add(
    "app.toast.busy_project_action",
    "Busy right now, cannot act on projects.",
    "当前正在处理中，暂时不能操作项目。",
)
_add("app.toast.project_pinned", "Project pinned.", "已置顶项目。")
_add("app.toast.project_unpinned", "Project unpinned.", "已取消置顶项目。")
_add("app.toast.project_renamed", "Project renamed.", "已重命名项目。")
_add(
    "app.toast.project_archived",
    "Project chats archived, {count} in total.",
    "已归档项目对话，共归档 {count} 个对话。",
)
_add("app.toast.project_removed", "Project {name} removed.", "已移除项目 {name}。")
_add(
    "app.toast.project_action_failed",
    "Project action failed: {error}",
    "项目操作失败: {error}",
)
_add(
    "app.toast.prompt_create_failed",
    "Failed to create {file}: {error}",
    "创建 {file} 失败: {error}",
)
_add(
    "app.toast.prompt_read_failed",
    "Failed to read {file}: {error}",
    "读取 {file} 失败: {error}",
)
_add(
    "app.toast.prompt_save_failed",
    "Failed to save {file}: {error}",
    "保存 {file} 失败: {error}",
)
_add("app.toast.prompt_saved", "Saved {file}", "已保存 {file}")
_add("app.toast.chat_unarchived", "Chat unarchived.", "已取消归档对话。")
_add("app.toast.chat_deleted", "Chat permanently deleted.", "已永久删除对话。")
_add(
    "app.toast.chats_deleted",
    "Permanently deleted {count} chats.",
    "已永久删除 {count} 个对话。",
)
_add("app.toast.history_cleared", "Chat history cleared.", "对话历史已清空。")
_add(
    "app.toast.project_create_failed",
    "Failed to create project: {error}",
    "新建项目失败: {error}",
)
_add(
    "app.toast.message_failed",
    "Failed to process message: {error}",
    "处理消息失败: {error}",
)
_add(
    "app.toast.request_failed",
    "Request failed. Check the model config and network connection.",
    "请求失败，请检查模型配置和网络连接。",
)

# --- app.py: toasts (model / skills) ----------------------------------------
_add(
    "app.toast.model_rename_failed",
    "Failed to rename model: {error}",
    "模型重命名失败: {error}",
)
_add(
    "app.toast.model_delete_failed",
    "Failed to delete model: {error}",
    "删除模型失败: {error}",
)
_add("app.toast.skill_slug_required", "Skill slug cannot be empty.", "技能标识不能为空。")
_add(
    "app.toast.skill_needs_project",
    "Select a project before installing into the workspace.",
    "请先选择项目后再安装到 Workspace。",
)
_add(
    "app.toast.skill_install_failed",
    "Failed to install skill: {error}",
    "安装 Skill 失败: {error}",
)
_add("app.toast.skill_installed", "Skill installed: {name}", "已安装技能：{name}")
_add("app.toast.skill_not_found", "No skill found to delete.", "未找到可删除的技能。")
_add(
    "app.toast.skill_path_invalid",
    "Invalid skill path, cannot delete.",
    "Skill 路径无效，无法删除。",
)
_add(
    "app.toast.skill_path_forbidden",
    "Skill is not in a directory allowed for deletion.",
    "Skill 不在允许删除的目录中。",
)
_add(
    "app.toast.skill_missing",
    "Skill no longer exists: {name}",
    "Skill 已不存在: {name}",
)
_add(
    "app.toast.skill_delete_failed",
    "Failed to delete skill: {error}",
    "删除 Skill 失败: {error}",
)
_add("app.toast.skill_deleted", "Skill deleted: {name}", "已删除技能：{name}")

# --- app.py: toasts (agent team) --------------------------------------------
_add(
    "app.toast.team_needs_project_create",
    "Select a project before creating a team member.",
    "请先选择项目后再创建 team 成员。",
)
_add(
    "app.toast.team_needs_project_edit",
    "Select a project before editing a team member.",
    "请先选择项目后再编辑 team 成员。",
)
_add(
    "app.toast.team_member_add_failed",
    "Failed to add member: {error}",
    "新增成员失败: {error}",
)
_add(
    "app.toast.team_member_rename_failed",
    "Failed to rename member: {error}",
    "重命名成员失败: {error}",
)
_add(
    "app.toast.team_max_turns_invalid",
    "Max turns must be a positive integer.",
    "Max turns 必须是正整数。",
)
_add(
    "app.toast.team_member_update_failed",
    "Failed to update member: {error}",
    "更新成员失败: {error}",
)
_add(
    "app.toast.team_description_save_failed",
    "Failed to save description: {error}",
    "保存 description 失败: {error}",
)
_add(
    "app.toast.team_tools_save_failed",
    "Failed to save tools: {error}",
    "保存 tools 失败: {error}",
)
_add(
    "app.toast.team_prompt_save_failed",
    "Failed to save prompt: {error}",
    "保存 prompt 失败: {error}",
)
_add(
    "app.toast.team_member_def_not_found",
    "No member definition found to delete: {name}",
    "未找到可删除的成员定义: {name}",
)
_add(
    "app.toast.team_member_def_deleted",
    "Member definition deleted: {name}",
    "已删除成员定义: {name}",
)
_add(
    "app.toast.team_reset_builtin_only",
    "Only builtin members can be reset: {name}",
    "仅内置成员支持重置: {name}",
)
_add(
    "app.toast.team_reset_unchanged",
    "Member is unmodified, no reset needed: {name}",
    "成员未被修改，无需重置: {name}",
)
_add("app.toast.team_reset_failed", "Reset failed: {name}", "重置失败: {name}")
_add(
    "app.toast.team_member_def_reset",
    "Member definition reset: {name}",
    "已重置成员定义: {name}",
)
_add(
    "app.toast.teammate_shutdown",
    "Teammate shut down: {name}",
    "已关闭 teammate: {name}",
)
_add(
    "app.toast.teammate_not_found",
    "Teammate not found: {name}",
    "未找到 teammate: {name}",
)

# --- app.py: memory sections ------------------------------------------------
_add("app.memory.core", "Core memory", "核心记忆")
_add("app.memory.preference", "Preference memory", "偏好记忆")
_add("app.memory.episodic", "Episodic memory", "情景记忆")

# --- commands: slash command descriptions -----------------------------------
_add("cmd.help.desc", "Open command help", "打开命令帮助")
_add("cmd.quit.desc", "Exit OmniAgent", "退出 OmniAgent")
_add("cmd.clear.desc", "Clear current chat", "清空当前会话")
_add(
    "cmd.comp.desc",
    "Compact the current conversation context immediately",
    "立即压缩当前对话上下文",
)
_add("cmd.memory.desc", "Open memory page", "打开记忆页面")
_add("cmd.search.desc", "Open web search settings", "打开网络搜索设置")
_add("cmd.skills.desc", "Open skills settings", "打开技能设置")
_add("cmd.agent.desc", "Open agent mode page", "打开智能体模式页面")
_add("cmd.team.desc", "Open team page", "打开团队页面")

# --- CLI: command handler messages ------------------------------------------
_add("cli.commands_header", "Commands:", "命令：")
_add(
    "cli.unknown_command",
    "Unknown command: {command}. Use /help to see available commands.",
    "未知命令：{command}。使用 /help 查看可用命令。",
)
_add("cli.goodbye", "Goodbye!", "再见！")
_add("cli.no_chat_to_clear", "No active conversation to clear.", "没有可清空的会话。")
_add("cli.history_cleared", "Conversation history cleared.", "已清空会话历史。")
_add("cli.comp_usage", "Usage: /comp", "用法：/comp")
_add(
    "cli.no_chat_to_compact", "No active conversation to compact.", "没有可压缩的会话。"
)
_add(
    "cli.compact_cancelled",
    "Context compaction was cancelled.",
    "上下文压缩已取消。",
)
_add("cli.continue_question", "Continue?", "是否继续？")
_add(
    "cli.approve_todo_list",
    "Approve current agent todo list?",
    "批准当前 Agent 的待办列表？",
)
_add(
    "cli.allow_edit_file",
    "Allow agent to edit file? ({file_path})",
    "允许 Agent 编辑文件？（{file_path}）",
)
_add(
    "cli.occurrences_to_replace",
    "Occurrences to replace: {occurrences}",
    "待替换的匹配数：{occurrences}",
)
_add(
    "cli.allow_patch_file",
    "Allow agent to patch file? ({file_path}:{start_line}-{end_line})",
    "允许 Agent 修补文件？（{file_path}:{start_line}-{end_line}）",
)
_add(
    "cli.command_exit_code",
    "Command exited with code {code}.",
    "命令退出，退出码 {code}。",
)
_add("cli.todo_item_count", "{count} todo item", "{count} 项待办")
_add("cli.todo_item_count_plural", "{count} todo items", "{count} 项待办")
_add("cli.task_count", "{count} task", "{count} 个任务")
_add("cli.task_count_plural", "{count} tasks", "{count} 个任务")

# --- widgets: sidebar -------------------------------------------------------
_add("sidebar.new_chat", "New Chat", "新会话")
_add("sidebar.settings", "Settings", "设置")
_add("sidebar.pinned", "Pinned", "已置顶")
_add("sidebar.projects", "Projects", "项目")
_add("sidebar.chats", "Chats", "会话")
_add("sidebar.no_chats", "No Chats", "暂无会话")
_add("sidebar.chat_title_placeholder", "Chat title", "会话标题")
_add("sidebar.project_name_placeholder", "Project name", "项目名称")
_add("sidebar.pin_chat", "Pin chat", "置顶会话")
_add("sidebar.unpin_chat", "Unpin chat", "取消置顶")
_add("sidebar.rename_chat", "Rename chat", "重命名会话")
_add("sidebar.archive_chat", "Archive chat", "归档会话")
_add("sidebar.pin_project", "Pin project", "置顶项目")
_add("sidebar.unpin_project", "Unpin project", "取消置顶")
_add("sidebar.rename_project", "Rename project", "重命名项目")
_add("sidebar.archive_chats", "Archive chats", "归档全部会话")

# --- widgets: chat input ----------------------------------------------------
_add("input.placeholder", "Type a message", "输入消息")
_add("input.mode.plan", "Plan", "规划")
_add("input.mode.build", "Build", "执行")
_add("input.no_model", "No model", "无模型")

# Approval levels: consumed by tui/data.py approval_levels().
_add("input.approval.confirm", "Ask for approval", "每次确认")
_add("input.approval.approve", "Approve for me", "自动批准")
_add("input.approval.full", "Full access", "完全访问")

# Thinking levels: consumed by tui/data.py thinking_levels().
_add("input.thinking.none", "Off", "关闭")
_add("input.thinking.minimal", "Minimal", "极低")
_add("input.thinking.low", "Low", "低")
_add("input.thinking.medium", "Medium", "中等")
_add("input.thinking.high", "High", "高")
_add("input.thinking.max", "Max", "最高")

_add("input.model_group.models", "Models", "模型")
_add("input.model_group.other", "Other", "其他")
_add("input.option_recommended", "{title} (Recommended)", "{title}（推荐）")
_add(
    "input.prompt_progress",
    "{current} of {total} questions",
    "第 {current}/{total} 个问题",
)
_add("input.custom_answer_label", "Type your own answer", "自定义回答")
_add("input.custom_answer_placeholder", "Type your own answer...", "输入你的回答…")
_add(
    "input.pending_limit",
    "You can queue at most {limit} messages.",
    "最多只能追加 {limit} 条消息。",
)
_add("input.cmd_hint.agent", "Open agent page", "打开智能体页面")
_add("input.cmd_hint.clear", "Reset chat", "重置会话")
_add("input.cmd_hint.comp", "Compact context", "压缩上下文")
_add("input.cmd_hint.help", "Open help page", "打开帮助页面")
_add("input.cmd_hint.memory", "Open memory page", "打开记忆页面")
_add("input.cmd_hint.quit", "Exit app", "退出应用")
_add("input.cmd_hint.search", "Open web search", "打开网络搜索")
_add("input.cmd_hint.skills", "Open skills page", "打开技能页面")
_add("input.cmd_hint.team", "Open team page", "打开团队页面")

# --- widgets: chat view -----------------------------------------------------
_add("chat.plan_header", "Plan", "规划")
_add("chat.tool_call_failed", "Tool call failed.", "工具调用失败。")
_add("chat.status.failed", "failed", "失败")
_add("chat.status.rejected", "rejected", "已拒绝")
_add("chat.thought_header", "{marker} Thought: {seconds}s", "{marker} 已思考：{seconds}s")
_add("chat.explored", "Explored", "已探索")
_add("chat.explored_empty", "0 reads, 0 searches", "0 次读取，0 次搜索")
_add("chat.count_separator", ", ", "，")
_add("chat.read_count", "{count} read", "{count} 次读取")
_add("chat.read_count_plural", "{count} reads", "{count} 次读取")
_add("chat.search_count", "{count} search", "{count} 次搜索")
_add("chat.search_count_plural", "{count} searches", "{count} 次搜索")
_add("chat.answered_count", "{count} answered", "已回答 {count} 个")
_add("chat.task_count", "{count} task", "{count} 个任务")
_add("chat.task_count_plural", "{count} tasks", "{count} 个任务")
_add("chat.changed_files_count", "{count} Changed file", "{count} 个文件已变更")
_add("chat.changed_files_count_plural", "{count} Changed files", "{count} 个文件已变更")

# --- widgets: chat view, tool display labels --------------------------------
# Tool names stay as protocol identifiers; only these display verbs localize.
_add("chat.tool.generic", "Tool", "工具")
_add("chat.tool.read_file", "Read", "读取")
_add("chat.tool.read_program_docs", "Read program docs", "读取程序文档")
_add("chat.tool.read_skill", "Read skill", "读取技能")
_add("chat.tool.grep", "Grep", "检索")
_add("chat.tool.glob", "Glob", "匹配")
_add("chat.tool.list_dir", "List dir", "列出目录")
_add("chat.tool.list_skills", "List skills", "列出技能")
_add("chat.tool.update_todo", "Todos", "待办")
_add("chat.tool.ask_user", "Questions", "提问")
_add("chat.tool.submit_plan", "Plan", "规划")
_add("chat.tool.web_fetch", "Webfetch", "网页抓取")
_add("chat.tool.web_search", "Websearch", "网络搜索")
_add("chat.tool.write_file", "Write", "写入")
_add("chat.tool.edit_file", "Edit", "编辑")
_add("chat.tool.bash", "Shell", "命令")
_add("chat.tool.local_http_check", "HTTP check", "HTTP 检查")
_add("chat.tool.git_status", "Git status", "Git 状态")
_add("chat.tool.git_diff", "Git diff", "Git 差异")
_add("chat.tool.dispatch_subagent", "Subagent", "子智能体")
_add("chat.tool.report_to_lead", "Report to Lead", "向 Lead 汇报")
_add("chat.tool.spawn_teammate", "Spawn teammate", "创建成员")
_add("chat.tool.list_teammates", "List teammates", "列出成员")
_add("chat.tool.send_message", "Send message", "发送消息")
_add("chat.tool.read_inbox", "Read inbox", "读取收件箱")
_add("chat.tool.broadcast", "Broadcast", "广播")
_add("chat.tool.shutdown_teammate", "Shutdown teammate", "关闭成员")

# --- widgets: chat view, context compaction ---------------------------------
_add("chat.compaction.auto_running", "Auto context compaction", "自动压缩上下文")
_add("chat.compaction.manual_running", "Manual context compaction", "手动压缩上下文")
_add("chat.compaction.done", "Context compact complete", "上下文压缩完成")
_add("chat.compaction.failed", "Context compact failed", "上下文压缩失败")
_add("chat.compaction.messages", "Message: {before} -> {after}", "消息：{before} -> {after}")
_add("chat.compaction.chars", "Chars: {before} -> {after}", "字符：{before} -> {after}")
_add("chat.compaction.model", "Compact model: {model}", "压缩模型：{model}")

# --- widgets: chat view, agent team -----------------------------------------
_add("chat.team.teammate", "Teammate", "成员")
_add("chat.team.lead", "Lead", "Lead")
_add("chat.team.report", "Report", "汇报")
_add("chat.team.status", "Status", "状态")
_add("chat.team.tasks", "Tasks", "任务")
_add("chat.team.scope", "Scope", "范围")
_add("chat.team.current", "Current", "当前")
_add("chat.team_status.active", "Ready", "就绪")
_add("chat.team_status.starting", "Starting", "启动中")
_add("chat.team_status.waiting", "Waiting", "等待中")
_add("chat.team_status.running", "Working", "进行中")
_add("chat.team_status.completed", "Done", "已完成")
_add("chat.team_status.failed", "Failed", "失败")
_add("chat.team_status.cancelling", "Stopping", "停止中")
_add("chat.team_status.cancelled", "Cancelled", "已取消")
_add("chat.team_status.interrupted", "Interrupted", "已中断")
_add("chat.team_status.unknown", "Unknown", "未知")

# --- widgets: todos ---------------------------------------------------------
_add(
    "todo.progress",
    "{completed} of {total} todos completed",
    "已完成 {completed}/{total} 项待办",
)

# --- widgets: modals and pickers --------------------------------------------
_add("modal.ok", "OK", "确定")
_add("modal.add", "Add", "添加")
_add("modal.choose_one", "Choose one", "请选择")
_add("modal.input.title", "Input", "输入")
_add("modal.memory.title", "Memory", "记忆")
_add("modal.file.title", "Enter file path", "输入文件路径")
_add("modal.project.title", "New project", "新建项目")
_add("modal.project.name", "Project name", "项目名称")
_add("modal.project.path", "Project path", "项目路径")
_add("modal.reference.title", "Add reference", "添加引用")
_add("modal.reference.type", "Type", "类型")
_add("modal.reference.path", "Path", "路径")
_add("modal.reference.type_file", "File", "文件")
_add("modal.reference.type_folder", "Folder", "文件夹")
_add("picker.choose_project", "Choose project", "选择项目")
_add("picker.new_project", "New project", "新建项目")
_add("picker.without_project", "Without project", "不使用项目")
_add("picker.search_placeholder", "Search projects", "搜索项目")

# --- settings: model creation errors ----------------------------------------
_add("settings.add_model_action", "Add", "添加")
_add("settings.fetch_models", "Fetch", "获取")
_add("settings.no_model_settings", "No model settings", "暂无模型设置")
_add("settings.no_items", "No items", "暂无条目")
_add(
    "settings.add_model_provider_required",
    "Provider cannot be empty.",
    "服务商不能为空。",
)
_add(
    "settings.add_model_name_required",
    "Model name cannot be empty.",
    "模型名称不能为空。",
)
_add(
    "settings.fetch_models_api_key_required",
    "Enter an API key before fetching models.",
    "请先输入 API 密钥，再获取模型列表。",
)
_add(
    "settings.fetch_models_loaded",
    "Loaded {count} available models.",
    "已获取 {count} 个可用模型。",
)
_add(
    "settings.fetch_models_empty",
    "The API returned no available models. You can still enter one manually.",
    "API 未返回可用模型，仍可手动输入。",
)
_add(
    "settings.fetch_models_failed",
    "Failed to fetch models: {error}",
    "获取模型列表失败: {error}",
)
_add(
    "settings.add_model_failed",
    "Failed to add model: {error}",
    "新增模型失败: {error}",
)
