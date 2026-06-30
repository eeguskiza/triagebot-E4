# CLAUDE.md

## Proyecto

Este repositorio contiene **TriageBot**, una aplicación web interna para crear, clasificar, consultar y gestionar tickets de soporte.

El equipo trabaja con metodología **Spec-Driven**. Antes de implementar código, hay que leer la especificación, planificar los cambios y asegurar que la implementación respeta los tests de aceptación.

---

## Estado actual (IMPLEMENTADO — leer primero)

> El proyecto **ya está implementado** y en `main` con **CI verde** (~106 tests, cobertura ~98%).
> Esta sección refleja la **realidad actual**. Si alguna sección de más abajo habla en futuro o
> dice "TODO", está obsoleta: **manda lo de aquí**. El contrato base (modelo, endpoints, reglas
> no negociables) sigue vigente; aquí se amplía con lo añadido después.

**Equipo y método**: Erik Eguskiza (`eeguskiza`) y Elena Torralbo, Spec-Driven. Una rama por
persona + PR a `main`; **nadie commitea directo a `main`** y **no se mergea con CI rojo**. Los
commits/PR se hacen **a nombre del usuario, sin trailer `Co-Authored-By`**; los PR se crean por
**API REST de GitHub** (no hay `gh` instalado). El repo es un **fork** (Actions se habilitaron a mano).

**Clasificador IA** (`app/classifier.py`): pluggable por `LLM_PROVIDER`; **backend activo = `openrouter`**
(SDK `openai`, **ya en `requirements.txt`**). Default de código y `.env.example`: `LLM_MODEL=google/gemini-3.1-flash-lite`.
El `.env` local (no commiteado) tiene `OPENROUTER_API_KEY`, `LLM_PROVIDER=openrouter`,
`OPENAI_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL`. Nunca lanza (valida enums, normaliza tags,
reintenta ×1, fallback=copia). Pista: un ticket `question/P3/sin tags` = se aplicó el fallback.

**Modelo de datos real** (entidad `Ticket`): `id`, `title`, `description`, `category`, `priority`,
`tags`, **`assignees`** (lista de responsables), `status`, `created_at`, `updated_at`,
**`status_changed_at`**, **`due_date`**.
- `status` ∈ `open | in_progress | resolved | closed` (default `open`); **reabrir** = volver a `open`.
- `status_changed_at`: "desde cuándo está en ese estado" (se fija al crear, se actualiza al cambiar `status`).
- `due_date`: fecha límite por prioridad (P1=hoy, P2=+1d, P3=+2d). **Vencido** = `due_date` pasada y status no terminal (`closed`/`resolved`).
- `assignees`: varios responsables (JSON, como `tags`).
- `app/config.py`: enums/límites por entorno (`TICKET_CATEGORIES`, `TICKET_PRIORITIES`, `TICKET_STATUSES`, `MAX_TAGS`, `MAX_TAG_LEN`, `FALLBACK_CATEGORY/PRIORITY`). `ALLOWED_*` de `models.py` salen de aquí.

**API JSON** (contrato, cubierto por tests): `POST /tickets` (201) · `GET /tickets`
(filtros combinables: `category`, `priority`, `status`, **`assignee`**, **`overdue`**) ·
**`GET /tickets/stats`** (resumen para Marta: `total` + conteos `by_category`/`by_priority`/`by_status`;
declarado **antes** de `/tickets/{id}` para no colisionar) ·
`GET /tickets/{id}` (200/404) · `PATCH /tickets/{id}` (`status`/`priority`; 200/404/422).

**Frontend HTMX** (`templates/index.html` + `_tickets_table.html`): `GET /` (página, acepta filtros
por query, default `status=open`), `GET /ui/tickets` (fragmento; página completa si no es petición HTMX),
`POST /ui/tickets` (crear), `POST /ui/tickets/{id}` (edición inline de estado/prioridad/responsables).
Incluye: formulario (título + textarea), tablero de 9 columnas, **filtros** (categoría/prioridad/estado +
responsable + "solo vencidos") + **buscador** (`q`), **paginación** (20/pág), **edición inline**, "desde
cuándo", badge **VENCIDO**, layout ancho con scroll horizontal y estado en la URL (`hx-push-url`).
`db.list_tickets`/`count_tickets` aceptan `q/limit/offset/assignee/overdue` opcionales (aditivos: sin
ellos el comportamiento es el histórico → el contrato JSON no cambia). SQLite usa **WAL +
`busy_timeout=5000`** para concurrencia de escritura.

