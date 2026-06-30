import os


def _parse_csv(env_var: str, default: str) -> list[str]:
    raw = os.environ.get(env_var, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


CATEGORIES: list[str] = _parse_csv("TICKET_CATEGORIES", "bug,feature_request,question,urgent")
PRIORITIES: list[str] = _parse_csv("TICKET_PRIORITIES", "P1,P2,P3")
# Ciclo de vida: open → in_progress → resolved (→ closed); reabrir = volver a open.
STATUSES: list[str] = _parse_csv("TICKET_STATUSES", "open,in_progress,resolved,closed")

MAX_TAGS: int = int(os.environ.get("MAX_TAGS", "5"))
MAX_TAG_LEN: int = int(os.environ.get("MAX_TAG_LEN", "30"))

FALLBACK_CATEGORY: str = os.environ.get("FALLBACK_CATEGORY", "question")
FALLBACK_PRIORITY: str = os.environ.get("FALLBACK_PRIORITY", "P3")
