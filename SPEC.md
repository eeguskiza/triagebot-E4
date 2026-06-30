# SPEC.md — Contrato funcional de TriageBot (Equipo B · Spec-Driven)

> **Fuente de verdad.** El contrato vinculante de este proyecto es
> `tests/test_acceptance.py` (5 tests, no se modifican) + `BRIEF.md` (lo que pide
> el cliente). Este SPEC traduce ambos a un contrato de implementación cerrado:
> si algo aquí choca con los tests, **mandan los tests**. Cualquier "spec"
> externo que contradiga `tests/test_acceptance.py` se ignora.

---

## 1. Objetivo

Aplicación web interna para que el equipo de Soporte registre **tickets** de
incidencias en lenguaje natural y el sistema los **clasifique automáticamente con
un LLM** (categoría, prioridad y tags). El usuario consulta, filtra y gestiona los
tickets desde un tablero web.

Debe quedar **funcionando end-to-end**: API REST + persistencia SQLite +
clasificación con IA + frontend mínimo (HTMX) + 5 tests verdes + CI verde.

---

## 2. Stack técnico

| Capa | Tecnología | Notas |
|------|------------|-------|
| Lenguaje | Python 3.11+ | |
| Framework | FastAPI | |
| Modelos/validación | Pydantic v2 | Ya en `requirements.txt`. **No** SQLModel. |
| Persistencia | SQLite vía `sqlite3` (stdlib) | Archivo local; ruta configurable (sección 4) |
| LLM | **Provider-pluggable** tras el contrato `classify_ticket` | OpenAI-compatible (local / OpenRouter) **y/o** Anthropic |
| Frontend | Jinja2 + HTMX + Tailwind (CDN) | Sin build tools |
| Tests | pytest + `fastapi.testclient.TestClient` | |
| Lint | ruff (line-length 100) | |
| CI | GitHub Actions (`.github/workflows/ci.yml`, ya presente) | |

**Decisión de proveedor: clasificador agnóstico del backend.** El proyecto hará
despliegues **locales y vía API**, así que `classify_ticket` abstrae el
proveedor y se elige por configuración (`LLM_PROVIDER`, sección 4/8):

- `local` — modelo de pesos abiertos (p. ej. `gpt-oss-120b`) servido por un
  endpoint OpenAI-compatible en local (Ollama/vLLM/LM Studio). Sin coste, offline.
- `openrouter` — el mismo interfaz OpenAI-compatible, hosted, vía OpenRouter
  (`gpt-oss-120b` u otros). **Comparte código con `local`** (solo cambia
  `base_url`/key/modelo) → mismo binario en local y en API.
- `anthropic` — Claude vía SDK `anthropic` (`ANTHROPIC_API_KEY`).

Los tests mockean el clasificador, así que el proveedor no afecta a su resultado;
sí afecta a la demo y al despliegue.

**Dependencias.** El default `anthropic` usa el SDK `anthropic` **ya presente**;
no requiere añadir nada. Para activar `local`/`openrouter` hay que **añadir el
SDK `openai` a `requirements.txt`** (aún no incluido) — hágase cuando se vaya a
usar ese backend. No se añade `SQLModel` (se usa `sqlite3` + Pydantic). El CI
instala desde `requirements.txt`, así que el backend que use la demo debe tener
su SDK declarado allí.

---

