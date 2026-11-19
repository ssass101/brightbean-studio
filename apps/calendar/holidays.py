"""Fechas especiales para Argentina: feriados, efemérides y fechas comerciales.

Carga ``data/holidays.json`` y calcula las fechas de cada año. Se usa en la
capa de fechas del calendario y en el bloque "Próximas fechas" del inicio.

Cada entrada del JSON admite una de estas formas de definir la fecha:

- Fija:               ``{"month": 5, "day": 25}``
- Día de la semana:   ``{"month": 10, "nth": 3, "weekday": 6}`` (3.er domingo de
  octubre; ``weekday`` 0 = lunes ... 6 = domingo; ``nth`` -1 = el último).
  Opcional ``"offset_days"`` suma días a esa fecha (Black Friday = 4.º jueves + 1).
- Relativa a Pascua:  ``{"easter_offset": -2}`` (Viernes Santo).

Opcionales: ``"movable": true`` aplica la regla de feriados trasladables de la
Ley 27.399 (martes/miércoles pasan al lunes anterior; jueves/viernes al lunes
siguiente) y ``"note"`` agrega un detalle que se muestra al pasar el mouse.

Importante: no incluye los "días puente" ni los cambios que el Gobierno decrete
caso por caso; los feriados oficiales conviene confirmarlos cada año.

Tipos: ``holiday`` (feriado/día no laborable), ``commercial`` (fecha de venta) y
``awareness`` (efeméride o día mundial).
"""

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load_holidays():
    """Carga holidays.json una sola vez."""
    data_path = Path(__file__).parent / "data" / "holidays.json"
    with open(data_path, encoding="utf-8") as f:
        return json.load(f)


def easter_sunday(year: int) -> date:
    """Domingo de Pascua (calendario gregoriano, algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, nth: int, weekday: int) -> date:
    """El n-ésimo ``weekday`` del mes; ``nth`` = -1 devuelve el último."""
    if nth > 0:
        first = date(year, month, 1)
        shift = (weekday - first.weekday()) % 7
        return first + timedelta(days=shift + 7 * (nth - 1))
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _apply_movable(d: date) -> date:
    """Regla de feriados trasladables (Ley 27.399)."""
    wd = d.weekday()
    if wd in (1, 2):  # martes, miércoles -> lunes anterior
        return d - timedelta(days=wd)
    if wd in (3, 4):  # jueves, viernes -> lunes siguiente
        return d + timedelta(days=7 - wd)
    return d


def resolve_date(entry: dict, year: int) -> date | None:
    """Fecha que tiene ``entry`` en ``year`` (None si no existe ese año)."""
    try:
        if "easter_offset" in entry:
            return easter_sunday(year) + timedelta(days=entry["easter_offset"])
        if "nth" in entry:
            d = _nth_weekday(year, entry["month"], entry["nth"], entry["weekday"])
            return d + timedelta(days=entry.get("offset_days", 0))
        d = date(year, entry["month"], entry["day"])
        return _apply_movable(d) if entry.get("movable") else d
    except ValueError:
        return None


def get_holidays_for_range(start_date, end_date):
    """Fechas especiales dentro del rango.

    Devuelve un dict ``{"AAAA-MM-DD": [entrada, ...]}``; puede haber varias el
    mismo día. Cada entrada incluye ``name``, ``emoji``, ``type`` y ``note``.
    """
    result: dict[str, list[dict]] = {}
    for year in range(start_date.year, end_date.year + 1):
        for entry in _load_holidays():
            d = resolve_date(entry, year)
            if d is None or not (start_date <= d <= end_date):
                continue
            result.setdefault(d.isoformat(), []).append(
                {
                    "name": entry["name"],
                    "emoji": entry.get("emoji", ""),
                    "type": entry.get("type", "awareness"),
                    "note": entry.get("note", ""),
                }
            )
    return result


def get_upcoming(from_date: date, limit: int = 6, days: int = 60) -> list[dict]:
    """Próximas fechas especiales desde ``from_date`` (inclusive), en orden."""
    found = get_holidays_for_range(from_date, from_date + timedelta(days=days))
    upcoming = []
    for iso in sorted(found):
        d = date.fromisoformat(iso)
        for item in found[iso]:
            upcoming.append({**item, "date": d, "days_left": (d - from_date).days})
    return upcoming[:limit]
