from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import classifier, db
from app.classifier import FALLBACK_CLASSIFICATION
from app.models import ALLOWED_CATEGORIES, ALLOWED_PRIORITIES, TicketCreate, TicketPatch

app = FastAPI(title="TriageBot")

# Las plantillas viven en <repo>/templates (no en app/), así que resolvemos la
# ruta desde este archivo para que funcione sea cual sea el directorio de trabajo.
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _safe_fallback() -> dict:
    """Copia independiente del fallback (incluida la lista mutable tags)."""
    return {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}


def _parse_assignees(raw: str) -> list[str]:
    """Convierte 'ana, luis' en ['ana', 'luis'] (responsables; máx. 10, 60 chars)."""
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()[:60]
        if name:
            names.append(name)
        if len(names) >= 10:
            break
    return names


def _classify_and_create(title: str, description: str) -> dict:
    """Clasifica (con fallback seguro) y persiste un ticket. Lógica compartida
    por la API JSON (`POST /tickets`) y la UI HTMX (`POST /ui/tickets`)."""
    try:
        classification = classifier.classify_ticket(title, description)
        if (classification.get("category") not in ALLOWED_CATEGORIES or
                classification.get("priority") not in ALLOWED_PRIORITIES):
            classification = _safe_fallback()
    except Exception:
        classification = _safe_fallback()

    return db.create_ticket({
        "title": title,
        "description": description,
        "category": classification["category"],
        "priority": classification["priority"],
        "tags": classification["tags"],
        "status": "open",
    })


# --------------------------------------------------------------------------- #
# API JSON (la que ejercitan los tests; su contrato no cambia)
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=201)
def create_ticket(body: TicketCreate):
    ticket = _classify_and_create(body.title, body.description)
    return JSONResponse(content=ticket, status_code=201)


@app.get("/tickets")
def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    overdue: bool = False,
):
    return db.list_tickets(category, priority, status, assignee=assignee, overdue=overdue)


@app.get("/tickets/stats")
def ticket_stats():
    return db.get_ticket_stats()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int):
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}")
def patch_ticket(ticket_id: int, body: TicketPatch):
    ticket = db.update_ticket(ticket_id, body.model_dump(exclude_none=True))
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# --------------------------------------------------------------------------- #
# UI HTMX (HTML; rutas separadas de la API JSON)
# --------------------------------------------------------------------------- #
PAGE_SIZE = 20


def _render_board(
    request: Request,
    category: str | None,
    priority: str | None,
    status: str | None,
    q: str | None,
    page: int,
    *,
    assignee: str | None = None,
    overdue: bool = False,
    full_page: bool,
):
    """Renderiza el tablero (página completa o solo el fragmento de tabla) con
    filtros + búsqueda + responsable + vencidos + paginación. Compartida por las rutas UI."""
    total = db.count_tickets(category, priority, status, q, assignee, overdue)
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(max(page, 1), pages)
    tickets = db.list_tickets(
        category, priority, status, q,
        limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, assignee=assignee, overdue=overdue,
    )
    context = {
        "tickets": tickets,
        "filters": {
            "category": category or "",
            "priority": priority or "",
            "status": status or "",
            "q": q or "",
            "assignee": assignee or "",
            "overdue": overdue,
        },
        "now_iso": datetime.now(UTC).isoformat(),
        "page": page,
        "pages": pages,
        "total": total,
        "page_size": PAGE_SIZE,
    }
    template = "index.html" if full_page else "_tickets_table.html"
    return templates.TemplateResponse(request, template, context)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    q: str | None = None,
    assignee: str | None = None,
    page: int = 1,
    overdue: bool = False,
):
    # UX para Marta: en la primera carga (sin parámetro `status` y sin filtrar
    # vencidos) mostramos los abiertos. Elegir "Estado (todos)" envía status="".
    effective_status = "open" if (status is None and not overdue) else (status or None)
    return _render_board(
        request, category or None, priority or None, effective_status, q or None,
        page, assignee=assignee or None, overdue=overdue, full_page=True,
    )


@app.get("/ui/tickets", response_class=HTMLResponse)
def ui_list_tickets(
    request: Request,
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    q: str | None = None,
    assignee: str | None = None,
    page: int = 1,
    overdue: bool = False,
):
    # Si la petición no viene de HTMX (recarga del navegador sobre la URL
    # pusheada), devolvemos la página completa para no perder el formulario.
    is_htmx = request.headers.get("HX-Request") == "true"
    return _render_board(
        request, category or None, priority or None, status or None, q or None,
        page, assignee=assignee or None, overdue=overdue, full_page=not is_htmx,
    )


@app.post("/ui/tickets", response_class=HTMLResponse)
def ui_create_ticket(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form(""),
    priority: str = Form(""),
    status: str = Form(""),
    q: str = Form(""),
    assignee: str = Form(""),
    overdue: str = Form(""),
):
    # Reutilizamos la validación de TicketCreate (strip + longitudes). Si la
    # entrada es inválida no creamos nada y devolvemos la tabla tal cual.
    try:
        valid = TicketCreate(title=title, description=description)
        _classify_and_create(valid.title, valid.description)
    except ValidationError:
        pass

    # Respetamos los filtros/búsqueda activos (el form los envía vía hx-include).
    return _render_board(
        request, category or None, priority or None, status or None, q or None,
        page=1, assignee=assignee or None, overdue=overdue == "true", full_page=False,
    )


@app.post("/ui/tickets/{ticket_id}", response_class=HTMLResponse)
def ui_update_ticket(
    request: Request,
    ticket_id: int,
    new_status: str = Form(""),
    new_priority: str = Form(""),
    new_assignees: str | None = Form(None),
    category: str = Form(""),
    priority: str = Form(""),
    status: str = Form(""),
    q: str = Form(""),
    assignee: str = Form(""),
    page: int = Form(1),
    overdue: str = Form(""),
):
    # Edición inline desde el tablero: status/priority (ciclo de vida, reabrir) y
    # responsables. Solo cambia el campo enviado; valida enums con TicketPatch.
    try:
        patch = TicketPatch(status=new_status or None, priority=new_priority or None)
        update = patch.model_dump(exclude_none=True)
        if new_assignees is not None:  # "" => limpiar responsables
            update["assignees"] = _parse_assignees(new_assignees)
        if update:
            db.update_ticket(ticket_id, update)
    except ValidationError:
        pass

    # Mantenemos la página actual (Marta no pierde su sitio al editar); _render_board
    # la reajusta si al cambiar el ticket la página deja de existir.
    return _render_board(
        request, category or None, priority or None, status or None, q or None,
        page=page, assignee=assignee or None, overdue=overdue == "true", full_page=False,
    )
