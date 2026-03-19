from dataclasses import dataclass


class ToolValidationError(Exception):
    """Raised when a tool call payload is invalid."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict


def _require_non_empty_string(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"参数 {field_name} 必须是非空字符串。")
    return value.strip()


def validate_disk_scan_rule(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolValidationError("工具参数必须是 JSON 对象。")

    return {"rule_id": _require_non_empty_string(args.get("rule_id"), "rule_id")}


def validate_disk_clean_selected(args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolValidationError("工具参数必须是 JSON 对象。")

    rule_id = _require_non_empty_string(args.get("rule_id"), "rule_id")
    files = args.get("files")

    if not isinstance(files, list) or not files:
        raise ToolValidationError("参数 files 必须是非空数组。")

    normalized_files: list[str] = []
    for file_item in files:
        normalized_files.append(_require_non_empty_string(file_item, "files[]"))

    return {"rule_id": rule_id, "files": normalized_files}


TOOL_DEFINITIONS = {
    "disk_scan_rule": ToolDefinition(
        name="disk_scan_rule",
        description="根据规则 ID 调用本地 agent 执行扫描。",
        parameters={
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
            "additionalProperties": False,
        },
    ),
    "disk_clean_selected": ToolDefinition(
        name="disk_clean_selected",
        description="根据规则 ID 和文件列表调用本地 agent 执行清理。",
        parameters={
            "type": "object",
            "properties": {
                "rule_id": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["rule_id", "files"],
            "additionalProperties": False,
        },
    ),
}
