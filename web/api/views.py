from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView


class HomeView(TemplateView):
    template_name = "home.html"


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok", "service": "smart-hub-web"})
