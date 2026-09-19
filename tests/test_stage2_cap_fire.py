from __future__ import annotations

import math
import unittest

from engine.stage2 import cap_fire as fire
from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_release_workspace as rw
from tests.test_stage2_cap_scenario_workspace import _facilities, _project


class FireModelTests(unittest.TestCase):
    def test_vce_distance_follows_the_epa_tnt_equivalence_formula(self):
        # 프로판 1000 kg(46,350 kJ/kg): W=2204.6 lb, HC=19,927 Btu/lb → X = 17·(0.1·2204.6·19927/1943)^(1/3) ≈ 223 m
        distance = fire.vce_distance_1psi_m(1000.0, 46350.0)
        expected = 17.0 * (0.1 * 1000 * 2.20462 * (46350 / 2.326) / 1943.0) ** (1 / 3)
        self.assertAlmostEqual(distance, expected, places=6)
        self.assertAlmostEqual(distance, 223.0, delta=1.5)

    def test_vce_scales_with_the_cube_root_of_the_mass_and_is_zero_without_fuel(self):
        self.assertAlmostEqual(fire.vce_distance_1psi_m(8000.0, 46350.0) / fire.vce_distance_1psi_m(1000.0, 46350.0), 2.0, places=6)
        self.assertEqual(fire.vce_distance_1psi_m(0.0, 46350.0), 0.0)

    def test_point_source_radius_solves_the_inverse_square_law(self):
        # Q=13.9 MW·0.3… : r = √(f·Q / (4π·5 kW/m²)) → 1 kg/s 프로판 제트 ≈ 14.9 m
        radius = fire.jet_fire_distance_m(1.0, 46350.0)
        self.assertAlmostEqual(radius, math.sqrt(0.3 * 46350e3 / (4 * math.pi * 5000.0)), places=9)
        self.assertAlmostEqual(radius, 14.9, delta=0.1)
        flux = 0.3 * 46350e3 / (4 * math.pi * radius ** 2)
        self.assertAlmostEqual(flux, 5000.0, delta=1e-6)

    def test_burning_rate_of_methanol_like_liquid(self):
        # m'' = 0.001·19930 / (2.5·(64.7−25) + 1100) = 0.0166 kg/m2·s
        self.assertAlmostEqual(fire.burning_rate_kg_m2_s(19930, 2.5, 64.7, 25.0, 1100.0), 0.0166, places=4)

    def test_bigger_pool_burns_farther(self):
        small = fire.pool_fire_distance_m(10.0, 0.0166, 19930.0)
        large = fire.pool_fire_distance_m(100.0, 0.0166, 19930.0)
        self.assertAlmostEqual(large / small, math.sqrt(10.0), places=6)


def _fire_project(state="기체·고압가스", **overrides):
    props = {"분자량": "44.1", "증기압": "5000 mmHg", "연소열": "46350"}
    props.update(overrides)
    project = _project(props, chemical="프로판")
    _facilities(project, {"용량": 10, "비중": 0.5, "취급물질": "프로판", "물질성상": state,
                         "운전압력(MPa)": 0.8, "운전온도(℃)": 25, "분자량": 44.1})
    [spec] = f9.rows(project)
    spec.update({"최대 연결구 크기(mm)": "100"})
    f9.save_specs(project, [spec])
    return project


SCENARIO = {"사고시나리오명": "E-1 프로판 화재·폭발", "대상 설비번호": "E-1", "유해화학물질명": "프로판",
            rw.BOUNDARY_COLUMN: "50"}


class FireEffectTests(unittest.TestCase):
    def test_gas_release_gives_explosion_and_jet_fire_distances(self):
        effect = rw.fire_effect_for_scenario(_fire_project(), SCENARIO)
        self.assertEqual(effect.problems, ())
        self.assertGreater(effect.explosion_m, 0)
        self.assertGreater(effect.fire_m, 0)
        self.assertEqual(effect.radius_m, max(effect.explosion_m, effect.fire_m))
        self.assertAlmostEqual(effect.off_site_m, max(0.0, effect.radius_m - 50.0))
        self.assertIn("제트 화재", effect.fire_basis)
        self.assertIn("전량", effect.explosion_basis)

    def test_missing_heat_of_combustion_is_asked_for_not_guessed(self):
        effect = rw.fire_effect_for_scenario(_fire_project(연소열=""), SCENARIO)
        self.assertIsNone(effect.radius_m)
        self.assertTrue(any("연소열" in p for p in effect.problems))
        supplied = rw.fire_effect_for_scenario(_fire_project(연소열=""), dict(SCENARIO, **{rw.HEAT_COLUMN: "46350"}))
        self.assertIsNotNone(supplied.radius_m)

    def test_liquid_pool_needs_burning_rate_inputs_but_explosion_still_works(self):
        project = _fire_project(state="액체", 증기압="200 mmHg", 연소열="19930", 분자량="32.04")
        effect = rw.fire_effect_for_scenario(project, SCENARIO)
        self.assertIsNotNone(effect.explosion_m)
        self.assertIsNone(effect.fire_m)
        self.assertTrue(any("비점" in p for p in effect.problems))
        full = rw.fire_effect_for_scenario(project, dict(SCENARIO, **{
            rw.BOILING_COLUMN: "64.7", rw.LIQUID_CP_KJ_COLUMN: "2.5", rw.VAPORIZATION_COLUMN: "1100"}))
        self.assertIsNotNone(full.fire_m)
        self.assertIn("풀 화재", full.fire_basis)
        self.assertIn("최초 10분", full.explosion_basis)

    def test_boundary_distance_is_required_for_the_off_site_figure(self):
        scenario = {k: v for k, v in SCENARIO.items() if k != rw.BOUNDARY_COLUMN}
        effect = rw.fire_effect_for_scenario(_fire_project(), scenario)
        self.assertIsNone(effect.off_site_m)
        self.assertTrue(any("경계" in p for p in effect.problems))


if __name__ == "__main__":
    unittest.main()
