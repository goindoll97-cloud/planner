from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from docx import Document

from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft
from engine.stage2.cap_calc import internal_volume_m3
from tests import test_stage2_cap_form1_engine as form1_tests

ROOT = Path(__file__).resolve().parents[1]


def _project():
    return form1_tests.CAPForm1EngineTests()._project()


def _screen():
    return form1_tests.CAPForm1EngineTests._screen()


class CAPCalcTests(unittest.TestCase):
    def test_geometry_volumes(self):
        self.assertAlmostEqual(internal_volume_m3("vertical_cylinder", diameter_m=2.0, height_m=3.0), 3.14159265 * 3.0, places=5)
        self.assertAlmostEqual(internal_volume_m3("sphere", diameter_m=2.0), 4.18879, places=4)
        self.assertEqual(internal_volume_m3("box", length_m=2, width_m=3, height_m=4), 24)

    def test_unusable_inputs_return_none(self):
        self.assertIsNone(internal_volume_m3("sphere", diameter_m=0))
        self.assertIsNone(internal_volume_m3("box", length_m=1, width_m=1))
        self.assertIsNone(internal_volume_m3("unknown", diameter_m=1))


class CAPWorkspaceTests(unittest.TestCase):
    def test_schema_covers_form1_tables_and_every_column_has_help(self):
        schema = ws.load_form_schema(1)
        self.assertEqual(schema["baseline_tables"], [6, 7, 8])
        for section in schema["sections"]:
            for column in section.get("columns", []):
                self.assertTrue(column.get("help"), f"{section['id']}.{column['id']} has no help text")

    def test_facility_grid_is_seeded_from_confirmed_facilities(self):
        rows = ws.facility_editor_rows(_project())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["설비번호"], "V-301")
        self.assertEqual(rows[0]["취급물질"], "염소")
        self.assertEqual(rows[0]["용량"], 2.5)

    def _filled(self, project, **overrides):
        rows = ws.facility_editor_rows(project)
        rows[0].update({"시설유형": "저장탱크", "물질성상": "액체", "용량": 2.5, "용량단위": "m3", "비중": 1.4})
        rows[0].update(overrides)
        return rows

    def test_max_holding_is_design_capacity_times_specific_gravity(self):
        project = _project()
        [result] = ws.compute_holdings(project, self._filled(project))
        self.assertEqual(result.problem, "")
        self.assertAlmostEqual(result.ton, 3.5)
        self.assertIn("설계용량 × 비중", result.basis)

    def test_liter_capacity_is_converted(self):
        project = _project()
        [result] = ws.compute_holdings(project, self._filled(project, 용량=2500, 용량단위="L"))
        self.assertAlmostEqual(result.ton, 3.5)

    def test_excluded_facility_types_are_zero_and_left_out_of_the_form(self):
        project = _project()
        rows = self._filled(project, 시설유형="사외배관")
        [result] = ws.compute_holdings(project, rows)
        self.assertTrue(result.excluded)
        ws.save_facility_rows(project, rows)
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
        self.assertEqual(form.facility_rows, ())

    def test_gas_is_not_estimated_and_asks_for_a_direct_value(self):
        project = _project()
        rows = self._filled(project, 물질성상="기체·고압가스")
        self.assertEqual(ws.extra_fields_for(rows[0]), ["직접확인 최대보유량", "질량단위", "직접확인 근거"])
        [asked] = ws.compute_holdings(project, rows)
        self.assertIsNone(asked.ton)
        rows[0].update({"직접확인 최대보유량": 800, "질량단위": "kg", "직접확인 근거": "운전압력 기준 산정"})
        [answered] = ws.compute_holdings(project, rows)
        self.assertAlmostEqual(answered.ton, 0.8)

    def test_reaction_process_asks_for_reference_content(self):
        row = {"시설유형": "제조·사용시설", "물질성상": "액체", "공정유형": "반응"}
        self.assertEqual(ws.extra_fields_for(row), ["공정유형", "별표4 기준함량(%)", "함량근거"])
        self.assertEqual(ws.extra_fields_for({"시설유형": "저장탱크", "물질성상": "액체"}), [])
        self.assertEqual(ws.extra_fields_for({"시설유형": "보관시설", "물질성상": "고체"}),
                         ["보관계획도 최대량", "일일최대보관량", "질량단위"])

    def test_edit_flows_to_form_tables_and_docx(self):
        project = _project()
        rows = self._filled(project, 설비명="수정된 염소탱크", 용량=4000, 용량단위="L", 비중=1.5)
        self.assertEqual(ws.save_facility_rows(project, rows), 1)
        self.assertEqual(project.get_field(ws.FACILITY_FIELD_KEY).status, "USER_CONFIRMED")

        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
            docx = build_cap_baseline_draft(project)

        self.assertEqual(form.facility_rows[0]["취급시설"], "수정된 염소탱크")
        self.assertEqual(form.facility_rows[0]["설계용량(m3)"], "4")
        self.assertEqual(form.facility_rows[0]["취급량(ton)"], "6")
        text = "\n".join(
            cell.text for row in Document(BytesIO(docx)).tables[6].rows for cell in row.cells
        )
        self.assertIn("수정된 염소탱크", text)

    def test_missing_core_answers_are_reported_per_facility(self):
        project = _project()
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
        self.assertEqual(len(form.needs), 1)
        self.assertTrue(form.needs[0])

    def test_blank_rows_are_not_saved(self):
        self.assertEqual(ws.save_facility_rows(_project(), [{"설비명": "", "용량": ""}]), 0)

    def test_steps_explain_the_core_terms_in_plain_language(self):
        steps = ws.steps(1)
        self.assertEqual([step["id"] for step in steps], ["scope", "chemicals", "facilities", "result"])
        terms = " ".join(item["term"] for step in steps for item in step["explain"])
        for needed in ("최대보유량이란?", "규정수량이란?", "1군의 조건"):
            self.assertIn(needed, terms)

    def test_result_sentences_are_one_line_per_substance(self):
        lines = ws.result_sentences([
            {"물질명": "염소", "사업장 내 최대보유량(ton)": "0.8", "하위규정수량(ton)": "0.5",
             "상위규정수량(ton)": "2", "규정수량 비교": "하위 이상·상위 미만"},
            {"물질명": "메탄올", "사업장 내 최대보유량(ton)": "", "하위규정수량(ton)": "", "상위규정수량(ton)": ""},
        ])
        self.assertIn("0.8톤", lines[0])
        self.assertIn("하위 이상·상위 미만", lines[0])
        self.assertIn("계산하지 못했습니다", lines[1])

    def test_kosha_result_is_only_a_candidate(self):
        from engine.kosha_msds import KOSHAMSDSResult

        fake = KOSHAMSDSResult("MATCHED", "7782-50-5", "ok", chemical_name="염소")
        with patch("engine.kosha_msds.lookup_by_cas", return_value=fake):
            found = ws.kosha_name_candidate("7782-50-5")
        self.assertEqual(found["chemical_name"], "염소")
        self.assertEqual(found["origin"], ws.ORIGIN_LOOKUP)

    def test_page_is_wired_into_navigation(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.Page("ui/cap_workspace_page.py"', app)
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("help=col.get(\"help\")", page)
        self.assertIn("build_cap_baseline_draft", page)


if __name__ == "__main__":
    unittest.main()
