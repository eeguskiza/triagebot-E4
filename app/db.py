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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    return conn


def init_db() -> None:
    get_connection().close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    return d


def create_ticket(data: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    tags_json = json.dumps(data.get("tags", []))
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO tickets (
                title, description, category, priority,
                tags, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["title"],
                data["description"],
                data["category"],
                data["priority"],
                tags_json,
                data.get("status", "open"),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_dict(row)


def list_tickets(category: str | None, priority: str | None, status: str | None) -> list[dict]:
    query = "SELECT * FROM tickets WHERE 1=1"
    params: list = []
    if category:
        query += " AND category = ?"
        params.append(category)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_ticket(ticket_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_ticket(ticket_id: int, data: dict) -> dict | None:
    row = get_ticket(ticket_id)
    if row is None:
        return None
    now = datetime.now(UTC).isoformat()
    fields = {k: v for k, v in data.items() if v is not None}
    fields["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [ticket_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row)
