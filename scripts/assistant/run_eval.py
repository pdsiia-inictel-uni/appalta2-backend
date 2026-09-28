"""Evalúa el modelo configurado con preguntas de prueba contra la base real.

Cada caso de `cases.json` puede verificar:
- expect_tool / expect_args: herramienta, sensor y periodo elegidos por el modelo (las fechas
  concretas las comprueban los valores esperados, porque el código puede completarlas).
- expect_values: números que deben aparecer en la respuesta (valores reales de la BD).
- expect_trend: "up" o "down", la respuesta debe describir esa tendencia.
- expect_keywords_any: al menos una de estas palabras en la respuesta.
- expect_no_data / expect_refusal: debe decir que no hay datos / que está fuera de alcance.
- expect_no_tool: no debe consultar herramientas.
- forbid_text: textos que NO deben aparecer (p. ej. "-127" o datos de otra estación).

Además, en TODOS los casos, cada medición de la respuesta (número + °C, %, hPa o pH)
debe existir en los datos que devolvieron las herramientas: si no, es un valor inventado.

La hora "actual" se fija con --now para que las respuestas esperadas no
cambien con el paso del tiempo.

Uso:  python -m scripts.assistant.run_eval [--now "2026-09-19 12:00"] [--only A1,B2] [--category F]
"""

import argparse
import logging
import asyncio
import json
import re
import statistics
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.assistant.chat.grounding import find_unsupported_values
from app.assistant.config import get_settings
from app.assistant.domain.dates import extract_date_range
from app.assistant.domain.periods import Period, PeriodError, resolve_period
from app.assistant.container import AssistantContainer

CASES = Path(__file__).with_name("cases.json")

REFUSAL_HINTS = (
    "solo puedo", "sólo puedo", "únicamente", "no puedo", "no tengo", "no cuento", "no dispongo",
    "no doy", "no brindo", "no ofrezco", "no proporciono", "no mide", "no registra", "fuera de",
)  # fmt: skip
NO_DATA_HINTS = (
    "no hay", "sin datos", "no se registr", "no tiene registros", "no existen", "no se encontr",
    "no tengo datos", "no cuenta con", "no dispongo", "no hay registros",
    "no están disponibles", "no está disponible", "no disponible",
)  # fmt: skip
# Verbos o expresiones de cambio (no adjetivos como "el más bajo", que no describen tendencia)
TREND_HINTS = {
    "down": ("bajó", "bajando", "a la baja", "disminu", "descend", "se redujo", "cayó", "decrec", "se secó"),
    "up": ("subió", "subiendo", "al alza", "aument", "ascend", "increment", "creció"),
}


def number_variants(value: str) -> set[str]:
    """'1003.7' → {'1003.7', '1003,7', '1.003,7', '1 003,7', '1,003.7'}; '22.0' también acepta '22'."""
    whole, _, dec = value.partition(".")
    variants = {value, value.replace(".", ",")}
    if len(whole) > 3 and dec:
        head, tail = whole[:-3], whole[-3:]
        variants |= {f"{head}.{tail},{dec}", f"{head} {tail},{dec}", f"{head},{tail}.{dec}"}
    if dec and set(dec) == {"0"}:
        variants.add(whole)
    return variants


def contains_number(text: str, value: str) -> bool:
    # Evita coincidencias parciales: "14.4" no debe coincidir dentro de "114.45".
    return any(re.search(rf"(?<![\d.,]){re.escape(v)}(?![\d]|[.,]\d)", text) for v in number_variants(value))


def same_interval(expected_period: str, args: dict, question: str, now: datetime | None) -> bool:
    """True si los argumentos del modelo cubren el mismo intervalo que el periodo esperado
    (p. ej. periodo 'rango' con fecha 2026-09-18 equivale a 'ayer' si hoy es 19/09)."""
    if now is None:
        return False
    try:
        start = datetime.strptime(args["fecha_inicio"], "%Y-%m-%d").date() if args.get("fecha_inicio") else None
        end = datetime.strptime(args["fecha_fin"], "%Y-%m-%d").date() if args.get("fecha_fin") else None
        if start is None and str(args.get("periodo", "")).lower() == "rango":
            start, end = extract_date_range(question, now.date()) or (None, None)  # mismo respaldo del sistema
        got = resolve_period(Period(str(args.get("periodo", "")).lower()), now, start, end)
        want = resolve_period(Period(expected_period), now)
    except (KeyError, ValueError, PeriodError):
        return False
    return (got.start, got.end) == (want.start, want.end)


