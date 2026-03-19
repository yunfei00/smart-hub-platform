# smart-hub-platform (V1 Skeleton)

Smart Hub Platform 第一版工程骨架，包含：
- `web/`: Django + DRF（提供 Web 页面与 API 骨架）
- `agent/`: FastAPI（提供 agent 服务最小入口）
- `docs/`: 项目文档目录

## V1 范围

### 当前要做
1. 本机磁盘清理
2. Web 页面操作（扫描 / 预览 / 执行）
3. 工具中心（工具说明 + 下载地址）

### 当前不做
- 用户系统
- 复杂 AI
- 自动任务调度
- 远程控制

## 快速开始

### 1) 安装依赖
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 启动 Web（Django + DRF）
```bash
cd web
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```
- 首页（磁盘清理页面）：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/api/health/`
- 页面会调用本地 Agent：`http://127.0.0.1:8001` 的 `/rules`、`/scan`、`/clean`

### 3) 启动 Agent（FastAPI）
```bash
uvicorn agent.main:app --reload --host 0.0.0.0 --port 8001
```
- 健康检查：`http://127.0.0.1:8001/health`

## 目录结构

```text
smart-hub-platform/
├── agent/
│   └── main.py
├── docs/
│   └── README.md
├── web/
│   ├── api/
│   │   ├── apps.py
│   │   └── views.py
│   ├── config/
│   │   ├── asgi.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── templates/
│   │   └── home.html
│   └── manage.py
└── requirements.txt
```

## 说明

当前仅提供最小可运行骨架，业务逻辑后续按模块逐步补充。
