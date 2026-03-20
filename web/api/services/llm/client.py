import json
import logging
from dataclasses import dataclass
from urllib import error, request

from api.services.system_config import RuntimeConfig

from .mode_handler import LLMPromptBuilder
from .tool_parser import LLMResponseFormatError, ParsedLLMResponse, parse_llm_response

logger = logging.getLogger(__name__)


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
class LLMResult:
    message: str
    model: str
    response_type: str
    items: list[dict] | None = None


@dataclass
class _CompletionMessage:
    content: str | list | None


@dataclass
class _CompletionChoice:
    message: _CompletionMessage
    finish_reason: str | None


@dataclass
class _ChatCompletion:
    model: str
    choices: list[_CompletionChoice]


class _ChatCompletionsAPI:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def create(self, model: str, messages: list[dict], timeout: int) -> _ChatCompletion:
        endpoint = f"{self.base_url}chat/completions"
        payload = {"model": model, "messages": messages}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))

        raw_choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        choices = [
            _CompletionChoice(
                message=_CompletionMessage(content=(choice.get("message", {}) or {}).get("content")),
                finish_reason=choice.get("finish_reason"),
            )
            for choice in raw_choices
            if isinstance(choice, dict)
        ]
        return _ChatCompletion(model=str(data.get("model") or model), choices=choices)


class _ChatAPI:
    def __init__(self, base_url: str, api_key: str):
        self.completions = _ChatCompletionsAPI(base_url=base_url, api_key=api_key)


class _OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str):
        self.chat = _ChatAPI(base_url=base_url, api_key=api_key)


class OpenAICompatibleLLMClient:
    """Minimal OpenAI-compatible chat completion client."""

    def __init__(self):
        self.enabled = RuntimeConfig.llm_enabled()
        self.provider = (RuntimeConfig.llm_provider() or "").strip().lower()
        self.base_url = (RuntimeConfig.llm_base_url() or "").rstrip("/")
        self.api_key = RuntimeConfig.llm_api_key() or ""
        self.model = RuntimeConfig.llm_model() or ""
        self.timeout = RuntimeConfig.llm_timeout()
        self.prompt_builder = LLMPromptBuilder()
        self._api_style = self._detect_api_style()

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
        if self._api_style in {"ollama_native_chat", "ollama_native_generate"}:
            raise LLMConfigError(
                "当前 LLM_BASE_URL 指向 Ollama 原生接口路径，请改为 OpenAI 兼容地址（如 http://localhost:11434/v1/）。"
            )

    def _detect_api_style(self) -> str:
        lower_url = self.base_url.lower()
        if "/api/chat" in lower_url:
            return "ollama_native_chat"
        if "/api/generate" in lower_url:
            return "ollama_native_generate"
        if "/v1/responses" in lower_url:
            return "openai_compatible_responses"
        if "/v1/chat/completions" in lower_url:
            return "openai_compatible_chat_completions"
        return "openai_compatible_base"

    def _normalize_openai_base_url(self) -> str:
        normalized = (self.base_url or "").rstrip("/")
        if normalized.endswith("/v1"):
            return f"{normalized}/"
        return f"{normalized}/v1/"

    @staticmethod
    def _extract_message_content(chat_completion) -> str:
        if not chat_completion.choices:
            return ""
        message = chat_completion.choices[0].message
        content = message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not item:
                    continue
                if isinstance(item, dict):
                    text = str(item.get("text", "")).strip()
                else:
                    text = str(getattr(item, "text", "")).strip()
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        return ""

    def _build_client(self, base_url: str, api_key: str) -> _OpenAICompatClient:
        return _OpenAICompatClient(base_url=base_url, api_key=api_key)

    @staticmethod
    def _from_parsed(parsed: ParsedLLMResponse, model_name: str) -> LLMResult:
        if parsed.response_type in {"rule_recommendation", "page_navigation"} and parsed.items:
            return LLMResult(
                message=parsed.message,
                model=model_name,
                response_type=parsed.response_type,
                items=[
                    {
                        "label": item.label,
                        "rule_id": item.rule_id,
                        "target_url": item.target_url,
                    }
                    for item in parsed.items
                ],
            )

        return LLMResult(
            message=parsed.message,
            model=model_name,
            response_type="answer",
            items=None,
        )

    def _request_completion(self, messages: list[dict]) -> tuple[_ChatCompletion, str]:
        self._validate()
        base_url = self._normalize_openai_base_url()
        api_key = self.api_key or "ollama"
        client = self._build_client(base_url=base_url, api_key=api_key)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=self.timeout,
            )
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

        logger.debug(
            "LLM response received: model=%s choices=%s finish_reason=%s",
            response.model,
            len(response.choices),
            response.choices[0].finish_reason if response.choices else None,
        )
        content = self._extract_message_content(response)
        if not content:
            raise LLMEmptyResponseError("模型返回为空，请调整提问后重试。")
        return response, content

    def ask_raw(self, mode: str, prompt: str, recommendation_context: dict) -> LLMResult:
        messages = self.prompt_builder.build_messages(mode, prompt, recommendation_context)
        logger.debug(
            "LLM raw request prepared: provider=%s api_style=%s base_url=%s model=%s mode=%s",
            self.provider,
            self._api_style,
            self._normalize_openai_base_url(),
            self.model,
            mode,
        )
        response, content = self._request_completion(messages)
        return LLMResult(
            message=content,
            model=response.model or self.model,
            response_type="answer",
            items=None,
        )

    def ask_with_history(
        self,
        mode: str,
        prompt: str,
        recommendation_context: dict,
        history_messages: list[dict],
    ) -> LLMResult:
        messages = self.prompt_builder.build_messages_with_history(
            mode,
            prompt,
            recommendation_context,
            history_messages=history_messages,
        )
        logger.debug(
            "LLM request prepared with history: provider=%s api_style=%s base_url=%s model=%s mode=%s history=%s",
            self.provider,
            self._api_style,
            self._normalize_openai_base_url(),
            self.model,
            mode,
            len(history_messages),
        )
        response, content = self._request_completion(messages)

        try:
            parsed = parse_llm_response(content)
        except LLMResponseFormatError as exc:
            logger.debug("LLM response parse failed. Raw content=%s", content)
            raise LLMEmptyResponseError(str(exc)) from exc

        model_name = response.model or self.model
        return self._from_parsed(parsed, model_name)

    def ask(self, mode: str, prompt: str, recommendation_context: dict) -> LLMResult:
        messages = self.prompt_builder.build_messages(mode, prompt, recommendation_context)
        logger.debug(
            "LLM request prepared: provider=%s api_style=%s base_url=%s model=%s mode=%s",
            self.provider,
            self._api_style,
            self._normalize_openai_base_url(),
            self.model,
            mode,
        )
        response, content = self._request_completion(messages)

        try:
            parsed = parse_llm_response(content)
        except LLMResponseFormatError as exc:
            logger.debug("LLM response parse failed. Raw content=%s", content)
            raise LLMEmptyResponseError(str(exc)) from exc

        model_name = response.model or self.model
        return self._from_parsed(parsed, model_name)