def check(case: dict, result, now: datetime | None = None) -> list[str]:
    """Devuelve la lista de fallos (vacía = caso aprobado)."""
    failures: list[str] = []
    answer = result.answer
    low = answer.lower()
    first = result.tools[0] if result.tools else None

    expected_tool = case.get("expect_tool")
    if expected_tool:
        allowed = expected_tool if isinstance(expected_tool, list) else [expected_tool]
        if first is None:
            failures.append("no usó herramientas")
        elif first.name not in allowed:
            failures.append(f"herramienta {first.name} (esperada {'/'.join(allowed)})")
        else:
            for key, expected in (case.get("expect_args") or {}).items():
                got = str(first.arguments.get(key, "")).strip().lower()
                if key == "periodo" and got != expected and same_interval(expected, first.arguments, case.get("question", ""), now):
                    continue
                if got != expected:
                    failures.append(f"{key}={got or '∅'} (esperado {expected})")
            if not first.ok:
                failures.append("la herramienta devolvió error")

    if case.get("expect_no_tool") and result.tools:
        failures.append(f"usó herramientas: {[t.name for t in result.tools]}")

    for value in case.get("expect_values", []):
        if not contains_number(answer, value):
            failures.append(f"falta el valor {value}")

    if (trend := case.get("expect_trend")) and not any(h in low for h in TREND_HINTS[trend]):
        failures.append(f"no describe tendencia '{trend}'")

    if (words := case.get("expect_keywords_any")) and not any(w.lower() in low for w in words):
        failures.append(f"no menciona ninguno de {words}")

    if case.get("expect_no_data") and not any(h in low for h in NO_DATA_HINTS):
        failures.append("no indica que no hay datos")

    if case.get("expect_refusal") and not any(h in low for h in REFUSAL_HINTS):
        failures.append("no rechaza / no aclara su alcance")

    if unsupported := find_unsupported_values(answer, [t.output for t in result.tools]):
        failures.append(f"valores inventados (no están en los datos): {unsupported}")

    for text in case.get("forbid_text", []):
        if text.lower() in low:
            failures.append(f"contiene texto prohibido '{text}'")

    return failures


async def main(now_text: str, only: set[str], category: str | None) -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.WARNING)
    now = datetime.strptime(now_text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(settings.timezone))
    container = AssistantContainer(settings, clock=lambda: now)
    service = container.chat_service

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if only:
        cases = [c for c in cases if c["id"] in only]
    if category:
        cases = [c for c in cases if c["category"].startswith(category)]

    print(f"Modelo: {settings.llm_model} · hora simulada: {now_text} · {len(cases)} casos\n")
    by_category: dict[str, list[bool]] = defaultdict(list)
    durations: list[float] = []
    try:
        for case in cases:
            result = await service.ask(case["station"], case["question"], "eval", uuid.uuid4().hex)
            failures = check(case, result, now)
            ok = not failures
            by_category[case["category"]].append(ok)
            durations.append(result.duration_ms / 1000)
            tools = ", ".join(f"{t.name}({json.dumps(t.arguments, ensure_ascii=False)})" for t in result.tools) or "—"
            print(f"{'✔' if ok else '✘'} {case['id']:3s} [{result.duration_ms / 1000:5.1f}s] {case['question']}")
            print(f"      herramientas: {tools}")
            print(f"      respuesta: {result.answer}")
            if failures:
                print(f"      FALLOS: {'; '.join(failures)}")
            print()
    finally:
        await container.aclose()

    total = sum(len(v) for v in by_category.values())
    passed = sum(sum(v) for v in by_category.values())
    print("Resumen por categoría:")
    for cat, results in by_category.items():
        print(f"  {cat:35s} {sum(results)}/{len(results)}")
    print(f"\nAciertos: {passed}/{total} ({passed / total:.0%})")
    print(f"Tiempo por pregunta: mediana {statistics.median(durations):.1f}s · máximo {max(durations):.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", default="2026-09-19 12:00", help="hora local simulada (YYYY-MM-DD HH:MM)")
    parser.add_argument("--only", default="", help="ids separados por coma, p. ej. A1,B2")
    parser.add_argument("--category", default=None, help="letra de categoría, p. ej. F")
    args = parser.parse_args()
    asyncio.run(main(args.now, {i.strip() for i in args.only.split(",") if i.strip()}, args.category))
