from django.conf import settings


def project_settings(_request):
    return {
        "project_name": settings.PROJECT_NAME,
        "agent_base_url": settings.AGENT_BASE_URL,
        "ai_enabled": settings.AI_ENABLED,
        "ai_provider": settings.AI_PROVIDER,
        "ai_base_url": settings.AI_BASE_URL,
        "ai_model": settings.AI_MODEL,
    }
