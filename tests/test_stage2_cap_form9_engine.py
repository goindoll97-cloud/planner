from __future__ import annotations

from io import BytesIO
import unittest

from openpyxl import load_workbook

from engine.stage2.cap_form9_engine import build_cap_form9_data
from engine.stage2.project import Stage2Project
from engine.stage2.workbook_enhancements import build_enhanced_integrated_authoring_workbook


class CAPForm9EngineTests(unittest.TestCase):
    def _project(self, *, connection: object = 50, capacity=20000, capacity_unit="L") -> Stage2Project:
        project = Stage2Project(
            project_id="S2-FORM9",
            company_name="테스트화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{
                "물질명": "톨루엔",
                "CAS 번호": "108-88-3",
                "함량(%)": 99.5,
                "물리적 상태": "액체",
                "최대보유량": 15000,
                "단위": "kg",
            }],
            "USER_CONFIRMED",
        )
        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{
                "설비번호": "TK-101",
                "설비명": "톨루엔 저장탱크",
                "설비종류": "저장탱크",
                "취급물질": "톨루엔",
                "용량": capacity,
                "용량단위": capacity_unit,
                "설계압력": "490 kPa",
                "운전압력": "1.5 bar",
                "설계온도": "80 ℃",
                "운전온도": "30 ℃",
                "최대보유량(kg)": 15000,
                "최대 연결구 크기(mm)": connection,
                "P&ID 번호": "PID-101",
            }],
            "USER_CONFIRMED",
        )
        return project

    def test_form9_normalizes_statutory_units(self):
        result = build_cap_form9_data(self._project())
        self.assertEqual(result.blockers, ())
        row = result.rows[0]
        self.assertEqual(row["CAS No."], "108-88-3")
        self.assertEqual(row["설계용량(m3)"], "20")
        self.assertEqual(row["취급량(ton)"], "15")
        self.assertEqual(row["연결구 크기(mm)"], "50")
        self.assertEqual(row["압력(MPa)-설계"], "0.49")
        self.assertEqual(row["압력(MPa)-운전"], "0.15")
        self.assertEqual(row["온도(℃)-설계"], "80")
        self.assertEqual(row["온도(℃)-운전"], "30")

    def test_flow_rate_is_not_copied_into_design_volume(self):
        result = build_cap_form9_data(self._project(capacity=25, capacity_unit="m3/h"))
        self.assertEqual(result.rows[0]["설계용량(m3)"], "-")
        self.assertFalse(any("설계용량" in blocker for blocker in result.blockers))

    def test_missing_connection_size_stays_blocking(self):
        result = build_cap_form9_data(self._project(connection=""))
        self.assertTrue(any("최대 연결구 크기" in blocker for blocker in result.blockers))
        self.assertEqual(result.rows[0]["연결구 크기(mm)"], "")

    def test_explicit_not_applicable_is_distinct_from_missing(self):
        result = build_cap_form9_data(self._project(connection="해당 없음"))
        self.assertEqual(result.rows[0]["연결구 크기(mm)"], "-")
        self.assertFalse(any("최대 연결구 크기" in blocker for blocker in result.blockers))

    def test_integrated_workbook_exposes_connection_size_input(self):
        wb = load_workbook(BytesIO(build_enhanced_integrated_authoring_workbook(self._project(), example=False)))
        headers = [str(cell.value or "") for cell in wb["03_설비정보"][4]]
        self.assertIn("최대 연결구 크기(mm)", headers)


if __name__ == "__main__":
    unittest.main()
