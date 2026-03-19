import json
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from django.conf import settings
from django.urls import reverse
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services.llm import (
    LLMConfigError,
    LLMEmptyResponseError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
)
from .services.llm.mode_handler import LLMModes
from .services.project_analysis import InvalidZipFileError, ProjectAnalysisError, ProjectAnalysisService


@dataclass(frozen=True)
class NavigationItem:
    label: str
    target_url: str


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
        selected_rule_id = self.request.GET.get("rule_id", "").strip()
        page_error = None
        if selected_rule_id and not any(rule.get("id") == selected_rule_id for rule in rules):
            page_error = "推荐规则不存在或已失效，请重新选择规则。"
            selected_rule_id = ""

        context.update(
            {
                "rules": rules,
                "rule_error": rule_error,
                "selected_rule_id": selected_rule_id,
                "scan_result": None,
                "clean_result": None,
                "page_error": page_error,
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
        return {"answer": "", "model": "", "success": False, "error_message": "", "type": "answer", "render_as_code": False}

    @staticmethod
    def _page_whitelist() -> dict[str, NavigationItem]:
        return {
            "disk_cleanup": NavigationItem(
                label="磁盘清理",
                target_url=reverse("disk-cleanup"),
            ),
            "tool_center": NavigationItem(
                label="工具中心",
                target_url=reverse("tool-center"),
            ),
        }

    def _load_rules(self) -> list[dict]:
        try:
            endpoint = f"{settings.AGENT_BASE_URL}/rules"
            with request.urlopen(endpoint, timeout=8) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8")).get("rules", [])
        except Exception:  # pylint: disable=broad-except
            return []

    def _recommendation_context(self) -> dict:
        pages = [
            {"page_key": page_key, "label": item.label, "target_url": item.target_url}
            for page_key, item in self._page_whitelist().items()
        ]
        rules = [
            {"rule_id": str(rule.get("id", "")).strip(), "label": str(rule.get("name", "")).strip()}
            for rule in self._load_rules()
            if str(rule.get("id", "")).strip() and str(rule.get("name", "")).strip()
        ]
        return {"pages": pages, "rules": rules}

    def _normalize_recommendations(self, response_type: str, items: list[dict] | None) -> list[dict]:
        if not items:
            return []

        normalized: list[dict] = []
        pages = self._page_whitelist()
        rules = {str(rule.get("id")) for rule in self._load_rules() if str(rule.get("id", "")).strip()}

        for item in items:
            label = str(item.get("label", "")).strip()
            if not label:
                continue

            if response_type == "rule_recommendation":
                rule_id = str(item.get("rule_id", "")).strip()
                if not rule_id or rule_id not in rules:
                    continue
                target_url = f"{reverse('disk-cleanup')}?rule_id={rule_id}"
                normalized.append({"label": label, "rule_id": rule_id, "target_url": target_url})
                continue

            if response_type == "page_navigation":
                target_url = str(item.get("target_url", "")).strip()
                page = next((value for value in pages.values() if value.target_url == target_url), None)
                if not page:
                    continue
                normalized.append({"label": label, "target_url": page.target_url})

        return normalized

    @staticmethod
    def _should_render_as_code(mode: str, answer: str) -> bool:
        code_modes = {
            LLMModes.CODE_GENERATION,
            LLMModes.CODE_EXPLANATION,
            LLMModes.SCRIPT_GENERATION,
        }
        if mode in code_modes:
            return True
        return "```" in (answer or "")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "mode": LLMModes.GENERAL_QA,
                "prompt": "",
                "response": self._default_response(),
                "recommendation_items": [],
                "page_error": None,
            }
        )
        return context

    def _handle_ask(self, context: dict, mode: str, prompt: str) -> None:
        service = OpenAICompatibleLLMClient()
        result = service.ask(mode=mode, prompt=prompt, recommendation_context=self._recommendation_context())
        context["response"] = {
            "answer": result.message,
            "model": result.model,
            "type": result.response_type,
            "success": True,
            "error_message": "",
            "render_as_code": self._should_render_as_code(mode, result.message),
        }
        context["recommendation_items"] = self._normalize_recommendations(
            result.response_type, result.items
        )

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        action = request.POST.get("action", "ask").strip().lower()
        mode = request.POST.get("mode", LLMModes.GENERAL_QA).strip().lower()
        prompt = request.POST.get("prompt", "").strip()

        context["mode"] = mode
        context["prompt"] = prompt

        if mode not in LLMModes.ALL:
            context["page_error"] = "mode 参数不合法。"
            return self.render_to_response(context)

        if action == "ask":
            if not prompt:
                context["page_error"] = "请输入 prompt。"
                return self.render_to_response(context)

            try:
                self._handle_ask(context, mode, prompt)
            except (
                LLMConfigError,
                LLMServiceUnavailableError,
                LLMTimeoutError,
                LLMEmptyResponseError,
            ) as exc:
                context["response"] = {
                    "answer": "",
                    "model": settings.LLM_MODEL,
                    "type": "answer",
                    "success": False,
                    "error_message": str(exc),
                    "render_as_code": False,
                }
            return self.render_to_response(context)

        context["page_error"] = "不支持的 action。"
        return self.render_to_response(context)


