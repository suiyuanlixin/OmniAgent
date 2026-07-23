# OmniAgent

OmniAgent 是一个基于 Python、Textual 和 Rich 的本地 AI Agent 工作台。它同时覆盖普通聊天、带工具的本地 Agent、多模型切换、长期记忆、会话持久化、网络搜索、Skills、子智能体和 Team 协作，适合在终端里完成代码阅读、实现、调试、文档整理等多步骤任务。

## 功能亮点

- Textual TUI 界面，包含侧边栏、会话流、设置页、Todo 面板、项目选择器和引用标签。
- 支持多模型档案 `model_list`，可在 GLM、Anthropic、OpenAI 兼容端点、Gemini 和 Ollama 之间切换。
- 支持普通输出、流式输出以及模型 reasoning / thinking 展示。
- 支持 `[@file:路径]` 与 `[@folder:路径]` 引用；文本文件可直接注入上下文，文件夹以只读方式延迟访问。
- 支持图片、音频、视频附件；仅在当前模型档案声明 `extra_modalities` 时直接作为多模态输入发送。
- 支持 Agent Plan mode / Build mode 分工，使用 todo 跟踪执行进度与最终校验。
- 支持子智能体 `reader`、`researcher`、`auditor`、`builder`。
- 支持 Team 模式，可启用内置 teammate：`architect`、`reviewer`、`devops`、`debugger`。
- 支持持久记忆、偏好记忆、情景记忆、自动上下文压缩与手动 `/comp` 压缩。
- 支持 Tavily 网络搜索、程序级 / 工作区级 Skills，以及 ClawHub / SkillHub 安装流程。
- 对写文件、补丁、命令执行等高风险操作提供审批保护。

## 环境要求

- Python 3.10+
- 可访问目标模型服务的 API Key
- 如需网络搜索，准备 Tavily API Key
- 如需本地模型，已安装并启动 Ollama

核心依赖位于 `requirements.txt`，其中包括：

- `textual`
- `rich`
- `prompt_toolkit`
- `zai-sdk`
- `anthropic`
- `openai`
- `ollama`
- `httpx`

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 快速开始

启动程序：

```bash
python main.py
```

说明：

- 启动后通过界面里的项目选择器选择工作区。
- 未选择项目时，可以正常聊天、搜索、使用记忆与程序文档，但不能启用工作区写操作 Agent。
- 选择项目后，Agent 才能读取、搜索、编辑并执行工作区内命令。
- 首次启动会在本地生成 `config.json` 和 `prompt.md`。

## 配置

当前配置文件为仓库根目录下的 `config.json`。程序实际使用的是“全局设置 + 多模型档案”结构，而不是旧版单模型平铺格式。

示例：

```json
{
  "general": {
    "render_markdown": true
  },
  "model_list": {
    "DeepSeek-V4-Pro": {
      "api_type": "openai",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-v4-pro",
      "api_key": "sk-xxxxxxxx",
      "max_tokens": 32000,
      "temperature": 1,
      "stream_mode": true,
      "thinking_mode": true,
      "reasoning_effort": "max",
      "extra_modalities": [],
      "context_window_tokens": 1000000
    }
  },
  "current_model": "DeepSeek-V4-Pro",
  "agent_mode": {
    "max_rounds": 150,
    "max_tool_calls": 500,
    "approve": "approve",
    "plan_mode": false,
    "agent_team": {
      "enable": true
    }
  },
  "skills": {
    "enable": true,
    "sources": {
      "app": true,
      "workspace": false
    },
    "auto_catalog": true,
    "max_skill_chars": 32000
  },
  "auto_compact": {
    "enable": true,
    "trigger_ratio": 0.75,
    "keep_recent_messages": 10,
    "compact_model": "auto"
  },
  "memory_system": {
    "memory_model": "auto"
  },
  "web_search": {
    "enable": true,
    "provider": "tavily",
    "api_key": "tvly-xxxxxxxx",
    "max_results": 10,
    "search_depth": "basic",
    "topic": "general"
  }
}
```

关键字段：

- `general.render_markdown`：是否将回答按 Markdown 渲染到聊天区。
- `model_list`：模型档案集合，可配置多个 profile。
- `current_model`：当前启用的模型档案名。
- `api_type`：支持 `glm`、`anthropic`、`openai`、`gemini`、`ollama`。
- `base_url`：兼容端点地址。`gemini` 留空时自动使用官方 OpenAI 兼容地址；`ollama` 留空时走本地默认服务。
- `thinking_mode` 与 `reasoning_effort`：控制推理内容显示与强度。
- `extra_modalities`：声明当前模型允许直接发送的附件模态，支持 `audio`、`image`、`video`。
- `agent_mode.approve`：审批模式，支持 `confirm`、`approve`、`full`。
- `agent_mode.plan_mode`：是否启用只读的 Plan mode。
- `agent_mode.agent_team.enable`：是否启用 Team 模式。
- `skills.sources.app`：是否加载程序目录 `skills/`。
- `skills.sources.workspace`：是否加载工作区 `.omniagent/skills/`。
- `auto_compact.compact_model`：上下文压缩模型，`auto` 表示跟随当前模型。
- `memory_system.memory_model`：记忆写入模型，`auto` 表示跟随当前模型。
- `web_search.provider`：当前仅支持 `tavily`。

