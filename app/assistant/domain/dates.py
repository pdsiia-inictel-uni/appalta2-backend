"""Extrae fechas concretas escritas en español dentro de una pregunta.

Los modelos pequeños suelen elegir bien el periodo "rango" pero olvidan
completar las fechas. Este intérprete determinista las obtiene del texto:

    "el 12 de septiembre"                  → 12/09 – 12/09
    "del 10 al 18 de setiembre"            → 10/09 – 18/09
    "entre el 30 de agosto y el 5 de sept" → 30/08 – 05/09
    "¿el 12 o el 13 de septiembre?"        → 12/09 – 13/09
    "12/09", "12/09/2026", "2026-09-12"

Sin año se asume el año actual; si esa fecha aún no ocurrió, el año anterior.
"""

import re
import unicodedata
from datetime import date
from typing import Optional

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9, "set": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "jun": 6, "jul": 7, "ago": 8, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip

_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
_TOKEN = re.compile(r"\b(?:(20\d{2})|(\d{1,2})|(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r"))\b")


def extract_date_range(text: str, today: date) -> Optional[tuple[date, date]]:
    """Devuelve (fecha_inicio, fecha_fin) de las fechas mencionadas, o None si no hay."""
    text = _normalize(text)
    found: list[date] = []

    for y, m, d in _ISO.findall(text):
        _append(found, int(y), int(m), int(d))
    text = _ISO.sub(" ", text)

    for d, m, y in _NUMERIC.findall(text):
        _append(found, int(y) if y else None, int(m), int(d), today)
    text = _NUMERIC.sub(" ", text)

    found += _spanish_dates(text, today)
    if not found:
        return None
    return min(found), max(found)


def _spanish_dates(text: str, today: date) -> list[date]:
    """Días seguidos de un mes: los días sin mes toman el siguiente mes mencionado."""
    result: list[date] = []
    pending_days: list[int] = []      # días que aún esperan su mes
    last_group: list[tuple[int, int]] = []  # (día, mes) del último mes, por si sigue un año

    for match in _TOKEN.finditer(text):
        year, day, month = match.groups()
        if day:
            pending_days.append(int(day))
        elif month:
            m = _MONTHS[month]
            last_group = [(d, m) for d in pending_days]
            result += [dt for d in pending_days if (dt := _make(None, m, d, today))]
            pending_days = []
        elif year and last_group:
            # "12 de septiembre de 2026": reemplaza el año asumido por el explícito
            for d, m in last_group:
                assumed = _make(None, m, d, today)
                if assumed in result:
                    result.remove(assumed)
                explicit = _make(int(year), m, d)
                if explicit:
                    result.append(explicit)
            last_group = []
    return result


def _append(found: list[date], year: Optional[int], month: int, day: int, today: Optional[date] = None) -> None:
    dt = _make(year, month, day, today)
    if dt:
        found.append(dt)


def _make(year: Optional[int], month: int, day: int, today: Optional[date] = None) -> Optional[date]:
    try:
        if year is not None:
            return date(year, month, day)
        assert today is not None
        candidate = date(today.year, month, day)
        return candidate if candidate <= today else date(today.year - 1, month, day)
    except ValueError:
        return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))
