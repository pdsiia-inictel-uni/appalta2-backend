"""Traduce periodos en lenguaje natural a rangos de tiempo exactos.

El modelo solo elige un periodo de una lista cerrada; las fechas las calcula
este código. Así se evita el error más común de los modelos pequeños.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

MAX_RANGE_DAYS = 92


class Period(str, Enum):
    HOY = "hoy"
    AYER = "ayer"
    ULTIMAS_24_HORAS = "ultimas_24_horas"
    ULTIMOS_7_DIAS = "ultimos_7_dias"
    ULTIMOS_30_DIAS = "ultimos_30_dias"
    RANGO = "rango"


class PeriodError(ValueError):
    """Periodo inválido; el mensaje se devuelve al modelo para que corrija."""


@dataclass(frozen=True)
class TimeRange:
    """Rango semiabierto [start, end) en la zona horaria local."""

    start: datetime
    end: datetime

    @property
    def start_ts(self) -> int:
        return int(self.start.timestamp())

    @property
    def end_ts(self) -> int:
        return int(self.end.timestamp())

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400


def resolve_period(
    period: Period,
    now: datetime,
    start_date: date | None = None,
    end_date: date | None = None,
) -> TimeRange:
    """`now` debe ser un datetime con zona horaria (hora local de la estación)."""
    if now.tzinfo is None:
        raise ValueError("now debe incluir zona horaria")

    today = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)

    match period:
        case Period.HOY:
            return TimeRange(today, now)
        case Period.AYER:
            return TimeRange(today - timedelta(days=1), today)
        case Period.ULTIMAS_24_HORAS:
            return TimeRange(now - timedelta(hours=24), now)
        case Period.ULTIMOS_7_DIAS:
            return TimeRange(now - timedelta(days=7), now)
        case Period.ULTIMOS_30_DIAS:
            return TimeRange(now - timedelta(days=30), now)
        case Period.RANGO:
            return _custom_range(now, start_date, end_date)
    raise PeriodError(f"Periodo no soportado: {period}")


def _custom_range(now: datetime, start_date: date | None, end_date: date | None) -> TimeRange:
    if start_date is None:
        raise PeriodError("Para periodo 'rango' indica fecha_inicio (YYYY-MM-DD).")
    end_date = end_date or start_date
    if end_date < start_date:
        raise PeriodError("fecha_fin no puede ser anterior a fecha_inicio.")

    start = datetime.combine(start_date, time.min, tzinfo=now.tzinfo)
    end = min(datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=now.tzinfo), now)
    if start >= now:
        raise PeriodError("La fecha solicitada está en el futuro; no hay datos.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise PeriodError(f"El rango máximo es de {MAX_RANGE_DAYS} días.")
    return TimeRange(start, end)
