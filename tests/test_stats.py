"""Tests para GET /tickets/stats."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

FAKE_CLASS = {"category": "bug", "priority": "P1", "tags": []}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: FAKE_CLASS)
    return TestClient(app)


def test_stats_empty_db(client):
    r = client.get("/tickets/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert "by_category" in data
    assert "by_priority" in data
    assert "by_status" in data
    # todas las claves deben estar presentes aunque valgan 0
    assert all(v == 0 for v in data["by_category"].values())
    assert all(v == 0 for v in data["by_priority"].values())
    assert all(v == 0 for v in data["by_status"].values())


def test_stats_correct_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": "P1", "tags": []},
    )
    c = TestClient(app)
    c.post("/tickets", json={"title": "uno", "description": "desc"})
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "feature_request", "priority": "P2", "tags": []},
    )
    c.post("/tickets", json={"title": "dos", "description": "desc"})

    r = c.get("/tickets/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["by_category"]["bug"] == 1
    assert data["by_category"]["feature_request"] == 1
    assert data["by_priority"]["P1"] == 1
    assert data["by_priority"]["P2"] == 1
    assert data["by_status"]["open"] == 2


def test_stats_reflects_patch(client):
    r = client.post("/tickets", json={"title": "t", "description": "d"})
    tid = r.json()["id"]

    before = client.get("/tickets/stats").json()
    assert before["by_status"]["open"] == 1
    assert before["by_status"]["closed"] == 0

    client.patch(f"/tickets/{tid}", json={"status": "closed"})

    after = client.get("/tickets/stats").json()
    assert after["by_status"]["open"] == 0
    assert after["by_status"]["closed"] == 1


def test_stats_does_not_shadow_ticket_by_id(client):
    r = client.post("/tickets", json={"title": "t", "description": "d"})
    tid = r.json()["id"]

    # /tickets/stats no debe ser absorbida por /tickets/{ticket_id}
    stats = client.get("/tickets/stats")
    assert stats.status_code == 200
    assert "total" in stats.json()

    # el endpoint de id sigue funcionando
    by_id = client.get(f"/tickets/{tid}")
    assert by_id.status_code == 200
    assert by_id.json()["id"] == tid
