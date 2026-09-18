from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from engine.stage2.cap_form1_engine import build_cap_form1_data, mass_to_ton, volume_to_m3
from engine.stage2.project import Stage2Project


class CAPForm1EngineTests(unittest.TestCase):
    def _project(self, *, linked: bool = True) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-FORM1",
            company_name="가상화학",
            site_name="제1공장",
            psm_required=False,
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            psm_selected=False,
            cap_selected=True,
            stage1_source_fingerprint="a" * 64 if linked else "",
        )
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{
                "물질명": "염소",
                "CAS 번호": "7782-50-5",
                "함량(%)": 99.9,
                "물리적 상태": "기체",
                "최대보유량": 800,
                "단위": "kg",
            }],
            "USER_CONFIRMED",
        )
        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{
                "설비번호": "V-301",
                "설비명": "염소 공급용기군",
                "설비종류": "압력용기",
                "단위공장·공정": "염소공급",
                "취급물질": "염소",
                "용량": 2.5,
                "용량단위": "m3",
                "최대보유량(kg)": 800,
            }],
            "USER_CONFIRMED",
        )
        project.set_field("cap.business.unit_plant_name", "단위공장명", "제1공장", "USER_CONFIRMED")
        return project

    @staticmethod
    def _screen():
        return SimpleNamespace(
            ready=True,
            blockers=[],
            messages=["direct rules ready"],
            legal_hits=[{
                "source_key": "CAP_QTY_APP3",
                "row_no": 1,
                "product_name": "염소",
                "cas": "7782-50-5",
                "item_no": "1",
                "legal_substance": "염소",
                "variant_type": "BASE",
                "lower_quantity_ton": 0.5,
                "upper_quantity_ton": 2.0,
            }],
        )

    def test_mass_and_volume_units_are_normalized(self):
        self.assertEqual(mass_to_ton(800, "kg"), 0.8)
        self.assertEqual(mass_to_ton(2.5, "ton"), 2.5)
        self.assertEqual(volume_to_m3(2500, "L"), 2.5)
        self.assertEqual(volume_to_m3(2.5, "m3"), 2.5)

    def test_form1_uses_stage1_legal_rule_and_writes_ton_values(self):
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=self._screen()):
            result = build_cap_form1_data(self._project())

        self.assertEqual(result.blockers, ())
        self.assertEqual(result.facility_rows[0]["취급량(ton)"], "0.8")
        self.assertEqual(result.facility_rows[0]["설계용량(m3)"], "2.5")
        row = result.chemical_rows[0]
        self.assertEqual(row["물질구분"], "사고대비물질")
        self.assertEqual(row["사업장 내 최대보유량(ton)"], "0.8")
        self.assertEqual(row["하위규정수량(ton)"], "0.5")
        self.assertEqual(row["상위규정수량(ton)"], "2")
        self.assertEqual(row["규정수량 비교"], "하위 이상·상위 미만")
        self.assertEqual(row["작성수준"], "2군")

    def test_direct_stage2_keeps_final_quantity_basis_fail_closed(self):
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=self._screen()):
            result = build_cap_form1_data(self._project(linked=False))

        self.assertTrue(any("Stage 1 판정과 연결되지 않은" in blocker for blocker in result.blockers))
        self.assertEqual(result.chemical_rows[0]["사업장 내 최대보유량(ton)"], "0.8")

    def test_unresolved_legal_match_keeps_thresholds_blank(self):
        screen = SimpleNamespace(ready=True, blockers=[], messages=[], legal_hits=[])
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen):
            result = build_cap_form1_data(self._project())

        row = result.chemical_rows[0]
        self.assertEqual(row["하위규정수량(ton)"], "")
        self.assertEqual(row["상위규정수량(ton)"], "")
        self.assertTrue(any("별표 1 유해·위험성 그룹" in blocker for blocker in result.blockers))


if __name__ == "__main__":
    unittest.main()
