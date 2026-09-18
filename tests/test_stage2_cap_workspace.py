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
        self.assertEqual(rows[0]["최대보유량(kg)"], 800)

    def test_edit_flows_to_form_tables_and_docx(self):
        project = _project()
        rows = ws.facility_editor_rows(project)
        rows[0]["설비명"] = "수정된 염소탱크"
        rows[0]["용량"] = 4000
        rows[0]["용량단위"] = "L"
        self.assertEqual(ws.save_facility_rows(project, rows), 1)
        self.assertEqual(project.get_field(ws.FACILITY_FIELD_KEY).status, "USER_CONFIRMED")

        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
            docx = build_cap_baseline_draft(project)

        self.assertEqual(form.facility_rows[0]["취급시설"], "수정된 염소탱크")
        self.assertEqual(form.facility_rows[0]["설계용량(m3)"], "4")
        text = "\n".join(
            cell.text for row in Document(BytesIO(docx)).tables[6].rows for cell in row.cells
        )
        self.assertIn("수정된 염소탱크", text)

    def test_blank_rows_are_not_saved_and_needs_list_only_missing_facts(self):
        project = _project()
        self.assertEqual(ws.save_facility_rows(project, [{"설비명": "", "용량": ""}]), 0)
        rows = ws.facility_editor_rows(project)
        rows[0]["용량"] = ""
        ws.save_facility_rows(project, rows)
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=_screen()):
            form = ws.resolve_form1(project)
        self.assertEqual(len(form.needs), 1)
        self.assertIn("설계용량", form.needs[0])

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
