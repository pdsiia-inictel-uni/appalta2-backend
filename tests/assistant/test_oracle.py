from datetime import date, datetime

from scripts.assistant.oracle import Oracle, Reading, _daily_avgs, _fmt, day_keywords
from app.assistant.domain.sensors import SENSORS
from tests.assistant.conftest import LIMA


def test_day_keywords_cover_spanish_and_peruvian_month_names():
    assert day_keywords(date(2026, 9, 12)) == ["12 de septiembre", "2026-09-12", "12/09", "12/9", "12 de setiembre"]


def test_values_are_formatted_like_the_assistant():
    assert _fmt(8.3, SENSORS["ph_suelo"]) == "8.3"
    assert _fmt(7.9017, SENSORS["ph_suelo"]) == "7.9"
    assert _fmt(22.0, SENSORS["temperatura_ambiente"]) == "22.0"


class FakeOracle(Oracle):
    """Oráculo con lecturas en memoria (sin BD)."""

    def __init__(self, readings):
        super().__init__(engine=None, tz=LIMA)
        self.data = readings

    def _readings(self, station, sensor, start, end):
        return [r for r in self.data if start <= r.ts < end]

    def _last(self, station, sensor, until):
        past = [r for r in self.data if r.ts <= until]
        return past[-1] if past else None


def ts(d, h, m=0):
    return int(datetime(2026, 9, d, h, m, tzinfo=LIMA).timestamp())


NOW = datetime(2026, 9, 25, 12, 0, tzinfo=LIMA)
DATA = [Reading(20.0, ts(17, 6)), Reading(31.5, ts(17, 13, 55)), Reading(18.0, ts(18, 5)), Reading(26.0, ts(18, 14))]
CASE = {"station": "EST002-PALTAS"}


def test_extremes_with_time_and_day():
    out = FakeOracle(DATA).expectations(
        {**CASE, "expect_db": {"sensor": "temperatura_ambiente", "from": "2026-09-17", "to": "2026-09-18",
                               "metrics": ["max", "max_time", "min_day"]}}, NOW)  # fmt: skip
    assert out["expect_values"] == ["31.5", "13:55"]
    assert "18 de setiembre" in out["expect_keywords_any"]


def test_empty_period_expects_no_data():
    out = FakeOracle(DATA).expectations({**CASE, "expect_db": {"sensor": "temperatura_ambiente", "period": "hoy", "metrics": ["max"]}}, NOW)
    assert out == {"expect_no_data": True}


def test_recent_window_without_data_is_anchored_to_last_record():
    # Hoy es 26/09 y la estación no envía desde el 18/09: "últimos 7 días" = hasta el último registro.
    out = FakeOracle(DATA).expectations(
        {**CASE, "expect_db": {"sensor": "temperatura_ambiente", "period": "ultimos_7_dias", "metrics": ["max"]}},
        datetime(2026, 9, 26, 12, 0, tzinfo=LIMA),
    )
    assert out == {"expect_values": ["31.5"]}


def test_trend_uses_daily_averages():
    out = FakeOracle(DATA).expectations(
        {**CASE, "expect_db": {"sensor": "temperatura_ambiente", "from": "2026-09-17", "to": "2026-09-18", "metrics": ["trend"]}}, NOW
    )
    assert out == {"expect_trend": "down"}  # 25.75 → 22.0 °C
    assert list(_daily_avgs(DATA, lambda t: datetime.fromtimestamp(t, LIMA)).values()) == [25.75, 22.0]
