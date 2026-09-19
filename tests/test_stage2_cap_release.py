from __future__ import annotations

import math
import unittest

from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_release as rel
from engine.stage2 import cap_release_workspace as rw
from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_scenario_workspace import _facilities, _project


class HoleAndRateTests(unittest.TestCase):
    def test_hole_is_twenty_percent_of_the_largest_connection(self):
        hole = rel.hole_diameter(100, operating_celsius=25, gauge_mpa=0.3)
        self.assertAlmostEqual(hole.diameter_mm, 20.0)
        self.assertIn("20%", hole.reason)

    def test_full_bore_exceptions_from_the_guideline(self):
        self.assertEqual(rel.hole_diameter(40).diameter_mm, 40)  # 50mm 미만
        self.assertEqual(rel.hole_diameter(100, operating_celsius=350).diameter_mm, 100)  # 350℃
        self.assertEqual(rel.hole_diameter(100, gauge_mpa=10 * 0.0980665).diameter_mm, 100)  # 10kgf/cm2
        self.assertEqual(rel.hole_diameter(100, gauge_mpa=0.9).diameter_mm, 20)  # 10kgf/cm2 미만
        self.assertEqual(rel.hole_diameter(150, is_tank_lorry=True).diameter_mm, 150)

    def test_open_top_tank_uses_half_the_perimeter_sum(self):
        hole = rel.hole_diameter(25, open_top_width_m=1.0, open_top_length_m=3.0, has_other_piping=False)
        self.assertAlmostEqual(hole.diameter_mm, (1.0 + 3.0) * 0.5 * 0.2 * 1000)

    def test_liquid_rate_matches_the_bernoulli_orifice_equation(self):
        # d=10mm, 물, ΔP=0.5MPa: 0.61·A·√(2ρΔP) = 1.515 kg/s
        rate = rel.liquid_release_rate(10, 1000, 0.5e6, 0)
        self.assertAlmostEqual(rate, 0.61 * math.pi * 0.005 ** 2 * math.sqrt(2 * 1000 * 0.5e6), places=9)
        self.assertAlmostEqual(rate, 1.515, places=2)

    def test_atmospheric_liquid_is_driven_by_head(self):
        rate = rel.liquid_release_rate(20, 1400, 0.0, 3.0)
        expected = 0.61 * math.pi * 0.01 ** 2 * 1400 * math.sqrt(2 * 9.80665 * 3.0)
        self.assertAlmostEqual(rate, expected, places=9)

    def test_gas_choked_flow_for_air_at_7_bar_abs(self):
        # 공기 300K 7bar(abs): 초크 질량속도 근사식 G ≈ 0.0404·P/√T (SI) = 1633 kg/m²·s, 10mm 구멍 → 0.128 kg/s
        rate = rel.gas_release_rate(10, 7.0e5, 300.0, 28.97, 1.4, 1.0)
        rule_of_thumb = 0.0404 * 7.0e5 / math.sqrt(300.0) * math.pi * 0.005 ** 2
        self.assertAlmostEqual(rate, rule_of_thumb, delta=0.001)
        self.assertAlmostEqual(rate, 0.1283, places=3)

    def test_gas_flow_is_subsonic_below_the_critical_pressure_ratio_and_zero_at_ambient(self):
        choked = rel.gas_release_rate(10, 1.8e5, 300.0, 28.97, 1.4, 1.0)   # 압력비 1.78 < 1.893
        just_above = rel.gas_release_rate(10, 1.9e5, 300.0, 28.97, 1.4, 1.0)  # 압력비 1.875 < 1.893
        higher = rel.gas_release_rate(10, 2.0e5, 300.0, 28.97, 1.4, 1.0)   # 초크
        self.assertLess(choked, just_above)
        self.assertLess(just_above, higher)
        self.assertEqual(rel.gas_release_rate(10, 1.0e5, 300.0, 28.97), 0.0)

    def test_amount_is_capped_by_inventory_and_durations_follow_the_table(self):
        self.assertEqual(rel.release_amount_kg(2.0, 20, 5000), 2400.0)
        self.assertEqual(rel.release_amount_kg(50.0, 20, 5000), 5000)
        self.assertEqual((rel.leak_duration_min("A", "A"), rel.leak_duration_min("C", "C")), (20, 60))
        self.assertEqual(rel.leak_duration_min("Z", "?"), 60)
        self.assertEqual(rel.worst_case_amount_kg(800), 800)


