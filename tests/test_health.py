from fastapi.testclient import TestClient

from paa.main import app


def test_healthz_returns_ok():
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lifespan_recovers_and_reports_state():
    from paa.main import create_app

    with TestClient(create_app()) as client:
        payload = client.get("/healthz").json()

    assert payload["db"] is True
    assert "recovered_tasks" in payload
    assert payload["status"] == "ok"


def test_router_demoted_when_primary_unreachable(monkeypatch):
    from paa import main as main_module

    class FakeRouter:
        demoted = False

        def demote(self):
            self.demoted = True

    router = FakeRouter()
    monkeypatch.setattr(main_module, "_probe", lambda *a, **k: False)
    settings = main_module.get_settings()
    monkeypatch.setattr(settings, "local_base_url", "http://127.0.0.1:1/v1", raising=False)

    with TestClient(main_module.create_app(router=router)) as client:
        payload = client.get("/healthz").json()

    assert router.demoted
    assert payload["primary_reachable"] is False
