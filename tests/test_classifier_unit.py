"""Tests unitarios del clasificador (app/classifier.py) SIN llamadas reales al LLM.

Cubren la lógica interna que los tests de API no tocan (mockean classify_ticket
entero): parseo robusto de JSON, normalización de tags, validación de enums,
reintento, dispatch por proveedor y la garantía de "nunca lanza / siempre fallback".
El camino OpenAI se prueba con un cliente FALSO (sin red, sin gastar cuota).
"""

from types import SimpleNamespace

import pytest

from app import classifier, config
from app.classifier import (
    FALLBACK_CLASSIFICATION,
    _build_system_prompt,
    _classify_anthropic,
    _classify_openai,
    _normalize_tags,
    _parse_json,
    _safe_fallback,
    _validate,
    classify_ticket,
)


# --------------------------------------------------------------------------- #
# _parse_json — tolerante a fences ```json y a texto alrededor
# --------------------------------------------------------------------------- #
def test_parse_json_plain_object():
    assert _parse_json('{"category": "bug", "priority": "P1", "tags": ["x"]}') == {
        "category": "bug", "priority": "P1", "tags": ["x"],
    }


@pytest.mark.parametrize("wrapped", [
    '```json\n{"category": "bug", "priority": "P1", "tags": []}\n```',
    '```\n{"category": "bug", "priority": "P1", "tags": []}\n```',
    'Claro, aquí tienes: {"category": "bug", "priority": "P1", "tags": []} ¡listo!',
])
def test_parse_json_handles_fences_and_surrounding_prose(wrapped):
    assert _parse_json(wrapped) == {"category": "bug", "priority": "P1", "tags": []}


def test_parse_json_picks_outermost_object_with_nested_braces():
    assert _parse_json('ruido {"a": {"b": 1}} fin') == {"a": {"b": 1}}


@pytest.mark.parametrize("bad", ["", None, "   ", "no hay json aquí", '{"roto": ,}', "{sin comillas}"])
def test_parse_json_returns_none_on_garbage(bad):
    assert _parse_json(bad) is None


def test_parse_json_non_dict_json_is_returned_as_is_and_rejected_by_validate():
    # json.loads de una lista devuelve la lista; _validate la rechaza luego.
    assert _parse_json("[1, 2, 3]") == [1, 2, 3]
    assert _validate([1, 2, 3]) is None


# --------------------------------------------------------------------------- #
# _normalize_tags — minúscula, recorte, cap, descarte de inválidos
# --------------------------------------------------------------------------- #
def test_normalize_tags_lowercases_and_drops_empty_and_non_strings():
    raw = ["LOGIN", "  Pago  ", "", "   ", 123, None, {"k": "v"}, "ok"]
    assert _normalize_tags(raw) == ["login", "pago", "ok"]


def test_normalize_tags_not_a_list_returns_empty():
    assert _normalize_tags("login,pago") == []
    assert _normalize_tags(None) == []


def test_normalize_tags_respects_max_count(monkeypatch):
    monkeypatch.setattr(config, "MAX_TAGS", 2)
    assert _normalize_tags(["a", "b", "c", "d"]) == ["a", "b"]


def test_normalize_tags_truncates_to_max_len(monkeypatch):
    monkeypatch.setattr(config, "MAX_TAG_LEN", 5)
    assert _normalize_tags(["abcdefghij"]) == ["abcde"]


# --------------------------------------------------------------------------- #
# _validate — enums vinculantes (case-sensitive) y forma del resultado
# --------------------------------------------------------------------------- #
def test_validate_ok_normalizes_tags_and_drops_extra_keys():
    out = _validate({"category": "bug", "priority": "P1", "tags": ["X"], "extra": "ignórame"})
    assert out == {"category": "bug", "priority": "P1", "tags": ["x"]}
    assert "extra" not in out


@pytest.mark.parametrize("data", [
    {"category": "BUG", "priority": "P1", "tags": []},      # mayúsculas no valen
    {"category": "nope", "priority": "P1", "tags": []},     # categoría fuera de enum
    {"category": "bug", "priority": "P9", "tags": []},      # prioridad fuera de enum
    {"priority": "P1", "tags": []},                          # falta category
    "no soy un dict",
    None,
    [1, 2],
])
def test_validate_rejects_invalid_payloads(data):
    assert _validate(data) is None


# --------------------------------------------------------------------------- #
# _safe_fallback — copia independiente (no muta la constante global)
# --------------------------------------------------------------------------- #
def test_safe_fallback_is_an_independent_copy():
    a = _safe_fallback()
    b = _safe_fallback()
    assert a == FALLBACK_CLASSIFICATION
    assert a is not FALLBACK_CLASSIFICATION
    assert a["tags"] is not FALLBACK_CLASSIFICATION["tags"]
    a["tags"].append("boom")
    a["category"] = "bug"
    assert FALLBACK_CLASSIFICATION["tags"] == []          # la constante no se contamina
    assert b["tags"] == []                                # ni otra copia previa


