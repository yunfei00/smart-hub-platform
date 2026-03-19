import json
from dataclasses import dataclass


class LLMResponseFormatError(Exception):
    """Raised when model output does not match the agreed JSON protocol."""


@dataclass(frozen=True)
class ParsedRecommendationItem:
    label: str
    rule_id: str | None = None
    target_url: str | None = None


@dataclass(frozen=True)
class ParsedLLMResponse:
    response_type: str
    message: str
    items: list[ParsedRecommendationItem] | None = None


def _parse_items(payload: dict, response_type: str) -> list[ParsedRecommendationItem]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise LLMResponseFormatError(f"{response_type} 格式错误：items 必须是非空数组。")

    items: list[ParsedRecommendationItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise LLMResponseFormatError(f"{response_type} 格式错误：items 元素必须是对象。")

        label = str(item.get("label", "")).strip()
        if not label:
            raise LLMResponseFormatError(f"{response_type} 格式错误：label 必填。")

        if response_type == "rule_recommendation":
            rule_id = str(item.get("rule_id", "")).strip()
            if not rule_id:
                raise LLMResponseFormatError("rule_recommendation 格式错误：rule_id 必填。")
            items.append(ParsedRecommendationItem(label=label, rule_id=rule_id))
            continue

        target_url = str(item.get("target_url", "")).strip()
        if not target_url:
            raise LLMResponseFormatError("page_navigation 格式错误：target_url 必填。")
        items.append(ParsedRecommendationItem(label=label, target_url=target_url))

    return items


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

    if response_type in {"rule_recommendation", "page_navigation"}:
        return ParsedLLMResponse(
            response_type=response_type,
            message=message,
            items=_parse_items(payload, response_type),
        )

    raise LLMResponseFormatError(
        "模型返回 type 非法，仅支持 answer、rule_recommendation 或 page_navigation。"
    )
