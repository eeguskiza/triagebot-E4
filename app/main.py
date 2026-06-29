from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app import classifier, db
from app.classifier import FALLBACK_CLASSIFICATION
from app.models import TicketCreate, TicketPatch, TicketResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creación idempotente del esquema al arrancar (producción). En tests no se
    # dispara —el TestClient no entra como context manager—, pero no pasa nada:
    # get_connection() también crea el esquema en cada conexión.
    db.init_db()
    yield


app = FastAPI(title="TriageBot", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=201, response_model=TicketResponse)
def create_ticket(body: TicketCreate):
    try:
        classification = classifier.classify_ticket(body.title, body.description)
    except Exception:
        # Copia independiente del fallback (incluida la lista mutable tags), por
        # si classify_ticket lanza sin pasar por su propia red de seguridad.
        classification = {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}

    return db.create_ticket({
        "title": body.title,
        "description": body.description,
        "category": classification["category"],
        "priority": classification["priority"],
        "tags": classification["tags"],
        "status": "open",
    })


@app.get("/tickets", response_model=list[TicketResponse])
def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
):
    return db.list_tickets(category, priority, status)


@app.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket(ticket_id: int):
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=TicketResponse)
def patch_ticket(ticket_id: int, body: TicketPatch):
    ticket = db.update_ticket(ticket_id, body.model_dump(exclude_none=True))
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.get("/")
def index():
    # TODO (Lab 2 / frontend): servir templates/index.html (formulario + tablero
    # + filtros con HTMX). De momento queda un placeholder JSON.
    return {"message": "TriageBot running"}
