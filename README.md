# Smart Hub Platform

一个面向组内日常运维的小型平台：提供 Web 统一入口，调用本地 Agent 执行磁盘扫描/清理，并展示常用工具下载信息。当前版本强调“配置化 + 最小可部署”，并在 Phase 12 引入记录中心用于保存历史执行与分析结果。

## 项目简介

- **Web（Django + DRF）**：页面入口、配置读取、错误提示与基础 API。
- **Agent（FastAPI）**：执行规则读取、扫描与清理。
- **配置文件驱动**：工具中心与规则均通过 JSON 管理，便于交付与内网部署。

## 当前功能范围

### 已实现
- 磁盘清理：按规则扫描、勾选、执行清理。
- 工具中心：展示工具信息（名称/版本/分类/平台/状态/下载地址等）。
- AI 助手：本地模型接入（OpenAI 兼容接口，默认 Ollama）+ 推荐入口“推荐 -> 用户点击 -> 页面跳转”。
- 统一配置：支持通过环境变量覆盖关键参数。
- 记录中心：保存并查看磁盘扫描/清理、项目分析、代码分析的历史记录。

### 暂不实现
- 用户系统、权限系统
- 数据库存储业务数据
- 任务调度、远程控制
- MCP、自动脚本执行、仓库读写、RAG/向量数据库、多轮会话记忆

## 目录结构

```text
smart-hub-platform/
├── agent/
│   ├── core/
│   ├── main.py
│   ├── rules.json
│   └── README.md
├── docs/
│   └── README.md
├── web/
│   ├── api/
│   ├── config/
│   │   ├── settings.py
│   │   └── tools.json
│   ├── templates/
│   └── manage.py
└── requirements.txt
```

## 快速启动

### 1) 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 启动 Agent

```bash
uvicorn agent.main:app --reload --host 0.0.0.0 --port 8001
```

- 健康检查：`http://127.0.0.1:8001/health`

### 3) 启动 Web

```bash
cd web
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

- 首页：`http://127.0.0.1:8000/`
- 磁盘清理：`http://127.0.0.1:8000/disk-cleanup/`
- 工具中心：`http://127.0.0.1:8000/tools/`
- AI 助手页面：`http://127.0.0.1:8000/ai-assistant/`
- 项目分析页面：`http://127.0.0.1:8000/project-analysis/`
- 代码分析页面：`http://127.0.0.1:8000/code-analysis/`
- 记录中心页面：`http://127.0.0.1:8000/records/`
- AI 接口：`POST http://127.0.0.1:8000/api/ai/ask/`
- Web 健康检查：`http://127.0.0.1:8000/api/health/`

## 配置文件与环境变量

Web 统一配置位于 `web/config/settings.py`，可通过环境变量覆盖：

- `PROJECT_NAME`：项目名（页面显示）
- `AGENT_BASE_URL`：Web 调用 Agent 的地址
- `TOOL_CONFIG_PATH`：工具配置 JSON 路径（默认 `web/config/tools.json`）
- `RULES_CONFIG_PATH`：规则文件路径说明（默认 `agent/rules.json`）
- `LLM_ENABLED`：是否启用本地模型能力（`true/false`）
- `LLM_PROVIDER`：模型提供方（默认 `ollama`，预留 `vllm`）
- `LLM_BASE_URL`：OpenAI 兼容服务地址（默认 `http://127.0.0.1:11434`）
- `LLM_API_KEY`：可选 API Key（Ollama 通常可留空）
- `LLM_MODEL`：模型名（如 `qwen2.5-coder:32b`）
- `LLM_TIMEOUT`：请求超时秒数（默认 `30`）

### 工具配置结构（`tools.json`）

每个工具支持字段：

- `id`
- `name`
- `version`
- `description`
- `download_url`
- `remark`
- `category`
- `platform`
- `status`


### Ollama 兼容接口示例配置

