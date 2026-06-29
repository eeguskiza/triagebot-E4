# CLAUDE.md

## Proyecto

Este repositorio contiene **TriageBot**, una aplicación web interna para crear, clasificar, consultar y gestionar tickets de soporte.

El equipo trabaja con metodología **Spec-Driven**. Antes de implementar código, hay que leer la especificación, planificar los cambios y asegurar que la implementación respeta los tests de aceptación.

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
* LLM pluggable (`LLM_PROVIDER`): `anthropic` (default) | `openrouter` | `local` (servidor OpenAI-compatible)
* pytest
* ruff
* GitHub Actions
* VS Code + Claude Code

No introducir React, Vue, Vite, Webpack, bases de datos externas ni frameworks frontend complejos.

Si necesitas añadir una dependencia porque la especificación la exige, comprueba primero que existe y justifica el cambio. No añadas dependencias innecesarias.

## Variables de entorno y secretos

El backend del clasificador se elige con `LLM_PROVIDER` (`anthropic` por defecto). Las keys se leen del entorno según el backend:

* `anthropic` (default): `ANTHROPIC_API_KEY` (+ `CLAUDE_MODEL`).
* `openrouter` / `local`: `OPENAI_BASE_URL`, `OPENROUTER_API_KEY`, `LLM_MODEL` (usan el SDK `openai`, aún no en `requirements.txt`).

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
* `status`: str, uno de `open`, `in_progress`, `closed`. Default: `open`.
* `created_at`: datetime UTC generado en servidor.
* `updated_at`: datetime UTC actualizado en cambios relevantes.

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
