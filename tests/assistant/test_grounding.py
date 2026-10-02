import pytest

from app.assistant.chat.grounding import find_unsupported_values

# Resultado real de la herramienta para "¿máxima de hoy?" sin datos (EST002, 19/09)
NO_DATA_TODAY = {
    "sensor": "Temperatura ambiente",
    "sin_datos": True,
    "ultimo_registro_disponible": {"valor": 31.9, "unidad": "°C", "fecha": "2026-09-18 13:56"},
}
STATS = {
    "promedio": 1003.7,
    "maximo": {"valor": 1004.9, "fecha": "2026-09-18 08:44"},
    "minimo": {"valor": 7.98, "fecha": "2026-09-15 11:25"},
    "tendencia": "descendente (bajó): de 8.2 a 7.78 pH (promedio diario)",
    "resumen_diario": ["2026-09-12: prom 24.0, min 17.1, max 35.6"],
}


def test_detects_invented_value():
    answer = "Según el último registro disponible, la temperatura ambiente fue de 18.5°C el 2026-09-18 a las 13:56."
    assert find_unsupported_values(answer, [NO_DATA_TODAY]) == ["18.5 °C"]


def test_accepts_real_value():
    answer = "No hay datos de hoy. El último registro fue 31.9 °C el 18 de septiembre a las 13:56."
    assert find_unsupported_values(answer, [NO_DATA_TODAY]) == []


@pytest.mark.parametrize(
    "answer",
    [
        "La presión promedio fue de 1003.7 hPa.",
        "La presión promedio fue de 1.003,7 hPa.",
        "La máxima fue 35,6 °C.",
        "El pH promedio fue 7.98 pH.",
        "El pH del suelo fue de 8.0.",          # 7.98 redondeado
        "Bajó de 8.2 a 7.78 pH.",
        "La máxima del día 12 fue de 35.6°C y la mínima 17.1 °C.",
    ],
)
def test_accepts_values_present_in_tool_outputs(answer):
    assert find_unsupported_values(answer, [STATS]) == []


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("La presión llegó a 1010.2 hPa.", ["1010.2 hPa"]),
        ("El pH del suelo fue de 6.5.", ["6.5 pH"]),
        ("La humedad fue del 45 %.", ["45 %"]),
    ],
)
def test_rejects_values_not_in_outputs(answer, expected):
    assert find_unsupported_values(answer, [STATS]) == expected


def test_ignores_numbers_without_units():
    assert find_unsupported_values("Hubo 137 lecturas el 13 de septiembre a las 05:32.", [STATS]) == []