`reasoning_effort` 的有效值按提供商不同：

- `glm` / `anthropic` / `openai`：`low`、`medium`、`high`、`xhigh`、`max`
- `gemini`：`minimal`、`low`、`medium`、`high`
- `ollama`：`low`、`medium`、`high`

推荐配置示例：

本地 Ollama：

```json
{
  "api_type": "ollama",
  "base_url": "",
  "model": "deepseek-r1:671b",
  "api_key": ""
}
```

Ollama 云端：

```json
{
  "api_type": "ollama",
  "base_url": "https://ollama.com",
  "model": "deepseek-v4-pro:cloud",
  "api_key": "xxxxxxxx"
}
```

`config.json` 已被 `.gitignore` 忽略，适合保存本地密钥和个人设置。

## 界面与命令

主要界面：

- 左侧 Sidebar：项目与会话管理、固定项目/会话、归档浏览。
- 中央 ChatView：消息流、Thinking 块、工具结果块、Todo 块、Markdown 渲染。
- 底部 ChatInput：输入、引用、附件、Plan / Build 切换、发送队列。
- Settings：模型、Agent、Skills、Web Search、Team 等设置。
- TodosPanel：展示当前 Agent 执行中的 todo 快照。

内置命令：

| 命令 | 说明 |
| --- | --- |
| `/help` | 打开命令帮助页面。 |
| `/quit` | 退出程序。 |
| `/clear` | 清空当前会话上下文。 |
| `/comp` | 立即按当前压缩策略压缩上下文。 |
| `/memory` | 打开记忆页面。 |
| `/search` | 打开 Web Search 设置页面。 |
| `/skills` | 打开 Skills 设置页面。 |
| `/agent` | 打开 Agent 设置页面。 |
| `/team` | 打开 Team 页面。 |

## 文件引用与多模态

支持两种引用语法：

- `[@file:path/to/file]`
- `[@folder:path/to/folder]`

示例：

```text
请总结 [@file:path/to/file]
检查 [@folder:path/to/folder]
```

规则：

- 相对路径只有在已选择工作区后可用。
- 路径会做真实存在校验；不存在的目标不会转换成引用标签。
- 文本文件内容会以只读上下文附加到本次请求，单文件最多附加 `60000` 个字符。
- 文件夹不会直接展开进上下文，而是作为本次请求的只读目录权限来源。
- 图片、音频、视频会按文件头和后缀识别类型。
- 只有当前模型档案的 `extra_modalities` 声明了对应模态，媒体才会直接随请求发送。

媒体限制：

- 图片最大 `10 MB`
- 音频最大 `50 MB`
- 视频最大 `50 MB`
- 单次多模态请求体总量最大 `64 MB`

## Agent 模式

Agent 模式用于多步骤本地任务。模型可以请求工具，客户端执行后再把结果反馈给模型，直到给出最终答复。

核心特性：

- Plan mode：只读规划模式，适合先澄清需求、拆任务、看设计、提问题。
- Build mode：实际执行模式，允许在工作区内读写文件和运行命令。
- Todo 跟踪：使用 `update_todo` 维护当前执行计划，并同步显示到对话流与 Todo 面板。
- 审批保护：写文件、补丁、命令执行会根据审批模式要求确认。
- 最终校验：任务结束前保留验证步骤，降低漏改和回归风险。

典型工具类别：

- 文件与目录：`list_dir`、`read_file`、`write_file`、`edit_file`
- 搜索与差异：`grep`、`glob`、`git_status`、`git_diff`
- 修改：`apply_patch`、`apply_unified_patch`
- 执行：`bash`
- 文档与网页：`read_program_docs`、`web_fetch`
- 协作：`update_todo`、`ask_user`
- 外部能力：`web_search`、`list_skills`、`read_skill`

安全限制：

- 必须带工作区启动后才能启用本地 Agent。
- 所有工作区工具只允许访问工作区及其子目录。
- 普通聊天不会获得工作区任意文件读写权限。
- 高风险命令仍需要审批。

## 子智能体与 Team

### 子智能体

Agent 默认支持以下子智能体：

- `reader`：快速阅读和总结代码
- `researcher`：资料搜索与方案调研
- `auditor`：审计与风险检查
- `builder`：小范围实现任务

主 Agent 可以派发子任务，但子智能体不能继续派发子智能体，也不能直接维护 todo 或向用户提问。

工作区中可通过模板覆盖内置 prompt：

```text
<workspace>/.omniagent/subagents/
├── reader.md
├── researcher.md
├── auditor.md
└── builder.md
```

### Team 模式

Team 模式支持多 teammate 协作，内置成员包括：

- `architect`
- `reviewer`
- `devops`
- `debugger`

团队配置和线程数据位于：

