from __future__ import annotations

from types import SimpleNamespace
from io import BytesIO

from docx import Document
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


    def test_form1_combines_direct_rule_verified_sds_app1_and_explicit_missing_basis(self):
        project = self._project()
        project.set_field("inventory.facilities", "설비목록", [], "USER_CONFIRMED")
        project.set_field("inventory.chemicals", "회사 물질목록", [
            {"물질명": "가상 톨루엔", "CAS 번호": "108-88-3", "함량(%)": 99.5,
             "최대보유량": 37000, "단위": "kg"},
            {"물질명": "가상 액화암모니아", "CAS 번호": "7664-41-7", "함량(%)": 99.9,
             "최대보유량": 1000, "단위": "kg",
             "별표1 SDS 분류(그룹|구분;...)": "급성독성(흡입)|2;인화성 액체|2",
             "별표1 SDS 분류 전체 확인": "예",
             "SDS 파일명": "암모니아_회사SDS.pdf", "SDS 개정일": "2026-01-02"},
            {"물질명": "가상 염산 35%", "CAS 번호": "7647-01-0", "함량(%)": 35,
             "최대보유량": 5000, "단위": "kg"},
        ], "USER_CONFIRMED")
        screen = SimpleNamespace(
            ready=True, blockers=[], messages=[], row_numbers=[1],
            legal_hits=[{"source_key": "CAP_QTY_APP3", "row_no": 1,
                         "lower_quantity_ton": 10, "upper_quantity_ton": 100}],
        )
        app1 = SimpleNamespace(ready=True, matched=True, blockers=[],
                               lower_quantity_ton=1.0, upper_quantity_ton=20.0)
        import pandas as pd
        scope = {"CAP_QTY_APP2": pd.DataFrame({
            "scope_type": ["DIRECT_CAS"], "direct_cas": ["108-88-3"]
        })}
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen), \
             patch("engine.stage2.cap_form1_engine.load_approved_scope_tables", return_value=(scope, [])), \
             patch("engine.stage2.cap_form1_engine.select_app1_quantities", return_value=app1) as selected:
            result = build_cap_form1_data(project)

        self.assertEqual(len(result.chemical_rows), 3)
        direct, app1_row, unresolved = result.chemical_rows
        self.assertEqual((direct["하위규정수량(ton)"], direct["상위규정수량(ton)"]), ("10", "100"))
        self.assertEqual((app1_row["하위규정수량(ton)"], app1_row["상위규정수량(ton)"]), ("1", "20"))
        self.assertEqual(app1_row["법령DB"], "CAP_QTY_APP1")
        self.assertEqual(app1_row["사업장 내 최대보유량(ton)"], "1")
        selected.assert_called_once_with([("급성독성(흡입)", 2), ("인화성 액체", 2)])
        self.assertEqual(unresolved["사업장 내 최대보유량(ton)"], "5")
        self.assertEqual(unresolved["하위규정수량(ton)"], "")
        self.assertEqual(unresolved["하위규정수량 표시"], "[확인 필요: 규정수량]")
        self.assertEqual(unresolved["상위규정수량 표시"], "[확인 필요: 규정수량]")
        self.assertTrue(any("가상 염산 35%" in b and "구분 근거" in b for b in result.blockers))

    def test_unresolved_direct_variant_never_gets_appendix1_as_a_backdoor(self):
        p = self._project()
        row = p.get_field("inventory.chemicals").value[0].copy()
        row.update({"별표1 SDS 분류(그룹|구분;...)": "급성독성(흡입)|2",
                    "별표1 SDS 분류 전체 확인": "예",
                    "SDS 파일명": "company_SDS.pdf", "SDS 개정일": "2026-01-01"})
        p.set_field("inventory.chemicals", "시험자료", [row], "USER_CONFIRMED")
        screen = SimpleNamespace(ready=True, blockers=["염소: 용액 적용조건 미확정"],
                                 messages=[], row_numbers=[1], legal_hits=[])
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen), \
             patch("engine.stage2.cap_form1_engine.load_approved_scope_tables", return_value=({}, [])), \
             patch("engine.stage2.cap_form1_engine.select_app1_quantities") as selected:
            out = build_cap_form1_data(p)
        selected.assert_not_called()
        self.assertEqual(out.chemical_rows[0]["상위규정수량(ton)"], "")
        self.assertIn("적용조건", out.chemical_rows[0]["규정수량 확인사유"])

    def test_missing_approved_appendix2_scope_never_allows_app1_fallback(self):
        p = self._project()
        row = p.get_field("inventory.chemicals").value[0].copy()
        row.update({"별표1 SDS 분류(그룹|구분;...)": "급성독성(흡입)|2",
                    "별표1 SDS 분류 전체 확인": "예",
                    "SDS 파일명": "company_SDS.pdf", "SDS 개정일": "2026-01-01"})
        p.set_field("inventory.chemicals", "시험자료", [row], "USER_CONFIRMED")
        screen = SimpleNamespace(ready=True, blockers=[], messages=[], row_numbers=[], legal_hits=[])
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen), \
             patch("engine.stage2.cap_form1_engine.load_approved_scope_tables", return_value=({}, ["CAP_QTY_APP2"])), \
             patch("engine.stage2.cap_form1_engine.select_app1_quantities") as selected:
            result = build_cap_form1_data(p)
        selected.assert_not_called()
        self.assertIn("포괄 규제범위", result.chemical_rows[0]["규정수량 확인사유"])


    def test_appendix1_requires_full_sds_and_valid_pair_format(self):
        from engine.stage2.cap_form1_engine import _app1_sds_pairs
        sample = {
            "별표1 SDS 분류 전체 확인": "예",
            "별표1 SDS 분류(그룹|구분;...)": "급성독성(흡입)|2;인화성 액체|2",
            "SDS 파일명": "확인된 회사SDS.pdf", "SDS 개정일": "2026-08-01",
        }
        self.assertEqual(_app1_sds_pairs(sample)[0],
                         [("급성독성(흡입)", 2), ("인화성 액체", 2)])
        self.assertTrue(_app1_sds_pairs({**sample, "별표1 SDS 분류 전체 확인": ""})[1])
        self.assertTrue(_app1_sds_pairs({**sample, "별표1 SDS 분류(그룹|구분;...)": "위험함"})[1])
        self.assertTrue(_app1_sds_pairs({**sample, "SDS 파일명": ""})[1])

    def test_form1_statutory_docx_both_renderers_show_verified_and_pending_quantities(self):
        from engine.stage2 import cap_baseline_docx as old
        from engine.stage2 import cap_catalog_docx as catalog
        from engine.stage2 import cap_form1_engine as form1
        from engine.stage2.cap_form1_engine import CAPForm1Data

        p = self._project()
        data = CAPForm1Data(
            facility_rows=({"단위공장": "제1공장", "유해화학물질": "톨루엔",
                             "CAS No.": "108-88-3", "함량(%)": 99.5,
                             "구분기호": "TK-01", "취급시설": "저장탱크",
                             "설계용량(m3)": "20", "취급량(ton)": "15"},),
            chemical_rows=(
                {"물질명": "톨루엔", "CAS No.": "108-88-3",
                 "물질구분": "사고대비물질", "사업장 내 최대보유량(ton)": "15",
                 "하위규정수량(ton)": "10", "상위규정수량(ton)": "100",
                 "하위규정수량 표시": "10", "상위규정수량 표시": "100"},
                {"물질명": "가상 염산", "CAS No.": "7647-01-0",
                 "사업장 내 최대보유량(ton)": "5",
                 "하위규정수량(ton)": "", "상위규정수량(ton)": "",
                 "하위규정수량 표시": "[확인 필요: 규정수량]",
                 "상위규정수량 표시": "[확인 필요: 규정수량]"},
            ),
            blockers=("가상 염산: 법령분류 확인 필요",),
            messages=(), legal_lookup_ready=True,
        )
        with patch.object(old, "build_cap_form1_data", return_value=data), \
             patch.object(form1, "build_cap_form1_data", return_value=data):
            for build in (old.build_cap_baseline_draft, catalog.build_cap_draft):
                doc = Document(BytesIO(build(p)))
                table = doc.tables[old.form_table_index_for(doc)["1"][1]]
                self.assertEqual(table.cell(2, 5).text, "10")
                self.assertEqual(table.cell(2, 6).text, "100")
                self.assertEqual(table.cell(3, 0).text, "가상 염산")
                self.assertEqual(table.cell(3, 3).text, "5")
                self.assertEqual(table.cell(3, 5).text, "[확인 필요: 규정수량]")
                self.assertEqual(table.cell(3, 6).text, "[확인 필요: 규정수량]")
                self.assertEqual(table.cell(0, 5).text, "구분 근거")

    def test_unresolved_legal_match_keeps_thresholds_blank(self):
        screen = SimpleNamespace(ready=True, blockers=[], messages=[], legal_hits=[])
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen):
            result = build_cap_form1_data(self._project())

        row = result.chemical_rows[0]
        self.assertEqual(row["하위규정수량(ton)"], "")
        self.assertEqual(row["상위규정수량(ton)"], "")
        self.assertTrue(any("별지 제1호 구분 근거" in blocker and "규정수량" in blocker
                            for blocker in result.blockers))


if __name__ == "__main__":
    unittest.main()
