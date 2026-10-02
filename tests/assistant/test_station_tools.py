from app.assistant.tools.station_tools import TOOL_DEFINITIONS, StationToolbox
from app.assistant.data.repository import Reading
from tests.assistant.conftest import LIMA, NOW, STATIONS, FakeRepository


def make_toolbox(repo, code="EST001-PALTAS"):
    return StationToolbox(repo, STATIONS[code], "America/Lima", clock=lambda: NOW)


def test_no_tool_accepts_a_station_parameter():
    for tool in TOOL_DEFINITIONS:
        props = tool["function"]["parameters"]["properties"]
        assert not any("estacion" in p or "station" in p for p in props)


def test_invented_station_argument_is_ignored(repo):
    result = make_toolbox(repo).execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "ayer", "estacion": "EST002-PALTAS"}
    )
    assert "error" not in result
    assert result["estacion"] == "ESTACIÓN 1"
    assert {station_id for _, station_id in repo.calls} == {1}


def test_stats_are_rounded_and_labeled(repo):
    result = make_toolbox(repo).execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "ayer"})
    assert result["promedio"] == 24.5
    assert result["maximo"]["valor"] == 28.0
    assert result["unidad"] == "°C"
    assert result["desde"] == "2026-09-24 00:00"
    assert "resumen_diario" not in result  # un solo día


def test_multi_day_period_includes_daily_summary(repo):
    result = make_toolbox(repo).execute("estadisticas_sensor", {"sensor": "humedad_suelo", "periodo": "ultimos_7_dias"})
    assert result["resumen_diario"][0].startswith("2026-09-18: prom")


def test_tolerates_sloppy_arguments(repo):
    result = make_toolbox(repo).execute(
        "estadisticas_sensor", {"sensor": " PH_SUELO ", "periodo": "Hoy", "fecha_inicio": "", "fecha_fin": ""}
    )
    assert "error" not in result


def test_no_data_reports_last_available_record():
    result = make_toolbox(FakeRepository(has_data=False)).execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "hoy"}
    )
    assert result["sin_datos"] is True
    assert result["ultimo_registro_disponible"] == {
        "valor": 31.9, "unidad": "°C", "fecha": "2026-09-18 13:56", "nota": "fuera del periodo consultado"
    }


def test_invalid_sensor_returns_error_not_exception(repo):
    result = make_toolbox(repo).execute("estadisticas_sensor", {"sensor": "viento", "periodo": "hoy"})
    assert "error" in result and "sensor" in result["error"]


def test_invalid_range_returns_error(repo):
    result = make_toolbox(repo).execute("estadisticas_sensor", {"sensor": "ph_suelo", "periodo": "rango"})
    assert "fecha_inicio" in result["error"]


def test_unknown_tool(repo):
    assert "error" in make_toolbox(repo).execute("borrar_datos", {})


def test_latest_readings_uses_bound_station(repo):
    result = make_toolbox(repo, "EST002-PALTAS").execute("lecturas_actuales", {})
    assert len(result["lecturas"]) == 6
    assert repo.calls == [("latest_readings", 2)]


def test_repository_failure_is_contained():
    class BrokenRepo(FakeRepository):
        def sensor_stats(self, *args):
            raise RuntimeError("db down")

    result = make_toolbox(BrokenRepo()).execute("estadisticas_sensor", {"sensor": "ph_suelo", "periodo": "hoy"})
    assert result == {"error": "No se pudo consultar la base de datos en este momento."}


def test_discarded_readings_are_reported():
    result = make_toolbox(FakeRepository(discarded=3)).execute(
        "estadisticas_sensor", {"sensor": "temperatura_suelo", "periodo": "ultimos_7_dias"}
    )
    assert "Se descartaron 3 lecturas" in result["avisos"][0]


def test_zero_soil_moisture_is_flagged():
    result = make_toolbox(FakeRepository(zeros=4)).execute(
        "estadisticas_sensor", {"sensor": "humedad_suelo", "periodo": "ayer"}
    )
    assert "4 de 10 lecturas marcan exactamente 0 %" in result["avisos"][0]


def test_zero_is_not_flagged_for_other_sensors():
    result = make_toolbox(FakeRepository(zeros=4)).execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "ayer"}
    )
    assert "avisos" not in result


