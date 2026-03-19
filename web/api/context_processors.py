from django.conf import settings


def project_settings(_request):
    return {
        "project_name": settings.PROJECT_NAME,
        "agent_base_url": settings.AGENT_BASE_URL,
        "llm_enabled": settings.LLM_ENABLED,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_base_url": settings.LLM_BASE_URL,
        "llm_model": settings.LLM_MODEL,
    }
