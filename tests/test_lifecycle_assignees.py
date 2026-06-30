"""Tests de Ciclo de vida (estados resolved/reabrir + 'desde cuándo') y
Responsables (varios assignees + filtro). Mockean el clasificador (sin red).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

HX = {"HX-Request": "true"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": "P1", "tags": []},
    )
    return TestClient(app)


def _new(client, title="T", description="desc"):
    return client.post("/tickets", json={"title": title, "description": description}).json()


# --------------------------------------------------------------------------- #
# Ciclo de vida: resolved, reabrir, "desde cuándo" (status_changed_at)
# --------------------------------------------------------------------------- #
def test_resolved_is_a_valid_status(client):
    tid = _new(client)["id"]
    r = client.patch(f"/tickets/{tid}", json={"status": "resolved"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


def test_reopen_a_resolved_ticket(client):
    tid = _new(client)["id"]
    client.patch(f"/tickets/{tid}", json={"status": "resolved"})
    reopened = client.patch(f"/tickets/{tid}", json={"status": "open"})
    assert reopened.json()["status"] == "open"


def test_status_changed_at_set_on_create(client):
    data = _new(client)
    assert data["status_changed_at"]
    assert data["status_changed_at"] == data["created_at"]


def test_status_changed_at_advances_when_status_changes(client):
    data = _new(client)
    tid, before = data["id"], data["status_changed_at"]
    after = client.patch(f"/tickets/{tid}", json={"status": "in_progress"}).json()
    assert after["status_changed_at"] != before


def test_status_changed_at_not_touched_when_only_priority_changes(client):
    data = _new(client)
    tid, before = data["id"], data["status_changed_at"]
    after = client.patch(f"/tickets/{tid}", json={"priority": "P2"}).json()
    assert after["status_changed_at"] == before


def test_invalid_status_still_rejected(client):
    tid = _new(client)["id"]
    assert client.patch(f"/tickets/{tid}", json={"status": "archivado"}).status_code == 422


# --------------------------------------------------------------------------- #
# Responsables: varios assignees + filtro por responsable
# --------------------------------------------------------------------------- #
def test_assignees_default_to_empty_list(client):
    data = _new(client)
    assert data["assignees"] == []
    assert isinstance(data["assignees"], list)


def test_inline_edit_sets_multiple_assignees(client):
    tid = _new(client)["id"]
    client.post(f"/ui/tickets/{tid}", data={"new_assignees": "Ana, Luis , Marta"}, headers=HX)
    assert client.get(f"/tickets/{tid}").json()["assignees"] == ["Ana", "Luis", "Marta"]


def test_inline_edit_can_clear_assignees(client):
    tid = _new(client)["id"]
    client.post(f"/ui/tickets/{tid}", data={"new_assignees": "Ana"}, headers=HX)
    client.post(f"/ui/tickets/{tid}", data={"new_assignees": ""}, headers=HX)
    assert client.get(f"/tickets/{tid}").json()["assignees"] == []


def test_filter_by_assignee_json_api(client):
    a = _new(client, title="A")["id"]
    b = _new(client, title="B")["id"]
    client.post(f"/ui/tickets/{a}", data={"new_assignees": "ana"}, headers=HX)
    client.post(f"/ui/tickets/{b}", data={"new_assignees": "luis"}, headers=HX)
    res = client.get("/tickets", params={"assignee": "ana"}).json()
    assert [t["id"] for t in res] == [a]


def test_ui_filter_by_assignee(client):
    a = _new(client, title="Ticket de Ana")["id"]
    _new(client, title="Ticket de Luis")
    client.post(f"/ui/tickets/{a}", data={"new_assignees": "ana"}, headers=HX)
    r = client.get("/ui/tickets", params={"assignee": "ana", "status": ""}, headers=HX)
    assert "Ticket de Ana" in r.text
    assert "Ticket de Luis" not in r.text


def test_inline_edit_assignees_keeps_status_and_priority(client):
    # Editar responsables no debe tocar status/priority del ticket.
    data = _new(client)
    tid = data["id"]
    client.post(f"/ui/tickets/{tid}", data={"new_assignees": "ana"}, headers=HX)
    after = client.get(f"/tickets/{tid}").json()
    assert after["status"] == data["status"]
    assert after["priority"] == data["priority"]
    assert after["assignees"] == ["ana"]
