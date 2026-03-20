import json
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from django.shortcuts import get_object_or_404
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
from .models import Conversation, ExecutionRecord, Message, SystemConfig, UploadFileRecord
from .services.project_analysis import InvalidZipFileError, ProjectAnalysisError, ProjectAnalysisService
from .services.code_analysis import CodeAnalysisError, CodeAnalysisService, InvalidCodeInputError
from .services.dashboard import DashboardService
from .services.record_center import RecordCenterService
from .services.system_config import RuntimeConfig, SystemConfigService
from .services.file_record import UploadFileRecordService


@dataclass(frozen=True)
class NavigationItem:
    label: str
    target_url: str


class LandingView(TemplateView):
    template_name = "home.html"


class DiskCleanupView(TemplateView):
    template_name = "disk_cleanup.html"

    def _agent_get(self, path: str) -> dict:
        endpoint = f"{RuntimeConfig.agent_base_url()}{path}"
        with request.urlopen(endpoint, timeout=8) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))

    def _agent_post(self, path: str, payload: dict) -> dict:
        endpoint = f"{RuntimeConfig.agent_base_url()}{path}"
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
                "rules_config_path": RuntimeConfig.rules_config_path(),
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
                RecordCenterService.create_record(
                    record_type=ExecutionRecord.TYPE_DISK_SCAN,
                    title=f"磁盘扫描：{selected_rule.get('name', '未命名规则')}",
                    summary=(
                        f"扫描到 {context['scan_result'].get('file_count', 0)} 项，"
                        f"总大小 {context['scan_result'].get('total_size', 0)} bytes。"
                    ),
                    content={"rule": selected_rule, "scan_result": context["scan_result"]},
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
                RecordCenterService.create_record(
                    record_type=ExecutionRecord.TYPE_DISK_CLEAN,
                    title=f"磁盘清理：{selected_rule.get('name', '未命名规则')}",
                    summary=(
                        f"清理 {clean_result.get('deleted_count', 0)} 项，"
                        f"释放 {clean_result.get('freed_size', 0)} bytes。"
                    ),
                    content={
                        "rule": selected_rule,
                        "selected_files": selected_files,
                        "clean_result": clean_result,
                    },
                )
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
        config_path = RuntimeConfig.tool_config_path()
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
                "tool_config_path": RuntimeConfig.tool_config_path(),
            }
        )
        return context


class RecordCenterListView(TemplateView):
    template_name = "record_center_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"records": ExecutionRecord.objects.all()[:100]})
        return context


class RecordCenterDetailView(TemplateView):
    template_name = "record_center_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = get_object_or_404(ExecutionRecord, pk=kwargs.get("record_id"))
        context.update({"record": record})
        return context




