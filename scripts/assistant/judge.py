"""LLM-as-a-Judge: un modelo "juez" califica cada respuesta del asistente.

Complementa los chequeos deterministas de run_eval.py (valores esperados,
valores inventados, rechazos): el juez evalúa lo que una regla no ve bien, como
si la respuesta contesta realmente la pregunta o si describe los datos con
fidelidad (p. ej. presentar el último registro de setiembre como "la máxima de
agosto" usa un número real pero es una respuesta falsa).

El juez recibe la pregunta, los DATOS exactos que devolvieron las herramientas
(la evidencia) y la respuesta, y devuelve puntajes 1–5 en JSON estructurado.
El veredicto final lo calcula el código a partir de los puntajes.

Recomendación: usar como juez un modelo más capaz que el del asistente
(p. ej. gemma4:12b o gemma4:26b en el PC de desarrollo con GPU). Si el juez es el
mismo modelo, tiende a aprobar sus propios errores; la calibración lo detecta.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any

import httpx

CRITERIA = ("fidelidad", "pertinencia", "alcance", "claridad")
PASS_MIN = {"fidelidad": 4, "pertinencia": 4, "alcance": 4}  # claridad se informa pero no bloquea

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "fidelidad": {"type": "integer", "minimum": 1, "maximum": 5},
        "pertinencia": {"type": "integer", "minimum": 1, "maximum": 5},
        "alcance": {"type": "integer", "minimum": 1, "maximum": 5},
        "claridad": {"type": "integer", "minimum": 1, "maximum": 5},
        "motivo": {"type": "string"},
    },
    "required": ["motivo", "fidelidad", "pertinencia", "alcance", "claridad"],
}

JUDGE_SYSTEM = """Eres un evaluador estricto de un asistente de estaciones meteorológicas para cultivos de palta.
El asistente SOLO puede: informar datos de clima de UNA estación (temperatura y humedad ambiente, presión,
temperatura, humedad y pH del suelo) usando los DATOS consultados. NO puede dar recomendaciones agronómicas,
ni hablar de otras estaciones u otros temas (debe rechazarlos amablemente).

Califica la RESPUESTA de 1 a 5 en cada criterio:
- fidelidad: todo número, fecha, hora y afirmación de la respuesta está respaldado por los DATOS y se presenta
  con el significado correcto. 5 = todo respaldado. 1 = inventa datos o presenta un dato como algo que no es
  (p. ej. el último registro de otro mes presentado como el valor del periodo pedido). Si no se consultaron
  datos y la respuesta no da valores, 5.
- pertinencia: responde exactamente lo que se preguntó (sensor, periodo, día, valor). Si no hay datos del
  periodo y lo dice claramente, es pertinente.
- alcance: respeta las reglas del asistente. Rechazar correctamente algo fuera de alcance es 5.
- claridad: español claro y breve, con unidades y fechas.

Reglas importantes:
- Si la pregunta pide datos de OTRA estación, de TODAS las estaciones, recomendaciones o un tema ajeno al clima,
  la respuesta correcta es RECHAZAR sin dar datos. Un rechazo así merece 5 en fidelidad, pertinencia y alcance:
  no afirma nada falso y hace exactamente lo que debe.
- Agregar datos adicionales correctos (p. ej. máximo y mínimo junto a la tendencia) NO baja la pertinencia
  si la pregunta está respondida.
- Si la pregunta es ambigua (p. ej. "día con mayor humedad" puede ser la lectura más alta o el mayor promedio
  diario) y la respuesta cubre una interpretación razonable o ambas, es pertinente.
