import uuid

from fastapi.testclient import TestClient

from paa.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_status_counts():
    with _client() as client:
        payload = client.get("/api/status").json()

    assert set(payload) == {"messages", "memories", "tasks", "audit_logs"}
    assert all(isinstance(v, int) for v in payload.values())


def test_messages_return_list():
    with _client() as client:
        response = client.get("/api/messages", params={"limit": 5})

    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list)
    if rows:
        assert {"id", "role", "content", "source"} <= set(rows[0])


def test_memories_respect_limit():
    with _client() as client:
        rows = client.get("/api/memories", params={"limit": 2}).json()

    assert len(rows) <= 2


def test_tasks_and_audit_are_lists():
    with _client() as client:
        assert isinstance(client.get("/api/tasks").json(), list)
        assert isinstance(client.get("/api/audit").json(), list)


def test_revoke_unknown_memory_returns_404():
    with _client() as client:
        response = client.post(f"/api/memories/{uuid.uuid4()}/revoke")

    assert response.status_code == 404
