from django.contrib import admin
from django.urls import path

from api.views import HomeView, HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", HomeView.as_view(), name="home"),
    path("api/health/", HealthView.as_view(), name="api-health"),
]
