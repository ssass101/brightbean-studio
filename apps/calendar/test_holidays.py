"""Pruebas de las fechas especiales de Argentina (feriados, efemérides, comerciales)."""

from datetime import date

import pytest

from apps.calendar.holidays import easter_sunday, get_holidays_for_range, get_upcoming


def _names(day: date) -> list[str]:
    return [h["name"] for h in get_holidays_for_range(day, day).get(day.isoformat(), [])]


@pytest.mark.parametrize("year,expected", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))])
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_moving_commercial_dates_2026():
    assert "Día de la Madre" in _names(date(2026, 10, 18))  # 3.er domingo de octubre
    assert "Día del Padre" in _names(date(2026, 6, 21))  # 3.er domingo de junio
    assert "Día de las Infancias" in _names(date(2026, 8, 16))  # 3.er domingo de agosto
    assert "Black Friday" in _names(date(2026, 11, 27))
    assert "Cyber Monday" in _names(date(2026, 11, 30))
    assert "Día del Community Manager" in _names(date(2026, 9, 28))  # último lunes de septiembre


def test_easter_based_holidays_2026():
    assert "Carnaval (lunes)" in _names(date(2026, 2, 16))
    assert "Carnaval (martes)" in _names(date(2026, 2, 17))
    assert "Viernes Santo" in _names(date(2026, 4, 3))


def test_movable_holidays_follow_ley_27399():
    # 20/11/2026 es viernes -> lunes 23. 17/6/2026 es miércoles -> lunes 15.
    assert "Día de la Soberanía Nacional" in _names(date(2026, 11, 23))
    assert "Día de la Soberanía Nacional" not in _names(date(2026, 11, 20))
    assert "Paso a la Inmortalidad del Gral. Güemes" in _names(date(2026, 6, 15))
    # 17/8/2026 es lunes y 12/10/2026 es lunes: no se mueven.
    assert "Paso a la Inmortalidad del Gral. San Martín" in _names(date(2026, 8, 17))
    assert "Día del Respeto a la Diversidad Cultural" in _names(date(2026, 10, 12))


def test_fixed_holidays_do_not_move():
    assert "Día de la Independencia" in _names(date(2026, 7, 9))
    assert "Navidad" in _names(date(2026, 12, 25))


def test_range_spanning_two_years():
    found = get_holidays_for_range(date(2026, 12, 30), date(2027, 1, 2))
    assert set(found) == {"2026-12-31", "2027-01-01"}


def test_upcoming_is_ordered_and_limited():
    upcoming = get_upcoming(date(2026, 11, 18), limit=4)
    assert len(upcoming) == 4
    assert [u["date"] for u in upcoming] == sorted(u["date"] for u in upcoming)
    assert upcoming[0]["name"] == "Día de la Soberanía Nacional"
    assert upcoming[0]["days_left"] == 5
