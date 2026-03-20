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


class SystemConfig(models.Model):
    TYPE_STRING = "string"
    TYPE_INT = "int"
    TYPE_BOOL = "bool"

    VALUE_TYPE_CHOICES = [
        (TYPE_STRING, "字符串"),
        (TYPE_INT, "整数"),
        (TYPE_BOOL, "布尔值"),
    ]

    config_key = models.CharField(max_length=100, unique=True)
    config_group = models.CharField(max_length=64)
    config_value = models.TextField(blank=True, default="")
    value_type = models.CharField(max_length=16, choices=VALUE_TYPE_CHOICES, default=TYPE_STRING)
    description = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["config_group", "config_key"]

    def __str__(self) -> str:
        return f"{self.config_group}.{self.config_key}"


class UploadFileRecord(models.Model):
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=1024)
    file_type = models.CharField(max_length=32, default="unknown")
    source_module = models.CharField(max_length=64, default="unknown")
    file_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.source_module})"