```bash
export LLM_ENABLED=true
export LLM_PROVIDER=ollama
export LLM_BASE_URL=http://127.0.0.1:11434
export LLM_API_KEY=""
export LLM_MODEL=qwen2.5-coder:32b
export LLM_TIMEOUT=30
```

接口调用示例：

```bash
curl -X POST http://127.0.0.1:8000/api/ai/ask/ \
  -H 'Content-Type: application/json' \
  -d '{"mode":"qa","prompt":"请简述 Python 生成器的用途"}'
```

响应结构：

```json
{
  "answer": "...",
  "model": "qwen2.5-coder:32b",
  "type": "answer",
  "items": [],
  "success": true,
  "error_message": ""
}
```

可选 `mode`：

- `qa`：通用问答
- `code_generation`：代码生成
- `code_explanation`：代码解释
- `script_generation`：脚本生成


## Phase 7.5：AI 推荐规则并跳转页面

当前 AI 助手已切换为“推荐 -> 用户点击 -> 页面跳转”模式，不再执行工具：

1. **输出协议**：模型按 JSON 返回 `answer` / `rule_recommendation` / `page_navigation`。
2. **推荐展示**：页面统一展示推荐按钮，用户点击后跳转目标页面。
3. **后端兜底**：`target_url` 由后端按白名单生成/校验，拒绝任意外链。

### 已支持推荐范围

- 页面入口：`/disk-cleanup/`、`/tools/`
- 规则推荐：基于 `agent/rules.json`（通过 Agent `/rules` 获取）
- 磁盘清理页支持 `rule_id` 参数预选规则，不会自动扫描或自动清理

### 安全限制

- 不执行工具（`/api/ai/tool-execute/` 已禁用）。
- 不自动扫描。
- 不自动清理。
- 不允许任意 URL 跳转。
- 推荐项必须来自系统白名单页面或规则。

## Phase 8：代码助手能力落地（轻量版）

AI 助手页面已扩展为 4 种模式，复用既有本地模型接入（OpenAI 兼容接口）：

1. 通用问答（`qa`）
2. 代码生成（`code_generation`）
3. 代码解释（`code_explanation`）
4. 脚本生成（`script_generation`）

### 当前能力边界

- 仅提供“生成与解释”能力。
- 不读取仓库文件，不直接修改本地文件。
- 不自动执行脚本或命令。
- 不引入多轮记忆、数据库或任务调度。

### 最小测试补充（Phase 8）

- 打开 `/ai-assistant/`，确认可切换 4 种模式并提交请求。
- 在代码相关模式下，输出区应以代码块样式优先展示结果。
- 使用 `/api/ai/ask/` 分别传入 4 种 `mode`，均返回统一响应结构（含 `type/items`）。

## 最小部署说明（组内可交付）

1. 在目标机器拉取代码并安装 Python 依赖。
2. 准备 `agent/rules.json` 与 `web/config/tools.json`。
3. 按需设置环境变量（至少确认 `AGENT_BASE_URL`）。
4. 先启动 Agent，再启动 Web。
5. 通过 `/health` 与页面功能验证服务可用。

## Phase 12：执行记录 / 分析记录中心（最小可用）

本阶段新增“记录中心”（`/records/`），用于保存和展示平台内历史执行结果与分析结果。

### 当前支持的记录类型

- `disk_scan`
- `disk_clean`
- `project_analysis`
- `code_analysis`

### 当前行为（MVP）

- 在以下功能执行成功后自动写入记录：
  - 磁盘扫描
  - 磁盘清理
  - 项目分析
  - 代码分析
- 提供记录列表页与详情页（Django 模板 + Bootstrap）。
- 记录内容以 JSON 存储，详情页可直接查看完整内容。

### 最小测试补充（Phase 12）

1. 执行一次磁盘扫描或清理后，访问 `/records/`，应出现新记录。
2. 执行一次项目分析与代码分析后，`/records/` 中应分别出现对应记录类型。
3. 打开任意记录详情页，确认可看到完整内容（含结构化 JSON）。

## 最小测试说明

建议每次改动后至少执行：