class ProjectAnalysisView(TemplateView):
    template_name = "project_analysis.html"

    @staticmethod
    def _default_context() -> dict:
        return {
            "analysis_result": None,
            "page_error": None,
            "uploaded_filename": "",
            "cleanup_enabled": False,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self._default_context())
        return context

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        uploaded_file = request.FILES.get("zip_file")
        cleanup_enabled = request.POST.get("cleanup", "") == "1"
        context["cleanup_enabled"] = cleanup_enabled

        if not uploaded_file:
            context["page_error"] = "请先选择 zip 文件。"
            return self.render_to_response(context)

        context["uploaded_filename"] = uploaded_file.name
        service = ProjectAnalysisService()
        work_dir = ""
        try:
            result = service.analyze(uploaded_file)
            work_dir = str(Path(result.context.extract_dir).parent)
            context["analysis_result"] = {
                "project_name": result.context.project_name,
                "extract_dir": result.context.extract_dir,
                "top_level_items": result.context.top_level_items,
                "tree_summary": result.context.tree_summary,
                "key_files": result.context.key_files,
                "tech_stack_clues": result.context.tech_stack_clues,
                "file_summaries": result.context.file_summaries,
                "ai_report": result.ai_report,
            }
        except InvalidZipFileError as exc:
            context["page_error"] = str(exc)
        except (
            LLMConfigError,
            LLMServiceUnavailableError,
            LLMTimeoutError,
            LLMEmptyResponseError,
        ) as exc:
            context["page_error"] = f"模型分析失败：{exc}"
        except ProjectAnalysisError as exc:
            context["page_error"] = str(exc)
        finally:
            if cleanup_enabled and work_dir:
                service.cleanup(work_dir)

        return self.render_to_response(context)


class AIAskAPIView(APIView):
    def post(self, request):
        mode = str(request.data.get("mode", LLMModes.GENERAL_QA)).strip().lower()
        prompt = str(request.data.get("prompt", "")).strip()

        if mode not in LLMModes.ALL:
            return Response(
                {
                    "answer": "",
                    "model": settings.LLM_MODEL,
                    "success": False,
                    "error_message": "mode 参数不合法。",
                    "type": "answer",
                    "items": [],
                    "render_as_code": False,
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
                    "type": "answer",
                    "items": [],
                    "render_as_code": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = OpenAICompatibleLLMClient()
        view = AIAssistantView()
        try:
            result = service.ask(
                mode=mode,
                prompt=prompt,
                recommendation_context=view._recommendation_context(),  # pylint: disable=protected-access
            )
            items = view._normalize_recommendations(  # pylint: disable=protected-access
                result.response_type, result.items
            )
            return Response(
                {
                    "answer": result.message,
                    "model": result.model,
                    "success": True,
                    "error_message": "",
                    "type": result.response_type,
                    "items": items,
                    "render_as_code": view._should_render_as_code(mode, result.message),  # pylint: disable=protected-access
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
                    "type": "answer",
                    "items": [],
                    "render_as_code": False,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class AIToolExecuteAPIView(APIView):
    def post(self, request):
        return Response(
            {"success": False, "error_message": "Phase 7.5 已禁用工具执行接口。", "result": None},
            status=status.HTTP_400_BAD_REQUEST,
        )


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok", "service": "smart-hub-web"})
