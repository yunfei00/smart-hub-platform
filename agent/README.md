# Agent Phase 1（核心能力）

## 本地运行

```bash
uvicorn agent.main:app --reload --host 0.0.0.0 --port 9000
```

## 最小测试

1. 查看规则：
```bash
curl http://127.0.0.1:9000/rules
```

2. 创建示例目录与文件：
```bash
mkdir -p tmp/sample-downloads
printf 'hello\n' > tmp/sample-downloads/a.txt
```

3. 扫描（命中 rules.json 中允许路径）：
```bash
curl -X POST http://127.0.0.1:9000/scan \
  -H 'Content-Type: application/json' \
  -d '{"path":"./tmp/sample-downloads"}'
```

4. 扫描非法路径（应返回 403）：
```bash
curl -X POST http://127.0.0.1:9000/scan \
  -H 'Content-Type: application/json' \
  -d '{"path":"./tmp/not-allowed"}'
```
