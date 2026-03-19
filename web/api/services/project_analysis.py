import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .llm import (
    LLMConfigError,
    LLMEmptyResponseError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
)


class ProjectAnalysisError(Exception):
    """Base error for project analysis workflow."""


class InvalidZipFileError(ProjectAnalysisError):
    """Raised when uploaded file is not a valid zip archive."""


@dataclass
class ProjectContext:
    project_name: str
    extract_dir: str
    top_level_items: list[str]
    tree_summary: list[str]
    key_files: list[str]
    tech_stack_clues: list[str]
    file_summaries: list[dict]


@dataclass
class ProjectAnalysisResult:
    context: ProjectContext
    ai_report: str


class ProjectAnalysisService:
    IGNORE_DIRS = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".idea",
        ".vscode",
    }
    ALLOWED_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".html",
        ".css",
        ".json",
        ".yml",
        ".yaml",
        ".md",
        ".sh",
        ".toml",
        ".ini",
    }

    MAX_TREE_LINES = 120
    MAX_TEXT_FILE_SIZE = 100 * 1024
    MAX_FILE_SUMMARIES = 12
    MAX_SUMMARY_CHARS = 1200

    def __init__(self):
        self.llm_client = OpenAICompatibleLLMClient()

    @staticmethod
    def _safe_member_path(root: Path, member: zipfile.ZipInfo) -> Path:
        target_path = (root / member.filename).resolve()
        if not str(target_path).startswith(str(root.resolve())):
            raise InvalidZipFileError("压缩包中包含非法路径，已拒绝处理。")
        return target_path

    def _save_upload_to_temp(self, uploaded_file) -> tuple[Path, Path]:
        suffix = Path(uploaded_file.name or "").suffix.lower()
        if suffix != ".zip":
            raise InvalidZipFileError("仅支持 .zip 文件上传。")

        work_dir = Path(tempfile.mkdtemp(prefix="phase9_project_analysis_"))
        zip_path = work_dir / "uploaded.zip"
        with zip_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        if not zipfile.is_zipfile(zip_path):
            raise InvalidZipFileError("上传文件不是有效的 zip 压缩包。")

        return work_dir, zip_path

    def _extract_zip(self, zip_path: Path, work_dir: Path) -> Path:
        extract_dir = work_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                self._safe_member_path(extract_dir, member)
            archive.extractall(extract_dir)

        return extract_dir

    def _iter_project_files(self, root: Path):
        for path in root.rglob("*"):
            rel_parts = path.relative_to(root).parts
            if any(part in self.IGNORE_DIRS for part in rel_parts):
                continue
            if path.is_file():
                yield path

    def _build_tree_summary(self, root: Path) -> list[str]:
        lines: list[str] = []

        def walk(current: Path, depth: int):
            if len(lines) >= self.MAX_TREE_LINES:
                return

            try:
                children = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
            except OSError:
                return

            for child in children:
                if child.name in self.IGNORE_DIRS:
                    continue
                rel = child.relative_to(root)
                indent = "  " * depth
                suffix = "/" if child.is_dir() else ""
                lines.append(f"{indent}- {rel.name}{suffix}")
                if len(lines) >= self.MAX_TREE_LINES:
                    break
                if child.is_dir() and depth < 3:
                    walk(child, depth + 1)

        walk(root, 0)
        return lines

    def _detect_tech_stack_clues(self, files: list[Path], root: Path) -> list[str]:
        rel_paths = {str(file.relative_to(root)) for file in files}
        clues: list[str] = []

        indicators = [
            ("Django/Python", {"manage.py", "requirements.txt", "pyproject.toml"}),
            ("Node.js", {"package.json", "pnpm-lock.yaml", "yarn.lock"}),
            ("TypeScript", {"tsconfig.json"}),
            ("Docker", {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}),
            ("Shell Automation", {"Makefile"}),
        ]

        base_names = {Path(item).name for item in rel_paths}
        for label, marker_files in indicators:
            if marker_files.intersection(base_names):
                clues.append(label)

        extension_hits = {file.suffix.lower() for file in files if file.suffix}
        if ".py" in extension_hits and "Django/Python" not in clues:
            clues.append("Python")
        if {".ts", ".tsx"}.intersection(extension_hits):
            clues.append("TypeScript/Frontend")
        if ".js" in extension_hits and "Node.js" not in clues:
            clues.append("JavaScript")

        return clues

    def _pick_key_files(self, files: list[Path], root: Path) -> list[Path]:
        priority_names = {
            "README.md",
            "requirements.txt",
            "pyproject.toml",
            "manage.py",
            "package.json",
            "tsconfig.json",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "Makefile",
            "setup.py",
            ".env.example",
        }

        prioritized = [file for file in files if file.name in priority_names]
        if len(prioritized) < self.MAX_FILE_SUMMARIES:
            remaining = [
                file
                for file in files
                if file not in prioritized and file.suffix.lower() in self.ALLOWED_EXTENSIONS
            ]
            prioritized.extend(remaining[: self.MAX_FILE_SUMMARIES - len(prioritized)])

        prioritized.sort(key=lambda path: str(path.relative_to(root)).lower())
        return prioritized[: self.MAX_FILE_SUMMARIES]

    def _summarize_file(self, file_path: Path, root: Path) -> dict | None:
        if file_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return None

        try:
            if file_path.stat().st_size > self.MAX_TEXT_FILE_SIZE:
                return None
            content = file_path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return None

        if not content:
            return None

        preview = content[: self.MAX_SUMMARY_CHARS]
        if len(content) > self.MAX_SUMMARY_CHARS:
            preview += "\n... (truncated)"

        return {
            "path": str(file_path.relative_to(root)),
            "size": file_path.stat().st_size,
            "preview": preview,
        }

    def _build_context(self, extract_dir: Path) -> ProjectContext:
        files = list(self._iter_project_files(extract_dir))
        top_level_items = [
            child.name + ("/" if child.is_dir() else "")
            for child in sorted(extract_dir.iterdir(), key=lambda item: item.name.lower())
            if child.name not in self.IGNORE_DIRS
        ]

        tree_summary = self._build_tree_summary(extract_dir)
        key_files = self._pick_key_files(files, extract_dir)
        file_summaries = [
            summary
            for summary in (self._summarize_file(path, extract_dir) for path in key_files)
            if summary
        ]

        project_name = extract_dir.name
        root_dirs = [item for item in extract_dir.iterdir() if item.is_dir() and item.name not in self.IGNORE_DIRS]
        if len(top_level_items) == 1 and root_dirs:
            project_name = root_dirs[0].name

        return ProjectContext(
            project_name=project_name,
            extract_dir=str(extract_dir),
            top_level_items=top_level_items,
            tree_summary=tree_summary,
            key_files=[str(path.relative_to(extract_dir)) for path in key_files],
            tech_stack_clues=self._detect_tech_stack_clues(files, extract_dir),
            file_summaries=file_summaries,
        )

    @staticmethod
    def _build_analysis_prompt(context: ProjectContext) -> str:
        payload = {
            "project_name": context.project_name,
            "top_level_items": context.top_level_items,
            "tree_summary": context.tree_summary,
            "key_files": context.key_files,
            "tech_stack_clues": context.tech_stack_clues,
            "file_summaries": context.file_summaries,
        }

        return (
            "请基于以下项目结构上下文做分析。"
            "请输出中文、清晰分段，至少覆盖："
            "1) 项目类型判断 2) 技术栈判断 3) 入口文件识别 "
            "4) 核心目录/模块说明 5) 风险点 6) 后续建议。"
            "若信息不足，请明确说明不确定项。\n\n"
            f"项目上下文(JSON)：\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _call_llm(self, context: ProjectContext) -> str:
        prompt = self._build_analysis_prompt(context)
        result = self.llm_client.ask(
            mode="qa",
            prompt=prompt,
            recommendation_context={"pages": [], "rules": []},
        )
        return result.message

    def analyze(self, uploaded_file) -> ProjectAnalysisResult:
        work_dir, zip_path = self._save_upload_to_temp(uploaded_file)
        try:
            extract_dir = self._extract_zip(zip_path, work_dir)
            context = self._build_context(extract_dir)
            ai_report = self._call_llm(context)
            return ProjectAnalysisResult(context=context, ai_report=ai_report)
        except (LLMConfigError, LLMServiceUnavailableError, LLMTimeoutError, LLMEmptyResponseError):
            raise
        except zipfile.BadZipFile as exc:
            raise InvalidZipFileError("zip 文件损坏或格式不正确。") from exc
        except ProjectAnalysisError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            raise ProjectAnalysisError("项目分析失败，请稍后重试。") from exc

    @staticmethod
    def cleanup(work_dir: str) -> None:
        if not work_dir:
            return
        shutil.rmtree(work_dir, ignore_errors=True)
