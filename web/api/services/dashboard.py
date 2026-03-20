from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import Count

from api.models import ExecutionRecord


@dataclass(frozen=True)
class DashboardStats:
    disk_scan_count: int
    disk_clean_count: int
    total_freed_bytes: int | None
    project_analysis_count: int
    code_analysis_count: int
    ai_assistant_count: int | None
    total_records: int
    recent_records: list[ExecutionRecord]
    type_distribution: list[dict[str, Any]]


class DashboardService:
    _FREED_SIZE_KEYS = {"freed_size", "freed_bytes", "released_size", "released_bytes"}

    @classmethod
    def build_stats(cls) -> DashboardStats:
        records = ExecutionRecord.objects.all()
        disk_scan_count = records.filter(record_type=ExecutionRecord.TYPE_DISK_SCAN).count()
        disk_clean_qs = records.filter(record_type=ExecutionRecord.TYPE_DISK_CLEAN)
        project_analysis_count = records.filter(
            record_type=ExecutionRecord.TYPE_PROJECT_ANALYSIS
        ).count()
        code_analysis_count = records.filter(record_type=ExecutionRecord.TYPE_CODE_ANALYSIS).count()

        recent_records = list(records[:5])
        distribution_rows = records.values("record_type").annotate(count=Count("id"))
        type_distribution = [
            {
                "record_type": row["record_type"],
                "count": row["count"],
            }
            for row in distribution_rows
        ]
        type_distribution.sort(key=lambda item: item["count"], reverse=True)

        total_freed_bytes = cls._sum_freed_size(disk_clean_qs)
        return DashboardStats(
            disk_scan_count=disk_scan_count,
            disk_clean_count=disk_clean_qs.count(),
            total_freed_bytes=total_freed_bytes,
            project_analysis_count=project_analysis_count,
            code_analysis_count=code_analysis_count,
            ai_assistant_count=None,
            total_records=records.count(),
            recent_records=recent_records,
            type_distribution=type_distribution,
        )

    @classmethod
    def _sum_freed_size(cls, disk_clean_qs) -> int | None:
        total = 0
        found = False
        for record in disk_clean_qs.only("content"):
            value = cls._extract_freed_size(record.content)
            if value is None:
                continue
            total += value
            found = True
        return total if found else None

    @classmethod
    def _extract_freed_size(cls, payload: Any) -> int | None:
        if not isinstance(payload, Mapping):
            return None

        direct_value = cls._coerce_size(payload.get("freed_size"))
        if direct_value is not None:
            return direct_value

        clean_result = payload.get("clean_result")
        if isinstance(clean_result, Mapping):
            nested_value = cls._coerce_size(clean_result.get("freed_size"))
            if nested_value is not None:
                return nested_value

        return cls._deep_search_size(payload)

    @classmethod
    def _deep_search_size(cls, payload: Any) -> int | None:
        if isinstance(payload, Mapping):
            for key, value in payload.items():
                if key in cls._FREED_SIZE_KEYS:
                    coerced = cls._coerce_size(value)
                    if coerced is not None:
                        return coerced
                nested = cls._deep_search_size(value)
                if nested is not None:
                    return nested
        if isinstance(payload, list):
            for item in payload:
                nested = cls._deep_search_size(item)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _coerce_size(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(int(value), 0)
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                parsed = Decimal(candidate)
            except InvalidOperation:
                return None
            return max(int(parsed), 0)
        return None

