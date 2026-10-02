from datetime import date

import pytest

from app.assistant.domain.dates import extract_date_range

TODAY = date(2026, 9, 19)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("¿Cuál fue la temperatura máxima el 17 de septiembre?", (date(2026, 9, 17), date(2026, 9, 17))),
        ("¿Cuál fue la temperatura mínima entre el 10 y el 18 de septiembre?", (date(2026, 9, 10), date(2026, 9, 18))),
        ("¿Cómo evolucionó la humedad del suelo del 10 al 18 de septiembre?", (date(2026, 9, 10), date(2026, 9, 18))),
        ("¿Qué día hizo más calor, el 12 o el 13 de septiembre?", (date(2026, 9, 12), date(2026, 9, 13))),
        ("pH del 4 al 18 de SETIEMBRE", (date(2026, 9, 4), date(2026, 9, 18))),
        ("entre el 30 de agosto y el 5 de septiembre", (date(2026, 8, 30), date(2026, 9, 5))),
        ("el 12 de septiembre de 2025", (date(2025, 9, 12), date(2025, 9, 12))),
        ("datos del 12/09", (date(2026, 9, 12), date(2026, 9, 12))),
        ("del 10/09/2026 al 15/09/2026", (date(2026, 9, 10), date(2026, 9, 15))),
        ("rango 2026-09-10 a 2026-09-12", (date(2026, 9, 10), date(2026, 9, 12))),
        # Sin año y aún no ocurrió este año → año anterior
        ("¿qué pasó el 25 de diciembre?", (date(2025, 12, 25), date(2025, 12, 25))),
        # Meses completos y expresiones relativas al mes
        ("¿Qué día de septiembre hizo más calor?", (date(2026, 9, 1), date(2026, 9, 30))),
        ("reporte de agosto de 2025", (date(2025, 8, 1), date(2025, 8, 31))),
        ("¿Qué día del mes hubo mayor temperatura?", (date(2026, 9, 1), date(2026, 9, 19))),
        ("Dame un reporte de este mes", (date(2026, 9, 1), date(2026, 9, 19))),
        ("¿cuál fue el día más frío del mes pasado?", (date(2026, 8, 1), date(2026, 8, 31))),
        ("en noviembre", (date(2025, 11, 1), date(2025, 11, 30))),  # aún no llega → año anterior
        # Días concretos + "del mes" → mandan los días
        ("el 12 de septiembre, ¿qué día del mes fue?", (date(2026, 9, 12), date(2026, 9, 12))),
    ],
)
def test_extracts_ranges(text, expected):
    assert extract_date_range(text, TODAY) == expected


@pytest.mark.parametrize(
    "text",
    ["¿Cómo está el clima ahora?", "promedio de los últimos 7 días", "¿temperatura de ayer?", "el 31 de febrero"],
)
def test_no_dates(text):
    assert extract_date_range(text, TODAY) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("¿Cuál fue la humedad ambiente más alta de los últimos 7 días?", "ultimos_7_dias"),
        ("¿Qué día de la última semana tuvo la temperatura más baja?", "ultimos_7_dias"),
        ("promedio de las últimas 24 horas", "ultimas_24_horas"),
        ("en el último mes", "ultimos_30_dias"),
        ("¿Cuál fue la temperatura máxima del mes pasado?", "mes_anterior"),
        ("¿Qué día del mes hubo mayor temperatura?", "este_mes"),
        ("¿máxima de hoy?", "hoy"),
        ("¿y ayer?", "ayer"),
        ("anteayer", None),
        ("¿Cómo está el clima?", None),
    ],
)
def test_infer_relative_period(text, expected):
    from app.assistant.domain.dates import infer_relative_period

    assert infer_relative_period(text) == expected
