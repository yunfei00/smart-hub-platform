from django.contrib import admin
from django.urls import path

from api.views import DiskCleanupView, HealthView, LandingView, ToolCenterView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", LandingView.as_view(), name="home"),
    path("disk-cleanup/", DiskCleanupView.as_view(), name="disk-cleanup"),
    path("tools/", ToolCenterView.as_view(), name="tool-center"),
    path("api/health/", HealthView.as_view(), name="api-health"),
]
