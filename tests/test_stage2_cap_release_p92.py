from __future__ import annotations

import unittest

from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_release as rel
from engine.stage2 import cap_release_workspace as rw
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_scenario_workspace import _facilities, _project

KGF = rel.KGF_CM2_PA


class Kosha92WorkedExampleTests(unittest.TestCase):
    """KOSHA GUIDE P-92-2023 붙임 1~3: 액체염소 철도차량 38mm 개구부."""

    def test_attachment1_gas_release_through_the_relief_valve_is_2_5_kg_s(self):
        # 안전밸브 1½"(38mm), 7.39 kgf/cm2(절대), 21℃, γ=1.325, MW=70.9, Cd=0.84 → 2.5 kg/s
        rate = rel.gas_release_rate(38, 7.39 * KGF, 294.0, 70.9, 1.325, cd=0.84)
        self.assertAlmostEqual(rate, 2.5, delta=0.05)

    def test_attachment1_regime_and_discharge_coefficient_follow_table1(self):
        critical = (2 / 2.325) ** (1.325 / 0.325)
        self.assertAlmostEqual(critical, 0.5413, places=4)
        self.assertLess(1.033 / 7.39, critical)  # 음속 이상
        self.assertEqual(rel.gas_discharge_coefficient(7.39 * KGF, 1.033 * KGF, 1.325), 0.84)
        self.assertEqual(rel.gas_discharge_coefficient(1.5 * KGF, 1.033 * KGF, 1.325), 0.61)  # 음속 미만
        self.assertEqual(rel.gas_discharge_coefficient(1.033 * KGF / 0.6, 1.033 * KGF, 1.325), 0.61)  # 압력비 0.6 > 0.5413
        near = 1.033 * KGF / 0.5413 * 1.02  # 임계압력비 바로 아래(음속 이상 경계)
        self.assertEqual(rel.gas_discharge_coefficient(near, 1.033 * KGF, 1.325), 0.75)

    def test_default_coefficient_is_chosen_automatically(self):
        auto = rel.gas_release_rate(38, 7.39 * KGF, 294.0, 70.9, 1.325)
        explicit = rel.gas_release_rate(38, 7.39 * KGF, 294.0, 70.9, 1.325, cd=0.84)
        self.assertAlmostEqual(auto, explicit)

    def test_attachment2_liquid_release_through_a_bottom_rupture_is_29_4_kg_s(self):
        rate = rel.liquid_release_rate(38, 1405, (7.39 - 1.033) * KGF, 1.3, cd=0.61)
        self.assertAlmostEqual(rate, 29.4, delta=0.2)

    def test_attachment3_equilibrium_saturated_liquid_release_is_11_6_kg_s(self):
        rate = rel.equilibrium_flashing_rate(38, 60.6, 21.6, 1405, 0.24, 294.0)
        self.assertAlmostEqual(rate, 11.6, delta=0.1)

    def test_flashing_release_is_slower_than_the_single_phase_liquid_estimate(self):
        single = rel.liquid_release_rate(38, 1405, (7.39 - 1.033) * KGF, 1.3, cd=0.61)
        flashing = rel.equilibrium_flashing_rate(38, 60.6, 21.6, 1405, 0.24, 294.0)
        self.assertLess(flashing, single)  # 2상 유동이 질량유량을 줄인다

    def test_flash_fraction_of_chlorine_at_21c_is_about_a_fifth(self):
        fraction = rel.flash_fraction(0.24, 60.6, 294.0, 239.0)  # 비점 -34℃
        self.assertAlmostEqual(fraction, 0.2, delta=0.03)


def _liquefied_project():
    project = _project({"분자량": "70.9", "물질상태": "기체"})
    _facilities(project, {"용량": 2, "비중": 1.405})
    [spec] = f9.rows(project)
    spec.update({"최대 연결구 크기(mm)": "38", "운전압력": "0.6", "운전온도": "21"})
    f9.save_specs(project, [spec])
    return project


class LiquefiedGasWiringTests(unittest.TestCase):
    SCENARIO = {"사고시나리오명": "E-1 염소 독성 누출", "대상 설비번호": "E-1", "유해화학물질명": "염소"}

    def test_without_flash_properties_the_single_phase_result_is_flagged(self):
        result = rw.release_for_scenario(_liquefied_project(), self.SCENARIO)
        self.assertEqual(result.problems, ())
        self.assertIn("플래시 증발 미반영", result.model)

    def test_flash_properties_switch_to_the_two_phase_equation(self):
        project = _liquefied_project()
        scenario = dict(self.SCENARIO, **{rw.LATENT_HEAT_COLUMN: "60.6", rw.LIQUID_CP_COLUMN: "0.24",
                                          rw.VAPOR_DENSITY_COLUMN: "21.6"})
        two_phase = rw.release_for_scenario(project, scenario)
        single = rw.release_for_scenario(project, self.SCENARIO)
        self.assertIn("P-92 식 6", two_phase.model)
        self.assertNotEqual(round(two_phase.rate_kg_s, 6), round(single.rate_kg_s, 6))
        expected = rel.equilibrium_flashing_rate(38, 60.6, 21.6, 1405.0, 0.24, 294.15)
        self.assertAlmostEqual(two_phase.rate_kg_s, expected)

    def test_short_leak_pipe_is_not_treated_as_equilibrium(self):
        project = _liquefied_project()
        scenario = dict(self.SCENARIO, **{rw.LATENT_HEAT_COLUMN: "60.6", rw.LIQUID_CP_COLUMN: "0.24",
                                          rw.VAPOR_DENSITY_COLUMN: "21.6", rw.LEAK_PIPE_COLUMN: "0.05"})
        self.assertIn("플래시 증발 미반영", rw.release_for_scenario(project, scenario).model)


if __name__ == "__main__":
    unittest.main()
