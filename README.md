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
- AI 助手入口：仅占位，支持配置项预留。
- 统一配置：支持通过环境变量覆盖关键参数。

### 暂不实现
- 用户系统、权限系统
- 数据库存储业务数据
- 任务调度、远程控制
- AI 模型接入、MCP、代码生成

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
- Web 健康检查：`http://127.0.0.1:8000/api/health/`

## 配置文件与环境变量

Web 统一配置位于 `web/config/settings.py`，可通过环境变量覆盖：

- `PROJECT_NAME`：项目名（页面显示）
- `AGENT_BASE_URL`：Web 调用 Agent 的地址
- `TOOL_CONFIG_PATH`：工具配置 JSON 路径（默认 `web/config/tools.json`）
- `RULES_CONFIG_PATH`：规则文件路径说明（默认 `agent/rules.json`）
- `AI_ENABLED`：是否启用 AI 入口（仅占位）
- `AI_PROVIDER`：AI 提供方（占位）
- `AI_BASE_URL`：AI 服务地址（占位）
- `AI_MODEL`：AI 模型名（占位）

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