**Tests y CI** (~120 tests, cobertura ~98%): además de `tests/test_acceptance.py` (5 obligatorios,
**NO tocar**) hay `test_lab3_backend.py`, `test_classifier_unit.py`, `test_ui.py`, `test_integration.py`,
`test_db.py`, `test_lifecycle_assignees.py`, `test_due_date.py`, **`test_robustness.py`** (casos límite QA:
unicode, XSS, SQLi, duplicados, IDs malformados, concurrencia) (+ benchmarks). CI
(`.github/workflows/ci.yml`): matriz **Python 3.11/3.12**, cache pip, `ruff` + `pytest --cov`, **umbral 65%**,
y un job `pages` que publica un dashboard de cobertura a GitHub Pages (solo en `main`). E501 ignorado en `tests/*.py`.

**Arrancar / demo** (¡hay columnas nuevas → recrear la BD!):
```bash
pip install -r requirements.txt
rm -f triagebot.db && python -m app.seed --reset   # esquema nuevo + ~140 tickets clasificados
uvicorn app.main:app --reload                        # http://127.0.0.1:8000
```
Seed: `python -m app.seed [--fallback] [--limit N] [--reset]` (`--fallback` no gasta cuota).

### Bugs conocidos / deuda técnica (auditoría QA — PENDIENTES de arreglar)

Encontrados en una caza de bugs con verificación por reproducción. **Aún no están arreglados** (salvo
que un PR posterior lo indique). Seguridad: SQLi y XSS están **mitigados** (queries parametrizadas +
autoescape de Jinja); la prompt-injection es de bajo impacto (la salida del LLM se valida contra enums).

- 🔴 **Blocker — esquema sin migrar**: una `triagebot.db` antigua (sin `assignees`/`status_changed_at`/
  `due_date`) da **500 en todos los endpoints** (`CREATE TABLE IF NOT EXISTS` no añade columnas). Workaround:
  borrar la BD. Fix real: `ALTER TABLE` idempotente en `get_connection` (`PRAGMA table_info`).
- 🟠 **P1 nace vencido**: `_DUE_DAYS["P1"]=0` → `due_date==created_at` → todo P1 sale VENCIDO al instante.
- 🟠 **`classify_ticket` puede lanzar**: si el LLM devuelve `category`/`priority` no-hasheable (lista/dict),
  el `in set(...)` lanza `TypeError` (rompe el "nunca lanza"). Fix: validar `isinstance(str)` antes.
- 🟠 **Config rompe el arranque**: `MAX_TAGS`/`MAX_TAG_LEN` no numérico → `int()` peta en import.
  `TICKET_CATEGORIES`/`PRIORITIES` vacío → enum vacío → toda clasificación al fallback.
- 🟠 **`id` ≥ 2⁶³** en `GET/PATCH /tickets/{id}` → 500 (OverflowError) en vez de 404.
- 🟠 **`due_date` no se recalcula** al cambiar `priority` (PATCH/inline).
- 🟠 **Seed todo vencido**: los 140 ejemplos tienen fechas fijas pasadas → salen todos VENCIDOS.
- 🟠 **Default `open` incoherente**: `GET /` fija `open`, pero recargar `/ui/tickets` no → misma vista,
  datos distintos.
- 🟡 **Menores**: comodines LIKE `%`/`_` sin escapar en `q`/`assignee`; formatos de fecha mezclados
  (`Z` vs `+00:00`) afectan el orden; `page` no entero → 422; selects del tablero hardcodeados (no siguen a
  `TICKET_STATUSES`); `seed --limit` negativo; tags del clasificador no re-acotados al persistir.

---

## Fuentes de verdad

Antes de modificar código, revisa siempre estos archivos:

1. `SPEC.md`: contrato funcional del producto.
2. `BRIEF.md`: necesidad del cliente y contexto de negocio.
3. `tests/test_acceptance.py`: criterios de aceptación ejecutables.
4. `README.md`: instrucciones generales del repo.
5. `.env.example`: variables de entorno esperadas.