```bash
python -m compileall web agent
cd web && python manage.py check
```

并手工验证：
- Agent 关闭时，磁盘清理页出现友好错误提示。
- 工具配置损坏时，工具中心显示友好错误信息。
- AI 助手页可提交 mode/prompt，并展示回答。
- AI 助手在给出推荐项时，展示可点击按钮并跳转目标页面。
- `/api/ai/ask/` 返回 `type + items`（无推荐时 items 为空数组）。
- `/disk-cleanup/?rule_id=<id>` 会预选规则；非法 rule_id 显示友好提示。
- `/api/ai/tool-execute/` 返回已禁用提示。
- LLM 未配置、超时、服务不可用时，页面和接口返回 error_message。

## Phase 9：上传压缩包分析项目结构（MVP）

新增“项目分析”页面：`/project-analysis/`，用于上传 zip 压缩包并生成项目结构分析报告（仅分析，不改代码）。

### 能力范围（当前版本）

1. 上传 `.zip` 文件，后端保存到临时目录并解压到临时分析目录。
2. 扫描项目结构时默认忽略以下目录：
   - `.git` / `.venv` / `venv` / `node_modules`
   - `dist` / `build` / `__pycache__`
   - `.idea` / `.vscode`
3. 默认仅读取常见文本文件（如 `.py/.js/.ts/.tsx/.html/.css/.json/.yml/.yaml/.md/.sh/.toml/.ini`）。
4. 提取并构建分析上下文（顶层结构、目录树摘要、关键文件、技术栈线索、关键文件片段）。
5. 复用本地模型接入能力（OpenAI 兼容接口）生成分析报告，页面展示：
   - 项目概览
   - 目录结构摘要
   - 关键文件
   - AI 分析报告

### 安全与限制

- 不做自动改代码。
- 不做自动执行代码。
- 不做仓库写回。
- 不做多轮项目记忆。
- 不引入数据库、用户系统、任务调度。
- 不将压缩包全部内容全量发送给模型。

### 最小测试补充（Phase 9）

1. 打开 `/project-analysis/`，上传一个有效 zip，点击“开始分析”，确认页面出现结构摘要与 AI 报告。
2. 上传非 zip 文件，确认页面提示“仅支持 .zip 文件上传”。
3. 未配置 LLM 或本地模型不可达时，确认页面展示友好错误。
4. 勾选“分析完成后清理临时目录（可选）”后提交，确认流程可完成且不影响结果展示。


## Phase 10：单文件与代码片段分析（MVP）

新增“代码分析”页面：`/code-analysis/`，支持代码片段与单文件分析（仅分析，不改代码）。

### 能力范围（当前版本）

1. 支持两种输入方式：
   - 粘贴代码片段
   - 上传单个代码文件
2. 上传文件仅支持常见文本后缀：`.py/.sh/.js/.ts/.json/.yaml/.yml/.md`。
3. 上传文件需为 UTF-8 文本；疑似二进制或非文本内容会被拒绝。
4. 对输入内容做基础大小限制（字符数上限），超限时返回友好提示。
5. 复用本地模型接入能力（OpenAI 兼容接口）并增加独立代码分析 service 层。
6. 页面按结构化模块展示分析结果：
   - 功能说明
   - 核心流程
   - 输入输出
   - 风险点
   - 优化建议

### 安全与限制

- 不实现自动改代码。
- 不实现自动执行代码。
- 不实现仓库写回。
- 不实现多轮记忆。
- 不引入数据库、用户系统、任务调度。

### 最小测试补充（Phase 10）

1. 打开 `/code-analysis/`，选择“粘贴代码片段”，输入任意示例代码后点击“开始分析”，确认页面展示 5 个分析模块。
2. 选择“上传单文件”，上传合法文本文件（如 `.py`），确认可得到分析结果。
3. 上传不在白名单的后缀（如 `.exe`）或非 UTF-8 文件，确认页面出现友好提示。
4. 输入超长代码内容，确认页面提示内容过大而非 traceback。