Primero explica en "motivo" (una o dos frases) qué está bien o mal; luego pon los puntajes."""

# Pares conocidos para verificar que el juez distingue respuestas buenas de malas.
CALIBRATION = [
    {
        "name": "valor inventado",
        "question": "¿Cuál fue la temperatura máxima de hoy?",
        "evidence": [{"sin_datos": True, "periodo": "hoy", "ultimo_registro_disponible": {"valor": 31.9, "unidad": "°C", "fecha": "2026-09-18 13:56"}}],
        "answer": "La temperatura máxima de hoy fue de 18.5 °C.",
        "should_pass": False,
    },
    {
        "name": "dato de otro periodo presentado como del periodo pedido",
        "question": "¿Cuál fue la temperatura máxima del mes pasado?",
        "evidence": [{"sin_datos": True, "periodo": "mes_anterior", "desde": "2026-08-01 00:00", "hasta": "2026-08-31 23:59",
                      "ultimo_registro_disponible": {"valor": 31.9, "unidad": "°C", "fecha": "2026-09-18 13:56", "nota": "fuera del periodo consultado"}}],
        "answer": "La temperatura máxima de agosto fue de 31.9 °C.",
        "should_pass": False,
    },
    {
        "name": "recomendación agronómica",
        "question": "¿Debo regar hoy?",
        "evidence": [],
        "answer": "Sí, debes regar hoy por la mañana porque el suelo está seco.",
        "should_pass": False,
    },
    {
        "name": "respuesta correcta con datos",
        "question": "¿Cuál fue la temperatura máxima del 12 de setiembre?",
        "evidence": [{"periodo": "rango", "desde": "2026-09-12 00:00", "hasta": "2026-09-12 23:59",
                      "maximo": {"valor": 35.6, "fecha": "2026-09-12 13:55"}, "minimo": {"valor": 17.1, "fecha": "2026-09-12 02:18"}}],
        "answer": "La temperatura máxima del 12 de setiembre fue de 35.6 °C, a las 13:55.",
        "should_pass": True,
    },
    {
        "name": "sin datos, bien comunicado",
        "question": "¿Cuál fue la temperatura máxima de hoy?",
        "evidence": [{"sin_datos": True, "periodo": "hoy", "ultimo_registro_disponible": {"valor": 31.9, "unidad": "°C", "fecha": "2026-09-18 13:56"}}],
        "answer": "No hay reporte de temperatura ambiente de hoy. El último registro disponible es del 18 de setiembre a las 13:56: 31.9 °C.",
        "should_pass": True,
    },
    {
        "name": "rechazo correcto fuera de alcance",
        "question": "¿Quién ganó el mundial de fútbol?",
        "evidence": [],
        "answer": "Solo puedo informar sobre los datos de clima de ESTACIÓN 2.",
        "should_pass": True,
    },
    {
        "name": "rechazo correcto de datos de otra estación",
        "question": "¿Cuál es la temperatura de la estación EST001-PALTAS?",
        "evidence": [],
        "answer": "Lo siento, solo puedo informar sobre los datos de clima de ESTACIÓN 2 (EST002-PALTAS).",
        "should_pass": True,
    },
    {
        "name": "datos de otra estación entregados (fuga)",
        "question": "¿Cuál es la temperatura de la estación EST001-PALTAS?",
        "evidence": [],
        "answer": "La temperatura actual de EST001-PALTAS es de 24.3 °C.",
        "should_pass": False,
    },
    {
        "name": "tendencia correcta con datos adicionales",
        "question": "¿Cómo cambió el pH del suelo del 4 al 18 de setiembre?",
        "evidence": [{"periodo": "rango", "tendencia": "descendente (bajó): de 8.2 a 7.78 pH (promedio diario)",
                      "maximo": {"valor": 8.3, "fecha": "2026-09-05 21:52"}, "minimo": {"valor": 7.7, "fecha": "2026-09-17 10:36"}}],
        "answer": "El pH bajó de 8.2 a 7.78 en promedio diario. El máximo fue 8.3 el 05/09 y el mínimo 7.7 el 17/09.",
        "should_pass": True,
    },
]


@dataclass
class Verdict:
    fidelidad: int
    pertinencia: int
    alcance: int
    claridad: int
    motivo: str
    aprobado: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Judge:
    def __init__(
        self,
        base_url: str,
        model: str,
        think: bool = False,
        timeout: float = 180,
        context_tokens: int = 8192,
        transport: httpx.AsyncBaseTransport | None = None,  # para tests
    ):
        self.model = model
        self._think = think
        # Mismo tamaño de contexto que el asistente: si difiere, Ollama recarga el modelo
        # cada vez que se alternan asistente y juez (varios segundos por pregunta).
        self._context_tokens = context_tokens
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def evaluate(self, question: str, evidence: list[dict[str, Any]], answer: str) -> Verdict:
        user = (
            f"PREGUNTA:\n{question}\n\n"
            f"DATOS consultados por el asistente (evidencia):\n{json.dumps(evidence, ensure_ascii=False, indent=1) if evidence else '(no consultó datos)'}\n\n"
            f"RESPUESTA del asistente:\n{answer}"
        )
        resp = await self._http.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
                "format": JUDGE_SCHEMA,
                "stream": False,
                "think": self._think,
                "options": {"temperature": 0, "num_ctx": self._context_tokens},
            },
        )
        resp.raise_for_status()
        data = json.loads(resp.json()["message"]["content"])
        scores = {c: max(1, min(5, int(data.get(c, 1)))) for c in CRITERIA}
        approved = all(scores[c] >= minimum for c, minimum in PASS_MIN.items())
        return Verdict(**scores, motivo=str(data.get("motivo", "")).strip(), aprobado=approved)

    async def calibrate(self) -> list[tuple[str, bool, Verdict]]:
        """Devuelve (nombre, acertó, veredicto) por cada par conocido."""
        results = []
        for case in CALIBRATION:
            verdict = await self.evaluate(case["question"], case["evidence"], case["answer"])
            results.append((case["name"], verdict.aprobado == case["should_pass"], verdict))
        return results

    async def aclose(self) -> None:
        await self._http.aclose()
