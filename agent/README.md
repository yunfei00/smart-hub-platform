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
printf 'world\n' > tmp/sample-downloads/b.txt
```

3. 扫描（命中 rules.json 中允许路径）：
```bash
curl -X POST http://127.0.0.1:9000/scan \
  -H 'Content-Type: application/json' \
  -d '{"path":"./tmp/sample-downloads"}'
```

4. 清理（删除规则路径内文件）：
```bash
curl -X POST http://127.0.0.1:9000/clean \
  -H 'Content-Type: application/json' \
  -d '{"rule_id":"sample-downloads", "files":["./tmp/sample-downloads/a.txt"]}'
```

5. 清理非法路径（应跳过并返回 failed_files）：
```bash
curl -X POST http://127.0.0.1:9000/clean \
  -H 'Content-Type: application/json' \
  -d '{"rule_id":"sample-downloads", "files":["./tmp/not-allowed/x.txt"]}'
```
