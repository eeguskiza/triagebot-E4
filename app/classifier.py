FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}


def classify_ticket(title: str, description: str) -> dict:
    """Classify a support ticket.

    TODO durante el bootcamp:
    - Llamar a Claude API usando ANTHROPIC_API_KEY.
    - Pedir JSON estricto.
    - Parsear y validar category, priority y tags.
    - Nunca propagar excepciones del SDK.
    - Devolver FALLBACK_CLASSIFICATION ante cualquier problema.
    """
    # Copia independiente del fallback: la constante contiene una lista mutable
    # (tags); copiamos también la lista para que mutar el resultado nunca altere
    # la constante global (ni el fallback de futuras llamadas).
    return {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}
