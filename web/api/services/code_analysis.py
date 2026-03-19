import json
from dataclasses import dataclass
from pathlib import Path

from .llm import (
    LLMConfigError,
    LLMEmptyResponseError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
)


class CodeAnalysisError(Exception):
    """Base error for code analysis workflow."""


class InvalidCodeInputError(CodeAnalysisError):
    """Raised when code snippet or uploaded file is invalid."""


@dataclass
class CodeAnalysisInput:
    input_type: str
    filename: str
    language: str
    code: str


@dataclass
class CodeAnalysisResult:
    model: str
    function_summary: str
    core_flow: str
    io_description: str
    risks: str
    optimization_suggestions: str
    raw_response: str


class CodeAnalysisService:
    ALLOWED_EXTENSIONS = {".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".md"}
    MAX_CODE_CHARS = 40_000

    def __init__(self):
        self.llm_client = OpenAICompatibleLLMClient()

    @staticmethod
    def _detect_language(filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        language_map = {
            ".py": "Python",
            ".sh": "Shell",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".json": "JSON",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".md": "Markdown",
        }
        return language_map.get(suffix, "Unknown")

    def build_input_from_snippet(self, snippet: str) -> CodeAnalysisInput:
        code = (snippet or "").strip()
        if not code:
            raise InvalidCodeInputError("请先输入代码片段。")
        if len(code) > self.MAX_CODE_CHARS:
            raise InvalidCodeInputError(
                f"代码片段过长（>{self.MAX_CODE_CHARS} 字符），请缩短后重试。"
            )

        return CodeAnalysisInput(
            input_type="snippet",
            filename="snippet.txt",
            language="Unknown",
            code=code,
        )

    def build_input_from_upload(self, uploaded_file) -> CodeAnalysisInput:
        if not uploaded_file:
            raise InvalidCodeInputError("请先上传代码文件。")

        filename = uploaded_file.name or "uploaded.txt"
        suffix = Path(filename).suffix.lower()
        if suffix not in self.ALLOWED_EXTENSIONS:
            raise InvalidCodeInputError(
                "仅支持上传常见文本文件：.py/.sh/.js/.ts/.json/.yaml/.yml/.md"
            )

        raw = uploaded_file.read()
        if not raw:
            raise InvalidCodeInputError("上传文件内容为空。")

        try:
            code = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise InvalidCodeInputError("上传文件不是 UTF-8 文本，疑似二进制文件。") from exc

        if not code:
            raise InvalidCodeInputError("上传文件内容为空。")
        if len(code) > self.MAX_CODE_CHARS:
            raise InvalidCodeInputError(
                f"上传文件内容过大（>{self.MAX_CODE_CHARS} 字符），请裁剪后再分析。"
            )

        return CodeAnalysisInput(
            input_type="upload",
            filename=filename,
            language=self._detect_language(filename),
            code=code,
        )

    @staticmethod
    def _build_prompt(payload: CodeAnalysisInput) -> str:
        context = {
            "input_type": payload.input_type,
            "filename": payload.filename,
            "language": payload.language,
            "code": payload.code,
        }
        return (
            "你是代码分析助手。请根据输入代码做最小可用分析，"
            "并严格输出 JSON 对象，不要输出额外说明。"
            'JSON 字段必须包含："function_summary", "core_flow", "io_description", '
            '"risks", "optimization_suggestions"。\n\n'
            "分析要求：\n"
            "1) function_summary: 说明代码主要功能。\n"
            "2) core_flow: 说明核心处理流程。\n"
            "3) io_description: 说明输入与输出。\n"
            "4) risks: 说明潜在风险点。\n"
            "5) optimization_suggestions: 给出优化建议。\n"
            "若信息不足，请明确写出不确定项。\n\n"
            f"输入上下文(JSON)：\n{json.dumps(context, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_response(content: str, model: str) -> CodeAnalysisResult:
        text = (content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
                text = "\n".join(lines[1:-1]).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMEmptyResponseError("模型输出格式不符合预期，未返回有效 JSON。") from exc

        keys = ["function_summary", "core_flow", "io_description", "risks", "optimization_suggestions"]
        missing = [key for key in keys if not str(parsed.get(key, "")).strip()]
        if missing:
            raise LLMEmptyResponseError(f"模型输出缺少必要字段：{', '.join(missing)}")

        return CodeAnalysisResult(
            model=model,
            function_summary=str(parsed.get("function_summary", "")).strip(),
            core_flow=str(parsed.get("core_flow", "")).strip(),
            io_description=str(parsed.get("io_description", "")).strip(),
            risks=str(parsed.get("risks", "")).strip(),
            optimization_suggestions=str(parsed.get("optimization_suggestions", "")).strip(),
            raw_response=content,
        )

    def analyze(self, payload: CodeAnalysisInput) -> CodeAnalysisResult:
        prompt = self._build_prompt(payload)
        try:
            result = self.llm_client.ask_raw(
                mode="code_explanation",
                prompt=prompt,
                recommendation_context={"pages": [], "rules": []},
            )
            return self._parse_response(result.message, result.model)
        except (LLMConfigError, LLMServiceUnavailableError, LLMTimeoutError, LLMEmptyResponseError):
            raise
        except Exception as exc:  # pylint: disable=broad-except
            raise CodeAnalysisError("代码分析失败，请稍后重试。") from exc
