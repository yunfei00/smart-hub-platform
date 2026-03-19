import json
from pathlib import Path

from .exceptions import AgentError
from .models import Rule

BASE_DIR = Path(__file__).resolve().parent.parent
RULES_FILE = BASE_DIR / "rules.json"


def load_rules() -> list[Rule]:
    if not RULES_FILE.exists():
        raise AgentError("rules.json 不存在", status_code=500)

    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentError(f"rules.json 格式错误: {exc}", status_code=500) from exc

    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise AgentError("rules.json 中 rules 字段必须是数组", status_code=500)

    try:
        return [Rule(**raw) for raw in raw_rules]
    except Exception as exc:  # pydantic validation
        raise AgentError(f"rules.json 规则项校验失败: {exc}", status_code=500) from exc
