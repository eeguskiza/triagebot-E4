# Lab 9 — Daily Digest Agent

Skill para OpenClaw que consume `GET /tickets` de TriageBot y genera un resumen
diario en lenguaje natural con conteos por prioridad, categorías, tickets urgentes
y recomendación de siguiente acción.

---

## Estructura

```
lab9/
  triage_daily_digest.py   ← skill principal (sin dependencias externas)
  skill.json               ← manifiesto para OpenClaw
  test_triage_daily_digest.py
  README.md
```

---

## 1. Levantar TriageBot localmente

```bash
# En el directorio raíz del repo
uvicorn app.main:app --reload
```

Comprueba que funciona:

```bash
curl http://localhost:8000/health
# → {"status":"ok"}

curl http://localhost:8000/tickets
# → [] o lista de tickets JSON
```

---

## 2. Poblar la base de datos (seed)

Si el tablero está vacío, carga datos de ejemplo:

```bash
# Sin gastar cuota del LLM (fallback):
python -m app.seed --fallback --limit 10

# Con clasificación real (gasta cuota):
python -m app.seed --limit 10
```

---

## 3. Exponer TriageBot con ngrok

```bash
ngrok http 8000
```

Copia la URL HTTPS que te da ngrok. Ejemplo:
```
https://cough-vagueness-throwing.ngrok-free.dev
```

Comprueba desde fuera:

```bash
curl -H "ngrok-skip-browser-warning: true" \
  https://cough-vagueness-throwing.ngrok-free.dev/tickets
```

---

## 4. Probar la skill localmente

```bash
# Apuntando al TriageBot local:
TRIAGEBOT_BASE_URL=http://localhost:8000 python lab9/triage_daily_digest.py

# Apuntando a ngrok:
TRIAGEBOT_BASE_URL=https://cough-vagueness-throwing.ngrok-free.dev \
  python lab9/triage_daily_digest.py
```

Salida esperada:
```
📋 *Daily Digest — TriageBot*
📅 01/07/2026 10:30 UTC

📊 *5 ticket(s) activo(s)*

**Por prioridad:**
  🔴 P1 (crítico): 1
  🟠 P2 (alto):    2
  🟡 P3 (normal):  2
...
```

---

## 5. Ejecutar los tests

```bash
pytest lab9/ -v --benchmark-disable
```

O junto con toda la suite:

```bash
pytest -v --benchmark-disable
```

---

## 6. Copiar la skill a la VPS (OpenClaw)

```bash
# Crear la carpeta de la skill en la VPS
ssh claw "mkdir -p ~/.openclaw/skills/triage_daily_digest"

# Copiar los archivos
scp lab9/triage_daily_digest.py claw:~/.openclaw/skills/triage_daily_digest/
scp lab9/skill.json              claw:~/.openclaw/skills/triage_daily_digest/
```

---

## 7. Configurar TRIAGEBOT_BASE_URL en la VPS

```bash
ssh claw
```

Dentro de la VPS:

```bash
# Opción A: variable de entorno en el arranque de OpenClaw
echo 'export TRIAGEBOT_BASE_URL=https://cough-vagueness-throwing.ngrok-free.dev' >> ~/.bashrc
source ~/.bashrc

# Opción B: fichero .env si OpenClaw lo soporta
echo 'TRIAGEBOT_BASE_URL=https://cough-vagueness-throwing.ngrok-free.dev' \
  >> ~/.openclaw/.env
```

Comprueba que la skill funciona desde la VPS:

```bash
TRIAGEBOT_BASE_URL=https://cough-vagueness-throwing.ngrok-free.dev \
  python ~/.openclaw/skills/triage_daily_digest/triage_daily_digest.py
```

---

## 8. Reiniciar OpenClaw

```bash
# Si usa systemd:
sudo systemctl restart openclaw

# Si corre como proceso en segundo plano:
pkill -f openclaw && openclaw &
```

---

## 9. Probar desde Telegram

Envía al bot de OpenClaw cualquiera de estos mensajes:

```
Dame el resumen de los tickets de hoy
¿Qué tickets hay pendientes?
Daily digest de TriageBot
Estado del tablero de incidencias
```

---

## Notas sobre el formato de skill de OpenClaw

La skill está implementada como módulo Python puro con un punto de entrada claro:

```python
from lab9.triage_daily_digest import get_digest
resultado = get_digest()   # devuelve string listo para enviar
```

Si OpenClaw espera un formato distinto (ej. función `run(args)`, clase `Skill`,
o un fichero `index.py`), adapta el wrapper así:

```python
# index.py — wrapper mínimo para el formato de OpenClaw
from triage_daily_digest import get_digest

def run(args=None):
    return get_digest()
```

Consulta `skill.json` para los metadatos de registro de la skill.