Si hay una diferencia entre una explicación informal y los tests reales del repo, los tests reales mandan.

## Objetivo funcional

TriageBot debe permitir:

1. Crear tickets con `title` y `description`.
2. Clasificarlos automáticamente mediante IA.
3. Persistir tickets en SQLite.
4. Consultar todos los tickets desde API.
5. Filtrar tickets por `category`, `priority` y `status`.
6. Actualizar manualmente `status` y `priority`.
7. Mostrar una página web sencilla con formulario, tablero y filtros.
8. Mantener tests y CI en verde.

## Stack técnico

Usa el stack del bootcamp:

* Python 3.11+
* FastAPI
* SQLite (módulo `sqlite3` de la stdlib) + Pydantic v2 para validación
* Jinja2
* HTMX
* Tailwind CSS por CDN
* LLM pluggable (`LLM_PROVIDER`): **`openrouter` (activo/default actual)** | `anthropic` | `local`. SDK `openai` **ya en `requirements.txt`**
* pytest
* ruff
* GitHub Actions
* VS Code + Claude Code

No introducir React, Vue, Vite, Webpack, bases de datos externas ni frameworks frontend complejos.

Si necesitas añadir una dependencia porque la especificación la exige, comprueba primero que existe y justifica el cambio. No añadas dependencias innecesarias.

## Variables de entorno y secretos

El backend del clasificador se elige con `LLM_PROVIDER` (`anthropic` por defecto). Las keys se leen del entorno según el backend:

* `openrouter` (**activo**) / `local`: `OPENAI_BASE_URL`, `OPENROUTER_API_KEY`, `LLM_MODEL` (SDK `openai`, **ya en `requirements.txt`**). Default `LLM_MODEL=google/gemini-3.1-flash-lite`.
* `anthropic`: `ANTHROPIC_API_KEY` (+ `CLAUDE_MODEL`).
* Enums/límites configurables: `TICKET_CATEGORIES`, `TICKET_PRIORITIES`, `TICKET_STATUSES`, `MAX_TAGS`, `MAX_TAG_LEN`, `FALLBACK_CATEGORY`, `FALLBACK_PRIORITY` (ver `app/config.py`).

Otra variable: `DATABASE_URL` (ruta SQLite, formato `sqlite:///...`). Detalle completo en `SPEC.md` §4.

Reglas obligatorias:

* No hardcodear API keys.
* No commitear `.env`.
* No imprimir claves en logs.
* No compartir claves fuera del equipo.
* Si falta la API key o falla el proveedor, la app debe seguir funcionando con fallback seguro.

## Modelo de datos

Entidad principal: `Ticket`.

Campos mínimos:

* `id`: int, primary key autoincremental.
* `title`: str, obligatorio, 1-200 caracteres tras `strip`.
* `description`: str, obligatorio, 1-5000 caracteres tras `strip`.
* `category`: str, uno de `bug`, `feature_request`, `question`, `urgent`.
* `priority`: str, uno de `P1`, `P2`, `P3`.
* `tags`: lista de strings, puede estar vacía. Máximo 5 tags, máximo 30 caracteres por tag.
* `assignees`: lista de responsables (varios), puede estar vacía. Se guarda como JSON (igual que `tags`).
* `status`: str, uno de `open`, `in_progress`, `resolved`, `closed`. Default: `open`. Reabrir = volver a `open`.
* `created_at`: datetime UTC generado en servidor.
* `updated_at`: datetime UTC actualizado en cambios relevantes.
* `status_changed_at`: datetime UTC; "desde cuándo está en ese estado" (se fija al crear, se actualiza al cambiar `status`).
* `due_date`: fecha límite UTC calculada por prioridad (P1=hoy, P2=+1d, P3=+2d). "Vencido" = `due_date` pasada y status no terminal.

Los enums son vinculantes. No devolver valores fuera de la lista ni variantes en mayúsculas como `"URGENT"`.

## Endpoints obligatorios

Implementar como mínimo estos endpoints en `app.main`.

### `POST /tickets`

Crea un ticket y lo clasifica síncronamente.

Entrada JSON:

```json
{
  "title": "La app no carga",
  "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión"
}
```

Reglas:

