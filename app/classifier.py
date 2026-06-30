"""Clasificador de tickets (única pieza que habla con el LLM).

Contrato público (BRIEF.md / SPEC.md §8):

    classify_ticket(title, description) -> {
        "category": "bug" | "feature_request" | "question" | "urgent",
        "priority": "P1" | "P2" | "P3",
        "tags": list[str],
    }

Nunca lanza: ante cualquier problema (falta de key, error de red, JSON inválido,
valores fuera de enum…) devuelve una copia de FALLBACK_CLASSIFICATION.

Backend pluggable vía LLM_PROVIDER:
- ``openrouter`` / ``local`` (por defecto): SDK ``openai`` (OpenAI-compatible).
- ``anthropic``: SDK ``anthropic`` con tool-use forzado.
La validación, normalización, reintento y fallback son comunes a todos.
"""

import json
import os
import re

from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES

# Carga .env si existe (no sobrescribe variables ya presentes en el entorno).
# Defensivo: si python-dotenv no está instalado, seguimos sin romper el import.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}

MAX_TAGS = 5
MAX_TAG_LEN = 30
MAX_TOKENS = 512

DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "google/gemini-3.1-flash-lite"
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "Eres un sistema de triage de tickets de soporte. Dado el título y la "
    "descripción de un ticket, clasifícalo y responde ÚNICAMENTE con un objeto "
    "JSON válido, sin texto adicional ni markdown, con esta forma exacta:\n"
    '{"category": "<bug|feature_request|question|urgent>", '
    '"priority": "<P1|P2|P3>", "tags": ["etiqueta", "..."]}\n'
    "Reglas:\n"
    "- category debe ser EXACTAMENTE uno de: bug, feature_request, question, urgent.\n"
    "- priority: P1 (urgente), P2 (importante), P3 (normal).\n"
    "- tags: como máximo 5 etiquetas cortas en minúscula (máx. 30 caracteres "
    "cada una). Puede ser una lista vacía.\n"
    "- No añadas ningún otro campo ni texto fuera del JSON."
)

# Esquema para el tool-use forzado de Anthropic.
CLASSIFY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": sorted(ALLOWED_CATEGORIES)},
        "priority": {"type": "string", "enum": sorted(ALLOWED_PRIORITIES)},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "priority", "tags"],
}


def _safe_fallback() -> dict:
    """Copia independiente del fallback (incluida la lista mutable ``tags``)."""
    return {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}


_BACKENDS = {
    "openrouter": "_classify_openai",
    "local": "_classify_openai",
    "anthropic": "_classify_anthropic",
}


def classify_ticket(title: str, description: str) -> dict:
    """Clasifica un ticket. Nunca lanza; devuelve el fallback ante cualquier fallo."""
    provider = os.environ.get("LLM_PROVIDER", "openrouter").strip().lower()
    backend = globals().get(_BACKENDS.get(provider, ""))
    if backend is None:  # LLM_PROVIDER desconocido: no reintentamos algo irrecuperable.
        return _safe_fallback()

    try:
        data = _call_with_retry(backend, title, description)
    except Exception:
        return _safe_fallback()

    validated = _validate(data)
    return validated if validated is not None else _safe_fallback()


def _call_with_retry(backend, title: str, description: str, attempts: int = 2) -> dict:
    """Llama al backend; reintenta una vez si falla. Propaga si todos los intentos fallan."""
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return backend(title, description)
        except Exception as exc:
            last_error = exc
    raise last_error if last_error is not None else RuntimeError("clasificación fallida")


def _classify_openai(title: str, description: str) -> dict:
    """Camino OpenAI-compatible (OpenRouter / servidor local)."""
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("falta OPENROUTER_API_KEY / OPENAI_API_KEY")

    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
    model = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(title, description)},
        ],
        temperature=0,
        max_tokens=MAX_TOKENS,
    )
    parsed = _parse_json(response.choices[0].message.content)
    if parsed is None:
        raise ValueError("la respuesta del modelo no es JSON válido")
    return parsed


def _classify_anthropic(title: str, description: str) -> dict:
    """Camino Anthropic (Claude) con tool-use forzado."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("falta ANTHROPIC_API_KEY")

    model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        tools=[{
            "name": "classify_ticket",
            "description": "Devuelve la clasificación del ticket de soporte.",
            "input_schema": CLASSIFY_TOOL_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "classify_ticket"},
        messages=[{
            "role": "user",
            "content": SYSTEM_PROMPT + "\n\n" + _user_prompt(title, description),
        }],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    raise ValueError("la respuesta no contiene un bloque tool_use")


def _user_prompt(title: str, description: str) -> str:
    return f"Título: {title}\n\nDescripción: {description}"


def _parse_json(content: str | None) -> dict | None:
    """Parsea JSON de forma robusta: tolera fences ```json y texto alrededor."""
    if not content:
        return None
    text = content.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Último intento: el primer objeto {...} que aparezca.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _validate(data: object) -> dict | None:
    """Valida contra los enums permitidos. Devuelve None si algo no encaja."""
    if not isinstance(data, dict):
        return None
    category = data.get("category")
    priority = data.get("priority")
    if category not in ALLOWED_CATEGORIES or priority not in ALLOWED_PRIORITIES:
        return None
    return {
        "category": category,
        "priority": priority,
        "tags": _normalize_tags(data.get("tags", [])),
    }


def _normalize_tags(raw: object) -> list[str]:
    """Lista de strings: minúscula, recortadas a 30 chars, máximo 5, sin vacíos."""
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()[:MAX_TAG_LEN]
        if tag:
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags
