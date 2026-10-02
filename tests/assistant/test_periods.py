from datetime import date, datetime, timezone

import pytest

from app.assistant.domain.periods import Period, PeriodError, resolve_period
from tests.assistant.conftest import LIMA, NOW


def test_hoy_starts_at_local_midnight():
    r = resolve_period(Period.HOY, NOW)
    assert r.start == datetime(2026, 9, 25, 0, 0, tzinfo=LIMA)
    assert r.end == NOW


def test_ayer_is_full_previous_day():
    r = resolve_period(Period.AYER, NOW)
    assert r.start == datetime(2026, 9, 24, tzinfo=LIMA)
    assert r.end == datetime(2026, 9, 25, tzinfo=LIMA)


def test_rango_includes_whole_end_day():
    r = resolve_period(Period.RANGO, NOW, date(2026, 9, 10), date(2026, 9, 15))
    assert r.start == datetime(2026, 9, 10, tzinfo=LIMA)
    assert r.end == datetime(2026, 9, 16, tzinfo=LIMA)


def test_rango_single_day_when_no_end_date():
    r = resolve_period(Period.RANGO, NOW, date(2026, 9, 12))
    assert r.days == 1


def test_rango_clamped_to_now():
    r = resolve_period(Period.RANGO, NOW, date(2026, 9, 25))
    assert r.end == NOW


@pytest.mark.parametrize(
    "start,end",
    [(None, None), (date(2026, 9, 15), date(2026, 9, 10)), (date(2026, 10, 1), None), (date(2026, 1, 1), date(2026, 9, 1))],
)
def test_rango_invalid(start, end):
    with pytest.raises(PeriodError):
        resolve_period(Period.RANGO, NOW, start, end)


def test_timestamps_are_utc_epoch():
    r = resolve_period(Period.AYER, NOW)
    # 2026-09-24 00:00 en Lima (UTC-5) = 05:00 UTC
    assert r.start_ts == int(datetime(2026, 9, 24, 5, 0, tzinfo=timezone.utc).timestamp())



def test_este_mes_starts_on_day_one():
    r = resolve_period(Period.ESTE_MES, NOW)
    assert r.start == datetime(2026, 9, 1, tzinfo=LIMA) and r.end == NOW


def test_mes_anterior_is_whole_previous_month():
    r = resolve_period(Period.MES_ANTERIOR, NOW)
    assert r.start == datetime(2026, 8, 1, tzinfo=LIMA)
    assert r.end == datetime(2026, 9, 1, tzinfo=LIMA)


def test_mes_anterior_in_january_goes_to_previous_year():
    r = resolve_period(Period.MES_ANTERIOR, datetime(2027, 1, 15, 10, 0, tzinfo=LIMA))
    assert r.start == datetime(2026, 12, 1, tzinfo=LIMA) and r.end == datetime(2027, 1, 1, tzinfo=LIMA)