* Validar `title` y `description`.
* Aplicar `strip`.
* Devolver `422` si el input es inválido.
* Llamar a `app.classifier.classify_ticket(title, description)`.
* Si el clasificador falla, usar fallback.
* Persistir el ticket en SQLite.
* Devolver `201 Created`.
* La respuesta ya debe incluir `category`, `priority`, `tags`, `status`, `created_at` y `updated_at`.

### `GET /tickets`

Devuelve lista JSON de tickets.

Debe aceptar filtros opcionales combinables:

* `category`
* `priority`
* `status`

Ejemplo:

```text
GET /tickets?category=urgent&priority=P2&status=in_progress
```

Recomendación: ordenar por `created_at` descendente.

### `GET /tickets/{ticket_id}`

Devuelve un ticket por id.

* `200 OK` si existe.
* `404 Not Found` si no existe.

Este endpoint puede no estar cubierto por los tests actuales, pero forma parte del contrato funcional de referencia.

### `PATCH /tickets/{ticket_id}`

Actualiza solo campos permitidos.

Campos modificables:

* `status`
* `priority`

Reglas:

* No permitir modificar `title`, `description`, `category`, `tags`, `created_at` ni `id`.
* Validar enums.
* Actualizar `updated_at`.
* Devolver el ticket actualizado.
* Devolver `404` si el ticket no existe.
* Devolver `422` si los valores son inválidos.

### `GET /`

Devuelve HTML, no JSON.

Debe renderizar una página sencilla con:

* Formulario para crear tickets.
* Tablero/listado de tickets.
* Filtros por `category`, `priority` y `status`.

Usar Jinja2 templates. No escribir HTML grande como string dentro de `main.py`.

## Clasificador

El módulo `app/classifier.py` encapsula toda la lógica de IA.

Regla importante: ningún otro módulo debe llamar directamente al SDK de IA. `main.py` no debe contener llamadas a OpenRouter/OpenAI/Anthropic.

Contrato público:

```python
def classify_ticket(title: str, description: str) -> dict:
    ...
```

Debe devolver siempre un diccionario con esta forma:

```python
{
    "category": "bug" | "feature_request" | "question" | "urgent",
    "priority": "P1" | "P2" | "P3",
    "tags": list[str],
}
```

Fallback obligatorio:

```python
FALLBACK_CLASSIFICATION = {
    "category": "question",
    "priority": "P3",
    "tags": [],
}
```

Reglas del clasificador:

* Seleccionar backend con `LLM_PROVIDER` (default `anthropic`); leer la key del entorno según el backend, nunca hardcodeada.
* Backends: `anthropic` (Claude vía SDK `anthropic`, tool-use forzado) | `openrouter`/`local` (SDK `openai`, JSON estricto). Detalle en `SPEC.md` §8.
* Pedir al modelo una respuesta estrictamente JSON.
* Parsear la respuesta.
* Validar `category`, `priority` y `tags`.
* Limitar tags a 5 elementos y 30 caracteres por tag.
* Reintentar una vez si falla la llamada.
* Si vuelve a fallar, devolver fallback.
* Si falta API key, devolver fallback.
* Si el modelo devuelve JSON inválido, devolver fallback.
* Si devuelve valores fuera de enum, devolver fallback.
* Nunca propagar excepciones del SDK al endpoint.

## Arquitectura recomendada

Mantener separación clara de responsabilidades.

Estructura recomendada:

```text
app/
  main.py
  models.py
  db.py
  classifier.py
  templates/
    index.html
    _tickets_table.html
tests/
  test_acceptance.py
```

Responsabilidades:

* `main.py`: crear la app FastAPI y definir rutas (API JSON + UI HTMX).
* `models.py`: schemas Pydantic (`TicketCreate`/`TicketUpdate`/`TicketRead`) y enums permitidos.
* `db.py`: conexión `sqlite3`, creación idempotente del esquema y helpers CRUD; (de)serialización de `tags`.
* `classifier.py`: integración con IA y fallback.
* `templates/index.html` + `templates/_tickets_table.html`: frontend mínimo.

Evitar meter todo en `main.py`.

## Base de datos

Usar SQLite.

Reglas:

