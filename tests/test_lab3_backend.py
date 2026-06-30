import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def _ok_classification(**kwargs):
    base = {"category": "bug", "priority": "P1", "tags": ["login"]}
    base.update(kwargs)
    return base


# 1 — title y description se guardan ya strippeados
def test_title_description_stored_stripped(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: _ok_classification())
    response = client.post(
        "/tickets",
        json={"title": "  Título con espacios  ", "description": "  Descripción con espacios  "},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Título con espacios"
    assert data["description"] == "Descripción con espacios"


# 2 — si el clasificador devuelve category inválida, se usa el fallback
def test_classifier_invalid_response_uses_fallback(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "INVALIDA", "priority": "P1", "tags": []},
    )
    response = client.post(
        "/tickets",
        json={"title": "Ticket de prueba", "description": "Descripción válida del ticket"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["category"] == "question"
    assert data["priority"] == "P3"
    assert data["tags"] == []


# 3 — filtros combinados devuelven solo los tickets que cumplen los 3 a la vez
def test_get_tickets_combined_filters(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: _ok_classification(category="urgent", priority="P1"),
    )
    client.post("/tickets", json={"title": "Ticket A", "description": "desc urgente P1"})

    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: _ok_classification(category="bug", priority="P2"),
    )
    client.post("/tickets", json={"title": "Ticket B", "description": "desc bug P2"})

    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: _ok_classification(category="urgent", priority="P2"),
    )
    r = client.post("/tickets", json={"title": "Ticket C", "description": "desc urgente P2"})
    ticket_c_id = r.json()["id"]
    # Parchear C a in_progress para que el filtro de status sea significativo
    client.patch(f"/tickets/{ticket_c_id}", json={"status": "in_progress"})

    filtered = client.get("/tickets", params={"category": "urgent", "priority": "P2", "status": "in_progress"})
    assert filtered.status_code == 200
    tickets = filtered.json()
    assert len(tickets) == 1
    assert tickets[0]["id"] == ticket_c_id


# 4 — PATCH con status inválido devuelve 422
def test_patch_invalid_status_returns_422(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: _ok_classification())
    r = client.post("/tickets", json={"title": "Ticket", "description": "Descripción del ticket"})
    ticket_id = r.json()["id"]
    response = client.patch(f"/tickets/{ticket_id}", json={"status": "borrado"})
    assert response.status_code == 422


# 5 — PATCH con priority inválida devuelve 422
def test_patch_invalid_priority_returns_422(client, monkeypatch):
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: _ok_classification())
    r = client.post("/tickets", json={"title": "Ticket", "description": "Descripción del ticket"})
    ticket_id = r.json()["id"]
    response = client.patch(f"/tickets/{ticket_id}", json={"priority": "P4"})
    assert response.status_code == 422


# 6 — PATCH de ticket inexistente devuelve 404
def test_patch_nonexistent_ticket_returns_404(client):
    response = client.patch("/tickets/99999", json={"status": "closed"})
    assert response.status_code == 404


# 7 — GET /tickets/{id} devuelve el ticket correcto
def test_get_ticket_by_id(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: _ok_classification(category="question", priority="P3", tags=[]),
    )
    created = client.post(
        "/tickets",
        json={"title": "Consulta de usuario", "description": "Cómo cambio mi contraseña"},
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    response = client.get(f"/tickets/{ticket_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == ticket_id
    assert data["title"] == "Consulta de usuario"
    assert data["category"] == "question"


# 8 — GET /tickets/{id} inexistente devuelve 404
def test_get_ticket_not_found_returns_404(client):
    response = client.get("/tickets/99999")
    assert response.status_code == 404


# 9 — tags se devuelven como lista, no como string JSON
def test_tags_returned_as_list(client, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: _ok_classification(tags=["auth", "critical", "mobile"]),
    )
    response = client.post(
        "/tickets",
        json={"title": "Error de login en móvil", "description": "Falla al autenticar desde la app"},
    )
    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["tags"], list)
    assert data["tags"] == ["auth", "critical", "mobile"]