def test_only_invalid_readings_in_period_is_no_data_with_warning():
    result = make_toolbox(FakeRepository(has_data=False, discarded=2)).execute(
        "estadisticas_sensor", {"sensor": "temperatura_suelo", "periodo": "hoy"}
    )
    assert result["sin_datos"] is True
    assert "Se descartaron 2 lecturas" in result["avisos"][0]


def test_latest_zero_soil_moisture_is_flagged():
    result = make_toolbox(FakeRepository(latest_value=0.0)).execute("lecturas_actuales", {})
    assert result["avisos"] == ["Humedad del suelo marca 0 %; puede indicar que el sensor está desconectado o fuera del suelo."]


def test_sensor_valid_ranges():
    from app.assistant.domain.sensors import SENSORS

    assert not SENSORS["temperatura_suelo"].is_valid(-127)
    assert SENSORS["temperatura_suelo"].is_valid(22.5)
    assert SENSORS["humedad_suelo"].is_valid(0)


def test_rango_without_dates_uses_dates_from_question(repo):
    toolbox = StationToolbox(
        repo, STATIONS["EST001-PALTAS"], "America/Lima", clock=lambda: NOW,
        question="¿Cuál fue la temperatura mínima entre el 10 y el 18 de septiembre?",
    )
    result = toolbox.execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "rango"})
    assert result["desde"] == "2026-09-10 00:00"
    assert result["hasta"] == "2026-09-18 23:59"


def test_question_dates_take_precedence_over_model(repo):
    # Pregunta "septiembre" y el modelo solo puso el día 1 → se usa el mes completo
    toolbox = StationToolbox(
        repo, STATIONS["EST001-PALTAS"], "America/Lima", clock=lambda: NOW, question="¿Qué día de septiembre hizo más calor?"
    )
    result = toolbox.execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "rango", "fecha_inicio": "2026-09-01"}
    )
    assert result["desde"] == "2026-09-01 00:00" and result["hasta"] == "2026-09-25 15:30"


def test_model_dates_used_when_question_has_none(repo):
    toolbox = StationToolbox(repo, STATIONS["EST001-PALTAS"], "America/Lima", clock=lambda: NOW, question="¿y ese día?")
    result = toolbox.execute(
        "estadisticas_sensor", {"sensor": "ph_suelo", "periodo": "rango", "fecha_inicio": "2026-09-12"}
    )
    assert result["desde"] == "2026-09-12 00:00" and result["hasta"] == "2026-09-12 23:59"


def test_invalid_model_date_is_ignored(repo):
    toolbox = StationToolbox(
        repo, STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: NOW, question="¿Qué día del mes fue el más frío?"
    )
    result = toolbox.execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "rango", "fecha_inicio": "rango"}
    )
    assert "error" not in result and result["desde"] == "2026-09-01 00:00"


def test_monthly_report_includes_daily_ranking():
    from app.assistant.data.repository import DailyStats
    from datetime import date as d

    class MonthRepo(FakeRepository):
        def daily_stats(self, station_id, sensor, start_ts, end_ts, tz):
            return [DailyStats(d(2026, 9, 5), 25.0, 24.2, 27.5), DailyStats(d(2026, 9, 6), 25.3, 24.1, 28.7),
                    DailyStats(d(2026, 9, 13), 21.8, 14.4, 34.6)]  # fmt: skip

    result = make_toolbox(MonthRepo()).execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "este_mes"})
    assert result["dia_con_promedio_mas_alto"] == {"fecha": "2026-09-06", "promedio": 25.3}
    assert result["dia_con_promedio_mas_bajo"] == {"fecha": "2026-09-13", "promedio": 21.8}
    assert result["dias_con_datos"] == 3


def test_definitions_include_current_year(repo):
    text = str(make_toolbox(repo).definitions)
    assert "usa 2026" in text


def test_trend_is_computed_by_code(repo):
    # FakeRepository: primer valor 22.0, último 25.0 → sube 3 °C (> umbral 0.5)
    result = make_toolbox(repo).execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "ayer"})
    assert result["tendencia"].startswith("ascendente (subió): de 22.0 a 25.0 °C")


