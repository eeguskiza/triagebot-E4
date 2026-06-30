"""Tests de integración end-to-end (API + clasificador real, sin red).

Mockean el backend interno (_classify_openai), NO classify_ticket, para ejercitar
el flujo completo: dispatch → validación → normalización → persistencia → respuesta.
Cubren contratos del SPEC visibles para el cliente: orden por created_at desc y
recorte de tags (≤5, ≤30 chars).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    return TestClient(app)


def test_get_tickets_ordered_by_created_at_desc(client, monkeypatch):
    # Orden esperado: más nuevo primero (desempate por id desc lo hace determinista).
    monkeypatch.setattr(
        "app.classifier._classify_openai",
        lambda t, d: {"category": "bug", "priority": "P1", "tags": []},
    )
    ids = [
        client.post("/tickets", json={"title": f"T{i}", "description": "x"}).json()["id"]
        for i in range(3)
    ]
    listed = client.get("/tickets").json()
    assert [t["id"] for t in listed] == sorted(ids, reverse=True)


def test_tags_are_capped_and_truncated_end_to_end(client, monkeypatch):
    # El backend devuelve 8 tags y uno larguísimo; el contrato (≤5, ≤30) debe
    # aplicarse en el flujo real y reflejarse en la respuesta de la API.
    long_tag = "x" * 50
    monkeypatch.setattr(
        "app.classifier._classify_openai",
        lambda t, d: {
            "category": "bug",
            "priority": "P1",
            "tags": [long_tag] + [f"t{i}" for i in range(7)],
        },
    )
    data = client.post("/tickets", json={"title": "T", "description": "x"}).json()
    assert len(data["tags"]) == 5                 # recortado a MAX_TAGS
    assert all(len(t) <= 30 for t in data["tags"])  # cada tag <= MAX_TAG_LEN
    assert data["tags"][0] == "x" * 30            # el largo, truncado a 30
