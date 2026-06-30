"""Tests para la feature de plazos (due_date)."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app

FAKE_CLASS = {"category": "bug", "priority": "P1", "tags": []}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: FAKE_CLASS)
    return TestClient(app)


# ── cálculo de due_date por prioridad ────────────────────────────────────────

@pytest.mark.parametrize("priority,days", [("P1", 0), ("P2", 1), ("P3", 2)])
def test_due_date_calculated_from_priority(tmp_path, monkeypatch, priority, days):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": priority, "tags": []},
    )
    c = TestClient(app)
    r = c.post("/tickets", json={"title": "titulo", "description": "descripcion"})
    assert r.status_code == 201
    ticket = r.json()
    assert "due_date" in ticket
    due = datetime.fromisoformat(ticket["due_date"])
    created = datetime.fromisoformat(ticket["created_at"])
    diff = (due - created).days
    assert diff == days, f"P{priority}: esperado {days} días, got {diff}"


def test_due_date_present_in_get_tickets(client):
    r = client.post("/tickets", json={"title": "t", "description": "d"})
    assert r.status_code == 201
    tickets = client.get("/tickets").json()
    assert len(tickets) == 1
    assert "due_date" in tickets[0]
    assert tickets[0]["due_date"] is not None


def test_due_date_present_in_get_by_id(client):
    r = client.post("/tickets", json={"title": "t", "description": "d"})
    tid = r.json()["id"]
    ticket = client.get(f"/tickets/{tid}").json()
    assert "due_date" in ticket


# ── filtro overdue ────────────────────────────────────────────────────────────

def test_overdue_filter_excludes_future_tickets(tmp_path, monkeypatch):
    """Ticket recién creado (P1 = vence hoy) no debe aparecer como vencido inmediatamente."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": "P3", "tags": []},
    )
    c = TestClient(app)
    c.post("/tickets", json={"title": "futuro", "description": "desc"})
    overdue = c.get("/tickets?overdue=true").json()
    assert overdue == [], "P3 recién creado no debe ser vencido"


def test_overdue_filter_includes_past_due_tickets(tmp_path, monkeypatch):
    """Ticket con due_date en el pasado y estado open aparece en overdue."""
    from app import db as app_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": "P1", "tags": []},
    )
    c = TestClient(app)

    # Creamos ticket con due_date explícitamente en el pasado
    past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    app_db.create_ticket({
        "title": "vencido", "description": "desc",
        "category": "bug", "priority": "P1", "tags": [], "status": "open",
        "due_date": past,
    })

    overdue = c.get("/tickets?overdue=true").json()
    assert len(overdue) == 1
    assert overdue[0]["title"] == "vencido"


def test_overdue_excludes_closed_tickets(tmp_path, monkeypatch):
    """Ticket vencido pero cerrado NO aparece en overdue."""
    from app import db as app_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    c = TestClient(app)

    past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    app_db.create_ticket({
        "title": "cerrado", "description": "desc",
        "category": "bug", "priority": "P1", "tags": [], "status": "closed",
        "due_date": past,
    })

    overdue = c.get("/tickets?overdue=true").json()
    assert overdue == [], "ticket cerrado no debe aparecer como vencido"
