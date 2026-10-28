from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import patch

from engine import kma_asos as kma
from tests.test_psm_workspace_page import _project


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
    """대기온도·습도는 ‘사고시나리오 결과’ 화면이 처음 열릴 때 주소로 관측소를 골라 채웁니다(화면에 입력칸 없음)."""

    def _project(self, address):
        from tests.test_demo_full_company import walk

        project, _ = walk()
        project.psm_required = True
        project.set_authoring_scope(psm_selected=True, cap_selected=True)
        project.set_field("business.address", "사업장 주소", address, "VERIFIED")
        return project

    def _run(self, project):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        rows = [{"project_id": project.project_id, "company_name": project.company_name}]
        with patch("engine.stage2.storage.list_projects", return_value=rows), \
             patch("engine.stage2.storage.load_project", return_value=project), \
             patch("engine.stage2.storage.save_project"):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "ui/scenario_results_page.py"), default_timeout=120)
            at.session_state["_stage2_active_project_id"] = project.project_id
            at.run()
            return at

    def test_scenario_page_fills_temperature_and_humidity_on_first_open(self):
        from engine.stage2 import psm_form19_2_workspace as f19

        project = self._project("울산광역시 남구 산업로 1")
        basis = kma.WeatherBasis("152", "울산", "2023-09-19 ~ 2026-09-18", 1096, 38.1, 61.2, 2.4, "2024-07-20")
        with patch("engine.kma_asos.three_year_basis", return_value=(basis, kma.DailyResult("OK", "", ()))):
            at = self._run(project)
        self.assertFalse(at.exception)
        self.assertEqual(project.get_field("psm.risk.weather_basis").value["관측소"], "울산(152)")
        rows = project.get_field(f19.TABLE_KEY).value
        self.assertEqual({(r["대기온도(℃)"], r["습도(%)"]) for r in rows}, {("38.1", "61.2")})
        self.assertTrue(any("채웠습니다" in s.value for s in at.success))
        self.assertEqual(len(at.text_input), 0)

    def test_unknown_station_points_to_the_file_instead_of_an_input_box(self):
        project = self._project("알 수 없는 마을 1")
        at = self._run(project)
        self.assertFalse(at.exception)
        self.assertTrue(any("관측소를 찾지 못했습니다" in i.value and "사업개요 파일" in i.value for i in at.info))
        self.assertEqual(len(at.text_input), 0)


if __name__ == "__main__":
    unittest.main()


from engine.stage2 import psm_weather as pw  # noqa: E402


class AutoFillTests(unittest.TestCase):
    def _fake(self, calls):
        def get(url, params):
            calls.append(params["stnIds"])
            return 200, _body([_day("2025-07-01", 36.0, 60), _day("2025-07-02", 33.0, 70)])
        return get

    def _with_address(self, project, text):
        project.set_field("business.address", "사업장 주소", text, "VERIFIED")
        return project

    def test_address_alone_is_enough_and_the_result_is_reused(self):
        project = self._with_address(_project(), "울산광역시 남구 산업로 1")
        calls = []
        with patch("engine.kma_asos._credential", return_value="KEY"):
            first = pw.auto_fill(project, today=date(2026, 9, 19), get=self._fake(calls))
            second = pw.auto_fill(project, today=date(2026, 9, 19), get=self._fake(calls))
        self.assertEqual((first.status, second.status), ("FILLED", "SAVED"))
        self.assertEqual(calls, ["152"])  # 두 번째는 조회하지 않는다
        saved = pw.saved(project)
        self.assertEqual((saved["관측소코드"], saved["최고기온(℃)"], saved["평균 상대습도(%)"]), ("152", 36.0, 65.0))

    def test_unknown_address_or_missing_address_asks_the_user_instead_of_guessing(self):
        blank = _project()
        blank.fields.pop("business.address", None)
        self.assertEqual(pw.auto_fill(blank).status, "NO_ADDRESS")
        unknown = self._with_address(_project(), "알 수 없는 마을 1")
        result = pw.auto_fill(unknown)
        self.assertEqual(result.status, "NO_STATION")
        self.assertEqual(pw.saved(unknown), {})

    def test_lookup_failure_is_a_status_not_an_exception(self):
        project = self._with_address(_project(), "울산광역시 남구")
        with patch("engine.kma_asos._credential", return_value=""):
            self.assertEqual(pw.auto_fill(project).status, "NOT_CONFIGURED")
