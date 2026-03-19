from django.db import models


class ExecutionRecord(models.Model):
    TYPE_DISK_SCAN = "disk_scan"
    TYPE_DISK_CLEAN = "disk_clean"
    TYPE_PROJECT_ANALYSIS = "project_analysis"
    TYPE_CODE_ANALYSIS = "code_analysis"

    RECORD_TYPE_CHOICES = [
        (TYPE_DISK_SCAN, "磁盘扫描"),
        (TYPE_DISK_CLEAN, "磁盘清理"),
        (TYPE_PROJECT_ANALYSIS, "项目分析"),
        (TYPE_CODE_ANALYSIS, "代码分析"),
    ]

    record_type = models.CharField(max_length=32, choices=RECORD_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    content = models.JSONField(default=dict, blank=True)
    source_name = models.CharField(max_length=128, default="web")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_record_type_display()} - {self.title}"