class UploadFileCenterView(TemplateView):
    template_name = "upload_file_center.html"

    @staticmethod
    def _format_size(size_in_bytes: int | None) -> str:
        if size_in_bytes is None:
            return "-"

        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(size_in_bytes)
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.2f} {units[idx]}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        records = list(UploadFileRecord.objects.all()[:200])
        rows: list[dict] = []

        for record in records:
            nav = UploadFileRecordService.SOURCE_NAVIGATION.get(record.source_module)
            rows.append(
                {
                    "record": record,
                    "file_exists": UploadFileRecordService.file_exists(record),
                    "file_size_display": self._format_size(record.file_size),
                    "source_nav": nav,
                }
            )

        context.update(
            {
                "files": rows,
                "page_error": self.request.GET.get("error", ""),
                "page_success": self.request.GET.get("success", ""),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        record_id = request.POST.get("record_id", "").strip()
        if not record_id.isdigit():
            context = self.get_context_data(**kwargs)
            context["page_error"] = "记录 ID 非法。"
            return self.render_to_response(context)

        record = get_object_or_404(UploadFileRecord, pk=int(record_id))
        _, warning = UploadFileRecordService.delete_record_and_file(record)

        if warning:
            context = self.get_context_data(**kwargs)
            context["page_success"] = "文件记录已删除。"
            context["page_error"] = warning
            return self.render_to_response(context)

        context = self.get_context_data(**kwargs)
        context["page_success"] = "文件记录与本地文件已删除。"
        return self.render_to_response(context)


class DashboardView(TemplateView):
    template_name = "dashboard.html"

    @staticmethod
    def _format_size(size_in_bytes: int | None) -> str:
        if size_in_bytes is None:
            return "-"

        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(size_in_bytes)
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.2f} {units[idx]}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stats = DashboardService.build_stats()
        context.update(
            {
                "stats": stats,
                "total_freed_display": self._format_size(stats.total_freed_bytes),
                "ai_assistant_display": (
                    str(stats.ai_assistant_count)
                    if stats.ai_assistant_count is not None
                    else "暂不可统计"
                ),
            }
        )
        return context


class SystemConfigListView(TemplateView):
    template_name = "system_config_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        SystemConfigService.ensure_defaults()
        context.update({"configs": SystemConfig.objects.all()})
        return context


class SystemConfigEditView(TemplateView):
    template_name = "system_config_edit.html"

    @staticmethod
    def _clean_value(value_type: str, raw_value: str):
        value = (raw_value or "").strip()
        if value_type == "int":
            try:
                int(value)
            except ValueError as exc:
                raise ValueError("请输入合法整数。") from exc
        if value_type == "bool" and value.lower() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("布尔值仅支持 true/false（也兼容 1/0、yes/no、on/off）。")
        return value

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        SystemConfigService.ensure_defaults()
        config = get_object_or_404(SystemConfig, config_key=kwargs["config_key"])
        context.update({"config": config, "page_error": None, "page_success": None})
        return context

    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        config = context["config"]
        raw_value = request.POST.get("config_value", "")
        try:
            cleaned_value = self._clean_value(config.value_type, raw_value)
            config.config_value = cleaned_value
            config.save(update_fields=["config_value", "updated_at"])
            context["page_success"] = "配置已更新。"
        except ValueError as exc:
            context["page_error"] = str(exc)
        return self.render_to_response(context)


class AIAssistantView(TemplateView):
    template_name = "ai_assistant.html"
    CONTEXT_WINDOW_SIZE = 8

    @staticmethod
    def _default_response() -> dict:
        return {
            "answer": "",
            "model": "",
            "success": False,
            "error_message": "",
            "type": "answer",
            "render_as_code": False,
        }

    @staticmethod
    def _default_mode() -> str:
        return LLMModes.GENERAL_QA

    @staticmethod
    def _build_title_from_prompt(prompt: str) -> str:
        clean_prompt = " ".join((prompt or "").strip().split())
        if not clean_prompt:
            return "新会话"
        return clean_prompt[:30]

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
            "code_analysis": NavigationItem(
                label="代码分析",
                target_url=reverse("code-analysis"),
            ),
        }

    def _load_rules(self) -> list[dict]:
        try:
            endpoint = f"{RuntimeConfig.agent_base_url()}/rules"
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

    def _get_conversation_items(self) -> list[Conversation]:
        return list(Conversation.objects.all()[:100])

    def _get_active_conversation(self, conversation_id: str | None) -> Conversation | None:
        if not conversation_id or not str(conversation_id).isdigit():
            return None
        return Conversation.objects.filter(pk=int(conversation_id)).first()

    def _serialize_messages(self, conversation: Conversation | None) -> list[dict]:
        if not conversation:
            return []
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at,
            }
            for msg in conversation.messages.all()
        ]

    def _history_window(self, conversation: Conversation) -> list[dict]:
        recent = list(conversation.messages.order_by("-created_at", "-id")[: self.CONTEXT_WINDOW_SIZE])
        recent.reverse()
        return [{"role": item.role, "content": item.content} for item in recent]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_conversation = kwargs.get("active_conversation")
        context.update(
            {
                "mode": kwargs.get("mode", self._default_mode()),
                "prompt": kwargs.get("prompt", ""),
                "response": kwargs.get("response", self._default_response()),
                "recommendation_items": kwargs.get("recommendation_items", []),
                "page_error": kwargs.get("page_error"),
                "conversations": self._get_conversation_items(),
                "active_conversation": active_conversation,
                "messages": self._serialize_messages(active_conversation),
            }
        )
        return context

    def _handle_ask(self, mode: str, prompt: str, conversation: Conversation) -> dict:
        history_messages = self._history_window(conversation)
        Message.objects.create(conversation=conversation, role=Message.ROLE_USER, content=prompt)
        if conversation.title == "新会话":
            conversation.title = self._build_title_from_prompt(prompt)
            conversation.save(update_fields=["title", "updated_at"])

        service = OpenAICompatibleLLMClient()
        result = service.ask_with_history(
            mode=mode,
            prompt=prompt,
            recommendation_context=self._recommendation_context(),
            history_messages=history_messages,
        )

        Message.objects.create(conversation=conversation, role=Message.ROLE_ASSISTANT, content=result.message)
        conversation.save(update_fields=["updated_at"])

        return {
            "response": {
                "answer": result.message,
                "model": result.model,
                "type": result.response_type,
                "success": True,
                "error_message": "",
                "render_as_code": self._should_render_as_code(mode, result.message),
            },
            "recommendation_items": self._normalize_recommendations(result.response_type, result.items),
        }

    def get(self, request, *args, **kwargs):
        active_conversation = self._get_active_conversation(request.GET.get("conversation_id"))
        return self.render_to_response(self.get_context_data(active_conversation=active_conversation))

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "ask").strip().lower()

        if action == "new_conversation":
            conversation = Conversation.objects.create(title="新会话")
            return self.render_to_response(self.get_context_data(active_conversation=conversation))

        mode = request.POST.get("mode", self._default_mode()).strip().lower()
        prompt = request.POST.get("prompt", "").strip()
        conversation = self._get_active_conversation(request.POST.get("conversation_id"))

        context_kwargs = {
            "mode": mode,
            "prompt": prompt,
            "active_conversation": conversation,
            "response": self._default_response(),
            "recommendation_items": [],
            "page_error": None,
        }

        if mode not in LLMModes.ALL:
            context_kwargs["page_error"] = "mode 参数不合法。"
            return self.render_to_response(self.get_context_data(**context_kwargs))

        if action != "ask":
            context_kwargs["page_error"] = "不支持的 action。"
            return self.render_to_response(self.get_context_data(**context_kwargs))

        if not conversation:
            conversation = Conversation.objects.create(title="新会话")
            context_kwargs["active_conversation"] = conversation

        if not prompt:
            context_kwargs["page_error"] = "请输入 prompt。"
            return self.render_to_response(self.get_context_data(**context_kwargs))

        try:
            result_payload = self._handle_ask(mode, prompt, conversation)
            context_kwargs["response"] = result_payload["response"]
            context_kwargs["recommendation_items"] = result_payload["recommendation_items"]
            context_kwargs["prompt"] = ""
        except (
            LLMConfigError,
            LLMServiceUnavailableError,
            LLMTimeoutError,
            LLMEmptyResponseError,
        ) as exc:
            context_kwargs["response"] = {
                "answer": "",
                "model": RuntimeConfig.llm_model(),
                "type": "answer",
                "success": False,
                "error_message": str(exc),
                "render_as_code": False,
            }

        return self.render_to_response(self.get_context_data(**context_kwargs))


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
            UploadFileRecordService.save_upload(
                uploaded_file,
                source_module=UploadFileRecordService.SOURCE_PROJECT_ANALYSIS,
            )
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
            RecordCenterService.create_record(
                record_type=ExecutionRecord.TYPE_PROJECT_ANALYSIS,
                title=f"项目分析：{result.context.project_name}",
                summary=(
                    f"关键文件 {len(result.context.key_files)} 个，"
                    f"技术栈线索 {len(result.context.tech_stack_clues)} 条。"
                ),
                content={
                    "uploaded_filename": uploaded_file.name,
                    "analysis_result": context["analysis_result"],
                },
            )
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


