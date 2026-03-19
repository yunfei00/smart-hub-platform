import json
from dataclasses import dataclass


class LLMResponseFormatError(Exception):
    """Raised when model output does not match the agreed JSON protocol."""


@dataclass(frozen=True)
class ParsedToolCall:
    tool_name: str
    arguments: dict


@dataclass(frozen=True)
class ParsedLLMResponse:
    response_type: str
    message: str
    tool_call: ParsedToolCall | None = None


def parse_llm_response(content: str) -> ParsedLLMResponse:
    raw = (content or "").strip()
    if not raw:
        raise LLMResponseFormatError("模型返回为空，请调整提问后重试。")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(
            "模型返回格式不符合 JSON 协议，请重试。"
        ) from exc

    if not isinstance(payload, dict):
        raise LLMResponseFormatError("模型返回必须为 JSON 对象。")

    response_type = str(payload.get("type", "")).strip()
    message = str(payload.get("message", "")).strip()
    if not message:
        raise LLMResponseFormatError("模型返回缺少 message 字段。")

    if response_type == "answer":
        return ParsedLLMResponse(response_type="answer", message=message)

    if response_type == "tool_call":
        tool_name = str(payload.get("tool_name", "")).strip()
        arguments = payload.get("arguments")
        if not tool_name or not isinstance(arguments, dict):
            raise LLMResponseFormatError("tool_call 格式错误：tool_name/arguments 不合法。")

        return ParsedLLMResponse(
            response_type="tool_call",
            message=message,
            tool_call=ParsedToolCall(tool_name=tool_name, arguments=arguments),
        )

    raise LLMResponseFormatError("模型返回 type 非法，仅支持 answer 或 tool_call。")
