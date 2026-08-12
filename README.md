# OmniAgent

OmniAgent 是一个运行在终端中的本地 AI Agent 工作台，适合聊天、代码阅读、文件修改、命令执行、网络搜索和多步骤任务协作。

## 主要功能

- Textual TUI 界面，支持会话管理、Markdown、Thinking、工具调用和 Todo 展示。
- 支持 Zai Chat Completions、Anthropic Messages、OpenAI Chat Completions、OpenAI Responses、Gemini Interactions 和 Ollama Chat。
- 支持多个 Provider 与模型档案，可在界面中切换和编辑。
- 支持 Plan / Build 两种 Agent 模式，并为文件修改和命令执行提供审批保护。
- 支持持久 Goal：Goal 位于 Plan / Build 之上，可跨消息和重启恢复，并显示规划、构建、验证阶段。
- 支持文件、文件夹、图片、音频和视频附件。
- 支持长期记忆、会话持久化、上下文压缩、Skills、子智能体和 Agent Team。
- 支持 Tavily、智谱和 Brave 网络搜索。

## 环境要求

- Python 3.10+
- 至少一个可用的模型服务
- 对应服务的 API Key；本地 Ollama 模型通常不需要 API Key
- 推荐使用支持 UTF-8 和 ANSI 颜色的现代终端

## 安装

在仓库根目录执行：

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 快速开始

启动程序：

```bash
omniagent
```

也可以使用：

```bash
python -m omniagent
```

首次使用建议按以下顺序操作：

1. 打开 **Settings**，添加模型并填写 Provider、Model、API Key 和 Base URL。
2. 选择刚添加的模型作为当前模型。
3. 如需让 Agent 操作本地项目，通过项目选择器选择工作区。
4. 在输入框中直接提问，或切换到 Plan / Build 模式处理任务。

> 未选择工作区时仍可聊天、使用记忆和网络搜索，但 Agent 不能读写项目文件或执行工作区命令。

### 持久 Goal

Goal 是跨轮次保存的持续目标层；Plan 负责只读规划，Build 负责执行，验证完成后 Goal 才会进入完成状态。

在输入框下方的 Plan / Build 模式栏中选择 **Goal**，然后输入目标并发送。首次发送会创建 Goal；Goal 未完成时，后续消息会继续当前目标。切换回 Plan 或 Build 会暂停 Goal，再次选择 Goal 后可继续。

Goal 状态会保存在会话记录中。应用重启后，仍可从最近一次状态、计划、当前步骤和进度继续工作。

## 模型配置

OmniAgent 使用“Provider → 模型档案”的方式管理模型。支持的 `api_type`：

- `ollama_chat`：Ollama Chat
- `openai_chat_completions`：OpenAI Chat Completions 及兼容接口
- `openai_responses`：OpenAI Responses
- `anthropic_messages`：Anthropic Messages
- `gemini_interactions`：Gemini Interactions
- `zai_chat_completions`：Zai Chat Completions

大多数配置都可以在 Settings 中完成：

- **Provider**：服务提供方名称，仅用于分类和展示。
- **API Type**：接口协议类型；下拉选项与 `api_type` 一一对应。`gemini_interactions` 使用 Google 官方推荐的 Gemini Interactions API。
- **Base URL**：对应接口的自定义服务地址；Zai Chat Completions 不使用该字段，Gemini Interactions 留空时使用 Google 官方端点。
- **Model**：实际发送给服务端的模型名，可从服务端获取列表或手动填写。
- **API Key**：服务密钥。
- **Thinking / Reasoning effort**：推理内容与推理强度。
- **Extra modalities**：为当前模型启用图片、音频或视频输入，并设置大小限制。

配置文件位置：

- 源码检出运行：仓库根目录的 `config.json`
- 普通安装运行：`~/.omniagent/config.json`
- 设置 `OMNIAGENT_HOME` 后：使用该目录保存配置和本地数据

`config.json` 默认被 Git 忽略，适合保存本机密钥。不要把包含真实 API Key 的配置文件提交到仓库。

## 日常使用

### 会话与项目

左侧栏用于管理项目和会话。选择项目后，Agent 才能访问该工作区。

