import zoneinfo
from datetime import datetime

from django.http import QueryDict
from django.test import SimpleTestCase

from apps.calendar.series import parse_series_config, series_dates

TZ = zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")


class SeriesDatesTests(SimpleTestCase):
    def test_three_weeks_mon_wed_fri_is_nine_publications(self):
        first = datetime(2026, 11, 23, 8, 0, tzinfo=TZ)  # Monday
        copies = series_dates(first, {"weekdays": [0, 2, 4], "count": 3, "unit": "weeks"}, TZ)
        self.assertEqual(len(copies) + 1, 9)
        self.assertTrue(all(c.hour == 8 and c.minute == 0 for c in copies))
        self.assertEqual(copies[0].date().isoformat(), "2026-11-25")

    def test_months_window(self):
        first = datetime(2026, 11, 23, 8, 0, tzinfo=TZ)
        copies = series_dates(first, {"weekdays": [6], "count": 1, "unit": "months"}, TZ)
        self.assertEqual([c.date().isoformat() for c in copies], ["2026-11-29", "2026-12-06", "2026-12-13", "2026-12-20"])

    def test_parse_requires_enabled_days_and_count(self):
        ok = QueryDict("repeat_enabled=1&repeat_weekdays=0&repeat_weekdays=4&repeat_count=3&repeat_unit=weeks")
        self.assertEqual(parse_series_config(ok), {"weekdays": [0, 4], "count": 3, "unit": "weeks"})
        self.assertIsNone(parse_series_config(QueryDict("repeat_count=3")))
        self.assertIsNone(parse_series_config(QueryDict("repeat_enabled=1&repeat_count=3")))
