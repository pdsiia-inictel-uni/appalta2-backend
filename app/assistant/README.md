# Módulo Asistente IA (`app/assistant`)

Chat conversacional por estación con rol de **ingeniero agrónomo experto en palta Hass**.
Responde con las mediciones reales de los 6 sensores de la estación consultada y las
interpreta para el cultivo (riesgos y recomendaciones), con lenguaje sencillo para
agricultores o técnico para ingenieros agrónomos.
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

## Reportes por sensor

Cada sensor mide cada ~10 minutos (unas 144 lecturas por día). La herramienta
`estadisticas_sensor` resume cualquier periodo y el **código** (no el modelo) calcula:

| Dato | Ejemplo de pregunta |
|---|---|
| Máximo y mínimo con día y hora | "¿Qué día del mes hubo mayor temperatura?" → 35.6 °C el 12/09 13:55 |
| Día con promedio más alto / más bajo | "¿Qué día tuvo la temperatura promedio más alta?" → 06/09, 25.3 °C |
| Promedio, días con datos y resumen diario | "Dame un reporte de la temperatura de este mes" |
| Tendencia (sube / baja / estable) | "¿Cómo cambió el pH del 4 al 18 de septiembre?" |

Periodos: `hoy`, `ayer`, `ultimas_24_horas`, `ultimos_7_dias`, `ultimos_30_dias`,
`este_mes`, `mes_anterior` y `rango`. Las fechas escritas por el usuario
("septiembre", "del 10 al 18", "mes pasado", "última semana") las interpreta
`domain/dates.py` y tienen prioridad sobre las que complete el modelo.

## Asesoría experta en palta Hass

`domain/avocado.py` evalúa **por código** cada resultado frente a los rangos de la palta
Hass. Solo cuando un valor está en exceso se entrega al modelo como `alertas_palta`, con
una recomendación breve; con valores normales no hay recomendación y la respuesta es solo
el dato:

| Sensor | Referencia | Alerta (con recomendación) |
|---|---|---|
| Temperatura ambiente | óptimo 20–25 °C | > 30 °C estrés por calor; ≥ 35 °C calor extremo; ≤ 2 °C helada |
| Humedad ambiente | 60–80 % | > 85 % promedio (hongos) |
| Temperatura del suelo | 18–25 °C | > 30 °C estrés de raíces |
| Humedad del suelo | 20–40 % (orientativo) | < 20 % seco; > 50 % encharcamiento / Phytophthora |
| pH del suelo | 5.5–6.5 | > 7.5 muy alcalino (clorosis); < 5.0 ácido |

Además: alerta combinada de calor con aire seco (DPV máximo > 2 kPa), el DPV como dato
técnico (`dpv`) y la etapa fenológica del mes. Las preguntas se entienden aunque tengan
errores de tipeo ("temperatrua", "promdio", "humdad del sulo", "setimbe").
La herramienta `diagnostico_palta` resume los 6 sensores de un periodo para preguntas
como "¿cómo están mis paltas?", "¿debo regar?" o "¿qué fertilizante aplico?".

## Secuencia de la conversación

`chat/planner.py` decide **por código** qué consultar antes de llamar al modelo, así el
modelo no puede responder "no hay datos" sin consultar ni pedir aclaraciones innecesarias:

| Pregunta | Consulta |
|---|---|
| "promedio de humedad de suelo del mes de setimbe" | `estadisticas_sensor` humedad del suelo, 01–30/09 (meses mal escritos se corrigen) |
| "cual es el promedio de humedad de suelo" (sin periodo) | mismo periodo de la consulta anterior; si no hay, últimos 7 días |
| "¿y el mínimo?", "¿y en agosto?" | mismos sensores de la consulta anterior |
| "¿la temperatura presentada es ambiental o de suelo?" | se responde con el contexto guardado, sin consultar |
| "última semana registrada" o periodo reciente sin datos | ventana anclada al último registro, con aviso (`periodo_ajustado`) |
| "¿cómo están mis paltas?", "¿debo regar hoy?" | `diagnostico_palta` |

La memoria guarda, además de las preguntas y respuestas, la última consulta (sensores y
fechas) y la describe en el prompt del sistema. Las respuestas se entregan en texto plano
(sin Markdown), que es como las muestra la app.

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
├── chat/              # orquestador, planificador de consultas, prompt del sistema, memoria
├── llm/               # contrato LLMClient + implementación Ollama
├── tools/             # herramientas que el modelo puede invocar (ligadas a una estación)
├── domain/            # sensores, periodos, fechas y conocimiento agronómico de palta Hass
└── data/              # engine de solo lectura + consultas SQL
tests/assistant/       # 232 tests sin BD ni modelo
scripts/assistant/     # chat en consola y evaluación con preguntas reales
```

## Principios de diseño

1. **Aislamiento por estación garantizado por código.** La estación sale de la URL;
   ninguna herramienta del modelo tiene parámetro de estación.
2. **El modelo nunca escribe SQL.** Elige sensor y periodo de listas cerradas; las
   consultas son parametrizadas y el engine del asistente es de solo lectura
   (`default_transaction_read_only`), con un pool propio separado del de la API.
3. **Las fechas las calcula el código** (`hoy`, `ayer`, `ultimos_7_dias`, `rango`…), en hora de Perú.
4. **Sin valores inventados.** Si el modelo da una medición o dice "no hay datos" sin consultar una herramienta,
   se le pide consultarla. Solo se aceptan cifras que estén en los datos consultados o en las referencias de palta Hass.
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

# Evaluación: 56 preguntas reales contra la BD y el modelo (scripts/assistant/cases.json)
.\venv\Scripts\python.exe -m scripts.assistant.run_eval
.\venv\Scripts\python.exe -m scripts.assistant.run_eval --only A1,E1
.\venv\Scripts\python.exe -m scripts.assistant.run_eval --now "2026-11-15 10:00"   # simula otra fecha
```

La evaluación usa la hora real y **calcula las respuestas esperadas desde la BD en cada
ejecución** (`scripts/assistant/oracle.py`, con SQL propio, independiente del asistente).
Por eso sigue siendo válida cuando llegan datos nuevos, se rellenan datos atrasados o cambia
el mes: "¿máxima de ayer?" se compara con el dato real de ayer, y si un periodo no tiene
datos se exige que el asistente lo diga. Conviene correrla antes de cada despliegue y una
vez al mes; el criterio de paso a producción es ≥ 95 % de aciertos. Para agregar un caso:

```json
{"id": "X1", "category": "…", "station": "EST002-PALTAS", "question": "¿Cuál fue la humedad del suelo mínima de ayer?",
 "expect_tool": "estadisticas_sensor", "expect_args": {"sensor": "humedad_suelo"},
 "expect_db": {"sensor": "humedad_suelo", "period": "ayer", "metrics": ["min"]}}
```

## Producción (servidor sin GPU)

- Ollama como servicio aparte (`ollama/ollama` con un volumen para los modelos) y
  `docker exec ollama ollama pull gemma4:e2b`.
- La memoria de conversación es en proceso: con un solo worker de uvicorn funciona
  tal cual; con varios workers o réplicas, implementar `ConversationStore` sobre Redis.
- Crear idealmente un usuario de PostgreSQL de solo lectura para el asistente.
- Proxy HTTPS con buffering desactivado para `/stream` (`X-Accel-Buffering: no` ya se envía).