def _scenario_project(**properties):
    project = _project(properties)
    _facilities(project, {"용량": 2, "비중": 1.4})
    [spec] = f9.rows(project)
    spec.update({"최대 연결구 크기(mm)": "100", "운전압력": "0.3", "운전온도": "25"})
    f9.save_specs(project, [spec])
    return project


class ScenarioReleaseTests(unittest.TestCase):
    SCENARIO = {"사고시나리오명": "E-1 염소 독성 누출", "대상 설비번호": "E-1", "유해화학물질명": "염소"}

    def test_inputs_come_from_earlier_forms_and_only_head_is_new(self):
        project = _scenario_project()
        result = rw.release_for_scenario(project, self.SCENARIO)
        self.assertEqual(result.problems, ())
        self.assertAlmostEqual(result.hole_mm, 20.0)
        expected_rate = rel.liquid_release_rate(20, 1400, 0.3e6, 0.0)
        self.assertAlmostEqual(result.rate_kg_s, expected_rate)
        self.assertEqual(result.duration_min, 60.0)  # 등급 미입력 = 수동 차단(C/C)
        self.assertAlmostEqual(result.amount_kg, min(expected_rate * 3600, 2800.0))

    def test_atmospheric_liquid_asks_for_head(self):
        project = _scenario_project()
        [spec] = f9.rows(project)
        spec["운전압력"] = "0"
        f9.save_specs(project, [spec])
        # 0 is blank-ignored by save_specs' truthiness only for empty strings; "0" is kept
        problems = rw.release_for_scenario(project, self.SCENARIO).problems
        self.assertTrue(any("액위" in p for p in problems))
        with_head = rw.release_for_scenario(project, dict(self.SCENARIO, **{rw.HEAD_COLUMN: "2.5"}))
        self.assertEqual(with_head.problems, ())
        self.assertGreater(with_head.rate_kg_s, 0)

    def test_missing_connection_is_reported_not_guessed(self):
        project = _project()
        _facilities(project, {"용량": 2, "비중": 1.4})
        problems = rw.release_for_scenario(project, self.SCENARIO).problems
        self.assertTrue(any("연결구" in p for p in problems))

    def test_gas_uses_molar_mass_from_form6(self):
        project = _scenario_project(분자량="70.9")
        rows = ws.facility_editor_rows(project)
        rows[0].update({"물질성상": "기체·고압가스", "용량": 10, "용량단위": "m3", "운전압력(MPa)": 0.5,
                        "운전온도(℃)": 25, "분자량": 70.9})
        ws.save_facility_rows(project, rows)
        [spec] = f9.rows(project)
        spec["최대 연결구 크기(mm)"] = "100"
        f9.save_specs(project, [spec])
        result = rw.release_for_scenario(project, self.SCENARIO)
        self.assertEqual(result.problems, ())
        expected = rel.gas_release_rate(20, 101325 + 0.5e6, 298.15, 70.9)
        self.assertAlmostEqual(result.rate_kg_s, expected)
        self.assertIn("기체 오리피스", result.model)

    def test_automatic_isolation_shortens_the_leak(self):
        project = _scenario_project()
        manual = rw.release_for_scenario(project, self.SCENARIO)
        automatic = rw.release_for_scenario(project, self.SCENARIO, detection="A", isolation="A")
        self.assertLess(automatic.duration_min, manual.duration_min)
        self.assertLessEqual(automatic.amount_kg, manual.amount_kg)

    def test_unknown_facility_is_reported(self):
        project = _scenario_project()
        result = rw.release_for_scenario(project, {"대상 설비번호": "ZZ-9"})
        self.assertTrue(result.problems)
        self.assertIsNone(result.rate_kg_s)


if __name__ == "__main__":
    unittest.main()
