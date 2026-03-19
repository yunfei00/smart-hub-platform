import json
from dataclasses import dataclass
from urllib import error, request

from django.conf import settings


class LLMError(Exception):
    """Base error for LLM service failures."""


class LLMConfigError(LLMError):
    """Raised when LLM config is invalid or disabled."""


class LLMServiceUnavailableError(LLMError):
    """Raised when model service is unavailable."""


class LLMTimeoutError(LLMError):
    """Raised when model request times out."""


class LLMEmptyResponseError(LLMError):
    """Raised when model response has no useful answer."""


@dataclass
class LLMToolSuggestion:
    name: str
    args: dict


@dataclass
class LLMResult:
    answer: str
    model: str
    tool_suggestion: LLMToolSuggestion | None = None


class OpenAICompatibleLLMService:
    """Minimal OpenAI-compatible chat completion client."""

    def __init__(self):
        self.enabled = settings.LLM_ENABLED
        self.provider = (settings.LLM_PROVIDER or "").strip().lower()
        self.base_url = (settings.LLM_BASE_URL or "").rstrip("/")
        self.api_key = settings.LLM_API_KEY or ""
        self.model = settings.LLM_MODEL or ""
        self.timeout = settings.LLM_TIMEOUT

    def _validate(self):
        if not self.enabled:
            raise LLMConfigError("LLM 功能未启用，请先设置 LLM_ENABLED=true。")
        if not self.provider:
            raise LLMConfigError("LLM_PROVIDER 未配置。")
        if self.provider not in {"ollama", "vllm"}:
            raise LLMConfigError("LLM_PROVIDER 仅支持 ollama 或 vllm。")
        if not self.base_url:
            raise LLMConfigError("LLM_BASE_URL 未配置。")
        if not self.model:
            raise LLMConfigError("LLM_MODEL 未配置。")

    @staticmethod
    def _base_system_prompt(mode: str) -> str:
        if mode == "code":
            return "你是代码助手。优先给出可执行示例，并附简短说明。"

        return "你是通用问答助手，请给出清晰、简洁、可执行的答案。"

    def _build_messages(self, mode: str, prompt: str, tool_schemas: list[dict] | None) -> list[dict]:
        if tool_schemas:
            tool_schema_json = json.dumps(tool_schemas, ensure_ascii=False)
            system_prompt = (
                f"{self._base_system_prompt(mode)}\n"
                "你可以给出普通文本回答，或建议使用工具。"
                "必须只输出一个 JSON 对象，不要输出其他文本。"
                "JSON 格式："
                '{"response_type":"text","answer":"..."}'
                " 或 "
                '{"response_type":"tool_suggestion","answer":"建议原因",'
                '"tool":{"name":"...","arguments":{...}}}。'
                "禁止建议白名单外工具。"
                f"可用白名单工具：{tool_schema_json}"
            )
        else:
            system_prompt = self._base_system_prompt(mode)

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

    @staticmethod
    def _parse_result(content: str) -> tuple[str, LLMToolSuggestion | None]:
        stripped = content.strip()
        if not stripped:
            raise LLMEmptyResponseError("模型返回为空，请调整提问后重试。")

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped, None

        if not isinstance(payload, dict):
            return stripped, None

        response_type = payload.get("response_type")
        answer = str(payload.get("answer", "")).strip()

        if response_type == "tool_suggestion":
            tool = payload.get("tool", {})
            if isinstance(tool, dict):
                name = str(tool.get("name", "")).strip()
                arguments = tool.get("arguments", {})
                if name and isinstance(arguments, dict):
                    return answer or "建议调用工具。", LLMToolSuggestion(name=name, args=arguments)

        if answer:
            return answer, None

        return stripped, None

    def ask(self, mode: str, prompt: str, tool_schemas: list[dict] | None = None) -> LLMResult:
        self._validate()

        endpoint = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": self._build_messages(mode, prompt, tool_schemas),
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise LLMTimeoutError("模型服务请求超时，请稍后重试。") from exc
        except error.URLError as exc:
            reason = str(getattr(exc, "reason", ""))
            if "timed out" in reason.lower():
                raise LLMTimeoutError("模型服务请求超时，请稍后重试。") from exc
            raise LLMServiceUnavailableError(
                "模型服务不可用，请检查 LLM_BASE_URL 与本地模型进程。"
            ) from exc
        except error.HTTPError as exc:
            detail = ""
            try:
                err_payload = json.loads(exc.read().decode("utf-8"))
                detail = err_payload.get("error", {}).get("message") or err_payload.get("detail") or ""
            except Exception:  # pylint: disable=broad-except
                detail = ""
            suffix = f"（{detail}）" if detail else ""
            raise LLMServiceUnavailableError(f"模型服务返回异常 HTTP {exc.code}{suffix}") from exc
        except json.JSONDecodeError as exc:
            raise LLMServiceUnavailableError("模型服务返回了无效 JSON。") from exc

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        answer, suggestion = self._parse_result(content)
        model_name = data.get("model") or self.model
        return LLMResult(answer=answer, model=model_name, tool_suggestion=suggestion)
