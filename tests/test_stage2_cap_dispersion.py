from __future__ import annotations

import math
import unittest

from engine.stage2 import cap_dispersion as disp
from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_release_workspace as rw
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_scenario_workspace import _facilities, _project


class GaussianTests(unittest.TestCase):
    def test_briggs_rural_neutral_coefficients_at_one_kilometre(self):
        sigma_y, sigma_z = disp.sigmas(1000.0, "D", disp.RURAL)
        self.assertAlmostEqual(sigma_y, 0.08 * 1000 * (1 + 0.1) ** -0.5, places=6)   # 76.28
        self.assertAlmostEqual(sigma_z, 0.06 * 1000 * (1 + 1.5) ** -0.5, places=6)   # 37.95
        self.assertAlmostEqual(sigma_y, 76.28, places=1)
        self.assertAlmostEqual(sigma_z, 37.95, places=1)

    def test_urban_spreads_faster_than_rural_for_the_same_class(self):
        rural = disp.sigmas(500.0, "D", disp.RURAL)
        urban = disp.sigmas(500.0, "D", disp.URBAN)
        self.assertGreater(urban[0], rural[0])
        self.assertGreater(urban[1], rural[1])

    def test_ground_level_centreline_concentration(self):
        # Q=1 kg/s, u=3 m/s, x=1 km, 전원 D: 1/(π·3·76.28·37.95) = 3.665e-5 kg/m3
        value = disp.ground_concentration(1.0, 1000.0, wind_ms=3.0, stability="D", terrain=disp.RURAL)
        self.assertAlmostEqual(value, 1 / (math.pi * 3 * 76.2770 * 37.9473), delta=1e-8)
        self.assertAlmostEqual(value, 3.665e-5, delta=2e-8)

    def test_distance_solves_the_endpoint_and_is_consistent_with_the_concentration(self):
        endpoint = 1.0e-5
        distance = disp.distance_to_endpoint(2.0, endpoint, wind_ms=3.0, stability="D", terrain=disp.RURAL)
        back = disp.ground_concentration(2.0, distance, wind_ms=3.0, stability="D", terrain=disp.RURAL)
        self.assertAlmostEqual(back, endpoint, delta=endpoint * 1e-3)

    def test_more_stable_air_and_lower_wind_reach_farther(self):
        args = dict(rate_kg_s=1.0, endpoint_kg_m3=1e-5, terrain=disp.RURAL)
        normal = disp.distance_to_endpoint(args["rate_kg_s"], args["endpoint_kg_m3"], wind_ms=3.0, stability="D", terrain=disp.RURAL)
        worst = disp.distance_to_endpoint(args["rate_kg_s"], args["endpoint_kg_m3"], wind_ms=1.5, stability="F", terrain=disp.RURAL)
        self.assertGreater(worst, normal)

    def test_trivial_sources_have_no_reach(self):
        self.assertEqual(disp.distance_to_endpoint(0.0, 1e-5), 0.0)
        self.assertEqual(disp.distance_to_endpoint(1e-12, 1e-3), 0.0)

    def test_ppm_conversion_uses_24_45_l_per_mol(self):
        self.assertAlmostEqual(disp.ppm_to_kg_m3(3.0, 70.9), 3.0 * 70.9 / 24.45 * 1e-6)


class PoolTests(unittest.TestCase):
    def test_unrestrained_pool_is_one_centimetre_deep(self):
        # 1000 kg, 밀도 1 g/cm3 → 1 m3 → 100 m2 (1 cm)
        self.assertAlmostEqual(disp.pool_area_m2(1000, 1.0), 100.0)

    def test_dike_limits_the_pool_when_smaller(self):
        self.assertEqual(disp.pool_area_m2(1000, 1.0, 40.0), 40.0)
        self.assertEqual(disp.pool_area_m2(1000, 1.0, 400.0), 100.0)

    def test_evaporation_of_water_is_of_the_expected_magnitude(self):
        # 물(MW18, VP 23.8mmHg, 298K) 3m/s, 1 m2: 실제 증발은 약 0.02 kg/min/m2
        rate = disp.evaporation_rate_kg_min(3.0, 18.0, 1.0, 23.8, 298.15)
        self.assertAlmostEqual(rate, 0.0219, delta=0.001)


LIQUID = {"사고시나리오명": "E-1 염소 독성 누출", "대상 설비번호": "E-1", "유해화학물질명": "염소"}


