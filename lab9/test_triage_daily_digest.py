"""Tests para la skill triage_daily_digest (Lab 9)."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Asegurar que el raíz del repo esté en el path para importar lab9.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab9.triage_daily_digest import build_digest, fetch_tickets, get_digest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TICKETS = [
    {
        "id": 1, "title": "App no carga", "description": "Pantalla en blanco",
        "category": "bug", "priority": "P1", "status": "open",
        "tags": ["login"], "created_at": "2026-07-01T08:00:00+00:00",
        "due_date": "2026-07-01T08:00:00+00:00",
    },
    {
        "id": 2, "title": "Añadir filtro por estado", "description": "Me gustaría filtrar",
        "category": "feature_request", "priority": "P2", "status": "open",
        "tags": [], "created_at": "2026-07-01T09:00:00+00:00",
        "due_date": "2026-07-02T09:00:00+00:00",
    },
    {
        "id": 3, "title": "¿Cómo pido acceso?", "description": "No sé cómo pedir permisos",
        "category": "question", "priority": "P3", "status": "open",
        "tags": [], "created_at": "2026-07-01T10:00:00+00:00",
        "due_date": "2026-07-03T10:00:00+00:00",
    },
    {
        "id": 4, "title": "Bug cerrado", "description": "Ya resuelto",
        "category": "bug", "priority": "P2", "status": "closed",
        "tags": [], "created_at": "2026-06-30T10:00:00+00:00",
        "due_date": "2026-06-30T10:00:00+00:00",
    },
]


def _mock_response(data: list) -> MagicMock:
    """Crea un mock de urlopen que devuelve data como JSON."""
    body = json.dumps(data).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests de build_digest (sin red)
# ---------------------------------------------------------------------------

def test_build_digest_empty_list():
    result = build_digest([])
    assert "no hay tickets" in result.lower() or "vacío" in result.lower()
    assert "Daily Digest" in result


def test_build_digest_shows_total_count():
    result = build_digest(SAMPLE_TICKETS)
    # 4 tickets pero 1 cerrado → 3 activos
    assert "3" in result


def test_build_digest_shows_priority_counts():
    result = build_digest(SAMPLE_TICKETS)
    assert "P1" in result
    assert "P2" in result
    assert "P3" in result


def test_build_digest_highlights_p1_tickets():
    result = build_digest(SAMPLE_TICKETS)
    assert "App no carga" in result


def test_build_digest_closed_tickets_not_in_active_count():
    result = build_digest(SAMPLE_TICKETS)
    # El ticket 4 está closed: no debe aparecer en urgentes/activos
    assert "Bug cerrado" not in result


def test_build_digest_includes_recommendation():
    result = build_digest(SAMPLE_TICKETS)
    assert "recomendad" in result.lower() or "siguiente" in result.lower()


def test_build_digest_only_closed_shows_empty():
    all_closed = [
        {**t, "status": "closed"} for t in SAMPLE_TICKETS
    ]
    result = build_digest(all_closed)
    assert "no hay tickets" in result.lower() or "vacío" in result.lower()


def test_build_digest_handles_missing_fields():
    minimal = [{"id": 1, "title": "ticket roto"}]
    result = build_digest(minimal)
    assert "Daily Digest" in result
    assert "1" in result


# ---------------------------------------------------------------------------
# Tests de fetch_tickets (red mockeada)
# ---------------------------------------------------------------------------

def test_fetch_tickets_parses_json():
    with patch("lab9.triage_daily_digest.urlopen", return_value=_mock_response(SAMPLE_TICKETS)):
        result = fetch_tickets("http://localhost:8000")
    assert len(result) == 4
    assert result[0]["title"] == "App no carga"


def test_fetch_tickets_raises_on_non_list():
    with patch("lab9.triage_daily_digest.urlopen", return_value=_mock_response({"error": "oops"})):
        with pytest.raises(ValueError, match="lista"):
            fetch_tickets("http://localhost:8000")


# ---------------------------------------------------------------------------
# Tests de get_digest (integración con manejo de errores)
# ---------------------------------------------------------------------------

def test_get_digest_returns_string():
    with patch("lab9.triage_daily_digest.urlopen", return_value=_mock_response(SAMPLE_TICKETS)):
        result = get_digest("http://localhost:8000")
    assert isinstance(result, str)
    assert "Daily Digest" in result


def test_get_digest_empty_list():
    with patch("lab9.triage_daily_digest.urlopen", return_value=_mock_response([])):
        result = get_digest("http://localhost:8000")
    assert "no hay tickets" in result.lower() or "vacío" in result.lower()


def test_get_digest_handles_network_error():
    from urllib.error import URLError
    with patch("lab9.triage_daily_digest.urlopen", side_effect=URLError("connection refused")):
        result = get_digest("http://localhost:9999")
    assert "error" in result.lower()
    assert "connection refused" in result.lower()


def test_get_digest_handles_http_error():
    from urllib.error import HTTPError
    err = HTTPError("http://x", 503, "Service Unavailable", {}, None)
    with patch("lab9.triage_daily_digest.urlopen", side_effect=err):
        result = get_digest("http://localhost:8000")
    assert "503" in result


def test_get_digest_handles_invalid_json():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html>ngrok warning</html>"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("lab9.triage_daily_digest.urlopen", return_value=mock_resp):
        result = get_digest("http://localhost:8000")
    assert "error" in result.lower() or "inválid" in result.lower()
