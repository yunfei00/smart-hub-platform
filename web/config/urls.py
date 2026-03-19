from django.contrib import admin
from django.urls import path

from api.views import (
    AIAskAPIView,
    AIAssistantView,
    AIToolExecuteAPIView,
    DiskCleanupView,
    CodeAnalysisView,
    HealthView,
    LandingView,
    RecordCenterDetailView,
    RecordCenterListView,
    ProjectAnalysisView,
    ToolCenterView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", LandingView.as_view(), name="home"),
    path("disk-cleanup/", DiskCleanupView.as_view(), name="disk-cleanup"),
    path("tools/", ToolCenterView.as_view(), name="tool-center"),
    path("ai-assistant/", AIAssistantView.as_view(), name="ai-assistant"),
    path("project-analysis/", ProjectAnalysisView.as_view(), name="project-analysis"),
    path("code-analysis/", CodeAnalysisView.as_view(), name="code-analysis"),
    path("records/", RecordCenterListView.as_view(), name="record-center"),
    path("records/<int:record_id>/", RecordCenterDetailView.as_view(), name="record-detail"),
    path("api/ai/ask/", AIAskAPIView.as_view(), name="api-ai-ask"),
    path("api/ai/tool-execute/", AIToolExecuteAPIView.as_view(), name="api-ai-tool-execute"),
    path("api/health/", HealthView.as_view(), name="api-health"),
]
