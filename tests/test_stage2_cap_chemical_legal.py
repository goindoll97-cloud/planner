from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

import pandas as pd

from engine.stage2.cap_chemical_legal import build_cap_chemical_legal_data
from engine.stage2.project import Stage2Project


class CAPChemicalLegalTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-FORM6",
            company_name="가상화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
            stage1_source_fingerprint="a" * 64,
        )
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{
                "물질명": "시험물질",
                "CAS 번호": "123-45-6",
                "함량(%)": 99,
                "물리적 상태": "액체",
                "최대보유량": 1000,
                "단위": "kg",
            }],
            "USER_CONFIRMED",
        )
        return project

    @staticmethod
    def _app2_table() -> pd.DataFrame:
        return pd.DataFrame([
            {
                "record_key": "10:1",
                "item_no": "10",
                "hazard_seq": "1",
                "designation_id": "2026-1-0010",
                "substance_name": "시험물질",
                "direct_cas": "123-45-6",
                "scope_type": "DIRECT_CAS",
                "hazard_category": "인체급성유해성",
                "content_threshold_pct": "25",
                "active": "true",
                "source_key": "CAP_QTY_APP2",
            },
        ])

    @staticmethod
    def _form1():
        return SimpleNamespace(
            chemical_rows=({
                "물질명": "시험물질",
                "CAS No.": "123-45-6",
                "물질구분": "사고대비물질",
            },),
            blockers=(),
        )

    def test_form6_uses_official_app2_unique_id_and_combines_material_classes(self):
        with (
            patch(
                "engine.stage2.cap_chemical_legal.load_approved_scope_tables",
                return_value=({"CAP_QTY_APP2": self._app2_table()}, []),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.screen_cap_scope_candidates_from_tables",
                return_value=pd.DataFrame(),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.build_cap_form1_data",
                return_value=self._form1(),
            ),
        ):
            result = build_cap_chemical_legal_data(self._project())

        self.assertEqual(result.blockers, ())
        row = result.rows[0]
        self.assertEqual(row["고유번호"], "2026-1-0010")
        self.assertEqual(row["물질구분"], "인체급성유해성물질 / 사고대비물질")
        self.assertNotIn("용액", row["물질구분"])

    def test_solution_specific_app2_row_stays_fail_closed_until_condition_is_confirmed(self):
        table = self._app2_table()
        table = pd.concat([
            table,
            pd.DataFrame([{
                "record_key": "10:2",
                "item_no": "10",
                "hazard_seq": "2",
                "designation_id": "2026-1-0010",
                "substance_name": "시험물질",
                "direct_cas": "123-45-6",
                "scope_type": "DIRECT_CAS",
                "hazard_category": "용액",
                "content_threshold_pct": "",
                "active": "true",
                "source_key": "CAP_QTY_APP2",
            }]),
        ], ignore_index=True)

        with (
            patch(
                "engine.stage2.cap_chemical_legal.load_approved_scope_tables",
                return_value=({"CAP_QTY_APP2": table}, []),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.screen_cap_scope_candidates_from_tables",
                return_value=pd.DataFrame(),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.build_cap_form1_data",
                return_value=self._form1(),
            ),
        ):
            result = build_cap_chemical_legal_data(self._project())

        self.assertEqual(result.rows[0].get("고유번호", ""), "")
        self.assertTrue(any("용액" in blocker for blocker in result.blockers))

    def test_accident_appendix_item_number_is_never_used_as_unique_id(self):
        with (
            patch(
                "engine.stage2.cap_chemical_legal.load_approved_scope_tables",
                return_value=({}, ["CAP_QTY_APP2"]),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.build_cap_form1_data",
                return_value=self._form1(),
            ),
        ):
            result = build_cap_chemical_legal_data(self._project())

        row = result.rows[0]
        self.assertEqual(row.get("고유번호", ""), "")
        self.assertEqual(row["물질구분"], "사고대비물질")
        self.assertTrue(any("사고대비물질 별표 3 연번을 고유번호로 대신 쓰지 않습니다" in x for x in result.blockers))

    def test_concentration_below_app2_threshold_does_not_promote_classification(self):
        project = self._project()
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{
                "물질명": "시험물질",
                "CAS 번호": "123-45-6",
                "함량(%)": 10,
                "물리적 상태": "액체",
                "최대보유량": 1000,
                "단위": "kg",
            }],
            "USER_CONFIRMED",
        )
        no_accident = SimpleNamespace(chemical_rows=({},), blockers=())
        with (
            patch(
                "engine.stage2.cap_chemical_legal.load_approved_scope_tables",
                return_value=({"CAP_QTY_APP2": self._app2_table()}, []),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.screen_cap_scope_candidates_from_tables",
                return_value=pd.DataFrame(),
            ),
            patch(
                "engine.stage2.cap_chemical_legal.build_cap_form1_data",
                return_value=no_accident,
            ),
        ):
            result = build_cap_chemical_legal_data(project)

        self.assertEqual(result.rows[0].get("고유번호", ""), "")
        self.assertTrue(result.blockers)


if __name__ == "__main__":
    unittest.main()
