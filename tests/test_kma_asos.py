from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import patch

from engine import kma_asos as kma
from tests.test_psm_workspace_page import _project, _run


def _body(items, total=None, code="00"):
    return json.dumps({"response": {"header": {"resultCode": code, "resultMsg": "NORMAL_SERVICE"},
                                    "body": {"dataType": "JSON", "items": {"item": items} if items else "",
                                             "numOfRows": 400, "pageNo": 1, "totalCount": total or len(items)}}})


def _day(tm, max_ta, rhm, ws="2.0"):
    return {"stnId": "152", "tm": tm, "maxTa": str(max_ta), "avgRhm": str(rhm), "avgWs": ws}


class AsosTests(unittest.TestCase):
    def test_station_table_comes_from_the_guide(self):
        stations = kma.stations()
        self.assertEqual(len(stations), 95)
        self.assertEqual(stations["152"]["name"], "울산")
        self.assertEqual(stations["108"]["name"], "서울")

    def test_station_is_suggested_from_the_address(self):
        self.assertEqual(kma.suggest_station("울산광역시 남구 산업로 1"), "152")
        self.assertEqual(kma.suggest_station("전라남도 여수시 산단로"), "168")
        self.assertEqual(kma.suggest_station("어딘가 알 수 없는 곳"), "")

    def test_request_follows_the_open_api_guide_and_pages_through_the_period(self):
        seen = []
        pages = {1: [_day("2024-01-01", 5, 50)] * 2, 2: [_day("2024-01-03", 7, 60)]}

        def fake(url, params):
            seen.append((url, dict(params)))
            return 200, _body(pages[params["pageNo"]], total=3)
        with patch("engine.kma_asos._credential", return_value="KEY"):
            result = kma.fetch_daily("152", date(2024, 1, 1), date(2024, 1, 3), get=fake)
        self.assertEqual(result.status, "OK")
        self.assertEqual(len(result.rows), 3)
        url, params = seen[0]
        self.assertTrue(url.endswith("/AsosDalyInfoService/getWthrDataList"))
        for name, value in (("dataCd", "ASOS"), ("dateCd", "DAY"), ("startDt", "20240101"), ("endDt", "20240103"),
                            ("stnIds", "152"), ("dataType", "JSON")):
            self.assertEqual(params[name], value)

    def test_summary_uses_the_hottest_day_and_mean_humidity_skipping_gaps(self):
        rows = [_day("2023-08-01", 35.2, 70), _day("2024-07-20", 38.1, 60), _day("2025-01-05", -8.0, 40),
                {"tm": "2025-01-06", "maxTa": "", "avgRhm": "", "avgWs": ""}]
        basis = kma.summarize(rows, "152", "2023-01-01 ~ 2025-12-31")
        self.assertEqual((basis.max_temperature_c, basis.max_temperature_date), (38.1, "2024-07-20"))
        self.assertEqual(basis.mean_humidity_pct, 56.7)
        self.assertEqual(basis.station_name, "울산")

    def test_three_year_period_ends_yesterday(self):
        seen = []

        def fake(url, params):
            seen.append(params)
            return 200, _body([_day("2026-01-01", 30, 60)])
        with patch("engine.kma_asos._credential", return_value="KEY"):
            basis, _ = kma.three_year_basis("152", today=date(2026, 9, 19), get=fake)
        self.assertEqual((seen[0]["startDt"], seen[0]["endDt"]), ("20230919", "20260918"))
        self.assertEqual(basis.period, "2023-09-19 ~ 2026-09-18")

    def test_no_key_no_data_and_errors_are_reported_not_raised(self):
        calls = []
        with patch("engine.kma_asos._credential", return_value=""):
            result = kma.fetch_daily("152", date(2024, 1, 1), date(2024, 1, 2), get=lambda *a: calls.append(1) or (200, ""))
        self.assertEqual((result.status, calls), ("NOT_CONFIGURED", []))
        with patch("engine.kma_asos._credential", return_value="KEY"):
            nodata = kma.fetch_daily("152", date(2024, 1, 1), date(2024, 1, 2), get=lambda u, p: (200, _body([], code="03")))
            broken = kma.fetch_daily("152", date(2024, 1, 1), date(2024, 1, 2), get=lambda u, p: (500, "oops"))
        self.assertEqual(nodata.status, "NO_DATA")
        self.assertEqual(broken.status, "ERROR")


class ScreenTests(unittest.TestCase):
    def test_button_fills_temperature_and_humidity_and_records_the_basis(self):
        project = _project()
        basis = kma.WeatherBasis("152", "울산", "2023-09-19 ~ 2026-09-18", 1096, 38.1, 61.2, 2.4, "2024-07-20")
        result = kma.DailyResult("OK", "", ())
        with patch("engine.kma_asos.three_year_basis", return_value=(basis, result)), \
             patch("engine.stage2.storage.save_project"):
            def click(at):
                at.button(key="psm19_weather_fill").click().run()
            at = _run(project, "19-2", click)
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="psm19_temp").value, "38.1")
        self.assertEqual(at.text_input(key="psm19_humidity").value, "61.2")
        record = project.get_field("psm.risk.weather_basis")
        self.assertEqual(record.value["관측소"], "울산(152)")
        self.assertTrue(any("채웠습니다" in s.value for s in at.success))

    def test_lookup_failure_leaves_the_fields_for_manual_input(self):
        project = _project()
        failed = kma.DailyResult("NOT_CONFIGURED", "키가 없어 조회하지 않았습니다.")
        with patch("engine.kma_asos.three_year_basis", return_value=(None, failed)):
            def click(at):
                at.button(key="psm19_weather_fill").click().run()
            at = _run(project, "19-2", click)
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="psm19_temp").value, "")
        self.assertTrue(any("키가 없어" in w.value for w in at.warning))


if __name__ == "__main__":
    unittest.main()
