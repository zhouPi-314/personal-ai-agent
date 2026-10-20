import pytest

from paa.config import get_settings
from paa.db import get_engine, get_session_factory


def test_engine_requires_database_url(monkeypatch):
    monkeypatch.setenv("PAA_DATABASE_URL", "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="PAA_DATABASE_URL"):
            get_engine()
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
