from dataclasses import dataclass

from ..tool_schemas import (
    TOOL_DEFINITIONS,
    ToolValidationError,
    validate_disk_clean_selected,
    validate_disk_scan_rule,
)
from .tool_executor import ToolExecutor


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict


class ToolRegistry:
    def __init__(self):
        self.tool_executor = ToolExecutor()
        self._validators = {
            "disk_scan_rule": validate_disk_scan_rule,
            "disk_clean_selected": validate_disk_clean_selected,
        }

    def list_tool_schemas(self) -> list[dict]:
        schemas = []
        for tool_name in ("disk_scan_rule", "disk_clean_selected"):
            tool_def = TOOL_DEFINITIONS[tool_name]
            schemas.append(
                {
                    "name": tool_name,
                    "description": tool_def.description,
                    "parameters": tool_def.parameters,
                }
            )
        return schemas

    def validate_tool_call(self, name: str, raw_args: dict) -> ToolCall:
        validator = self._validators.get(name)
        if not validator:
            raise ToolValidationError(f"工具 {name} 不在白名单中。")

        validated_args = validator(raw_args)
        return ToolCall(name=name, args=validated_args)

    def execute(self, tool_call: ToolCall) -> dict:
        if tool_call.name == "disk_scan_rule":
            return self.tool_executor.execute_disk_scan_rule(tool_call.args)

        if tool_call.name == "disk_clean_selected":
            return self.tool_executor.execute_disk_clean_selected(tool_call.args)

        raise ToolValidationError(f"工具 {tool_call.name} 不在白名单中。")