def test_trend_stable_below_threshold():
    from app.assistant.domain.sensors import SENSORS
    from app.assistant.tools.station_tools import _trend

    assert _trend(8.20, 8.25, SENSORS["ph_suelo"], "promedio diario").startswith("estable")
    assert _trend(8.20, 7.78, SENSORS["ph_suelo"], "promedio diario").startswith("descendente (bajó)")


def test_relative_period_in_question_overrides_model_single_day(repo):
    toolbox = StationToolbox(
        repo, STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: NOW,
        question="¿Qué día de la última semana tuvo la temperatura más baja?",
    )
    result = toolbox.execute(
        "estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "rango", "fecha_inicio": "2026-09-12"}
    )
    assert result["periodo"] == "ultimos_7_dias" and result["desde"] == "2026-09-18 15:30"


def test_no_data_has_explicit_message():
    toolbox = StationToolbox(
        FakeRepository(has_data=False), STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: NOW,
        question="¿Cuál fue la temperatura máxima del mes pasado?",
    )
    result = toolbox.execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "rango"})
    assert result["mensaje"] == "No hay reporte de temperatura ambiente de agosto de 2026."
    assert result["respuesta_directa"] == (
        "No hay reporte de temperatura ambiente de agosto de 2026. "
        "El último registro disponible es del 18 de setiembre de 2026 a las 13:56: temperatura ambiente 31.9 °C."
    )
    assert result["ultimo_registro_disponible"]["nota"] == "fuera del periodo consultado"


def test_today_without_data_gives_direct_answer():
    toolbox = StationToolbox(FakeRepository(has_data=False), STATIONS["EST002-PALTAS"], "America/Lima", clock=lambda: NOW)
    result = toolbox.execute("estadisticas_sensor", {"sensor": "temperatura_ambiente", "periodo": "hoy"})
    assert result["respuesta_directa"] == (
        "No hay reporte de temperatura ambiente de hoy (25 de setiembre de 2026). "
        "El último registro disponible es del 18 de setiembre de 2026 a las 13:56: temperatura ambiente 31.9 °C."
    )


def test_stale_latest_readings_are_not_presented_as_current():
    from datetime import datetime as dt

    class StaleRepo(FakeRepository):
        def latest_readings(self, station_id, sensors):
            ts = int(dt(2026, 9, 18, 13, 56, tzinfo=LIMA).timestamp())
            return [Reading(s.db_code, v, ts) for s, v in zip(sensors, [31.9, 53.7, 1002.1, 32.5, 21.8, 7.7])]

    result = make_toolbox(StaleRepo(), "EST002-PALTAS").execute("lecturas_actuales", {})
    answer = result["respuesta_directa"]
    assert answer.startswith(
        "No hay reporte de hoy (25 de setiembre de 2026) en ESTACIÓN 2: la estación no envía datos desde hace "
        "7 días (conviene revisar su energía y conexión). El último registro disponible es del "
        "18 de setiembre de 2026 a las 13:56: temperatura ambiente 31.9 °C, humedad ambiente 53.7 %, "
        "presión atmosférica 1002.1 hPa, temperatura del suelo 32.5 °C, humedad del suelo 21.8 %, pH del suelo 7.7."
    )
    # Solo alertas serias (calculadas por código): 31.9 °C, 32.5 °C en el suelo y pH 7.7; 21.8 % es normal
    assert answer.endswith(
        "\n\nAlertas para la palta:\n"
        "• Temperatura de 31.9 °C: sobre 30 °C, estrés por calor. Recomendación: no dejar secar el suelo en las horas de calor.\n"
        "• Temperatura de 32.5 °C en el suelo: sobre 30 °C, estrés de raíces. Recomendación: cobertura orgánica (mulch) sobre el suelo.\n"
        "• pH de 7.7: muy alcalino (óptimo 5.5–6.5), causa clorosis por falta de hierro y zinc. Recomendación: acidificar el agua de riego y aplicar quelatos de hierro."
    )


def test_readings_from_today_have_no_direct_answer(repo):
    # FakeRepository devuelve lecturas de hace 10 minutos: el modelo redacta normalmente
    assert "respuesta_directa" not in make_toolbox(repo).execute("lecturas_actuales", {})
