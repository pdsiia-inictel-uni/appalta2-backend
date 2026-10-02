import json
from pathlib import Path

import pytest

from app.assistant.chat.service import ChatResult, ToolExecution
from scripts.assistant.run_eval import check, contains_number


@pytest.mark.parametrize(
    "text,value,expected",
    [
        ("La máxima fue 35.6 °C", "35.6", True),
        ("La máxima fue 35,6 °C", "35.6", True),
        ("Promedio de 1.003,7 hPa", "1003.7", True),
        ("Promedio de 1003.7 hPa", "1003.7", True),
        ("Fue de 22 °C", "22.0", True),
        ("Fue de 114.45", "14.4", False),
        ("Fue de 14.45", "14.4", False),
        ("Fue de 35.6.", "35.6", True),
    ],
)
def test_contains_number(text, value, expected):
    assert contains_number(text, value) is expected


def result(answer, *tools, output=None):
    return ChatResult(answer, "EST002-PALTAS", "s", [ToolExecution(n, a, True, output or {}) for n, a in tools])


def test_check_passes_correct_answer():
    case = {
        "expect_tool": "estadisticas_sensor",
        "expect_args": {"sensor": "temperatura_ambiente", "periodo": "ayer"},
        "expect_values": ["33.3"],
    }
    r = result(
        "Ayer la máxima fue 33,3 °C a las 12:34.",
        ("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "ayer"}),
        output={"maximo": {"valor": 33.3, "fecha": "2026-09-18 12:34"}},
    )
    assert check(case, r) == []


def test_check_detects_wrong_args_and_missing_value():
    case = {"expect_tool": "estadisticas_sensor", "expect_args": {"periodo": "ayer"}, "expect_values": ["33.3"]}
    r = result("Fue 29 °C.", ("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "hoy"}))
    assert check(case, r) == [
        "periodo=hoy (esperado ayer)",
        "falta el valor 33.3",
        "valores inventados (no están en los datos): ['29 °C']",
    ]


def test_check_refusal_and_forbidden_text():
    case = {"expect_refusal": True, "expect_no_tool": True, "forbid_text": ["EST001"]}
    assert check(case, result("Solo puedo informar sobre ESTACIÓN 2.")) == []
    bad = check(case, result("EST001 tiene 20 °C.", ("lecturas_actuales", {})))
    assert "no rechaza / no aclara su alcance" in bad
    assert "contiene texto prohibido 'EST001'" in bad


def test_cases_file_is_consistent():
    cases = json.loads(Path("scripts/assistant/cases.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    for c in cases:
        assert c["station"].startswith("EST") and c["question"] and c["category"]


def test_check_flags_invented_values():
    r = ChatResult(
        "El último registro fue 18.5 °C.", "EST002-PALTAS", "s",
        [ToolExecution("estadisticas_sensor", {}, True, {"ultimo_registro_disponible": {"valor": 31.9}})],
    )
    assert check({}, r) == ["valores inventados (no están en los datos): ['18.5 °C']"]


def test_rango_equivalent_to_expected_period_is_accepted():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 9, 19, 12, 0, tzinfo=ZoneInfo("America/Lima"))
    case = {"expect_tool": "estadisticas_sensor", "expect_args": {"periodo": "ayer"}}
    same_day = result("", ("estadisticas_sensor", {"periodo": "rango", "fecha_inicio": "2026-09-18"}))
    other_day = result("", ("estadisticas_sensor", {"periodo": "rango", "fecha_inicio": "2026-09-17"}))
    assert check(case, same_day, now) == []
    assert check(case, other_day, now) == ["periodo=rango (esperado ayer)"]