## 3. Estructura del proyecto y responsabilidades

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/main.py` | App FastAPI, rutas (API JSON + UI HTMX), orquestación crear→clasificar→persistir. Sin HTML grande en strings; sin llamadas directas al SDK del LLM. |
| `app/models.py` | Schemas Pydantic (`TicketCreate`, `TicketUpdate`, `TicketRead`) y constantes de enums (`ALLOWED_CATEGORIES`, `ALLOWED_PRIORITIES`, `ALLOWED_STATUSES`, ya presentes). |
| `app/db.py` | Conexión SQLite, creación idempotente del esquema y operaciones CRUD. (de)serialización de `tags`. |
| `app/classifier.py` | **Único** módulo que habla con el LLM. Expone `classify_ticket(title, description) -> dict` y `FALLBACK_CLASSIFICATION`. Nunca propaga excepciones. |
| `templates/index.html` | Página del tablero (formulario + filtros + tabla). |
| `templates/_tickets_table.html` | Fragmento de la tabla de tickets (lo refresca HTMX). |

---

## 4. Configuración (variables de entorno)

| Variable | Uso | Default |
|----------|-----|---------|
| `DATABASE_URL` | Ruta de la BD en formato `sqlite:///<ruta>`. | `sqlite:///./triagebot.db` |
| `LLM_PROVIDER` | Selecciona el backend del clasificador: `local` \| `openrouter` \| `anthropic`. | `anthropic` |
| **OpenAI-compatible** (`local` / `openrouter`) | | |
| `OPENAI_BASE_URL` | Endpoint OpenAI-compatible. Local: p. ej. `http://localhost:11434/v1`. OpenRouter: `https://openrouter.ai/api/v1`. | — |
| `OPENROUTER_API_KEY` | Key para OpenRouter (en `local`, muchos servidores aceptan cualquier valor o ninguno). **Nunca** hardcodear. | — |
| `LLM_MODEL` | Modelo en el backend OpenAI-compatible. | `openai/gpt-oss-120b` (OpenRouter) / nombre del modelo local |
| **Anthropic** (`anthropic`) | | |
| `ANTHROPIC_API_KEY` | Key del SDK de Anthropic. **Nunca** hardcodear. | — |
| `CLAUDE_MODEL` | Modelo Claude. | `claude-opus-4-8` (alternativas de coste: `claude-haiku-4-5`, `claude-sonnet-4-6`) |

Solo es obligatoria la configuración del backend que se vaya a usar. `.env`
nunca se commitea; `.env.example` debe listar estas variables (sin valores).

### ⚠️ Manejo de `DATABASE_URL` (crítico para los tests)

El fixture de los tests hace, **en este orden**:

```python
monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
return TestClient(app)   # NO se usa como context manager → NO se ejecuta el lifespan/startup
```

Consecuencias **obligatorias** para la implementación:

1. **`DATABASE_URL` se lee en cada petición**, dentro de la función que abre la
   conexión — **no** en import-time ni en un único `@app.on_event("startup")`
   (que no se dispara porque el `TestClient` no entra como context manager). Si
   resuelves la ruta al importar el módulo, todos los tests escriben en la BD
   equivocada.
2. **El esquema se crea de forma idempotente** (`CREATE TABLE IF NOT EXISTS`) al
   abrir la conexión / primer uso, para que cada `tmp_path` nuevo funcione sin
   estado previo.
3. **Parseo del formato**: quitar el prefijo `sqlite:///` una vez:
   `path = url.replace("sqlite:///", "", 1)`. Como `tmp_path` es absoluto, la URL
   queda con 4 barras (`sqlite:////abs/...`) y tras quitar el prefijo queda
   `/abs/...` (ruta absoluta correcta). El default relativo (`./triagebot.db`)
   también funciona con ese parseo.

---

## 5. Modelo de datos

Una sola entidad: **Ticket**.

| Campo | Tipo | Reglas |
|-------|------|--------|
| `id` | int | PK autoincremental (`INTEGER PRIMARY KEY AUTOINCREMENT`) |
| `title` | str | Obligatorio. 1–200 chars **tras `strip()`** |
| `description` | str | Obligatorio. 1–5000 chars **tras `strip()`** |
| `category` | str | `bug` \| `feature_request` \| `question` \| `urgent` |
| `priority` | str | `P1` \| `P2` \| `P3` |
| `tags` | list[str] | Lista (puede estar vacía). Recomendado: máx. 5 tags, máx. 30 chars c/u, en minúscula |
| `status` | str | `open` \| `in_progress` \| `closed`. Default `open` |
| `created_at` | datetime | UTC, generado en servidor. Serializa a ISO 8601 (string) en la respuesta |
| `updated_at` | datetime | UTC; se actualiza en cambios (PATCH) |

