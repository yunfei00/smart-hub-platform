from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from api.models import UploadFileRecord


@dataclass(frozen=True)
class SourceNavigation:
    label: str
    url_name: str


class UploadFileRecordService:
    SOURCE_PROJECT_ANALYSIS = "project_analysis"
    SOURCE_CODE_ANALYSIS = "code_analysis"

    SOURCE_NAVIGATION = {
        SOURCE_PROJECT_ANALYSIS: SourceNavigation(label="前往项目分析", url_name="project-analysis"),
        SOURCE_CODE_ANALYSIS: SourceNavigation(label="前往代码分析", url_name="code-analysis"),
    }

    @staticmethod
    def storage_root() -> Path:
        root = Path(settings.BASE_DIR) / "uploaded_files"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def save_upload(cls, uploaded_file, source_module: str) -> UploadFileRecord:
        original_name = Path(uploaded_file.name or "uploaded.bin").name
        suffix = Path(original_name).suffix.lower() or ""
        file_type = suffix[1:] if suffix.startswith(".") else suffix

        module_dir = cls.storage_root() / source_module
        module_dir.mkdir(parents=True, exist_ok=True)

        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        stored_path = module_dir / stored_name

        with stored_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)

        file_size = int(getattr(uploaded_file, "size", stored_path.stat().st_size) or 0)

        return UploadFileRecord.objects.create(
            file_name=original_name,
            file_path=str(stored_path),
            file_type=file_type or "unknown",
            source_module=source_module,
            file_size=file_size,
        )

    @staticmethod
    def file_exists(record: UploadFileRecord) -> bool:
        return Path(record.file_path).exists()

    @classmethod
    def delete_record_and_file(cls, record: UploadFileRecord) -> tuple[bool, str | None]:
        target_path = Path(record.file_path)
        file_deleted = False
        warning: str | None = None

        if target_path.exists():
            target_path.unlink()
            file_deleted = True
        else:
            warning = "本地文件不存在，仅删除记录。"

        record.delete()
        return file_deleted, warning
