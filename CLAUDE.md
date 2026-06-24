# CLAUDE.md

> **Equipo B (Spec-Driven):** este archivo es vuestro. Completadlo con vuestras
> convenciones como parte del trabajo de hoy — es tan importante como el `SPEC.md`
> que vais a escribir. Claude Code lo lee automáticamente al abrir el repo.
>
> **Equipo A (Vibe):** podéis ignorarlo. No estáis obligados a tocarlo.

Este repo es una plantilla docente para construir **TriageBot**, una aplicación
FastAPI que clasifica tickets de soporte con la API de Claude.

## Stack (innegociable)

- Python 3.11+
- FastAPI
- SQLite
- HTMX + Jinja2
- Tailwind (por CDN)
- SDK oficial de Anthropic
- pytest
- ruff

## Reglas del taller (para todos los equipos)

Estas reglas no son metodología: son condiciones del bootcamp. Se cumplen seas
del equipo que seas.

1. No modifiques `tests/test_acceptance.py` salvo que el profesor lo indique
   expresamente.
2. Nunca hardcodees una API key en el código.
3. Lee la API key desde la variable de entorno `ANTHROPIC_API_KEY`.
4. `.env` nunca se commitea. Comprueba que está en `.gitignore` antes de tu
   primer commit.

## Comandos útiles

```bash
pytest -v
pytest --cov=app
ruff check .
uvicorn app.main:app --reload
```

---

> A partir de aquí, el archivo está vacío **a propósito**.
>
> Si sois **Equipo B**, este es vuestro lienzo. Un buen `CLAUDE.md` suele incluir:
> la estructura de archivos esperada, las convenciones de código, cómo se manejan
> los errores, qué módulos pueden importar qué, lo que la IA **no** debe hacer en
> este repo, y vuestro flujo de trabajo. Lo que decidáis aquí guía a Claude Code
> en cada sesión, sin que tengáis que repetirlo en cada prompt.
