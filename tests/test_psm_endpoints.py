from __future__ import annotations

import unittest

from engine.stage2 import cap_fire as fire
from engine.stage2 import psm_endpoints as ep
from engine.stage2 import psm_erpg


class PsmEndpointTests(unittest.TestCase):
    def test_cap_defaults_are_unchanged(self):
        self.assertAlmostEqual(fire.jet_fire_distance_m(2.0, 50000.0), fire.jet_fire_distance_m(2.0, 50000.0, 5.0))
        self.assertAlmostEqual(fire.pool_fire_distance_m(40.0, 0.05, 40000.0),
                               fire.pool_fire_distance_m(40.0, 0.05, 40000.0, 5.0))

    def test_form_defaults_match_the_printed_form(self):
        self.assertEqual(ep.FIRE_KW_M2, (4.0, 12.5, 37.5))
        self.assertEqual(ep.OVERPRESSURE_KPA, (7.0, 21.0, 70.0))
        self.assertEqual(ep.TOXIC_LABELS, ("ERPG 1", "ERPG 2", "ERPG 3"))

    def test_higher_flux_reaches_a_shorter_distance(self):
        distances = ep.fire_distances(kind="jet", heat_kj_kg=50000.0, release_rate_kg_s=2.0)
        meters = [d.meters for d in distances]
        self.assertEqual([d.label for d in distances], ["4 kW/m2", "12.5 kW/m2", "37.5 kW/m2"])
        self.assertTrue(meters[0] > meters[1] > meters[2] > 0)
        # 4 kW/m2 는 CAP 5 kW/m2 보다 멀리 나온다
        self.assertGreater(meters[0], fire.jet_fire_distance_m(2.0, 50000.0))

    def test_only_the_verified_overpressure_is_calculated(self):
        seven, twenty_one, seventy = ep.explosion_distances(1000.0, 46000.0)
        self.assertEqual(seven.status, "OK")
        self.assertAlmostEqual(seven.meters, fire.vce_distance_1psi_m(1000.0, 46000.0))
        self.assertEqual((twenty_one.status, twenty_one.meters, seventy.status), ("HOLD", None, "HOLD"))

    def test_erpg_values_come_from_the_kosha_table(self):
        one, two, three = ep.toxic_distances("7782-50-5", 1.0, wind_ms=1.5, stability="F", terrain="rural")
        self.assertEqual((one.status, two.status, three.status), ("OK", "OK", "OK"))
        self.assertTrue(one.meters > two.meters > three.meters > 0)  # 염소 3/9/58 mg/m3
        self.assertIn("C-C-46-2026", two.note)

    def test_missing_levels_use_the_guideline_rule_and_are_labelled_estimates(self):
        # 염화에틸은 ERPG-2만 있다: ERPG-1 = 1/10, ERPG-3 = 5배 (규정 7(2))
        levels = psm_erpg.resolve("75-00-3")
        self.assertEqual([lv.status for lv in levels], ["ESTIMATED", "TABLE", "ESTIMATED"])
        self.assertAlmostEqual(levels[0].mg_m3, levels[1].mg_m3 / 10)
        self.assertAlmostEqual(levels[2].mg_m3, levels[1].mg_m3 * 5)

    def test_not_applicable_is_never_estimated_or_replaced(self):
        levels = psm_erpg.resolve("75-44-5")  # 포스겐 ERPG-1 = NA
        self.assertEqual(levels[0].status, "NOT_APPLICABLE")
        self.assertIsNone(levels[0].mg_m3)
        one = ep.toxic_distances("75-44-5", 1.0, wind_ms=1.5, stability="F", terrain="rural")[0]
        self.assertEqual((one.status, one.meters), ("HOLD", None))

    def test_unknown_substance_is_held_unless_stel_or_twa_is_given(self):
        self.assertTrue(all(lv.status == "HOLD" for lv in psm_erpg.resolve("64-17-5")))
        levels = psm_erpg.resolve("64-17-5", twa_mg_m3=10.0)
        self.assertEqual([lv.status for lv in levels], ["ESTIMATED"] * 3)
        self.assertAlmostEqual(levels[1].mg_m3, 30.0)

    def test_table_is_complete_and_units_are_consistent(self):
        import json
        doc = json.loads(psm_erpg.DATA_FILE.read_text(encoding="utf-8"))
        self.assertEqual(doc["meta"]["count"], len(doc["substances"]))
        self.assertEqual(psm_erpg.resolve("7782-50-5")[1].ppm, 3.0)

    def test_custom_interest_values_need_a_basis(self):
        self.assertEqual(ep.Endpoints().problems(), ())
        self.assertTrue(ep.Endpoints(fire_kw_m2=(5.0, 12.5, 37.5)).problems())
        self.assertEqual(ep.Endpoints(fire_kw_m2=(5.0, 12.5, 37.5), custom_basis="내부 기준").problems(), ())


if __name__ == "__main__":
    unittest.main()