def _toxic_project(**properties):
    props = {"분자량": "70.9", "증기압": "5000 mmHg"}
    props.update(properties)
    project = _project(props)
    _facilities(project, {"용량": 2, "비중": 1.4, "물질성상": "기체·고압가스", "운전압력(MPa)": 0.5, "운전온도(℃)": 25,
                         "분자량": 70.9})
    [spec] = f9.rows(project)
    spec.update({"최대 연결구 크기(mm)": "100"})
    f9.save_specs(project, [spec])
    return project


class ToxicEffectTests(unittest.TestCase):
    def test_gas_release_reaches_a_finite_distance_using_the_erpg2_endpoint(self):
        project = _toxic_project()
        effect = rw.toxic_effect_for_scenario(project, dict(LIQUID, **{rw.BOUNDARY_COLUMN: "30"}))
        self.assertEqual(effect.problems, ())
        self.assertIn("ERPG-2 3 ppm", effect.endpoint_basis)
        self.assertGreater(effect.radius_m, 100)
        self.assertAlmostEqual(effect.off_site_m, max(0.0, effect.radius_m - 30.0))
        endpoint_kg_m3 = disp.ppm_to_kg_m3(3.0, 70.9)
        back = disp.ground_concentration(effect.source_rate_kg_s, effect.radius_m, wind_ms=3.0, stability="D",
                                         terrain=disp.RURAL)
        self.assertAlmostEqual(back, endpoint_kg_m3, delta=endpoint_kg_m3 * 1e-2)
        self.assertTrue(any("중가스" in note for note in effect.notes))  # 염소는 공기보다 무겁다

    def test_worst_case_weather_reaches_farther(self):
        project = _toxic_project()
        scenario = dict(LIQUID, **{rw.BOUNDARY_COLUMN: "30"})
        normal = rw.toxic_effect_for_scenario(project, scenario)
        worst = rw.toxic_effect_for_scenario(project, scenario, weather=rw.default_weather(project, worst_case=True))
        self.assertGreater(worst.radius_m, normal.radius_m)

    def test_industrial_complex_selects_urban_terrain(self):
        project = _toxic_project()
        self.assertEqual(rw.default_terrain(project), disp.RURAL)
        project.set_field(rw.INDUSTRIAL_KEY, "산업단지", "울산미포국가산업단지", "USER_CONFIRMED")
        self.assertEqual(rw.default_terrain(project), disp.URBAN)
        project.set_field(rw.INDUSTRIAL_KEY, "산업단지", "해당 없음", "USER_CONFIRMED")
        self.assertEqual(rw.default_terrain(project), disp.RURAL)

    def test_missing_boundary_distance_is_reported_but_radius_is_still_given(self):
        effect = rw.toxic_effect_for_scenario(_toxic_project(), LIQUID)
        self.assertIsNotNone(effect.radius_m)
        self.assertIsNone(effect.off_site_m)
        self.assertTrue(any("경계" in p for p in effect.problems))

    def test_unlisted_substance_needs_a_fallback_endpoint(self):
        project = _toxic_project()
        chemicals = project.get_field("inventory.chemicals").value
        chemicals[0]["CAS 번호"] = "111-11-1"
        project.set_field("inventory.chemicals", "화학물질 목록", chemicals, "VERIFIED")
        effect = rw.toxic_effect_for_scenario(project, LIQUID)
        self.assertIsNone(effect.radius_m)
        self.assertTrue(any("끝점농도" in p for p in effect.problems))

    def test_liquid_pool_uses_evaporation_and_the_dike_area(self):
        project = _project({"분자량": "92.14", "증기압": "28.4 mmHg", "CAS 번호": "108-88-3"}, chemical="톨루엔")
        _facilities(project, {"용량": 30, "비중": 0.87, "취급물질": "톨루엔", "물질성상": "액체"})
        [spec] = f9.rows(project)
        spec.update({"최대 연결구 크기(mm)": "100", "운전압력": "0.3", "운전온도": "25"})
        f9.save_specs(project, [spec])
        scenario = {"사고시나리오명": "E-1 톨루엔 독성 누출", "대상 설비번호": "E-1", "유해화학물질명": "톨루엔",
                    rw.BOUNDARY_COLUMN: "10"}
        free = rw.toxic_effect_for_scenario(project, scenario)
        self.assertEqual(free.problems, ())
        self.assertIn("액체 풀 증발", free.source)
        project.set_field(rw.DIKE_KEY, "확산방지설비", [{"대상 설비번호": "E-1", "적용여부": "예", "내부 길이(m)": "2", "내부 폭(m)": "2"}],
                          "USER_CONFIRMED")
        diked = rw.toxic_effect_for_scenario(project, scenario)
        self.assertIn("4.0 m2", diked.source)
        self.assertLessEqual(diked.source_rate_kg_s, free.source_rate_kg_s)


if __name__ == "__main__":
    unittest.main()
