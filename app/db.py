import json
import os
import sqlite3
from datetime import UTC, datetime


def _get_db_path() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return "triagebot.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open',
            assignees TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status_changed_at TEXT NOT NULL DEFAULT ''
        )
    """)
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["assignees"] = json.loads(d["assignees"])  # responsables (lista, como tags)
    return d


def create_ticket(data: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    # created_at/updated_at se generan en servidor; el seeding puede pasar la
    # fecha original del ticket para preservarla (los endpoints no la pasan).
    created_at = data.get("created_at") or now
    updated_at = data.get("updated_at") or created_at
    # status_changed_at = "desde cuándo está en este estado" (ciclo de vida).
    status_changed_at = data.get("status_changed_at") or created_at
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO tickets (
                title, description, category, priority,
                tags, status, assignees, created_at, updated_at, status_changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["title"],
                data["description"],
                data["category"],
                data["priority"],
                json.dumps(data.get("tags", [])),
                data.get("status", "open"),
                json.dumps(data.get("assignees", [])),
                created_at,
                updated_at,
                status_changed_at,
            ),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


def _where(category: str | None, priority: str | None, status: str | None,
           q: str | None, assignee: str | None = None) -> tuple[str, list]:
    """Construye el WHERE dinámico (filtros AND + búsqueda) y sus parámetros."""
    clause = " WHERE 1=1"
    params: list = []
    if category:
        clause += " AND category = ?"
        params.append(category)
    if priority:
        clause += " AND priority = ?"
        params.append(priority)
    if status:
        clause += " AND status = ?"
        params.append(status)
    if q:
        clause += " AND (title LIKE ? OR description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like])
    if assignee:
        # assignees se guarda como JSON '["ana", "luis"]'; casamos el nombre exacto.
        clause += " AND assignees LIKE ?"
        params.append(f'%"{assignee}"%')
    return clause, params


def list_tickets(
    category: str | None,
    priority: str | None,
    status: str | None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    assignee: str | None = None,
) -> list[dict]:
    """Lista tickets con filtros AND, búsqueda, filtro por responsable y paginación.

    Sin `q`/`assignee`/`limit` devuelve todos los que cumplen los filtros
    (comportamiento histórico que usan la API JSON y los tests).
    """
    clause, params = _where(category, priority, status, q, assignee)
    query = "SELECT * FROM tickets" + clause + " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_tickets(
    category: str | None,
    priority: str | None,
    status: str | None,
    q: str | None = None,
    assignee: str | None = None,
) -> int:
    """Cuenta los tickets que cumplen los filtros/búsqueda (para paginación)."""
    clause, params = _where(category, priority, status, q, assignee)
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM tickets" + clause, params).fetchone()[0]


def get_ticket(ticket_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_ticket(ticket_id: int, data: dict) -> dict | None:
    current = get_ticket(ticket_id)
    if current is None:
        return None
    now = datetime.now(UTC).isoformat()
    fields = {k: v for k, v in data.items() if v is not None}
    # Responsables: la lista se guarda serializada a JSON (como tags).
    if "assignees" in fields:
        fields["assignees"] = json.dumps(fields["assignees"])
    # Ciclo de vida: si el estado cambia, registramos "desde cuándo" (reabrir incluido).
    if "status" in fields and fields["status"] != current["status"]:
        fields["status_changed_at"] = now
    fields["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [ticket_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row)
