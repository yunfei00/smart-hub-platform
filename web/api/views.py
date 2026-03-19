import json
from urllib import error, request

from django.conf import settings
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services.llm import (
    LLMConfigError,
    LLMEmptyResponseError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    OpenAICompatibleLLMService,
)


class LandingView(TemplateView):
    template_name = "home.html"


class DiskCleanupView(TemplateView):
    template_name = "disk_cleanup.html"

    def _agent_get(self, path: str) -> dict:
        endpoint = f"{settings.AGENT_BASE_URL}{path}"
        with request.urlopen(endpoint, timeout=8) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))

    def _agent_post(self, path: str, payload: dict) -> dict:
        endpoint = f"{settings.AGENT_BASE_URL}{path}"
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=20) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _friendly_agent_error(exc: Exception, action: str) -> str:
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

    def _load_rules(self) -> tuple[list[dict], str | None]:
        try:
            data = self._agent_get("/rules")
            return data.get("rules", []), None
        except Exception as exc:  # pylint: disable=broad-except
            return [], self._friendly_agent_error(exc, "加载规则")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rules, rule_error = self._load_rules()
        context.update(
            {
                "rules": rules,
                "rule_error": rule_error,
                "selected_rule_id": "",
                "scan_result": None,
                "clean_result": None,
                "page_error": None,
                "selected_files": [],
                "rules_config_path": settings.RULES_CONFIG_PATH,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        action = request.POST.get("action")
        selected_rule_id = request.POST.get("rule_id", "")
        selected_files = request.POST.getlist("selected_files")

        context["selected_rule_id"] = selected_rule_id
        context["selected_files"] = selected_files

        if not selected_rule_id:
            context["page_error"] = "请先选择规则。"
            return self.render_to_response(context)

        selected_rule = next(
            (rule for rule in context["rules"] if rule.get("id") == selected_rule_id), None
        )
        if not selected_rule:
            context["page_error"] = "未找到对应规则，请刷新页面后重试。"
            return self.render_to_response(context)

        try:
            if action == "scan":
                context["scan_result"] = self._agent_post(
                    "/scan", {"path": selected_rule.get("path", "")}
                )
            elif action == "clean":
                if not selected_files:
                    context["page_error"] = "请先勾选要清理的项。"
                    return self.render_to_response(context)

                clean_result = self._agent_post(
                    "/clean",
                    {"rule_id": selected_rule_id, "files": selected_files},
                )
                context["clean_result"] = clean_result
                context["scan_result"] = self._agent_post(
                    "/scan", {"path": selected_rule.get("path", "")}
                )
                context["selected_files"] = []
            else:
                context["page_error"] = "不支持的操作。"
        except Exception as exc:  # pylint: disable=broad-except
            context["page_error"] = self._friendly_agent_error(
                exc, "扫描" if action == "scan" else "清理"
            )

        return self.render_to_response(context)


class ToolCenterView(TemplateView):
    template_name = "tool_center.html"

    def _load_tools(self) -> tuple[list[dict], str | None]:
        config_path = settings.TOOL_CONFIG_PATH
        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except FileNotFoundError:
            return [], "工具配置文件不存在，请检查 TOOL_CONFIG_PATH。"
        except json.JSONDecodeError:
            return [], "工具配置格式错误，请检查 JSON 内容。"
        except Exception:  # pylint: disable=broad-except
            return [], "读取工具配置失败，请稍后重试。"

        tools = data.get("tools", []) if isinstance(data, dict) else []
        if not isinstance(tools, list):
            return [], "工具配置格式错误：tools 字段必须是数组。"

        return tools, None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tools, load_error = self._load_tools()
        context.update(
            {
                "tools": tools,
                "load_error": load_error,
                "tool_config_path": settings.TOOL_CONFIG_PATH,
            }
        )
        return context


class AIAssistantView(TemplateView):
    template_name = "ai_assistant.html"

    @staticmethod
    def _default_response() -> dict:
        return {"answer": "", "model": "", "success": False, "error_message": ""}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "mode": "qa",
                "prompt": "",
                "response": self._default_response(),
                "page_error": None,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        mode = request.POST.get("mode", "qa").strip().lower()
        prompt = request.POST.get("prompt", "").strip()

        context["mode"] = mode
        context["prompt"] = prompt

        if mode not in {"qa", "code"}:
            context["page_error"] = "mode 参数不合法。"
            return self.render_to_response(context)

        if not prompt:
            context["page_error"] = "请输入 prompt。"
            return self.render_to_response(context)

        service = OpenAICompatibleLLMService()
        try:
            result = service.ask(mode=mode, prompt=prompt)
            context["response"] = {
                "answer": result.answer,
                "model": result.model,
                "success": True,
                "error_message": "",
            }
        except (
            LLMConfigError,
            LLMServiceUnavailableError,
            LLMTimeoutError,
            LLMEmptyResponseError,
        ) as exc:
            context["response"] = {
                "answer": "",
                "model": settings.LLM_MODEL,
                "success": False,
                "error_message": str(exc),
            }

        return self.render_to_response(context)


class AIAskAPIView(APIView):
    def post(self, request):
        mode = str(request.data.get("mode", "qa")).strip().lower()
        prompt = str(request.data.get("prompt", "")).strip()

        if mode not in {"qa", "code"}:
            return Response(
                {
                    "answer": "",
                    "model": settings.LLM_MODEL,
                    "success": False,
                    "error_message": "mode 参数不合法。",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not prompt:
            return Response(
                {
                    "answer": "",
                    "model": settings.LLM_MODEL,
                    "success": False,
                    "error_message": "prompt 不能为空。",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = OpenAICompatibleLLMService()
        try:
            result = service.ask(mode=mode, prompt=prompt)
            return Response(
                {
                    "answer": result.answer,
                    "model": result.model,
                    "success": True,
                    "error_message": "",
                }
            )
        except (
            LLMConfigError,
            LLMServiceUnavailableError,
            LLMTimeoutError,
            LLMEmptyResponseError,
        ) as exc:
            return Response(
                {
                    "answer": "",
                    "model": settings.LLM_MODEL,
                    "success": False,
                    "error_message": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok", "service": "smart-hub-web"})