`category`, `priority` y `tags` los rellena el clasificador al crear el ticket.
**Los enums son vinculantes y case-sensitive** (`urgent`, no `URGENT`; `P1`, no
`p1`). Devolver un valor fuera de lista rompe los tests.

### Esquema SQLite (`tickets`)

```sql
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    priority    TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',  -- JSON array serializado
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,               -- ISO 8601 UTC
    updated_at  TEXT NOT NULL
);
```

- `tags` se guarda como **JSON string** (`json.dumps`) y se devuelve como lista
  (`json.loads`), **preservando el orden** (el test compara
  `tags == ["login", "customer-impact"]`).
- Usar `row_factory = sqlite3.Row` para mapear filas a dict cómodamente.

### Schemas Pydantic (`app/models.py`)

- **`TicketCreate`**: `title: str`, `description: str`. Validadores que hacen
  `strip()` y comprueban longitud (1–200 / 1–5000). Un título de solo espacios
  (`"   "`) queda vacío tras `strip()` y debe **fallar** la validación → FastAPI
  responde **422** automáticamente.
- **`TicketUpdate`**: `status: str | None`, `priority: str | None` (ambos
  opcionales). Validar contra los enums permitidos; valor inválido → 422.
- **`TicketRead`**: todos los campos del ticket para la respuesta JSON
  (incluye `id`, `tags` como lista, `created_at`/`updated_at`).

> Implementa la longitud con validadores que trabajen sobre el texto ya
> "trimmeado" (no con `min_length`/`max_length` a secas, que no detectan el
> título de solo espacios). Guarda el valor ya `strip()`-eado.

---

## 6. API REST

Tres endpoints JSON (los que ejercitan los tests) + rutas HTML/HTMX (sección 7).

### `POST /tickets` → `201 Created`

Crea un ticket, lo clasifica **síncronamente** y lo persiste. La respuesta ya
trae el ticket clasificado.

Request:
```json
{ "title": "La app no carga", "description": "Pantalla en blanco al iniciar sesión" }
```
Response `201`:
```json
{
  "id": 1,
  "title": "La app no carga",
  "description": "Pantalla en blanco al iniciar sesión",
  "category": "bug",
  "priority": "P1",
  "tags": ["login", "customer-impact"],
  "status": "open",
  "created_at": "2026-06-29T09:30:00Z",
  "updated_at": "2026-06-29T09:30:00Z"
}
```

Reglas:
- `status_code=201` explícito en la ruta.
- **422** si `title`/`description` faltan, están vacíos, son solo espacios o
  exceden longitud (validación Pydantic).
- **Nunca 5xx por fallo del LLM.** Ver sección 8 (fallback a nivel de endpoint).

#### 🔑 Dos detalles que hacen pasar los tests

1. **Llamar al clasificador por atributo de módulo**, porque el test hace
   `monkeypatch.setattr("app.classifier.classify_ticket", ...)`:
   ```python
   from app import classifier
   ...
   result = classifier.classify_ticket(title, description)   # ✅ respeta el monkeypatch
   ```
   **No** uses `from app.classifier import classify_ticket` (enlazaría el nombre
   en import-time y el monkeypatch no tendría efecto).
2. **Envolver la llamada en `try/except`** y aplicar el fallback ante cualquier
   excepción (lo exige el test 4, que sustituye `classify_ticket` por una función
   que lanza `RuntimeError`):
   ```python
   try:
       c = classifier.classify_ticket(title, description)
   except Exception:
       c = dict(classifier.FALLBACK_CLASSIFICATION)
   ```

### `GET /tickets` → `200 OK`

Lista de tickets en JSON, ordenada por `created_at` **descendente** (desempate
por `id` desc).

Query params opcionales y **combinables con AND**: `category`, `priority`,
`status`. Cada uno, si está presente, filtra por igualdad exacta.

```
GET /tickets?category=urgent&priority=P2&status=in_progress
```

Para que sea estable con los tests, los filtros se aplican en SQL (`WHERE`
dinámico) o en memoria, pero el resultado debe ser **exactamente** los tickets
que cumplen todos los filtros presentes.

### `PATCH /tickets/{id}` → `200 OK`

