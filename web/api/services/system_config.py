from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

from api.models import SystemConfig


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    group: str
    value_type: str
    description: str
    default_value: Any


class SystemConfigService:
    PHASE13_SPECS: tuple[ConfigSpec, ...] = (
        ConfigSpec("PROJECT_NAME", "平台基础配置", "string", "平台名称", settings.PROJECT_NAME),
        ConfigSpec("PROJECT_DESC", "平台基础配置", "string", "平台描述", getattr(settings, "PROJECT_DESC", "")),
        ConfigSpec("AGENT_BASE_URL", "Agent 配置", "string", "Agent 服务地址", settings.AGENT_BASE_URL),
        ConfigSpec(
            "RULES_CONFIG_PATH",
            "Agent 配置",
            "string",
            "规则配置文件路径",
            str(settings.RULES_CONFIG_PATH),
        ),
        ConfigSpec("LLM_ENABLED", "AI 配置", "bool", "是否启用 LLM", settings.LLM_ENABLED),
        ConfigSpec("LLM_PROVIDER", "AI 配置", "string", "LLM 提供方", settings.LLM_PROVIDER),
        ConfigSpec("LLM_BASE_URL", "AI 配置", "string", "LLM 服务地址", settings.LLM_BASE_URL),
        ConfigSpec("LLM_API_KEY", "AI 配置", "string", "LLM API Key", settings.LLM_API_KEY),
        ConfigSpec("LLM_MODEL", "AI 配置", "string", "LLM 模型名", settings.LLM_MODEL),
        ConfigSpec("LLM_TIMEOUT", "AI 配置", "int", "LLM 请求超时（秒）", settings.LLM_TIMEOUT),
        ConfigSpec(
            "TOOL_CONFIG_PATH",
            "工具中心配置",
            "string",
            "工具配置文件路径",
            str(settings.TOOL_CONFIG_PATH),
        ),
    )

    @classmethod
    def ensure_defaults(cls) -> None:
        for spec in cls.PHASE13_SPECS:
            SystemConfig.objects.get_or_create(
                config_key=spec.key,
                defaults={
                    "config_group": spec.group,
                    "config_value": cls._serialize(spec.default_value, spec.value_type),
                    "value_type": spec.value_type,
                    "description": spec.description,
                },
            )

    @classmethod
    def get_value(cls, key: str, fallback: Any, value_type: str = "string") -> Any:
        row = SystemConfig.objects.filter(config_key=key).first()
        if not row:
            return fallback

        target_type = row.value_type or value_type
        try:
            return cls._parse(row.config_value, target_type)
        except ValueError:
            return fallback

    @staticmethod
    def _parse(value: str, value_type: str) -> Any:
        raw = (value or "").strip()
        if value_type == "bool":
            if raw.lower() in {"1", "true", "yes", "on"}:
                return True
            if raw.lower() in {"0", "false", "no", "off"}:
                return False
            raise ValueError("invalid bool")
        if value_type == "int":
            return int(raw)
        return raw

    @staticmethod
    def _serialize(value: Any, value_type: str) -> str:
        if value_type == "bool":
            return "true" if bool(value) else "false"
        return str(value)


class RuntimeConfig:
    @staticmethod
    def project_name() -> str:
        return SystemConfigService.get_value("PROJECT_NAME", settings.PROJECT_NAME, "string")

    @staticmethod
    def project_desc() -> str:
        return SystemConfigService.get_value("PROJECT_DESC", getattr(settings, "PROJECT_DESC", ""), "string")

    @staticmethod
    def agent_base_url() -> str:
        return SystemConfigService.get_value("AGENT_BASE_URL", settings.AGENT_BASE_URL, "string")

    @staticmethod
    def rules_config_path() -> Path:
        raw = SystemConfigService.get_value(
            "RULES_CONFIG_PATH", str(settings.RULES_CONFIG_PATH), "string"
        )
        return Path(raw)

    @staticmethod
    def llm_enabled() -> bool:
        return SystemConfigService.get_value("LLM_ENABLED", settings.LLM_ENABLED, "bool")

    @staticmethod
    def llm_provider() -> str:
        return SystemConfigService.get_value("LLM_PROVIDER", settings.LLM_PROVIDER, "string")

    @staticmethod
    def llm_base_url() -> str:
        return SystemConfigService.get_value("LLM_BASE_URL", settings.LLM_BASE_URL, "string")

    @staticmethod
    def llm_api_key() -> str:
        return SystemConfigService.get_value("LLM_API_KEY", settings.LLM_API_KEY, "string")

    @staticmethod
    def llm_model() -> str:
        return SystemConfigService.get_value("LLM_MODEL", settings.LLM_MODEL, "string")

    @staticmethod
    def llm_timeout() -> int:
        return SystemConfigService.get_value("LLM_TIMEOUT", settings.LLM_TIMEOUT, "int")

    @staticmethod
    def tool_config_path() -> Path:
        raw = SystemConfigService.get_value("TOOL_CONFIG_PATH", str(settings.TOOL_CONFIG_PATH), "string")
        return Path(raw)
