from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import classifier, db
from app.classifier import FALLBACK_CLASSIFICATION
from app.models import TicketCreate, TicketPatch

app = FastAPI(title="TriageBot")

# Las plantillas viven en <repo>/templates (no en app/), así que resolvemos la
# ruta desde este archivo para que funcione sea cual sea el directorio de trabajo.
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _safe_fallback() -> dict:
    """Copia independiente del fallback (incluida la lista mutable tags)."""
    return {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}


def _classify_and_create(title: str, description: str) -> dict:
    """Clasifica (con fallback seguro) y persiste un ticket. Lógica compartida
    por la API JSON (`POST /tickets`) y la UI HTMX (`POST /ui/tickets`)."""
    try:
        classification = classifier.classify_ticket(title, description)
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
):
    return db.list_tickets(category, priority, status)


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
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    tickets = db.list_tickets(None, None, None)
    return templates.TemplateResponse(
        "index.html", {"request": request, "tickets": tickets}
    )


@app.get("/ui/tickets", response_class=HTMLResponse)
def ui_list_tickets(
    request: Request,
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
):
    # Los <select> envían "" para "todas"; lo tratamos como sin filtro.
    tickets = db.list_tickets(category or None, priority or None, status or None)
    return templates.TemplateResponse(
        "_tickets_table.html", {"request": request, "tickets": tickets}
    )


@app.post("/ui/tickets", response_class=HTMLResponse)
def ui_create_ticket(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    category: str = Form(""),
    priority: str = Form(""),
    status: str = Form(""),
):
    # Reutilizamos la validación de TicketCreate (strip + longitudes). Si la
    # entrada es inválida no creamos nada y devolvemos la tabla tal cual.
    try:
        valid = TicketCreate(title=title, description=description)
        _classify_and_create(valid.title, valid.description)
    except ValidationError:
        pass

    # Respetamos los filtros activos (el form los envía vía hx-include) para que
    # la tabla devuelta sea coherente con lo que el usuario está viendo.
    tickets = db.list_tickets(category or None, priority or None, status or None)
    return templates.TemplateResponse(
        "_tickets_table.html", {"request": request, "tickets": tickets}
    )
