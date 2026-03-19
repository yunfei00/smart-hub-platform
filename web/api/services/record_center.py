from __future__ import annotations

from typing import Any

from api.models import ExecutionRecord


class RecordCenterService:
    SOURCE_NAME = "web"

    @classmethod
    def create_record(
        cls,
        *,
        record_type: str,
        title: str,
        summary: str,
        content: dict[str, Any] | list[Any] | str,
        source_name: str | None = None,
    ) -> ExecutionRecord:
        payload: dict[str, Any] | list[Any]
        if isinstance(content, str):
            payload = {"text": content}
        else:
            payload = content

        return ExecutionRecord.objects.create(
            record_type=record_type,
            title=title,
            summary=summary,
            content=payload,
            source_name=source_name or cls.SOURCE_NAME,
        )
