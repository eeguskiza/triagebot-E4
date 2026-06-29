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
    # Copia independiente del fallback (SPEC §8): nunca devolvemos la constante
    # compartida; copiamos también la lista mutable tags para que mutar el
    # resultado no altere la constante global.
    return {**FALLBACK_CLASSIFICATION, "tags": list(FALLBACK_CLASSIFICATION["tags"])}
