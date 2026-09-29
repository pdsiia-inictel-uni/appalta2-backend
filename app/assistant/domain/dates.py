"""Extrae fechas concretas escritas en español dentro de una pregunta.

Los modelos pequeños suelen elegir bien el periodo "rango" pero olvidan
completar las fechas. Este intérprete determinista las obtiene del texto:

    "el 12 de septiembre"                  → 12/09 – 12/09
    "del 10 al 18 de setiembre"            → 10/09 – 18/09
    "entre el 30 de agosto y el 5 de sept" → 30/08 – 05/09
    "¿el 12 o el 13 de septiembre?"        → 12/09 – 13/09
    "12/09", "12/09/2026", "2026-09-12"
    "en septiembre", "agosto de 2026"      → mes completo
    "este mes", "del mes", "mes actual"    → mes en curso
    "el mes pasado", "mes anterior"        → mes anterior completo

Sin año se asume el año actual; si esa fecha (o mes) aún no llegó, el año anterior.
"""

import calendar
import re
import unicodedata
from datetime import date, timedelta
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
_CURRENT_MONTH = re.compile(r"\b(?:este|del|en el|el) mes\b(?! (?:pasado|anterior))|\bmes (?:actual|en curso)\b")
_PREVIOUS_MONTH = re.compile(r"\bmes (?:pasado|anterior)\b")

Range = tuple[date, date]


def extract_date_range(text: str, today: date) -> Optional[Range]:
    """Devuelve (fecha_inicio, fecha_fin) que cubre todo lo mencionado, o None si no hay fechas."""
    text = _normalize(text)
    ranges: list[Range] = []

    for y, m, d in _ISO.findall(text):
        _add_day(ranges, int(y), int(m), int(d))
    text = _ISO.sub(" ", text)

    for d, m, y in _NUMERIC.findall(text):
        _add_day(ranges, int(y) if y else None, int(m), int(d), today)
    text = _NUMERIC.sub(" ", text)

    ranges += _spanish_dates(text, today)

    if _PREVIOUS_MONTH.search(text):
        last_of_previous = today.replace(day=1) - timedelta(days=1)
        ranges.append((last_of_previous.replace(day=1), last_of_previous))
    elif not ranges and _CURRENT_MONTH.search(text):
        ranges.append((today.replace(day=1), today))

    if not ranges:
        return None
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _spanish_dates(text: str, today: date) -> list[Range]:
    """Días seguidos de un mes (los días sin mes toman el siguiente mes mencionado);
    un mes sin días equivale al mes completo."""
    result: list[Range] = []
    pending_days: list[int] = []
    # Rangos del último mes procesado y cómo se construyeron, por si sigue un año explícito.
    last: list[tuple[Range, Optional[int], int]] = []  # (rango, día o None si mes completo, mes)

    for match in _TOKEN.finditer(text):
        year, day, month = match.groups()
        if day:
            pending_days.append(int(day))
        elif month:
            m = _MONTHS[month]
            last = []
            if pending_days:
                for d in pending_days:
                    if dt := _make_day(None, m, d, today):
                        last.append(((dt, dt), d, m))
            else:
                last.append((_month_range(None, m, today), None, m))
            result += [r for r, _, _ in last]
            pending_days = []
        elif year and last:
            # "12 de septiembre de 2026" / "agosto de 2025": reemplaza el año asumido
            for r, d, m in last:
                result.remove(r)
                if d is None:
                    result.append(_month_range(int(year), m, today))
                elif dt := _make_day(int(year), m, d):
                    result.append((dt, dt))
            last = []
    return result


def _month_range(year: Optional[int], month: int, today: date) -> Range:
    if year is None:
        year = today.year if month <= today.month else today.year - 1
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _add_day(ranges: list[Range], year: Optional[int], month: int, day: int, today: Optional[date] = None) -> None:
    if dt := _make_day(year, month, day, today):
        ranges.append((dt, dt))


def _make_day(year: Optional[int], month: int, day: int, today: Optional[date] = None) -> Optional[date]:
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


# Expresiones relativas → periodo (se evalúan en este orden)
_RELATIVE_PERIODS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bultim[oa]s? 24 horas\b|\bultimo dia\b"), "ultimas_24_horas"),
    (re.compile(r"\bultim[oa]s? 7 dias\b|\bultima semana\b|\besta semana\b|\bsemana pasada\b"), "ultimos_7_dias"),
    (re.compile(r"\bultim[oa]s? 30 dias\b|\bultimo mes\b"), "ultimos_30_dias"),
    (_PREVIOUS_MONTH, "mes_anterior"),
    (_CURRENT_MONTH, "este_mes"),
    (re.compile(r"\bhoy\b"), "hoy"),
    (re.compile(r"\bayer\b"), "ayer"),
]


def infer_relative_period(text: str) -> Optional[str]:
    """Periodo relativo mencionado en la pregunta ('últimos 7 días', 'ayer', 'mes pasado'…), o None."""
    text = _normalize(text)
    for pattern, period in _RELATIVE_PERIODS:
        if pattern.search(text):
            return period
    return None


_MONTH_NAMES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip


def format_date_es(d: date) -> str:
    """date(2026, 9, 18) → '18 de setiembre de 2026' (nombre de mes usado en Perú)."""
    return f"{d.day} de {_MONTH_NAMES[d.month - 1]} de {d.year}"


def format_month_es(d: date) -> str:
    """date(2026, 9, 1) → 'setiembre de 2026'."""
    return f"{_MONTH_NAMES[d.month - 1]} de {d.year}"
