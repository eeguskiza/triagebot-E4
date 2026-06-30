"""Tests de la capa de datos (app/db.py): búsqueda, paginación y count.

Verifican que las opciones nuevas son aditivas (sin `q`/`limit` el comportamiento
histórico se mantiene → la API JSON y los tests obligatorios no cambian).
"""

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return tmp_path


def _make(title, description="desc", category="bug", priority="P1", status="open"):
    db.create_ticket({
        "title": title, "description": description, "category": category,
        "priority": priority, "tags": [], "status": status,
    })


def test_list_without_limit_returns_all(tmp_db):
    for i in range(30):
        _make(f"T{i}")
    # Contrato histórico: sin limit devuelve TODO (lo que usan API JSON y tests).
    assert len(db.list_tickets(None, None, None)) == 30


def test_list_with_limit_and_offset_paginates(tmp_db):
    for i in range(25):
        _make(f"T{i}")
    page1 = db.list_tickets(None, None, None, limit=20, offset=0)
    page2 = db.list_tickets(None, None, None, limit=20, offset=20)
    assert len(page1) == 20
    assert len(page2) == 5
    # Sin solapamiento entre páginas.
    assert {t["id"] for t in page1}.isdisjoint({t["id"] for t in page2})


def test_count_tickets_respects_filters(tmp_db):
    _make("A", category="bug")
    _make("B", category="urgent")
    _make("C", category="urgent")
    assert db.count_tickets(None, None, None) == 3
    assert db.count_tickets("urgent", None, None) == 2


def test_search_matches_title_and_description(tmp_db):
    _make("Error de login", description="no puedo entrar")
    _make("Exportar PDF", description="informe mensual con checkout")
    by_title = db.list_tickets(None, None, None, q="login")
    by_desc = db.list_tickets(None, None, None, q="checkout")
    assert [t["title"] for t in by_title] == ["Error de login"]
    assert [t["title"] for t in by_desc] == ["Exportar PDF"]
    assert db.count_tickets(None, None, None, q="login") == 1


def test_search_combines_with_filters(tmp_db):
    _make("Login lento", category="bug")
    _make("Login caído", category="urgent")
    # q + filtro category → AND
    res = db.list_tickets("urgent", None, None, q="login")
    assert [t["title"] for t in res] == ["Login caído"]


def test_get_db_path_fallback_when_no_env(monkeypatch):
    # Sin DATABASE_URL (o con formato incorrecto) → devuelve "triagebot.db".
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.db import _get_db_path
    assert _get_db_path() == "triagebot.db"

    monkeypatch.setenv("DATABASE_URL", "postgres://localhost/foo")
    assert _get_db_path() == "triagebot.db"
