from __future__ import annotations

import json
import unittest

from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_endpoints as ep
from engine.stage2.project import Stage2Project


class EndpointTableTests(unittest.TestCase):
    def test_tables_are_complete_against_the_guideline_serial_numbers(self):
        meta = json.loads(ep.DATA_PATH.read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["row_counts"], meta["table_max_serial"])
        self.assertEqual({k: len(v) for k, v in ep.load_tables().items()}, meta["row_counts"])

    def test_known_values_from_the_guideline(self):
        chlorine = ep.endpoint_for("7782-50-5")
        self.assertEqual((chlorine.table, chlorine.value, chlorine.unit), ("ERPG-2", 3.0, "ppm"))
        self.assertEqual(ep.endpoint_for("7664-41-7").value, 150.0)  # 암모니아 ERPG-2
        self.assertEqual(ep.endpoint_for("108-88-3").value, 300.0)  # 톨루엔은 AEGL-2(560)보다 ERPG-2 우선
        self.assertEqual(ep.load_tables()["IDLH"]["1333-82-0"]["unit"], "mg/m3")  # 원문 단위: mg Cr(VI)/m3

    def test_priority_falls_back_erpg_aegl_pac_idlh_with_tenth_of_idlh(self):
        tables = ep.load_tables()
        aegl_cas = next(c for c in tables["AEGL-2"] if c not in tables["ERPG-2"])
        aegl_only = ep.endpoint_for(aegl_cas)
        self.assertEqual((aegl_only.table, aegl_only.value), ("AEGL-2", tables["AEGL-2"][aegl_cas]["value"]))
        pac_cas = next(c for c in tables["PAC-2"] if c not in tables["ERPG-2"] and c not in tables["AEGL-2"])
        self.assertEqual(ep.endpoint_for(pac_cas).table, "PAC-2")
        idlh_cas = next(c for c in tables["IDLH"] if all(c not in tables[t] for t in ("ERPG-2", "AEGL-2", "PAC-2")))
        chosen = ep.endpoint_for(idlh_cas)
        self.assertEqual((chosen.table, chosen.factor), ("IDLH", 0.1))
        self.assertAlmostEqual(chosen.endpoint_value, chosen.value * 0.1)

    def test_unknown_cas_has_no_endpoint(self):
        self.assertIsNone(ep.endpoint_for("000-00-0"))

    def test_unit_conversion_follows_the_guideline_formula(self):
        self.assertAlmostEqual(ep.mg_m3_to_ppm(ep.ppm_to_mg_m3(3.0, 70.9), 70.9), 3.0)
        self.assertAlmostEqual(ep.ppm_to_mg_m3(24.45, 100.0), 100.0)

    def test_fallback_values_follow_the_guideline_order(self):
        self.assertEqual(ep.fallback_endpoint_mg_m3(lc50_mg_m3=1000, lc50_minutes=30), (100.0, "0.1 × LC50(30분 노출)"))
        self.assertEqual(ep.fallback_endpoint_mg_m3(lc50_mg_m3=1000, lc50_minutes=240)[0], 200.0)
        self.assertEqual(ep.fallback_endpoint_mg_m3(lclo_mg_m3=50)[0], 50.0)
        self.assertAlmostEqual(ep.fallback_endpoint_mg_m3(ld50_mg_kg=100)[0], 100 * 70 / 0.4 * 0.01)
        self.assertAlmostEqual(ep.fallback_endpoint_mg_m3(ldlo_mg_kg=100)[0], 100 * 70 / 0.4 * 0.1)
        self.assertIsNone(ep.fallback_endpoint_mg_m3())

    def test_parser_reads_wrapped_values_and_two_unit_values(self):
        text = "\n".join([
            "연번 화학물질명 CAS number AEGL",
            "31 O-Isopropyl methyl phosphonofiuoridate 107-44-8 0.0060 ppm",
            "0.035 mg/m3",
            "32 Toluene 108-88-3 560 ppm",
            "출처) AEGL",
        ])
        parsed = ep.parse_guideline_text(text)["AEGL-2"]
        self.assertEqual(parsed["107-44-8"]["value"], 0.006)
        self.assertEqual(parsed["107-44-8"]["alternative"], "0.035 mg/m3")
        self.assertEqual(parsed["108-88-3"]["value"], 560.0)


class ExposureLevelCandidateTests(unittest.TestCase):
    def _project(self):
        project = Stage2Project(project_id="S2-EP", company_name="테스트", cap_required=True, scope_confirmed=True,
                                cap_selected=True)
        project.set_field("inventory.chemicals", "화학물질 목록", [
            {"물질명": "염소", "CAS 번호": "7782-50-5", "함량(%)": "99"},
            {"물질명": "혼합제품", "CAS 번호": "7782-50-5, 7664-41-7"},
        ], "VERIFIED")
        return project

    def test_exposure_level_is_proposed_for_single_substances_without_any_kosha_call(self):
        found = {c.field: c for c in chem.candidates(self._project())}
        self.assertEqual(found["위험노출수준"].value, "ERPG-2 3 ppm")
        self.assertEqual(found["위험노출수준"].source, chem.GUIDELINE_SOURCE)
        self.assertEqual(len(chem.guideline_candidates(self._project())), 1)  # 혼합제품은 제외

    def test_accepting_a_guideline_value_does_not_claim_a_kosha_sds(self):
        project = self._project()
        self.assertGreater(chem.apply_candidates(project, ["7782-50-5"]), 0)
        row = project.get_field("cap.chemical.details").value[0]
        self.assertEqual(row["위험노출수준"], "ERPG-2 3 ppm")
        self.assertFalse(row.get("SDS 파일명"))


if __name__ == "__main__":
    unittest.main()
