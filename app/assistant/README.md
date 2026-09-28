# Módulo Asistente IA (`app/assistant`)

Chat conversacional por estación. Responde **solo** sobre los 6 sensores de clima
de la estación consultada, con las mediciones reales de la base de datos.
Es un módulo autocontenido del monolito: se registra con dos líneas en
`app/main.py` y no modifica ninguna otra parte de la API.

| Sensor (nombre para el modelo) | Código en BD | Unidad | Rango válido |
|---|---|---|---|
| `temperatura_ambiente` | `ambient_temperature` | °C | −10 a 50 |
| `humedad_ambiente` | `ambient_humidity` | % | 0 a 100 |
| `presion_atmosferica` | `atmospheric_pressure` | hPa | 500 a 1100 |
| `temperatura_suelo` | `soil_temperature` | °C | −10 a 60 |
| `humedad_suelo` | `soil_moisture` | % | 0 a 100 (0 exacto se avisa) |
| `ph_suelo` | `soil_ph` | pH | 0 a 14 |

## Rutas

Todas requieren `Authorization: Bearer <access_token>` de `/api/v1/user/login`.

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/chat/{station_code}` | Respuesta completa en JSON |
| POST | `/api/v1/chat/{station_code}/stream` | Respuesta en streaming (SSE): `tool`, `delta`, `reset`, `done`, `error` |
| DELETE | `/api/v1/chat/{station_code}/sessions/{session_id}` | Reinicia la conversación |
| GET | `/api/v1/assistant/health` | Base de datos y modelo disponibles (sin token) |

Petición: `{"question": "¿Cuál fue la temperatura máxima de ayer?", "session_id": "id-conversacion"}`

Errores: `401` token inválido o expirado · `404` estación inexistente ·
`422` pregunta vacía o mayor a 500 caracteres · `503` asistente ocupado o modelo no disponible.

## Estructura

```
app/assistant/
├── __init__.py        # expone assistant_router (lo único que importa app/main.py)
├── config.py          # AssistantSettings: LLM_*, CHAT_*, ASSISTANT_DB_* (todo con valores por defecto)
├── container.py       # arma las dependencias en la primera consulta y las libera al apagar
├── api/               # rutas, esquemas y validación del token
├── chat/              # orquestador, prompt del sistema, memoria de conversación
├── llm/               # contrato LLMClient + implementación Ollama
├── tools/             # herramientas que el modelo puede invocar (ligadas a una estación)
├── domain/            # catálogo de sensores y periodos de tiempo
└── data/              # engine de solo lectura + consultas SQL
tests/assistant/       # 56 tests sin BD ni modelo
scripts/assistant/     # chat en consola y evaluación con preguntas reales
```

## Principios de diseño

1. **Aislamiento por estación garantizado por código.** La estación sale de la URL;
   ninguna herramienta del modelo tiene parámetro de estación.
2. **El modelo nunca escribe SQL.** Elige sensor y periodo de listas cerradas; las
   consultas son parametrizadas y el engine del asistente es de solo lectura
   (`default_transaction_read_only`), con un pool propio separado del de la API.
3. **Las fechas las calcula el código** (`hoy`, `ayer`, `ultimos_7_dias`, `rango`…), en hora de Perú.
4. **Sin valores inventados.** Si el modelo da una medición sin consultar una herramienta, se le pide consultarla.
5. **Calidad de datos.** Se descartan lecturas imposibles (p. ej. −127 °C de una sonda desconectada) y se avisa.
6. **Pensado para CPU.** Prompt corto, resultados compactos, `think` desactivado y cola con límite de concurrencia.
7. **Proveedor intercambiable.** Cambiar Ollama por otro servicio es una clase nueva que cumpla `LLMClient`.

## Autenticación

Valida el token con la `SECRET_KEY` y el `ALGORITHM` de `app/services/auth.py`
(no se duplican). No reutiliza `verify_token` porque esa función **devuelve**
la excepción en lugar de lanzarla cuando el token es inválido, así que acepta
tokens inválidos o expirados. Conviene corregirla (`return` → `raise`) cuando se
revise la API.

## Configuración (opcional, en el mismo `.env`)

```
LLM_BASE_URL=http://localhost:11434   # en Docker Compose: http://ollama:11434
LLM_MODEL=gemma4:e2b
LLM_MAX_CONCURRENCY=2                 # igual a OLLAMA_NUM_PARALLEL; en CPU 1–2
LLM_QUEUE_TIMEOUT_SECONDS=60
LLM_TIMEOUT_SECONDS=180
TIMEZONE=America/Lima
```

## Desarrollo

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Tests (no necesitan BD ni modelo)
.\venv\Scripts\python.exe -m pytest tests/assistant

# Chat en consola contra la BD real
.\venv\Scripts\python.exe -m scripts.assistant.chat_cli --station EST001-PALTAS

# Evaluación: 27 preguntas con respuestas reales (scripts/assistant/cases.json)
.\venv\Scripts\python.exe -m scripts.assistant.run_eval
.\venv\Scripts\python.exe -m scripts.assistant.run_eval --only A1,E1
```

## Producción (servidor sin GPU)

- Ollama como servicio aparte (`ollama/ollama` con un volumen para los modelos) y
  `docker exec ollama ollama pull gemma4:e2b`.
- La memoria de conversación es en proceso: con un solo worker de uvicorn funciona
  tal cual; con varios workers o réplicas, implementar `ConversationStore` sobre Redis.
- Crear idealmente un usuario de PostgreSQL de solo lectura para el asistente.
- Proxy HTTPS con buffering desactivado para `/stream` (`X-Accel-Buffering: no` ya se envía).
