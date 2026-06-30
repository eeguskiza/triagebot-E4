import pytest
from fastapi.testclient import TestClient

from app.main import app

FAKE_CLASSIFICATION = {"category": "bug", "priority": "P1", "tags": ["perf"]}
TICKET_PAYLOAD = {"title": "Perf test ticket", "description": "Benchmark description for performance testing"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'perf.db'}")
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: FAKE_CLASSIFICATION)
    return TestClient(app)


@pytest.fixture()
def client_with_tickets(client):
    for i in range(10):
        client.post("/tickets", json={"title": f"Ticket {i}", "description": f"Description {i}"})
    return client


def test_post_ticket_performance(benchmark, client):
    result = benchmark(client.post, "/tickets", json=TICKET_PAYLOAD)
    assert result.status_code == 201


def test_get_tickets_performance(benchmark, client_with_tickets):
    result = benchmark(client_with_tickets.get, "/tickets")
    assert result.status_code == 200


def test_get_tickets_with_filter_performance(benchmark, client_with_tickets):
    result = benchmark(client_with_tickets.get, "/tickets?category=bug&priority=P1")
    assert result.status_code == 200


def test_get_ticket_by_id_performance(benchmark, client):
    r = client.post("/tickets", json=TICKET_PAYLOAD)
    ticket_id = r.json()["id"]
    result = benchmark(client.get, f"/tickets/{ticket_id}")
    assert result.status_code == 200


def test_patch_ticket_performance(benchmark, client):
    r = client.post("/tickets", json=TICKET_PAYLOAD)
    ticket_id = r.json()["id"]
    result = benchmark(client.patch, f"/tickets/{ticket_id}", json={"status": "in_progress"})
    assert result.status_code == 200
