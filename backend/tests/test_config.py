from odin.config import Settings, get_settings


def test_defaults_independent_of_dotenv():
    s = Settings(_env_file=None)
    assert s.environment == "dev"
    assert s.debug is False
    assert s.worker_max_attempts == 5
    assert s.answer_model == "z-ai/glm-5.2"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_env_override(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    s = Settings(_env_file=None)
    assert s.environment == "prod"
    assert s.embedding_dimensions == 768


def test_provider_keys_optional(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.openrouter_api_key is None
    assert s.openai_api_key is None


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
