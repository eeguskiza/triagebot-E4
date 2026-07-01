#!/usr/bin/env python3
"""
TriageBot Daily Digest — skill para OpenClaw.

Lee TRIAGEBOT_BASE_URL del entorno, llama a GET /tickets y devuelve
un resumen en lenguaje natural listo para enviarse por Telegram.

Uso standalone (para probar):
    TRIAGEBOT_BASE_URL=https://cough-vagueness-throwing.ngrok-free.dev \
        python lab9/triage_daily_digest.py

Uso como módulo desde el agente:
    from lab9.triage_daily_digest import get_digest
    print(get_digest())

Solo usa módulos de la stdlib (urllib, json, os, datetime).
Sin dependencias externas — funciona en cualquier Python 3.9+.
"""

import json
import os
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

TRIAGEBOT_BASE_URL = os.environ.get("TRIAGEBOT_BASE_URL", "http://localhost:8000")

# Cabecera requerida para saltarse la pantalla de aviso de ngrok (free tier).
_NGROK_HEADER = {"ngrok-skip-browser-warning": "true"}


# ---------------------------------------------------------------------------
# Capa de red
# ---------------------------------------------------------------------------

def fetch_tickets(base_url: str) -> list[dict]:
    """
    Llama a GET /tickets y devuelve la lista de tickets.

    Lanza HTTPError, URLError o ValueError si algo falla.
    """
    url = base_url.rstrip("/") + "/tickets"
    req = Request(url, headers={"Accept": "application/json", **_NGROK_HEADER})
    with urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"GET /tickets devolvió {type(data).__name__}, se esperaba lista")
    return data


# ---------------------------------------------------------------------------
# Lógica del digest
# ---------------------------------------------------------------------------

def _safe(ticket: dict, key: str, default: str = "") -> str:
    """Extrae un campo del ticket de forma segura."""
    val = ticket.get(key)
    return str(val).strip() if val is not None else default


def build_digest(tickets: list[dict]) -> str:
    """
    Genera el daily digest en texto plano / Markdown ligero.

    Maneja tickets con campos faltantes (compatibilidad hacia atrás).
    """
    now_iso = datetime.now(UTC).isoformat()
    now_fmt = datetime.now(UTC).strftime("%d/%m/%Y %H:%M") + " UTC"

    # Separar activos (open / in_progress) de cerrados
    active = [t for t in tickets if _safe(t, "status", "open") not in ("closed", "resolved")]
    closed_count = len(tickets) - len(active)

    if not active:
        return (
            "📋 *Daily Digest — TriageBot*\n\n"
            "✅ No hay tickets pendientes en este momento.\n"
            + (f"{closed_count} ticket(s) cerrados." if closed_count else "El tablero está vacío.")
        )

    # Conteos por prioridad
    by_priority: dict[str, list[dict]] = {"P1": [], "P2": [], "P3": []}
    by_category: dict[str, int] = {}
    urgent: list[dict] = []
    blocked: list[dict] = []

    for t in active:
        p = _safe(t, "priority", "P3")
        if p in by_priority:
            by_priority[p].append(t)

        cat = _safe(t, "category", "question")
        by_category[cat] = by_category.get(cat, 0) + 1

        # Urgente = P1 o categoría urgent
        if p == "P1" or cat == "urgent":
            urgent.append(t)

        # Bloqueado = en_progreso con due_date vencida
        due = _safe(t, "due_date")
        status = _safe(t, "status", "open")
        if status == "in_progress" and due and due < now_iso:
            blocked.append(t)

    top_categories = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:4]

    lines = [
        "📋 *Daily Digest — TriageBot*",
        f"📅 {now_fmt}",
        "",
        f"📊 *{len(active)} ticket(s) activo(s)*"
        + (f"  ·  {closed_count} cerrados" if closed_count else ""),
        "",
        "**Por prioridad:**",
        f"  🔴 P1 (crítico): {len(by_priority['P1'])}",
        f"  🟠 P2 (alto):    {len(by_priority['P2'])}",
        f"  🟡 P3 (normal):  {len(by_priority['P3'])}",
    ]

    if top_categories:
        lines += ["", "**Categorías:**"]
        for cat, count in top_categories:
            icons = {"bug": "🐛", "feature_request": "✨", "question": "❓", "urgent": "🚨"}
            icon = icons.get(cat, "•")
            lines.append(f"  {icon} {cat}: {count}")

    if urgent:
        lines += ["", f"🚨 *{len(urgent)} urgente(s) / P1 — atención inmediata:*"]
        for t in urgent[:5]:
            tid = _safe(t, "id", "?")
            title = _safe(t, "title", "sin título")[:70]
            lines.append(f"  [{tid}] {title}")

    if blocked:
        lines += ["", f"🔒 *{len(blocked)} bloqueado(s) — en progreso y vencidos:*"]
        for t in blocked[:3]:
            tid = _safe(t, "id", "?")
            title = _safe(t, "title", "sin título")[:70]
            due = _safe(t, "due_date", "—")[:10]
            lines.append(f"  [{tid}] {title}  (venció {due})")

    # Recomendación
    lines += ["", "💡 *Siguiente acción recomendada:*"]
    if by_priority["P1"]:
        n = len(by_priority["P1"])
        lines.append(f"  Resolver los {n} ticket(s) P1 críticos antes de cualquier otra tarea.")
    elif blocked:
        lines.append("  Desbloquear los tickets en_progreso que han superado su plazo.")
    elif by_priority["P2"]:
        n = len(by_priority["P2"])
        lines.append(f"  Revisar y asignar los {n} ticket(s) P2 de alta prioridad.")
    else:
        lines.append("  No hay críticos. Buen momento para cerrar los P3 pendientes.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Punto de entrada público (lo que llama el agente)
# ---------------------------------------------------------------------------

def get_digest(base_url: str | None = None) -> str:
    """
    Obtiene los tickets de TriageBot y devuelve el daily digest como string.

    Si el endpoint no está disponible devuelve un mensaje de error claro
    en lugar de lanzar una excepción — el agente puede reenviarlo tal cual.
    """
    url = (base_url or TRIAGEBOT_BASE_URL).rstrip("/")
    try:
        tickets = fetch_tickets(url)
    except HTTPError as exc:
        return (
            f"❌ *Daily Digest — error de conexión*\n\n"
            f"TriageBot respondió con HTTP {exc.code} ({exc.reason}).\n"
            f"URL: {url}/tickets"
        )
    except URLError as exc:
        return (
            f"❌ *Daily Digest — error de red*\n\n"
            f"No se pudo conectar con TriageBot en {url}.\n"
            f"Detalle: {exc.reason}"
        )
    except json.JSONDecodeError:
        return (
            f"❌ *Daily Digest — respuesta inválida*\n\n"
            f"TriageBot devolvió algo que no es JSON válido.\n"
            f"¿Está levantado? URL: {url}/tickets"
        )
    except ValueError as exc:
        return f"❌ *Daily Digest — formato inesperado*\n\n{exc}"
    except Exception as exc:  # noqa: BLE001
        return f"❌ *Daily Digest — error inesperado*\n\n{exc}"

    return build_digest(tickets)


# ---------------------------------------------------------------------------
# Uso como script
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(get_digest())
