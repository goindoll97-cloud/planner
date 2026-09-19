from __future__ import annotations

import unittest

from engine.stage2 import cap_fire as fire
from engine.stage2 import psm_endpoints as ep


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

    def test_erpg_never_falls_back_to_another_indicator(self):
        record = ep.ErpgRecord("75-35-4", "1,1-Dichloroethylene", {2: 500.0, 3: 1000.0}, {1: "Insufficient Data"})
        one, two, three = ep.toxic_distance_inputs(record)
        self.assertEqual((one.status, two.status, three.status), ("HOLD", "OK", "OK"))
        self.assertIn("Insufficient Data", one.note)
        self.assertTrue(all(d.status == "HOLD" for d in ep.toxic_distance_inputs(None)))

    def test_custom_interest_values_need_a_basis(self):
        self.assertEqual(ep.Endpoints().problems(), ())
        self.assertTrue(ep.Endpoints(fire_kw_m2=(5.0, 12.5, 37.5)).problems())
        self.assertEqual(ep.Endpoints(fire_kw_m2=(5.0, 12.5, 37.5), custom_basis="내부 기준").problems(), ())


if __name__ == "__main__":
    unittest.main()