- 普通聊天适合问答、解释和内容生成。
- **Plan mode** 只读取和分析工作区，用于先确认方案；允许计划后会切换到 Build mode 执行。
- **Build mode** 可以根据审批设置修改文件和运行命令。
- **Goal mode** 是会话级的持久自动执行协调层，不是 Plan/Build 的替代品。它会保留当前底层模式：从 Plan 开始时先提交计划，批准后在同一 Goal 中切换到 Build；从 Build 开始时直接执行。Goal 会保存成功标准、计划、当前步骤、进度与验证结果，并自动从检查点继续，直到完成、阻塞、失败、暂停或用户关闭。
- Goal 不设置总轮次、总时长、Token 或费用上限；模型请求仍受当前 Provider、模型上下文、审批与普通 Agent 单次运行配置约束。离开 Goal 模式只会暂停，不会丢失状态；重新选择 Goal 或点击继续即可恢复。
- Todo 会按会话保存，中断后重新进入同一会话仍可继续。Goal 声明完成前必须清空未完成 Todo，并在产生工作区变更时通过现有自动最终验证。

### 审批模式

Agent 设置提供三种审批级别：

- **每次确认**：敏感操作执行前询问。
- **自动批准**：自动批准常规操作，减少交互中断。
- **完全访问**：给予更高操作权限，请只在可信工作区中使用。

建议首次使用时保留“每次确认”。

### 文件与文件夹引用

在消息中使用：

```text
请总结 [@file:path/to/file]
检查 [@folder:path/to/folder]
```

说明：

- 相对路径需要先选择工作区。
- 文本文件会根据大小直接加入上下文，较大的文件由 Agent 按需读取。
- 文件夹不会整体塞入上下文，而是作为本次请求可读取的目录。
- 图片、音频和视频只有在当前模型启用了对应模态后才会直接发送。

也可以通过输入区的附件功能选择文件。

### 常用命令

| 命令 | 作用 |
| --- | --- |
| `/help` | 查看命令帮助 |
| `/clear` | 清空当前会话上下文 |
| `/comp` | 立即压缩当前上下文 |
| `/memory` | 打开记忆页面 |
| `/search` | 打开网络搜索设置 |
| `/skills` | 打开 Skills 设置 |
| `/agent` | 打开 Agent 设置 |
| `/team` | 打开 Agent Team 页面 |
| `/quit` | 退出程序 |

## 网络搜索

OmniAgent 支持以下搜索 Provider：

- Tavily
- 智谱
- Brave

输入 `/search` 打开设置，启用搜索、选择 Provider 并填写对应 API Key。启用后，普通聊天和 Agent 都可以根据需要搜索实时信息，搜索结果会保留来源链接。

## Skills、子智能体与 Team

### Skills

Skills 是供 Agent 读取的可复用工作流说明。可以在 `/skills` 页面启用、查看和安装 Skills，安装来源支持 ClawHub 和 SkillHub。

Skills 可来自：

- 程序级目录：`skills/`
- 工作区目录：`<workspace>/.omniagent/skills/`

### 子智能体

子智能体适合把读取、研究、审计或实现任务交给独立上下文处理。不同模式下可用角色不同，Agent 会根据任务自动选择。

### Agent Team

Agent Team 适合并行处理较大的任务，可使用架构、审查、实现、运维和调试等角色。输入 `/team` 打开 Team 页面并启用该功能。

涉及写文件的成员会受到写入范围限制，以减少并发修改冲突。最终结果仍由主 Agent 汇总。

## 记忆与本地数据

OmniAgent 会在本地保存：

- 长期记忆与用户偏好
- 会话、历史记录和 Todo
- Skills
- 子智能体和 Team 运行数据

普通安装默认保存在 `~/.omniagent/`；源码检出运行时使用仓库根目录。工作区相关状态保存在：

```text
<workspace>/.omniagent/
```

首次运行还会生成 `prompt.md`。你可以在其中填写个人提示词、回复风格或长期角色设定，它会影响普通聊天和 Agent 模式。

## 常见问题

### 无法开启 Agent 模式

请先通过项目选择器选择工作区。未选择项目时，Agent 不会获得项目文件和命令权限。

### 网络搜索显示 `missing key`

输入 `/search`，确认已经：

1. 启用 Web Search。
2. 选择搜索 Provider。
3. 为当前 Provider 填写有效的 API Key。

### Ollama 无法连接

确认 Ollama 服务已经启动，并已拉取需要的模型：

```bash
ollama pull <model>
ollama run <model>
```

同时检查模型档案中的 `base_url` 和模型名是否正确。本地默认 Ollama 服务通常使用 `http://localhost:11434`。

### 模型请求失败或无响应

依次检查：

- API Key 是否有效
- Base URL 是否与接口类型匹配
- 模型名是否存在
- 服务是否正常运行
- 当前网络是否能够访问模型服务

### 终端显示异常

建议使用 Windows Terminal、PowerShell 7、iTerm2、GNOME Terminal 等支持 UTF-8 和 ANSI 颜色的终端。

## 许可证

GNU 通用公共许可证 v3.0
