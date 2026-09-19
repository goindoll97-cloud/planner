from __future__ import annotations

import unittest

from engine.stage2 import cap_release_workspace as rw
from engine.stage2 import psm_form19_2_workspace as f19
from engine.stage2 import statutory_report as report
from tests.test_stage2_cap_dispersion import LIQUID, _toxic_project

WEATHER = {"대기온도(℃)": "30", "습도(%)": "70"}


class PsmForm19_2Tests(unittest.TestCase):
    def test_toxic_erpg2_matches_the_cap_result_for_the_same_release(self):
        project = _toxic_project()  # 염소: 두 근거표 모두 ERPG-2 3 ppm
        cap = rw.toxic_effect_for_scenario(project, dict(LIQUID, **{rw.BOUNDARY_COLUMN: "30"}))
        result = f19.scenario_row(project, LIQUID, f19.ALTERNATIVE, WEATHER)
        self.assertAlmostEqual(float(result.row["독성-ERPG 2"]), cap.radius_m, delta=1.0)
        self.assertGreater(float(result.row["독성-ERPG 1"]), float(result.row["독성-ERPG 2"]))
        self.assertGreater(float(result.row["독성-ERPG 2"]), float(result.row["독성-ERPG 3"]))
        self.assertEqual(result.row["시나리오 구분"], f19.ALTERNATIVE)
        self.assertEqual((result.row["풍속(m/s)"], result.row["대기안정도(A~F)"]), ("3", "D"))

    def test_worst_case_uses_the_form_weather_and_reaches_farther(self):
        project = _toxic_project()
        worst = f19.scenario_row(project, LIQUID, f19.WORST, WEATHER)
        normal = f19.scenario_row(project, LIQUID, f19.ALTERNATIVE, WEATHER)
        self.assertEqual((worst.row["풍속(m/s)"], worst.row["대기안정도(A~F)"]), ("1.5", "F"))
        self.assertGreater(float(worst.row["독성-ERPG 2"]), float(normal.row["독성-ERPG 2"]))

    def test_missing_weather_inputs_and_unsupported_cells_are_reported_not_invented(self):
        result = f19.scenario_row(_toxic_project(), LIQUID, f19.WORST, {})
        text = "\n".join(result.problems)
        self.assertIn("대기온도", text)
        self.assertIn("습도", text)
        self.assertEqual(result.row["폭발-21 kPa"], "")
        self.assertTrue(any("25% LEL" in h for h in result.holds))
        self.assertTrue(any("연소열" in h for h in result.holds))

    def test_saved_table_feeds_the_statutory_form_reader(self):
        project = _toxic_project()
        from engine.stage2 import cap_scenario_workspace as sc
        sc.save_scenarios(project, [dict(LIQUID)])
        results = f19.build(project, {LIQUID["사고시나리오명"]: f19.WORST}, WEATHER)
        self.assertEqual(f19.save(project, results), 1)
        [row] = report._rows(project, f19.TABLE_KEY)
        self.assertEqual(row["물질명"], "염소")
        self.assertTrue(float(row["독성-ERPG 2"]) > 0)


if __name__ == "__main__":
    unittest.main()
