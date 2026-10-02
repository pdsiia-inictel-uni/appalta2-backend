"""Evalúa el modelo configurado con preguntas de prueba contra la base real.

Cada caso de `cases.json` puede verificar:
- expect_tool / expect_args: herramienta, sensor y periodo elegidos por el modelo (las fechas
  concretas las comprueban los valores esperados, porque el código puede completarlas).
- expect_db: respuesta esperada calculada desde la BD al momento de evaluar (ver oracle.py):
  valores, días, hora o tendencia; si el periodo no tiene datos, se espera "no hay datos".
  Así la evaluación sigue siendo válida cuando llegan datos nuevos o cambia el mes.
- expect_values: números fijos que deben aparecer en la respuesta.
- expect_trend: "up" o "down", la respuesta debe describir esa tendencia.
- expect_keywords_any: al menos una de estas palabras en la respuesta.
- expect_no_data / expect_refusal: debe decir que no hay datos / que está fuera de alcance.
- expect_no_tool: no debe consultar herramientas.
- forbid_text: textos que NO deben aparecer (p. ej. "-127" o datos de otra estación).

Además, en TODOS los casos, cada medición de la respuesta (número + °C, %, hPa o pH)
debe existir en los datos que devolvieron las herramientas: si no, es un valor inventado.

Por defecto se evalúa con la hora real (como en producción); --now simula otra hora.

Con --judge, además, un LLM juez califica cada respuesta (fidelidad, pertinencia,
alcance, claridad) y se aplica el criterio de paso a producción; el proceso
termina con código 1 si no se cumple (útil en CI).

Uso:  python -m scripts.assistant.run_eval [--now "2026-10-01 12:00"] [--only A1,B2] [--category F]
      python -m scripts.assistant.run_eval --judge --judge-model gemma4:12b --report reporte.json
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
from app.assistant.domain.avocado import REFERENCE_TEXT
from app.assistant.config import get_settings
from app.assistant.domain.periods import Period, PeriodError, resolve_period
from app.assistant.tools.station_tools import StatsArgs, effective_range
from app.assistant.container import AssistantContainer
from scripts.assistant.judge import CRITERIA, Judge
from scripts.assistant.oracle import Oracle

CASES = Path(__file__).with_name("cases.json")

REFUSAL_HINTS = (
    "solo puedo", "sólo puedo", "únicamente", "no puedo", "no tengo", "no cuento", "no dispongo",
    "no doy", "no brindo", "no ofrezco", "no proporciono", "no mide", "no registra", "fuera de", "solo respondo", "no está relacionada",
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
    "stable": ("estable", "se mantuvo", "sin cambios", "sin variación"),
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
    """True si la consulta real (misma lógica que la herramienta) cubre el mismo intervalo
    que el periodo esperado; p. ej. 'rango' 2026-09-18 equivale a 'ayer' si hoy es 19/09."""
    if now is None:
        return False
    try:
        # El sensor no influye en el intervalo; se completa por si el caso no lo trae.
        _, got = effective_range(StatsArgs.model_validate({"sensor": "temperatura_ambiente", **args}), question, now)
        want = resolve_period(Period(expected_period), now)
    except (ValueError, PeriodError):
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

    # Las referencias de palta Hass ("óptimo 20–40 %") son válidas, igual que en el servicio.
    if unsupported := find_unsupported_values(answer, [t.output for t in result.tools] + [REFERENCE_TEXT]):
        failures.append(f"valores inventados (no están en los datos): {unsupported}")

    for text in case.get("forbid_text", []):
        if text.lower() in low:
            failures.append(f"contiene texto prohibido '{text}'")

    return failures


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    logging.basicConfig(level=logging.WARNING)
    tz = ZoneInfo(settings.timezone)
    # Sin --now: hora real, como en producción (las respuestas esperadas las calcula el oráculo).
    now = datetime.strptime(args.now, "%Y-%m-%d %H:%M").replace(tzinfo=tz) if args.now else datetime.now(tz)
    args.now = now.strftime("%Y-%m-%d %H:%M")
    container = AssistantContainer(settings, clock=lambda: now)
    service = container.chat_service
    oracle = Oracle(container.engine, tz)
    judge = (
        Judge(
            settings.llm_base_url,
            args.judge_model or settings.llm_model,
            think=args.judge_think,
            context_tokens=settings.llm_context_tokens,
        )
        if args.judge
        else None
    )

    only = {i.strip() for i in args.only.split(",") if i.strip()}
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if only:
        cases = [c for c in cases if c["id"] in only]
    if args.category:
        cases = [c for c in cases if c["category"].startswith(args.category)]

    print(f"Modelo: {settings.llm_model} · hora simulada: {args.now} · {len(cases)} casos")
    if judge:
        print(f"Juez: {judge.model}" + (" (el mismo modelo del asistente: resultados menos confiables)" if judge.model == settings.llm_model else ""))
    print()

    by_category: dict[str, list[bool]] = defaultdict(list)
    durations: list[float] = []
    report: dict = {"modelo": settings.llm_model, "hora_simulada": args.now, "juez": judge.model if judge else None, "casos": []}
    calibration_ok = None
    try:
        if judge:
            calibration = await judge.calibrate()
            calibration_ok = all(ok for _, ok, _ in calibration)
            print("Calibración del juez (debe distinguir respuestas buenas de malas conocidas):")
            for name, ok, verdict in calibration:
                print(f"  {'✔' if ok else '✘'} {name}: {'aprobada' if verdict.aprobado else 'rechazada'} — {verdict.motivo}")
            report["calibracion"] = [{"caso": n, "acierto": ok, **v.as_dict()} for n, ok, v in calibration]
            print()

        for case in cases:
            case = {**case, **oracle.expectations(case, now)}
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
            entry = {"id": case["id"], "pregunta": case["question"], "respuesta": result.answer, "fallos": failures}
            if judge:
                verdict = await judge.evaluate(case["question"], [t.output for t in result.tools], result.answer)
                scores = " ".join(f"{c[:4]}={getattr(verdict, c)}" for c in CRITERIA)
                print(f"      JUEZ: {'aprobada' if verdict.aprobado else 'RECHAZADA'} ({scores}) — {verdict.motivo}")
                entry["juez"] = verdict.as_dict()
            report["casos"].append(entry)
            print()
    finally:
        await container.aclose()
        if judge:
            await judge.aclose()

    total = sum(len(v) for v in by_category.values())
    passed = sum(sum(v) for v in by_category.values())
    print("Resumen por categoría:")
    for cat, results in by_category.items():
        print(f"  {cat:35s} {sum(results)}/{len(results)}")
    accuracy = passed / total
    print(f"\nAciertos (chequeos deterministas): {passed}/{total} ({accuracy:.0%})")
    print(f"Tiempo por pregunta: mediana {statistics.median(durations):.1f}s · máximo {max(durations):.1f}s")

    gate_ok = accuracy >= args.min_accuracy
    report["aciertos"] = accuracy
    if judge:
        verdicts = [c["juez"] for c in report["casos"]]
        approval = sum(v["aprobado"] for v in verdicts) / len(verdicts)
        mean_fid = statistics.mean(v["fidelidad"] for v in verdicts)
        severe = [c["id"] for c in report["casos"] if c["juez"]["fidelidad"] <= 2]
        means = {c: statistics.mean(v[c] for v in verdicts) for c in CRITERIA}
        print(f"Juez: aprobadas {approval:.0%} · promedios " + " · ".join(f"{c} {m:.2f}" for c, m in means.items()))
        if severe:
            print(f"Juez: fidelidad grave (≤2) en {severe}")
        gate_ok = gate_ok and approval >= args.min_judge_approval and mean_fid >= args.min_faithfulness and not severe
        if not calibration_ok:
            print("AVISO: el juez falló la calibración; sus veredictos no son confiables. Usa un modelo juez más capaz.")
            gate_ok = False
        report.update(aprobacion_juez=approval, promedios_juez=means, fidelidad_grave=severe, calibracion_ok=calibration_ok)

    criteria = f"aciertos ≥ {args.min_accuracy:.0%}"
    if judge:
        criteria += f", aprobación del juez ≥ {args.min_judge_approval:.0%}, fidelidad media ≥ {args.min_faithfulness}, sin fidelidad ≤ 2, juez calibrado"
    print(f"\n{'✅ APTO PARA PRODUCCIÓN' if gate_ok else '❌ NO APTO PARA PRODUCCIÓN'} ({criteria})")
    report["apto_produccion"] = gate_ok

    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Reporte guardado en {args.report}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", default=None, help="hora local simulada (YYYY-MM-DD HH:MM); por defecto, la real")
    parser.add_argument("--only", default="", help="ids separados por coma, p. ej. A1,B2")
    parser.add_argument("--category", default=None, help="letra de categoría, p. ej. F")
    parser.add_argument("--judge", action="store_true", help="califica cada respuesta con un LLM juez")
    parser.add_argument("--judge-model", default=None, help="modelo juez en Ollama (por defecto, el del asistente)")
    parser.add_argument("--judge-think", action="store_true", help="activa el razonamiento del juez (más lento, más preciso)")
    parser.add_argument("--min-accuracy", type=float, default=0.95)
    parser.add_argument("--min-judge-approval", type=float, default=0.90)
    parser.add_argument("--min-faithfulness", type=float, default=4.5)
    parser.add_argument("--report", default=None, help="ruta de un reporte JSON con todos los resultados")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