```text
<workspace>/.omniagent/team/
├── config.json
├── inbox/
└── threads/
```

## Skills

Skills 是给 Agent 使用的可复用工作流说明，不直接执行脚本，也不能绕过安全限制。

支持两个来源：

- 程序目录：`skills/`
- 工作区目录：`<workspace>/.omniagent/skills/`

安装来源支持 `ClawHub` 和 `SkillHub`。

## 网络搜索

网络搜索使用 Tavily。开启并配置 key 后：

- 普通聊天可按需调用搜索
- Agent 模式会获得 `web_search` 工具
- 结果会附带来源链接，适合处理外部、实时、易变信息

当前配置方式：

- 输入 `/search` 打开 Web Search 设置页面
- 在设置页中开启/关闭搜索
- 在设置页中填写 Tavily API Key
- 在设置页中调整 `provider`、`max_results`、`depth`、`topic`

当前仅支持 `tavily`，搜索深度支持 `basic`、`fast`、`ultra-fast`、`advanced`，主题支持 `general`、`news`、`finance`。

## 记忆、会话与本地数据

### 持久记忆

程序会在 `memory/` 下维护长期记忆：

```text
memory/
├── core.md
├── preferences.md
└── episodes/
    └── YYYY-MM-DD.md
```

- `core.md`：长期事实、目标、约束
- `preferences.md`：用户偏好
- `episodes/`：按日期归档的情景记忆

### 会话存储

会话和项目索引保存在 `sessions/`：

```text
sessions/
├── projects.json
├── pinned.json
├── pinned_projects.json
├── projects/
└── orphan/
```

每个会话会保存 JSON 快照，并在旁边保留 `.history.jsonl` 历史。

### 工作区状态

工作区相关运行数据保存在 `<workspace>/.omniagent/`，例如：

- `todos/`
- `skills/`
- `subagents/`
- `team/`

以下路径默认已被 `.gitignore` 忽略：

- `config.json`
- `prompt.md`
- `memory/`
- `sessions/`
- `skills/`
- `.clawhub/`
- `.skillhub/`
- `.omniagent/`

## 自定义提示词

首次运行会生成 `prompt.md`。你可以把个人提示词、回复风格、角色设定写在其中。该文件会在每次模型请求前读取，并同时影响普通聊天与 Agent 模式。

`prompt.md` 已被 `.gitignore` 忽略，适合保存只在本机使用的长期提示词。

## 项目结构

```text
OmniAgent/
├── README.md
├── requirements.txt
├── main.py                  # 程序入口与外部引用处理
├── chat.py                  # 对话引擎、模型调用、Agent 主循环
├── config.py                # 配置模型、全局设置与持久化
├── commands.py              # 斜杠命令定义
├── tools.py                 # Agent 工具定义与执行器
├── search.py                # Tavily 搜索封装
├── memory.py                # 持久记忆与历史
├── session.py               # 会话与项目索引存储
├── todo.py                  # Todo 状态与快照
├── references.py            # 文件 / 文件夹引用解析
├── skills.py                # Skills 加载与读取
├── installer.py             # Skills 安装器
├── subagents.py             # 子智能体注册与限制
├── team.py                  # Team 模式与 teammate 管理
├── ui.py                    # 控制台展示辅助
└── tui/
    ├── __main__.py          # `python -m tui` 入口
    ├── app.py               # Textual 主应用
    ├── theme.py             # 主题与 CSS 生成
    ├── runtime.py           # TUI / console bridge
    └── widgets/             # 输入框、聊天区、侧边栏、设置页、Todo 面板等组件
```

## 开发说明

当前仓库以 `requirements.txt` + 手动运行为主，未提供：

- `pyproject.toml`
- 自动化测试目录
- 仓库级 `pytest` / `ruff` / `black` / `mypy` 配置

推荐开发流程：

```bash
pip install -r requirements.txt
python main.py
```

修改后重点手动验证：

- TUI 布局与交互
- 模型切换与配置保存
- Agent 工具审批流程
- Todo、记忆、会话持久化
- 引用与附件发送逻辑

## 常见问题

### 无法开启 Agent 模式

请确认已经在界面中选择了项目工作区：

- 底部信息栏可打开项目选择器
- 只有选中项目后，Agent 才能使用工作区内的读写和命令能力

### 网络搜索显示 `missing key`

请打开 Web Search 设置页面并完成以下配置：

- 输入 `/search`
- 开启 Web Search
- 填写 Tavily API Key

### Ollama 本地模型无法连接

确认 Ollama 已安装、服务已启动，并已拉取模型：

```bash
ollama pull deepseek-r1:671b
ollama run deepseek-r1:671b
```

### 请求失败或无响应

检查：

- `api_key` 是否正确
- `base_url` 是否匹配目标服务
- `model` 是否存在
- 当前网络是否可访问相应 API

### 终端显示异常

建议使用支持 UTF-8 和 ANSI 颜色的现代终端，例如 Windows Terminal、PowerShell 7、iTerm2 或 GNOME Terminal。

## 许可证

GNU 通用公共许可证 v3.0
