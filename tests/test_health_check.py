from paa import health
from paa.config import Settings


def _settings(**kwargs) -> Settings:
    base = {
        "onebot_http_url": "http://127.0.0.1:3000",
        "local_base_url": "http://127.0.0.1:18900/v1",
        "backup_remote": "paa@backup.example.com",
    }
    base.update(kwargs)
    return Settings(**base)


def test_all_reachable_is_ok(monkeypatch):
    monkeypatch.setattr(health, "_tcp", lambda *a, **k: (True, 12.0))
    monkeypatch.setattr(health, "_check_db", lambda: health._item("db", "数据库", True))
    monkeypatch.setattr(
        health, "_check_qq", lambda s: health._item("qq", "QQ 账号", True, detail="123")
    )

    result = health.check_all(_settings())

    assert result["status"] == "ok"
    assert {item["key"] for item in result["items"]} == {
        "paa",
        "db",
        "napcat",
        "qq",
        "dsh",
        "cloud",
    }


def test_any_false_marks_degraded(monkeypatch):
    monkeypatch.setattr(health, "_tcp", lambda *a, **k: (False, 1500.0))
    monkeypatch.setattr(health, "_check_db", lambda: health._item("db", "数据库", True))
    monkeypatch.setattr(health, "_check_qq", lambda s: health._item("qq", "QQ 账号", False))

    result = health.check_all(_settings())

    assert result["status"] == "degraded"


def test_missing_config_reports_unknown(monkeypatch):
    monkeypatch.setattr(health, "_tcp", lambda *a, **k: (True, 1.0))
    monkeypatch.setattr(health, "_check_db", lambda: health._item("db", "数据库", True))

    result = health.check_all(_settings(backup_remote="", onebot_http_url=""))
    by_key = {item["key"]: item for item in result["items"]}

    assert by_key["cloud"]["ok"] is None
    assert by_key["napcat"]["ok"] is None
