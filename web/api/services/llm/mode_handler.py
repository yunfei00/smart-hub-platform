import json


class LLMModes:
    GENERAL_QA = "qa"
    CODE_GENERATION = "code_generation"
    CODE_EXPLANATION = "code_explanation"
    SCRIPT_GENERATION = "script_generation"

    ALL = {
        GENERAL_QA,
        CODE_GENERATION,
        CODE_EXPLANATION,
        SCRIPT_GENERATION,
    }


class LLMPromptBuilder:
    """Builds mode-specific system prompts for the local LLM client."""

    @staticmethod
    def _mode_instruction(mode: str) -> str:
        if mode == LLMModes.CODE_GENERATION:
            return (
                "你是代码生成助手。根据用户需求生成完整、可直接运行的示例代码，"
                "并在 message 中包含必要的输入输出说明。"
            )
        if mode == LLMModes.CODE_EXPLANATION:
            return (
                "你是代码解释助手。优先解释用户提供代码的作用、关键逻辑和潜在风险，"
                "必要时给出改进建议。"
            )
        if mode == LLMModes.SCRIPT_GENERATION:
            return (
                "你是脚本生成助手。按用户要求生成 Python 或 Bash 等脚本，"
                "并补充执行前置条件与注意事项。"
            )

        return "你是通用问答助手，请给出清晰、简洁、可执行的答案。"

    def build_system_prompt(self, mode: str, recommendation_context: dict) -> str:
        recommendation_context_json = json.dumps(recommendation_context, ensure_ascii=False)
        return (
            f"{self._mode_instruction(mode)}\n"
            "你必须只输出一个 JSON 对象，不要输出其他文本。"
            "JSON 协议："
            '{"type":"answer","message":"..."}'
            " 或 "
            '{"type":"rule_recommendation","message":"...","items":[{"label":"...","rule_id":"...","target_url":"..."}]}'
            " 或 "
            '{"type":"page_navigation","message":"...","items":[{"label":"...","target_url":"..."}]}。'
            "只允许推荐系统白名单中的规则或页面，不要输出外部链接。"
            f"白名单上下文：{recommendation_context_json}"
        )

    def build_messages(self, mode: str, prompt: str, recommendation_context: dict) -> list[dict]:
        return self.build_messages_with_history(mode, prompt, recommendation_context, history_messages=[])

    def build_messages_with_history(
        self,
        mode: str,
        prompt: str,
        recommendation_context: dict,
        history_messages: list[dict],
    ) -> list[dict]:
        messages = [{"role": "system", "content": self.build_system_prompt(mode, recommendation_context)}]
        for item in history_messages:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant", "system"} or not content:
                continue
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt})
        return messages
