import json
from urllib import error, request

from api.services.system_config import RuntimeConfig


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""


class AgentClient:
    def __init__(self):
        self.base_url = RuntimeConfig.agent_base_url().rstrip("/")

    def get(self, path: str) -> dict:
        endpoint = f"{self.base_url}{path}"
        try:
            with request.urlopen(endpoint, timeout=8) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            raise ToolExecutionError(self._friendly_error(exc, "访问 agent 接口")) from exc

    def post(self, path: str, payload: dict, timeout: int = 20) -> dict:
        endpoint = f"{self.base_url}{path}"
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            raise ToolExecutionError(self._friendly_error(exc, "调用 agent 接口")) from exc

    @staticmethod
    def _friendly_error(exc: Exception, action: str) -> str:
        if isinstance(exc, error.URLError):
            return f"Agent 服务暂不可用，无法{action}。请检查 Agent 是否启动。"

        if isinstance(exc, error.HTTPError):
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("error") or payload.get("detail") or ""
            except Exception:  # pylint: disable=broad-except
                detail = ""
            suffix = f"（{detail}）" if detail else ""
            return f"Agent 请求失败，无法{action}（HTTP {exc.code}）{suffix}"

        return f"{action}失败，请稍后重试。"


class ToolExecutor:
    def __init__(self):
        self.agent_client = AgentClient()

    def execute_disk_scan_rule(self, args: dict) -> dict:
        rule_id = args["rule_id"]
        rules_payload = self.agent_client.get("/rules")
        rules = rules_payload.get("rules", [])
        selected_rule = next((rule for rule in rules if rule.get("id") == rule_id), None)
        if not selected_rule:
            raise ToolExecutionError("rule_id 不存在或不可用。")

        path = selected_rule.get("path", "")
        if not path:
            raise ToolExecutionError("规则未配置有效 path，无法扫描。")

        return self.agent_client.post("/scan", {"path": path})

    def execute_disk_clean_selected(self, args: dict) -> dict:
        return self.agent_client.post(
            "/clean",
            {"rule_id": args["rule_id"], "files": args["files"]},
        )
