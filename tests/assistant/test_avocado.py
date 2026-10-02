import pytest

from app.assistant.domain.avocado import Summary, evaluate_combined, evaluate_sensor, phenological_stage, vapor_pressure_deficit


def test_extreme_heat_alerts_with_one_short_recommendation():
    [alert] = evaluate_sensor("temperatura_ambiente", Summary(23.8, 17.0, 35.6))
    assert alert == (
        "Máxima de 35.6 °C: calor extremo (sobre 35 °C), riesgo de caída de flores y frutos. "
        "Recomendación: regar en horas frescas sin encharcar."
    )


def test_temperature_above_normal_alerts():
    [alert] = evaluate_sensor("temperatura_ambiente", Summary(24.0, 18.0, 31.9))
    assert alert.startswith("Máxima de 31.9 °C: sobre 30 °C, estrés por calor.")


def test_frost_alerts():
    [alert] = evaluate_sensor("temperatura_ambiente", Summary(9.0, 1.5, 18.0))
    assert alert.startswith("Mínima de 1.5 °C: riesgo de helada.")


@pytest.mark.parametrize(
    "sensor, summary",
    [
        ("temperatura_ambiente", Summary(22.0, 14.4, 28.0)),  # normal (14.4 °C de noche no es alerta)
        ("humedad_ambiente", Summary(74.0, 45.4, 98.5)),  # aire seco puntual: no es alerta por sí solo
        ("temperatura_suelo", Summary(24.0, 12.0, 29.0)),
        ("humedad_suelo", Summary(43.8, 0.0, 78.1)),  # algo húmedo, no encharcado
        ("ph_suelo", Summary(7.2, 6.9, 7.5)),  # algo alto, no grave
        ("presion_atmosferica", Summary(999.0, 988.0, 1005.0)),
    ],
)
def test_normal_or_mild_values_give_no_recommendation(sensor, summary):
    assert evaluate_sensor(sensor, summary) == []


def test_alkaline_ph_alerts():
    [alert] = evaluate_sensor("ph_suelo", Summary(8.02, 7.7, 8.3))
    assert alert.startswith("pH promedio de 8.02: muy alcalino (óptimo 5.5–6.5)")
    assert "quelatos de hierro" in alert


def test_soil_moisture_extremes_alert():
    assert "suelo seco" in evaluate_sensor("humedad_suelo", Summary(6.4, 0.0, 17.6))[0]
    assert "Phytophthora" in evaluate_sensor("humedad_suelo", Summary(55.0, 40.0, 80.0))[0]


def test_single_reading_wording():
    [alert] = evaluate_sensor("ph_suelo", Summary(7.7, 7.7, 7.7), single_reading=True)
    assert alert.startswith("pH de 7.7: muy alcalino")


def test_combined_heat_and_dry_air():
    [alert] = evaluate_combined({"temperatura_ambiente": Summary(24.0, 15.0, 35.6), "humedad_ambiente": Summary(74.0, 45.4, 98.5)})
    assert alert.startswith("Calor con aire seco (DPV máximo aprox. 3.17 kPa)")
    assert evaluate_combined({"temperatura_ambiente": Summary(21.0, 15.0, 26.0), "humedad_ambiente": Summary(75.0, 60.0, 95.0)}) == []


def test_vapor_pressure_deficit_is_data():
    assert vapor_pressure_deficit(Summary(24.0, 15.0, 35.6), Summary(74.0, 45.4, 98.5)) == (
        "DPV medio aprox. 0.78 kPa; DPV máximo aprox. 3.17 kPa (máxima de temperatura con mínima de humedad)."
    )
    assert vapor_pressure_deficit(None, Summary(74.0, 45.4, 98.5)) == ""


def test_phenology_for_september():
    assert phenological_stage(9) == "floración y cuaje (referencial para la costa peruana)"
