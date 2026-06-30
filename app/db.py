import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

# Días hasta vencimiento según prioridad (Plazos).
_DUE_DAYS = {"P1": 0, "P2": 1, "P3": 2}


def _get_db_path() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return "triagebot.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    # Concurrencia: WAL permite lectores en paralelo con un escritor; busy_timeout
    # hace que una escritura espere al lock (hasta 5 s) en vez de fallar con
    # "database is locked" bajo POSTs concurrentes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
            status_changed_at TEXT NOT NULL DEFAULT '',
            due_date TEXT
        )
    """)
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["assignees"] = json.loads(d["assignees"])  # responsables (lista, como tags)
    return d


def _calc_due_date(priority: str, created_at: str) -> str:
    """Calcula due_date sumando días al created_at según prioridad (Plazos)."""
    base = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    delta = timedelta(days=_DUE_DAYS.get(priority, 2))
    return (base + delta).isoformat()


def create_ticket(data: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    # created_at/updated_at se generan en servidor; el seeding puede pasar la
    # fecha original del ticket para preservarla (los endpoints no la pasan).
    created_at = data.get("created_at") or now
    updated_at = data.get("updated_at") or created_at
    # status_changed_at = "desde cuándo está en este estado" (ciclo de vida).
    status_changed_at = data.get("status_changed_at") or created_at
    # due_date calculada a partir de la prioridad (Plazos).
    due_date = data.get("due_date") or _calc_due_date(data["priority"], created_at)
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO tickets (
                title, description, category, priority, tags, status,
                assignees, created_at, updated_at, status_changed_at, due_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                due_date,
            ),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


def _where(
    category: str | None,
    priority: str | None,
    status: str | None,
    q: str | None,
    assignee: str | None = None,
    overdue: bool = False,
) -> tuple[str, list]:
    """Construye el WHERE dinámico (filtros AND + búsqueda + responsable + vencidos)."""
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
    if overdue:
        now = datetime.now(UTC).isoformat()
        # Vencido = due_date pasó Y el ticket NO está en estado terminal.
        # Terminales = closed y resolved (reconciliado con el ciclo de vida).
        clause += (
            " AND due_date IS NOT NULL AND due_date < ?"
            " AND status NOT IN ('closed', 'resolved')"
        )
        params.append(now)
    return clause, params


def list_tickets(
    category: str | None,
    priority: str | None,
    status: str | None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    assignee: str | None = None,
    overdue: bool = False,
) -> list[dict]:
    """Lista tickets con filtros AND, búsqueda, responsable, vencidos y paginación.

    Sin `q`/`assignee`/`overdue`/`limit` devuelve todos los que cumplen los filtros
    (comportamiento histórico que usan la API JSON y los tests).
    """
    clause, params = _where(category, priority, status, q, assignee, overdue)
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
    overdue: bool = False,
) -> int:
    """Cuenta los tickets que cumplen los filtros/búsqueda (para paginación)."""
    clause, params = _where(category, priority, status, q, assignee, overdue)
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