Actualiza **solo** `status` y/o `priority` (el resto es inmutable tras la
creación). Actualiza `updated_at`.

Request: `{ "status": "in_progress", "priority": "P2" }`

- `200` con el ticket actualizado (refleja los nuevos valores).
- `422` si un valor no pertenece a su enum.
- `404` si el ticket no existe.

### Auxiliares

- `GET /health` → `{"status": "ok"}` (ya existe; mantener).
- `GET /tickets/{id}` → ticket o `404`. *No exigido por los tests, pero útil y
  coherente con el `404` del PATCH.*

---

## 7. Frontend mínimo (HTMX)

Objetivo: tablero funcional, sin framework JS. La API JSON anterior **no se
toca** (la usan los tests); el UI usa rutas/fragmentos propios que devuelven
HTML y reutilizan la misma lógica de crear/persistir/filtrar.

`GET /` → `templates/index.html`, con:

1. **Formulario** (`title`, `description`) + botón "Crear ticket". Envía con
   `hx-post` a una ruta de UI que crea el ticket (misma orquestación que
   `POST /tickets`) y devuelve el fragmento `_tickets_table.html` actualizado.
2. **Tablero** que renderiza los tickets: `id`, `title`, `category` (con color
   por valor), `priority` (badge), `tags`, `status`, `created_at`.
3. **Filtros + buscador**: tres `select` (categoría / prioridad / estado) y un
   campo de **búsqueda** (`q`, busca en `title`/`description`) que con `hx-get`
   piden el fragmento filtrado y lo intercambian.
4. **Paginación**: `PAGE_SIZE = 20` por página, con pie "Página X de Y · N
   tickets" y botones Anterior/Siguiente.
5. **Edición inline** (brief §4): cada fila lleva `select` de `status` y
   `priority`; al cambiarlos se persiste con un `hx-post` y se refresca la tabla.

UX para Marta: en la primera carga el tablero muestra `status=open` por defecto
(elegir "todos" envía `status=""`). El estado (filtros/búsqueda/página) se
refleja en la URL (`hx-push-url`) para que **recargar no lo pierda**.

Rutas de UI (HTML, separadas del API JSON):
- `GET /` → página completa, ya filtrada/paginada según query params
  (`category`, `priority`, `status`, `q`, `page`).
- `GET /ui/tickets` → fragmento `_tickets_table.html` (filtros + `q` + `page`);
  devuelve la página completa si la petición no es de HTMX (recarga directa).
- `POST /ui/tickets` → crea ticket y devuelve el fragmento actualizado.
- `POST /ui/tickets/{id}` → edición inline de `status`/`priority` (campos
  `new_status` / `new_priority`); valida con `TicketPatch` y devuelve el fragmento.

La capa de datos (`db.list_tickets`) acepta `q`, `limit` y `offset` opcionales y
`db.count_tickets` da el total; **sin `q`/`limit` el comportamiento es el
histórico**, así que la API JSON `GET /tickets` y los tests no cambian.

Reglas: Jinja2 para templates; nada de HTML grande dentro de `main.py`; sin
React/Vue ni build tools. Diseño correcto y legible, no espectacular.

---

## 8. Clasificador IA (`app/classifier.py`)

Encapsula **toda** la lógica de IA. Es el único módulo que llama al LLM.

### Contrato público

```python
FALLBACK_CLASSIFICATION = {"category": "question", "priority": "P3", "tags": []}

def classify_ticket(title: str, description: str) -> dict:
    """
    Devuelve EXACTAMENTE:
    {
      "category": "bug" | "feature_request" | "question" | "urgent",
      "priority": "P1" | "P2" | "P3",
      "tags": list[str]   # recomendado: <=5 elementos, <=30 chars, minúscula
    }
    Nunca lanza: ante cualquier problema devuelve FALLBACK_CLASSIFICATION.
    """
```

### Backends soportados (provider-pluggable)

`classify_ticket` despacha según `LLM_PROVIDER`. Todos devuelven el **mismo dict**
del contrato; la lógica de validación, normalización, reintento y fallback es
**común** a todos los backends (no se duplica por proveedor).

