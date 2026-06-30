"""Tests de robustez / casos límite de QA (unicode, XSS, SQLi, duplicados,
IDs malformados, concurrencia). No tocan la API ni los tests obligatorios.
"""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": "bug", "priority": "P1", "tags": []},
    )
    return TestClient(app)


# --------------------------------------------------------------------------- #
# #3 — Emojis y caracteres unicode no latinos: se conservan intactos
# --------------------------------------------------------------------------- #
def test_unicode_and_emojis_are_preserved(client):
    title = "🔥 Fallo en café — 日本語 ✓"
    description = "Описание con émojis 🚀 y 中文 — el niño no entró"
    r = client.post("/tickets", json={"title": title, "description": description})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == title
    assert data["description"] == description
    assert any(t["title"] == title for t in client.get("/tickets").json())


# --------------------------------------------------------------------------- #
# #4 — HTML/JS en la entrada: el título (que SÍ se renderiza) va escapado;
#       la descripción se persiste literal y no se expone cruda en el tablero.
# --------------------------------------------------------------------------- #
def test_html_in_description_persisted_and_not_exposed_raw(client):
    # La descripción no se muestra en el tablero hoy; este test fija ese contrato:
    # si alguien la renderizara SIN escapar en el futuro, este assert lo pillaría.
    desc = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    r = client.post("/tickets", json={"title": "T", "description": desc})
    assert r.status_code == 201
    assert r.json()["description"] == desc            # JSON: se guarda literal
    assert "<script>alert(" not in client.get("/", params={"status": ""}).text


def test_html_in_title_is_escaped_in_board(client):
    client.post("/tickets", json={"title": "<script>alert(1)</script>", "description": "d"})
    body = client.get("/", params={"status": ""}).text
    assert "<script>alert(1)</script>" not in body    # nunca crudo
    assert "&lt;script&gt;" in body                   # escapado


# --------------------------------------------------------------------------- #
# #5 — Inyección SQL: queries parametrizadas; ni rompe ni devuelve de más
# --------------------------------------------------------------------------- #
def test_sql_injection_in_search_is_safe(client):
    # Nota: el buscador (q) vive en la UI (/ui/tickets) y en db.list_tickets;
    # GET /tickets (JSON) no tiene `q`. Probamos la búsqueda real.
    client.post("/tickets", json={"title": "alpha", "description": "x"})
    client.post("/tickets", json={"title": "beta", "description": "y"})
    # q se parametriza → el intento de inyección casa como literal: no devuelve nada.
    assert db.list_tickets(None, None, None, q="' OR '1'='1") == []
    # Intento de DROP no destruye la tabla.
    db.list_tickets(None, None, None, q="'; DROP TABLE tickets; --")
    assert len(db.list_tickets(None, None, None)) == 2
    # Y por la ruta UI tampoco "se cuela todo".
    r = client.get("/ui/tickets", params={"q": "' OR '1'='1", "status": ""},
                   headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "alpha" not in r.text and "beta" not in r.text


def test_sql_injection_in_assignee_filter_is_safe(client):
    # Sembramos tickets CON responsables (db.create_ticket; el POST no asigna).
    db.create_ticket({"title": "A", "description": "x", "category": "bug",
                      "priority": "P1", "tags": [], "assignees": ["ana"]})
    db.create_ticket({"title": "B", "description": "y", "category": "bug",
                      "priority": "P1", "tags": [], "assignees": ["luis"]})
    # El filtro legítimo funciona...
    assert [t["title"] for t in db.list_tickets(None, None, None, assignee="ana")] == ["A"]
    # ...y un intento de inyección NO filtra de más (sigue parametrizado).
    assert client.get("/tickets", params={"assignee": "' OR 1=1 --"}).json() == []
    assert db.list_tickets(None, None, None, assignee='" OR "1"="1') == []


# --------------------------------------------------------------------------- #
# #7 — Mismo ticket dos veces: comportamiento definido (2 tickets distintos)
# --------------------------------------------------------------------------- #
def test_duplicate_submissions_create_distinct_tickets(client):
    payload = {"title": "ticket repetido", "description": "mismo contenido"}
    a = client.post("/tickets", json=payload)
    b = client.post("/tickets", json=payload)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]            # ids distintos, sin error
    dups = [t for t in client.get("/tickets").json() if t["title"] == "ticket repetido"]
    assert len(dups) == 2                              # intencional: no hay dedup


# --------------------------------------------------------------------------- #
# #8 — IDs malformados: 422 si no es entero, 404 si no existe; sin crash
# --------------------------------------------------------------------------- #
def test_malformed_ids(client):
    assert client.get("/tickets/abc").status_code == 422
    assert client.patch("/tickets/abc", json={"status": "open"}).status_code == 422
    assert client.get("/tickets/-1").status_code == 404
    assert client.get("/tickets/99999999999").status_code == 404
    assert client.patch("/tickets/99999999999", json={"status": "open"}).status_code == 404


# --------------------------------------------------------------------------- #
# #10 — Concurrencia
# --------------------------------------------------------------------------- #
def test_concurrent_inserts_no_duplicates_or_errors(tmp_path, monkeypatch):
    # 20 inserts concurrentes: ninguno falla, ids únicos, sin corrupción ni pérdida.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'conc.db'}")
    db.get_connection().close()  # crea el esquema una vez antes de la carga concurrente

    def _make(i: int) -> dict:
        return db.create_ticket({
            "title": f"t{i}", "description": "x",
            "category": "bug", "priority": "P1", "tags": [],
        })

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(_make, range(20)))

    assert len(results) == 20
    assert len({r["id"] for r in results}) == 20       # 20 ids únicos
    assert len(db.list_tickets(None, None, None)) == 20


def test_busy_timeout_lets_a_contended_write_succeed(tmp_path, monkeypatch):
    # Prueba que SÍ depende del fix: un hilo retiene el lock de escritura ~0.4 s;
    # gracias a busy_timeout, create_ticket ESPERA y no falla con "database is
    # locked" (sin busy_timeout / con timeout=0 fallaría al instante).
    dbpath = tmp_path / "lock.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbpath}")
    db.get_connection().close()  # crea el esquema (y deja la BD en modo WAL)

    locked = threading.Event()

    def _holder():
        # La conexión se crea y se cierra dentro del MISMO hilo (sqlite lo exige).
        conn = sqlite3.connect(str(dbpath))
        conn.execute("BEGIN IMMEDIATE")  # adquiere el lock de escritura
        locked.set()
        time.sleep(0.4)
        conn.commit()
        conn.close()

    th = threading.Thread(target=_holder)
    th.start()
    assert locked.wait(2)  # esperamos a que el holder tenga el lock

    t0 = time.time()
    ticket = db.create_ticket({  # contiende por el lock → espera (busy_timeout) y se crea
        "title": "contended", "description": "x",
        "category": "bug", "priority": "P1", "tags": [],
    })
    elapsed = time.time() - t0
    th.join()

    assert ticket["id"]    # se creó pese al lock retenido
    assert elapsed >= 0.2  # de verdad esperó (no falló al instante)
