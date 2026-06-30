from pydantic import BaseModel, field_validator

from app import config

ALLOWED_CATEGORIES: set[str] = set(config.CATEGORIES)
ALLOWED_PRIORITIES: set[str] = set(config.PRIORITIES)
ALLOWED_STATUSES: set[str] = set(config.STATUSES)


class TicketCreate(BaseModel):
    title: str
    description: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("title must be 1-200 characters")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 5000:
            raise ValueError("description must be 1-5000 characters")
        return v


class TicketPatch(BaseModel):
    status: str | None = None
    priority: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {ALLOWED_STATUSES}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_PRIORITIES:
            raise ValueError(f"priority must be one of {ALLOWED_PRIORITIES}")
        return v