- **`local` / `openrouter` (SDK `openai`)** — mismo código, solo cambian
  `base_url`/key/modelo:
  - `OpenAI(base_url=OPENAI_BASE_URL, api_key=...)`.
  - `chat.completions.create(model=LLM_MODEL, messages=[...], ...)`.
  - JSON estricto: pedirlo en el prompt y, si el backend lo soporta,
    `response_format={"type": "json_object"}`. Leer
    `response.choices[0].message.content` y parsear con `json.loads`. (Modelos
    locales arbitrarios pueden no soportar tool-calls/JSON-mode → prompt+parse es
    lo más portable.)
- **`anthropic` (SDK `anthropic`)** — `anthropic.Anthropic()` resuelve
  `ANTHROPIC_API_KEY`. JSON estricto vía **tool-use forzado** (compatible con
  `anthropic==0.42.0`, que no tiene `messages.parse`/`output_config`): tool
  `classify_ticket` con `input_schema` (`category`/`priority` como `enum`, `tags`
  array), `tool_choice={"type":"tool","name":"classify_ticket"}`, y leer
  `block.input` del bloque `tool_use`. Sin `temperature`/`top_p`/`thinking`.

`max_tokens` modesto (p. ej. 512) en cualquier backend.

### Requisitos comunes (no negociables)

1. **El backend se elige por `LLM_PROVIDER`**; las keys/URLs se leen del entorno,
   nunca hardcodeadas.
2. **Valida la salida** contra los enums (`ALLOWED_*` de `models.py`). Normaliza
   `tags` (lista de strings, recorta a ≤5, ≤30 chars, minúscula; descarta no
   válidos). Si `category`/`priority` no son válidos → fallback.
3. **Reintenta una vez** si la llamada falla; si vuelve a fallar → fallback.
4. **No propaga excepciones** (de ningún SDK). Cualquier error (red, timeout,
   parseo, validación) → `FALLBACK_CLASSIFICATION` (devolver **copia**, no la
   constante).

> Doble red de seguridad: el clasificador nunca lanza en operación normal, **y**
> el endpoint además lo envuelve en `try/except` (sección 6). El test 4 prueba el
> segundo nivel sustituyendo la función por una que lanza.

### Prompt orientativo (no obligatorio)

> Eres un sistema de triage de tickets de soporte. Dado el título y la
> descripción, devuelve la clasificación: `category`
> (bug/feature_request/question/urgent), `priority` (P1=urgente, P2=importante,
> P3=normal) y `tags` (≤5 etiquetas cortas, en minúscula). Responde solo con el
> JSON pedido (camino OpenAI-compatible) o con la tool `classify_ticket` (camino
> Anthropic); sin texto extra ni markdown.

---

## 9. Tests de aceptación (contrato vinculante)

`tests/test_acceptance.py` — **no se modifica** (regla del taller). Los 5 tests y
lo que cada uno obliga a implementar:

| # | Test (nombre real) | Qué verifica | Implica |
|---|--------------------|--------------|---------|
| 1 | `test_post_ticket_creates_ticket_with_classification` | `POST /tickets` → `201`; `id` int, `title`/`description`, `category=="bug"`, `priority=="P1"`, `tags==["login","customer-impact"]`, `status=="open"`, `created_at`/`updated_at` presentes. (clasificador mockeado) | 201 explícito; ticket completo en la respuesta; `tags` lista ordenada; timestamps. Llamar al clasificador por atributo de módulo. |
| 2 | `test_created_ticket_is_persisted_and_listed` | Tras crear, `GET /tickets` lo incluye (con su `category`). | Persistencia real + listado. |
| 3 | `test_post_ticket_rejects_invalid_input` | 5 payloads → `422`: título vacío, título solo espacios, título >200, descripción vacía, descripción >5000. | Validación con `strip()` + longitudes; whitespace-only falla. |
| 4 | `test_classifier_failure_uses_safe_fallback` | Con `classify_ticket` lanzando `RuntimeError`, `POST /tickets` igual da `201` con `category=="question"`, `priority=="P3"`, `tags==[]`, `status=="open"`. | `try/except` a nivel de endpoint + `FALLBACK_CLASSIFICATION`. |
| 5 | `test_update_ticket_and_filter_by_status_priority_category` | Crear; `PATCH /tickets/{id}` `{status:"in_progress", priority:"P2"}` → `200` (refleja cambios); `GET /tickets?category=...&priority=P2&status=in_progress` → **exactamente 1**. | PATCH parcial + `updated_at`; filtros combinados exactos. |

