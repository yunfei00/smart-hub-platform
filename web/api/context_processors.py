from .services.system_config import RuntimeConfig


def project_settings(_request):
    return {
        "project_name": RuntimeConfig.project_name(),
        "project_desc": RuntimeConfig.project_desc(),
        "agent_base_url": RuntimeConfig.agent_base_url(),
        "llm_enabled": RuntimeConfig.llm_enabled(),
        "llm_provider": RuntimeConfig.llm_provider(),
        "llm_base_url": RuntimeConfig.llm_base_url(),
        "llm_model": RuntimeConfig.llm_model(),
    }