class CodeAnalysisView(TemplateView):
    template_name = "code_analysis.html"

    @staticmethod
    def _default_context() -> dict:
        return {
            "input_mode": "snippet",
            "snippet": "",
            "analysis_result": None,
            "page_error": None,
            "uploaded_filename": "",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self._default_context())
        return context

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        input_mode = request.POST.get("input_mode", "snippet").strip().lower()
        snippet = request.POST.get("snippet", "")

        context["input_mode"] = input_mode
        context["snippet"] = snippet

        service = CodeAnalysisService()
        try:
            if input_mode == "upload":
                uploaded_file = request.FILES.get("code_file")
                if uploaded_file:
                    context["uploaded_filename"] = uploaded_file.name
                    UploadFileRecordService.save_upload(
                        uploaded_file,
                        source_module=UploadFileRecordService.SOURCE_CODE_ANALYSIS,
                    )
                payload = service.build_input_from_upload(uploaded_file)
            else:
                payload = service.build_input_from_snippet(snippet)

            result = service.analyze(payload)
            context["analysis_result"] = {
                "model": result.model,
                "function_summary": result.function_summary,
                "core_flow": result.core_flow,
                "io_description": result.io_description,
                "risks": result.risks,
                "optimization_suggestions": result.optimization_suggestions,
            }
            RecordCenterService.create_record(
                record_type=ExecutionRecord.TYPE_CODE_ANALYSIS,
                title=f"代码分析：{context['uploaded_filename'] or '代码片段'}",
                summary=f"模型 {result.model} 已完成分析。",
                content={
                    "input_mode": input_mode,
                    "uploaded_filename": context["uploaded_filename"],
                    "snippet": snippet if input_mode == "snippet" else "",
                    "analysis_result": context["analysis_result"],
                },
            )
        except InvalidCodeInputError as exc:
            context["page_error"] = str(exc)
        except (
            LLMConfigError,
            LLMServiceUnavailableError,
            LLMTimeoutError,
            LLMEmptyResponseError,
        ) as exc:
            context["page_error"] = f"模型分析失败：{exc}"
        except CodeAnalysisError as exc:
            context["page_error"] = str(exc)

        return self.render_to_response(context)


class AIAskAPIView(APIView):
    def post(self, request):
        mode = str(request.data.get("mode", LLMModes.GENERAL_QA)).strip().lower()
        prompt = str(request.data.get("prompt", "")).strip()

        if mode not in LLMModes.ALL:
            return Response(
                {
                    "answer": "",
                    "model": RuntimeConfig.llm_model(),
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
                    "model": RuntimeConfig.llm_model(),
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
                    "model": RuntimeConfig.llm_model(),
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
