import json
from urllib import error, request

from django.conf import settings
from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView


class HomeView(TemplateView):
    template_name = "home.html"

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

    def _load_rules(self) -> tuple[list[dict], str | None]:
        try:
            data = self._agent_get("/rules")
            return data.get("rules", []), None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            return [], f"加载规则失败（HTTP {exc.code}）：{detail}"
        except Exception as exc:  # pylint: disable=broad-except
            return [], f"加载规则失败：{exc}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rules, rule_error = self._load_rules()
        context.update(
            {
                "agent_base_url": settings.AGENT_BASE_URL,
                "rules": rules,
                "rule_error": rule_error,
                "selected_rule_id": "",
                "scan_result": None,
                "clean_result": None,
                "page_error": None,
                "selected_files": [],
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
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            context["page_error"] = f"调用 Agent 失败（HTTP {exc.code}）：{detail}"
        except Exception as exc:  # pylint: disable=broad-except
            context["page_error"] = f"调用 Agent 失败：{exc}"

        return self.render_to_response(context)


class ToolCenterView(TemplateView):
    template_name = "tool_center.html"

    def _load_tools(self) -> tuple[list[dict], str | None]:
        config_path = settings.BASE_DIR / "config" / "tools.json"
        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except FileNotFoundError:
            return [], f"工具配置不存在：{config_path}"
        except json.JSONDecodeError as exc:
            return [], f"工具配置格式错误：{exc}"
        except Exception as exc:  # pylint: disable=broad-except
            return [], f"读取工具配置失败：{exc}"

        tools = data.get("tools", []) if isinstance(data, dict) else []
        if not isinstance(tools, list):
            return [], "工具配置格式错误：tools 字段必须是数组。"

        return tools, None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tools, load_error = self._load_tools()
        context.update({"tools": tools, "load_error": load_error})
        return context


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok", "service": "smart-hub-web"})
