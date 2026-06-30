"""Tests de la UI HTMX (GET / y rutas /ui/tickets) — sin red (clasificador mockeado).

Cubren lo que los tests de API no tocan: que `/` devuelva HTML con formulario y
filtros, que el fragmento de tabla se renderice y filtre, el caso de crear con
filtro activo, y el escapado HTML (anti-XSS) de la entrada del usuario.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def _mock_classifier(monkeypatch, category="bug", priority="P1", tags=None):
    tags = tags if tags is not None else ["login"]
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": category, "priority": priority, "tags": list(tags)},
    )


def test_index_returns_html_with_form_and_filters(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert 'hx-post="/ui/tickets"' in body          # formulario de creación
    assert 'name="title"' in body and 'name="description"' in body
    # los tres filtros
    assert 'name="category"' in body
    assert 'name="priority"' in body
    assert 'name="status"' in body


def test_index_shows_empty_state_when_no_tickets(client):
    assert "No hay tickets" in client.get("/").text


def test_ui_tickets_fragment_renders_table(client):
    r = client.get("/ui/tickets")
    assert r.status_code == 200
    assert "<table" in r.text


def test_ui_create_ticket_via_form_creates_and_renders_row(client, monkeypatch):
    _mock_classifier(monkeypatch, category="feature_request", priority="P2", tags=["pdf"])
    r = client.post("/ui/tickets", data={"title": "Exportar a PDF", "description": "Necesitamos PDF"})
    assert r.status_code == 200
    assert "Exportar a PDF" in r.text
    # y queda persistido (visible vía API JSON)
    assert any(t["title"] == "Exportar a PDF" for t in client.get("/tickets").json())


def test_ui_create_with_active_filter_keeps_view_consistent(client, monkeypatch):
    # El ticket nuevo es 'open'; si filtramos por status=closed no debe aparecer
    # en el fragmento devuelto, pero SÍ debe persistirse.
    _mock_classifier(monkeypatch)
    r = client.post(
        "/ui/tickets",
        data={"title": "Ticket abierto", "description": "desc", "status": "closed"},
    )
    assert r.status_code == 200
    assert "Ticket abierto" not in r.text                 # filtrado fuera de la vista
    assert any(t["title"] == "Ticket abierto" for t in client.get("/tickets").json())  # persistido


def test_ui_create_invalid_input_creates_nothing(client, monkeypatch):
    _mock_classifier(monkeypatch)
    r = client.post("/ui/tickets", data={"title": "   ", "description": "válida"})
    assert r.status_code == 200
    assert client.get("/tickets").json() == []            # no se creó nada


def test_ui_list_filters_are_combined_with_and(client, monkeypatch):
    _mock_classifier(monkeypatch, category="urgent", priority="P1")
    client.post("/ui/tickets", data={"title": "Urge P1", "description": "x"})
    _mock_classifier(monkeypatch, category="bug", priority="P2")
    client.post("/ui/tickets", data={"title": "Bug P2", "description": "y"})
    # C comparte SOLO la categoría con el filtro: si el filtro de priority se
    # ignorara (o fuera OR), C aparecería → el test lo detecta.
    _mock_classifier(monkeypatch, category="urgent", priority="P2")
    client.post("/ui/tickets", data={"title": "Urge P2", "description": "z"})

    r = client.get("/ui/tickets", params={"category": "urgent", "priority": "P1"})
    assert "Urge P1" in r.text          # cumple ambos filtros
    assert "Bug P2" not in r.text        # no cumple ninguno
    assert "Urge P2" not in r.text       # cumple category pero NO priority → AND real


def test_ui_escapes_html_in_user_input_no_xss(client, monkeypatch):
    # Anti-XSS: el título malicioso debe salir escapado, nunca como <script> crudo.
    _mock_classifier(monkeypatch)
    payload = "<script>alert('xss')</script>"
    r = client.post("/ui/tickets", data={"title": payload, "description": "desc válida"})
    assert r.status_code == 200
    assert payload not in r.text                          # no aparece crudo
    assert "&lt;script&gt;" in r.text                     # aparece escapado


# --------------------------------------------------------------------------- #
# Buscador, paginación, edición inline y persistencia de estado
# --------------------------------------------------------------------------- #
HX = {"HX-Request": "true"}


def test_ui_search_narrows_results(client, monkeypatch):
    _mock_classifier(monkeypatch)
    client.post("/ui/tickets", data={"title": "Error de login", "description": "no entro"})
    client.post("/ui/tickets", data={"title": "Exportar PDF", "description": "informes"})

    r = client.get("/ui/tickets", params={"q": "login"}, headers=HX)
    assert "Error de login" in r.text
    assert "Exportar PDF" not in r.text


def test_ui_search_matches_description_too(client, monkeypatch):
    _mock_classifier(monkeypatch)
    client.post("/ui/tickets", data={"title": "Cosa", "description": "fallo en el checkout"})
    r = client.get("/ui/tickets", params={"q": "checkout"}, headers=HX)
    assert "Cosa" in r.text


def test_ui_inline_edit_changes_status(client, monkeypatch):
    _mock_classifier(monkeypatch)
    tid = client.post("/tickets", json={"title": "Ticket", "description": "desc"}).json()["id"]
    r = client.post(f"/ui/tickets/{tid}", data={"new_status": "closed"}, headers=HX)
    assert r.status_code == 200
    assert client.get(f"/tickets/{tid}").json()["status"] == "closed"


def test_ui_inline_edit_changes_priority(client, monkeypatch):
    _mock_classifier(monkeypatch, priority="P1")
    tid = client.post("/tickets", json={"title": "Ticket", "description": "desc"}).json()["id"]
    client.post(f"/ui/tickets/{tid}", data={"new_priority": "P3"}, headers=HX)
    assert client.get(f"/tickets/{tid}").json()["priority"] == "P3"


def test_index_defaults_to_open_status(client, monkeypatch):
    # Crea 1 ticket y lo pasa a closed; GET / (sin params) muestra abiertos por
    # defecto, así que el cerrado no debe aparecer.
    _mock_classifier(monkeypatch)
    tid = client.post("/tickets", json={"title": "Cerrado", "description": "x"}).json()["id"]
    client.post(f"/ui/tickets/{tid}", data={"new_status": "closed"}, headers=HX)
    assert "Cerrado" not in client.get("/").text                 # filtrado a open por defecto
    assert "Cerrado" in client.get("/", params={"status": ""}).text  # "todos" lo muestra


def test_index_preserves_filter_via_query(client, monkeypatch):
    _mock_classifier(monkeypatch, category="urgent")
    client.post("/tickets", json={"title": "Urgente", "description": "x"})
    # GET / con filtro explícito por query → la página ya viene filtrada (estado al recargar).
    assert "Urgente" in client.get("/", params={"category": "urgent", "status": ""}).text
    assert "Urgente" not in client.get("/", params={"category": "bug", "status": ""}).text


def test_ui_inline_edit_keeps_current_page(client, monkeypatch):
    # Marta no debe perder su sitio: editar un ticket estando en la página 2
    # devuelve la página 2 (no salta a la 1).
    _mock_classifier(monkeypatch)
    ids = [client.post("/tickets", json={"title": f"T{i}", "description": "x"}).json()["id"]
           for i in range(23)]
    r = client.post(
        f"/ui/tickets/{ids[0]}",
        data={"new_priority": "P2", "status": "", "page": 2},
        headers=HX,
    )
    assert "Página 2 de 2" in r.text


def test_ui_pagination_caps_page_size(client, monkeypatch):
    _mock_classifier(monkeypatch)
    for i in range(23):
        client.post("/tickets", json={"title": f"T{i}", "description": "x"})
    # Página 1: como máximo PAGE_SIZE (20) filas; hay un <select name="new_status"> por fila.
    page1 = client.get("/ui/tickets", params={"status": ""}, headers=HX).text
    assert page1.count('name="new_status"') == 20
    page2 = client.get("/ui/tickets", params={"status": "", "page": 2}, headers=HX).text
    assert page2.count('name="new_status"') == 3            # 23 - 20


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ui_inline_edit_invalid_status_is_ignored(client, monkeypatch):
    # ValidationError silenciada: status inválido no cae el endpoint ni cambia el ticket.
    _mock_classifier(monkeypatch)
    tid = client.post("/tickets", json={"title": "T", "description": "d"}).json()["id"]
    r = client.post(f"/ui/tickets/{tid}", data={"new_status": "INVALIDO"}, headers=HX)
    assert r.status_code == 200
    assert client.get(f"/tickets/{tid}").json()["status"] == "open"  # sin cambios


def test_assignees_capped_at_ten(client, monkeypatch):
    # _parse_assignees: si llegan 11 nombres, solo persisten los 10 primeros.
    _mock_classifier(monkeypatch)
    tid = client.post("/tickets", json={"title": "T", "description": "d"}).json()["id"]
    eleven = ",".join(f"user{i}" for i in range(11))
    client.post(f"/ui/tickets/{tid}", data={"new_assignees": eleven}, headers=HX)
    assert len(client.get(f"/tickets/{tid}").json()["assignees"]) == 10
