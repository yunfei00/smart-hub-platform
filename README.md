# Smart Hub Platform

一个面向组内日常运维的小型平台：提供 Web 统一入口，调用本地 Agent 执行磁盘扫描/清理，并展示常用工具下载信息。当前版本强调“配置化 + 最小可部署”，不引入数据库驱动业务功能。

## 项目简介

- **Web（Django + DRF）**：页面入口、配置读取、错误提示与基础 API。
- **Agent（FastAPI）**：执行规则读取、扫描与清理。
- **配置文件驱动**：工具中心与规则均通过 JSON 管理，便于交付与内网部署。

## 当前功能范围

### 已实现
- 磁盘清理：按规则扫描、勾选、执行清理。
- 工具中心：展示工具信息（名称/版本/分类/平台/状态/下载地址等）。
- AI 助手：本地模型接入（OpenAI 兼容接口，默认 Ollama）+ 白名单工具“建议 -> 确认 -> 执行”。
- 统一配置：支持通过环境变量覆盖关键参数。

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
  "success": true,
  "error_message": ""
}
```


## Phase 7：AI 助手接入白名单工具调用

当前 AI 助手采用“建议 -> 确认 -> 执行”的安全闭环：

1. **建议**：模型仅按稳定 JSON 协议输出两类结果：`answer` 或 `tool_call`。
2. **确认**：页面展示工具名、参数和建议说明，等待用户点击“确认执行”。
3. **执行**：后端对白名单工具和参数二次校验，再调用 Agent 返回结果。

### 白名单工具（第一批）

- `disk_scan_rule`：参数 `rule_id`，通过 rule_id 查规则路径后调用 `/scan`。
- `disk_clean_selected`：参数 `rule_id, files`，调用 `/clean`。

### 安全限制

- 不支持自动执行。
- 不允许模型执行任意命令。
- 不允许传入任意路径（仅允许通过 `rule_id` 间接解析规则路径）。
- 仅允许白名单工具（当前仅 `disk_scan_rule` / `disk_clean_selected`），参数必须校验。
- 仍依赖 Agent 侧规则白名单做最终校验。

## 最小部署说明（组内可交付）

1. 在目标机器拉取代码并安装 Python 依赖。
2. 准备 `agent/rules.json` 与 `web/config/tools.json`。
3. 按需设置环境变量（至少确认 `AGENT_BASE_URL`）。
4. 先启动 Agent，再启动 Web。
5. 通过 `/health` 与页面功能验证服务可用。

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
- AI 助手在给出工具建议时，会展示工具名/参数预览，确认后才执行并显示结果。
- `/api/ai/ask/` 返回 `tool_suggestion`（如有建议）。
- `/api/ai/tool-execute/` 仅执行白名单工具并返回结果。
- LLM 未配置、超时、服务不可用时，页面和接口返回 error_message。