# --------------------------------------------------------------------------- #
# classify_ticket — orquestación: dispatch, reintento, validación y fallback.
# Mockeamos el backend (_classify_openai) → sin red.
# --------------------------------------------------------------------------- #
def test_classify_ticket_success_path(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(
        classifier, "_classify_openai",
        lambda t, d: {"category": "urgent", "priority": "P1", "tags": ["Caída", "prod"]},
    )
    assert classify_ticket("x", "y") == {
        "category": "urgent", "priority": "P1", "tags": ["caída", "prod"],
    }


def test_classify_ticket_retries_once_then_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    calls = []

    def boom(t, d):
        calls.append(1)
        raise RuntimeError("red caída")

    monkeypatch.setattr(classifier, "_classify_openai", boom)
    result = classify_ticket("x", "y")
    assert result == FALLBACK_CLASSIFICATION
    assert len(calls) == 2                     # 1 intento + 1 reintento


def test_classify_ticket_recovers_on_second_attempt(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    state = {"n": 0}

    def flaky(t, d):
        state["n"] += 1
        if state["n"] == 1:
            raise TimeoutError("primer intento falla")
        return {"category": "bug", "priority": "P2", "tags": []}

    monkeypatch.setattr(classifier, "_classify_openai", flaky)
    assert classify_ticket("x", "y")["category"] == "bug"
    assert state["n"] == 2


def test_classify_ticket_out_of_enum_response_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(
        classifier, "_classify_openai",
        lambda t, d: {"category": "no-existe", "priority": "P1", "tags": []},
    )
    assert classify_ticket("x", "y") == FALLBACK_CLASSIFICATION


@pytest.mark.parametrize("exc", [RuntimeError, ValueError, KeyError, TimeoutError])
def test_classify_ticket_never_raises(monkeypatch, exc):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")

    def raiser(t, d):
        raise exc("boom")

    monkeypatch.setattr(classifier, "_classify_openai", raiser)
    # No debe propagar ninguna excepción y devolver el fallback.
    assert classify_ticket("x", "y") == FALLBACK_CLASSIFICATION


def test_classify_ticket_returns_independent_copy_on_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(classifier, "_classify_openai", lambda t, d: (_ for _ in ()).throw(RuntimeError()))
    result = classify_ticket("x", "y")
    result["tags"].append("mutado")
    assert FALLBACK_CLASSIFICATION["tags"] == []      # la constante sigue intacta


def test_classify_ticket_unknown_provider_falls_back_without_calling_backend(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "marte")
    spy = {"openai": 0, "anthropic": 0}
    monkeypatch.setattr(classifier, "_classify_openai", lambda t, d: spy.__setitem__("openai", spy["openai"] + 1))
    monkeypatch.setattr(classifier, "_classify_anthropic", lambda t, d: spy.__setitem__("anthropic", spy["anthropic"] + 1))
    assert classify_ticket("x", "y") == FALLBACK_CLASSIFICATION
    assert spy == {"openai": 0, "anthropic": 0}        # no se reintenta lo irrecuperable


# --------------------------------------------------------------------------- #
# _classify_openai — camino OpenAI con cliente FALSO (sin red)
# --------------------------------------------------------------------------- #
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_openai_factory(content):
    class _FakeCompletions:
        def create(self, **kwargs):
            return _FakeResponse(content)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = _FakeChat()

    return _FakeClient


def test_classify_openai_parses_fake_client_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        "openai.OpenAI",
        _fake_openai_factory('{"category": "bug", "priority": "P1", "tags": ["login"]}'),
    )
    assert _classify_openai("t", "d") == {"category": "bug", "priority": "P1", "tags": ["login"]}


def test_classify_openai_handles_fenced_json(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        "openai.OpenAI",
        _fake_openai_factory('```json\n{"category": "question", "priority": "P3", "tags": []}\n```'),
    )
    assert _classify_openai("t", "d")["category"] == "question"


def test_classify_openai_raises_on_unparseable_content(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", _fake_openai_factory("lo siento, no puedo"))
    with pytest.raises(ValueError):
        _classify_openai("t", "d")


def test_classify_openai_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _classify_openai("t", "d")


# --------------------------------------------------------------------------- #
# _classify_anthropic — camino Anthropic (tool-use) con cliente FALSO (sin red)
# --------------------------------------------------------------------------- #
def _fake_anthropic_factory(content_blocks):
    class _FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=content_blocks)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    return _FakeClient


def test_classify_anthropic_returns_tool_use_input(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    block = SimpleNamespace(type="tool_use", input={"category": "bug", "priority": "P1", "tags": ["x"]})
    monkeypatch.setattr("anthropic.Anthropic", _fake_anthropic_factory([block]))
    assert _classify_anthropic("t", "d") == {"category": "bug", "priority": "P1", "tags": ["x"]}


def test_classify_anthropic_raises_without_tool_use_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    block = SimpleNamespace(type="text", text="no usé la tool")
    monkeypatch.setattr("anthropic.Anthropic", _fake_anthropic_factory([block]))
    with pytest.raises(ValueError):
        _classify_anthropic("t", "d")


def test_classify_anthropic_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _classify_anthropic("t", "d")


def test_classify_ticket_dispatches_to_anthropic_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    called = {"n": 0}

    def fake(t, d):
        called["n"] += 1
        return {"category": "question", "priority": "P3", "tags": []}

    monkeypatch.setattr(classifier, "_classify_anthropic", fake)
    assert classify_ticket("x", "y")["category"] == "question"
    assert called["n"] == 1                 # se enrutó al backend anthropic


# --------------------------------------------------------------------------- #
# Config modular — el prompt refleja las categorías/prioridades configuradas
# --------------------------------------------------------------------------- #
def test_system_prompt_reflects_configured_enums(monkeypatch):
    monkeypatch.setattr(config, "CATEGORIES", ["bug", "billing", "security"])
    monkeypatch.setattr(config, "PRIORITIES", ["P0", "P1"])
    prompt = _build_system_prompt()
    assert "billing" in prompt and "security" in prompt
    assert "P0" in prompt
