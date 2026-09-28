"""Verifica que las mediciones de una respuesta existan en los datos consultados.

Un modelo pequeño puede "rellenar" un valor que la herramienta no le dio (por
ejemplo, inventar la temperatura del último registro). Aquí se extrae cada
número acompañado de una unidad de sensor (°C, %, hPa, pH) y se busca en los
resultados de las herramientas, aceptando el redondeo que haga el modelo
(p. ej. 7.98 → "8.0") y el formato peruano ("1.003,7", "35,6").
"""

import json
import re
from typing import Any, Iterable

_NUMBER = r"-?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?"

# "35.6 °C", "35,6°", "98.5 %", "1.003,7 hPa", "7.7 pH"
_VALUE_THEN_UNIT = re.compile(rf"(?<![\d.,])({_NUMBER})\s*(°\s*C?|%|hPa\b|pH\b)", re.IGNORECASE)
# "pH de 7.7", "pH del suelo fue de 7.7", "pH: 7.7"
_PH_THEN_VALUE = re.compile(
    rf"\bpH\b(?:\s+del\s+suelo)?(?:\s+(?:es|fue|era|estuvo|promedio|promedió|de|en|:))*\s*({_NUMBER})(?!\s*(?:°|%|hPa))",
    re.IGNORECASE,
)
_EVIDENCE_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def find_unsupported_values(answer: str, tool_outputs: Iterable[Any]) -> list[str]:
    """Mediciones de la respuesta que no aparecen en ningún resultado de herramienta."""
    evidence = [float(n) for out in tool_outputs for n in _EVIDENCE_NUMBER.findall(_as_text(out))]
    unsupported = []
    for raw, unit in _mentioned_values(answer):
        value, decimals = _parse(raw)
        if not any(abs(round(e, decimals) - value) < 1e-9 for e in evidence):
            unsupported.append(f"{raw} {unit}".strip())
    return unsupported


def _mentioned_values(answer: str) -> list[tuple[str, str]]:
    found = [(m.group(1), m.group(2)) for m in _VALUE_THEN_UNIT.finditer(answer)]
    found += [(m.group(1), "pH") for m in _PH_THEN_VALUE.finditer(answer)]
    return found


def _parse(raw: str) -> tuple[float, int]:
    """Convierte '1.003,7' / '1 003,7' / '1,003.7' / '35,6' / '35.6' → (valor, decimales)."""
    s = raw.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", s) and len(s.split(".")[0].lstrip("-")) <= 1:
        # "1.003" como separador de miles (solo si no puede ser un decimal razonable)
        s = s.replace(".", "")
    decimals = len(s.split(".")[1]) if "." in s else 0
    return float(s), decimals


def _as_text(output: Any) -> str:
    return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
