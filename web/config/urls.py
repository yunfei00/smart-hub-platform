from django.contrib import admin
from django.urls import path

from api.views import HealthView, HomeView, ToolCenterView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", HomeView.as_view(), name="home"),
    path("tools/", ToolCenterView.as_view(), name="tool-center"),
    path("api/health/", HealthView.as_view(), name="api-health"),
]
