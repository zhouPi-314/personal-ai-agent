from paa.config import get_settings


def test_env_var_overrides_defaults(monkeypatch):
    monkeypatch.setenv("PAA_ENV", "test")
    get_settings.cache_clear()
    try:
        assert get_settings().env == "test"
    finally:
        get_settings.cache_clear()


def test_settings_has_stable_field_names():
    settings = get_settings()
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "model_api_key")