Los tests inyectan la BD vía `DATABASE_URL` (sección 4) y mockean el
clasificador (no consumen tokens). Releer las secciones 4 y 6 antes de codificar:
ahí están los dos fallos más probables (resolución tardía de `DATABASE_URL` y
llamada al clasificador por atributo de módulo).

---

## 10. Datos de ejemplo (opcional, para la demo)

`seed_tickets.json` (en el repo) trae ~130 tickets reales con `title`,
`description` y `created_at`. Un script opcional (`python -m app.seed` o similar)
puede cargarlos: insertarlos clasificándolos con el LLM, **o** sin gastar tokens
insertándolos con la clasificación de fallback. No es requisito de aceptación;
sirve para poblar el tablero en la demo.

---

## 11. Calidad y CI

- `ruff check .` limpio (config en `pyproject.toml`, line-length 100).
- `pytest -v` → 5 verdes; `pytest --cov=app` para cobertura.
- CI (`.github/workflows/ci.yml`, ya presente): instala deps, `ruff check .`,
  `pytest -v --cov=app` en push/PR a `main`. Debe quedar **verde**.
- Commits pequeños y frecuentes; leer el diff antes de aceptar cambios de la IA.

---

## 12. Criterios de aceptación (Definition of Done)

- [ ] Los 5 tests de `tests/test_acceptance.py` en verde.
- [ ] CI verde en GitHub Actions (último commit en `main`).
- [ ] `uvicorn app.main:app --reload` arranca y `GET /` muestra el tablero.
- [ ] Crear un ticket por web lo clasifica y aparece en la tabla.
- [ ] Filtros por categoría/prioridad/estado funcionan.
- [ ] Si la IA falla, la app no cae y usa fallback (visible/manual en la demo).
- [ ] `.env` ignorado por git; ninguna API key en el código.
- [ ] `README.md` con instrucciones de arranque.

---

## 13. Decisiones tomadas (registro)

- **Proveedor LLM: pluggable** (`LLM_PROVIDER` = `local` | `openrouter` |
  `anthropic`) tras el contrato `classify_ticket`. Razón: se harán despliegues
  locales y vía API; el interfaz OpenAI-compatible permite el mismo código en
  local (servidor abierto, p. ej. `gpt-oss-120b`) y en OpenRouter. Implica añadir
  el SDK `openai` a `requirements.txt`.
- **Persistencia: `sqlite3` stdlib + Pydantic** (no SQLModel). Razón: no añadir
  dependencias innecesarias; suficiente para el alcance.
- **Salida estructurada:** prompt+JSON (con `response_format` si el backend lo
  soporta) en el camino OpenAI-compatible; tool-use forzado en Anthropic
  (compatible con `anthropic==0.42.0`, sin `messages.parse`).
- **Modelo configurable** (`LLM_MODEL` / `CLAUDE_MODEL` según backend).
- **Campos editables por PATCH: solo `status` y `priority`** (lo que pide el
  brief; el resto inmutable).
- **Filtros combinables con AND**; orden por `created_at` desc.
- **`tags` se persiste como JSON string** y se devuelve como lista ordenada.

---

## 14. No negociable

- No modificar `tests/test_acceptance.py` (salvo indicación expresa del profesor).
- No commitear `.env`; confirmar que está en `.gitignore`.
- No hardcodear API keys; leer las keys del entorno según el backend
  (`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`).
- No propagar excepciones del SDK del LLM al endpoint (fallback seguro).
- No introducir React/Vue ni build tools.
- No adoptar especificaciones externas que contradigan `tests/test_acceptance.py`.