* La base local puede llamarse `triagebot.db`.
* La app debe leer `DATABASE_URL` (formato `sqlite:///...`) **en cada petición/conexión**, no en import-time: los tests lo inyectan con `monkeypatch.setenv` antes de crear el `TestClient` y NO usan el context manager (no se dispara `startup`). Resolverlo al importar rompe los tests.
* Crear el esquema de forma idempotente (`CREATE TABLE IF NOT EXISTS`) antes de usarlo; no dependas solo de `@app.on_event("startup")`.
* No commitear archivos `.db`, `.sqlite` ni `.sqlite3`.
* Guardar `tags` de forma compatible con SQLite. Puede usarse JSON serializado si es necesario.

## Tests

No modificar `tests/test_acceptance.py`.

Los tests actuales del repo comprueban como mínimo:

1. `POST /tickets` crea ticket con clasificación y devuelve `201`.
2. El ticket creado queda persistido y aparece en `GET /tickets`.
3. Inputs inválidos devuelven `422`.
4. Si falla el clasificador, se aplica fallback y la app no cae.
5. Se puede actualizar `status`/`priority` y filtrar por `category`, `priority` y `status`.

Los tests pueden mockear `app.classifier.classify_ticket`, así que no acoples los endpoints a una llamada real al LLM durante los tests.

## Ruff y estilo

Ejecutar:

```bash
ruff check .
```

Si Ruff falla por líneas largas dentro de `tests/test_acceptance.py`, no modifiques el test. Configura Ruff para ignorar `E501` solo en ese archivo, por ejemplo en `pyproject.toml`.

Ejemplo:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint.per-file-ignores]
"tests/test_acceptance.py" = ["E501"]
```

No uses `ruff check . --fix` a ciegas sin revisar el diff.

## Comandos útiles

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Ejecutar app:

```bash
uvicorn app.main:app --reload
```

Ejecutar tests:

```bash
pytest -v
```

Ejecutar cobertura:

```bash
pytest --cov=app
```

Ejecutar lint:

```bash
ruff check .
```

## Flujo de trabajo con Claude Code

Antes de tocar código:

1. Leer `SPEC.md`, `BRIEF.md` y `tests/test_acceptance.py`.
2. Proponer un plan breve.
3. Identificar archivos a modificar.
4. Explicar riesgos.
5. Implementar en cambios pequeños.

Durante la implementación:

* Priorizar que pasen tests antes que mejorar estética.
* No cambiar contratos públicos sin necesidad.
* No editar tests para hacerlos pasar.
* No introducir dependencias no verificadas.
* No generar código “fake” que solo pase tests pero rompa el comportamiento esperado.
* Mantener commits pequeños.
* Revisar el diff antes de aceptar cambios.

Después de cada bloque importante:

```bash
ruff check .
pytest -v
```

Si ambos pasan, preparar commit.

## Prompting recomendado

Para cada feature, seguir esta estructura:

```text
Contexto:
Estamos implementando TriageBot siguiendo SPEC.md y tests/test_acceptance.py.

Objetivo:
Implementar <feature concreta>.

Restricciones:
- No modificar tests/test_acceptance.py.
- No hardcodear claves.
- No romper endpoints existentes.
- Mantener FastAPI + SQLite (`sqlite3`) + Pydantic.
- Aplicar fallback si falla el clasificador.

Criterios de aceptación:
- ruff check . pasa.
- pytest -v pasa.
- El comportamiento cumple SPEC.md.
```

## Orden recomendado de implementación

1. Configurar `pyproject.toml` si Ruff falla por tests del profesor.
2. Crear modelos y base de datos.
3. Implementar `POST /tickets`.
4. Implementar `GET /tickets` con filtros.
5. Implementar fallback robusto en `classifier.py`.
6. Implementar `PATCH /tickets/{ticket_id}`.
7. Implementar `GET /tickets/{ticket_id}`.
8. Implementar frontend mínimo con Jinja2 + HTMX.
9. Ejecutar `ruff check .`, `pytest -v` y `pytest --cov=app`.
10. Actualizar `README.md` si cambian instrucciones de arranque.

## No negociable

* No commitear `.env`.
* No hardcodear API keys.
* No modificar `tests/test_acceptance.py`.
* No propagar excepciones del LLM al endpoint.
* No introducir React ni frontend complejo.
* No cambiar de stack salvo indicación explícita del profesor.
* No llamar al LLM desde `main.py`.
* No aceptar cambios de IA sin revisar el diff.
* No hacer merge con CI rojo.
