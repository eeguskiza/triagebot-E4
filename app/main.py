from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app import classifier
import app.db as db
from app.classifier import FALLBACK_CLASSIFICATION
from app.models import TicketCreate, TicketPatch

app = FastAPI(title="TriageBot")


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=201)
def create_ticket(body: TicketCreate):
    try:
        classification = classifier.classify_ticket(body.title, body.description)
    except Exception:
        classification = FALLBACK_CLASSIFICATION

    ticket = db.create_ticket({
        "title": body.title,
        "description": body.description,
        "category": classification["category"],
        "priority": classification["priority"],
        "tags": classification["tags"],
        "status": "open",
    })
    return JSONResponse(content=ticket, status_code=201)


@app.get("/tickets")
def list_tickets(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
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


@app.get("/")
def index():
    return {"message": "TriageBot running"}
