"""Carga los tickets de ``seed_tickets.json`` en la base de datos.

Pensado para poblar el tablero en la demo (SPEC §10). No es requisito de los
tests. Reutiliza el clasificador real y la capa de persistencia.

Uso:
    python -m app.seed                  # clasifica con el LLM (consume cuota)
    python -m app.seed --fallback       # sin LLM: fallback (no consume cuota)
    python -m app.seed --limit 20       # solo los primeros 20
    python -m app.seed --reset          # vacía la tabla antes de cargar

Lee DATABASE_URL del entorno/.env igual que la app (por defecto triagebot.db),
así que los tickets aparecen en la misma web.
"""

import argparse
import json
import os
from pathlib import Path

from app import classifier, db

SEED_FILE = Path(__file__).resolve().parent.parent / "seed_tickets.json"


def _classify(title: str, description: str, use_fallback: bool) -> dict:
    if use_fallback:
        fb = classifier.FALLBACK_CLASSIFICATION
        return {**fb, "tags": list(fb["tags"])}
    # classify_ticket nunca lanza: ante cualquier fallo devuelve el fallback.
    return classifier.classify_ticket(title, description)


def load_seed(limit: int | None = None, use_fallback: bool = False, reset: bool = False) -> int:
    if not SEED_FILE.exists():
        raise FileNotFoundError(f"No se encuentra {SEED_FILE}")

    tickets = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    if limit is not None:
        tickets = tickets[:limit]

    if reset:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM tickets")
        print("Tabla 'tickets' vaciada (--reset).")

    if not use_fallback:
        provider = os.environ.get("LLM_PROVIDER", "openrouter")
        print(f"Clasificando {len(tickets)} tickets con el LLM (LLM_PROVIDER={provider}). "
              "Esto consume cuota y puede tardar. Ctrl+C para cancelar.")

    created = 0
    total = len(tickets)
    for i, item in enumerate(tickets, start=1):
        title = (item.get("title") or "").strip()
        description = (item.get("description") or "").strip()
        if not title or not description:
            print(f"[{i}/{total}] omitido (título/descripción vacíos)")
            continue

        c = _classify(title, description, use_fallback)
        db.create_ticket({
            "title": title,
            "description": description,
            "category": c["category"],
            "priority": c["priority"],
            "tags": c["tags"],
            "status": "open",
            "created_at": item.get("created_at"),
        })
        created += 1
        print(f"[{i}/{total}] {c['category']}/{c['priority']} {c['tags']} - {title[:60]}")

    print(f"\nHecho: {created} tickets cargados en la base de datos.")
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga seed_tickets.json en la BD.")
    parser.add_argument("--fallback", action="store_true",
                        help="no llama al LLM; usa la clasificación de fallback (no gasta cuota)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cargar solo los primeros N tickets")
    parser.add_argument("--reset", action="store_true",
                        help="vaciar la tabla antes de cargar")
    args = parser.parse_args()
    load_seed(limit=args.limit, use_fallback=args.fallback, reset=args.reset)


if __name__ == "__main__":
    main()
