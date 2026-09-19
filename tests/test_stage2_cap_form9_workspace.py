from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2 import cap_form9_workspace as f9
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from tests import test_stage2_cap_form1_engine as form1_tests

ROOT = Path(__file__).resolve().parents[1]


def _project():
    project = form1_tests.CAPForm1EngineTests()._project()
    rows = ws.facility_editor_rows(project)
    rows[0].update({"설비번호": "TK-1", "설비명": "염소 저장탱크", "시설유형": "저장탱크",
                    "물질성상": "액체", "용량": 2.5, "용량단위": "m3", "비중": 1.4})
    ws.save_facility_rows(project, rows)
    return project


class CAPForm9WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline(self):
        self.assertTrue(ws.load_form_schema(9)["title"].replace(" ", "").endswith(
            guide.form_guidelines()[9].title.replace("ㆍ", "").replace(" ", "")))
        header = " ".join(guide.form_guidelines()[9].table_header(0))
        for label in ("연결구", "압력", "온도", "설계용량", "취급량"):
            self.assertIn(label, header)
        self.assertTrue(all(help_text for _, _, help_text in f9.SPEC_COLUMNS))

    def test_rows_come_from_form1_with_computed_values(self):
        [row] = f9.rows(_project())
        self.assertEqual((row["구분기호"], row["설계용량(m3)"], row["취급량(ton)"]), ("TK-1", "2.5", "3.5"))
        self.assertEqual(row["설계압력"], "")

    def test_missing_specs_are_reported_then_cleared_by_input(self):
        project = _project()
        before = "\n".join(f9.needs(project))
        for label in ("연결구", "설계압력", "운전압력", "설계온도", "운전온도"):
            self.assertIn(label, before)
        [row] = f9.rows(project)
        row.update({"최대 연결구 크기(mm)": "50", "설계압력": "500 kPa", "운전압력": "0.3",
                    "설계온도": "60", "운전온도": "-"})
        self.assertEqual(f9.save_specs(project, [row]), 1)
        after = "\n".join(f9.needs(project))
        for label in ("연결구", "설계압력", "운전압력", "설계온도", "운전온도"):
            self.assertNotIn(f"{label}이 비어", after)

    def test_specs_reach_the_docx_with_unit_conversion(self):
        project = _project()
        [row] = f9.rows(project)
        row.update({"최대 연결구 크기(mm)": "50", "설계압력": "500 kPa", "운전압력": "0.3",
                    "설계온도": "60", "운전온도": "25"})
        f9.save_specs(project, [row])
        table = Document(BytesIO(build_cap_baseline_draft(project))).tables[FORM_TABLE_INDEX["9"][0]]
        text = "\n".join(c.text for r in table.rows for c in r.cells)
        for expected in ("TK-1", "50", "0.5", "0.3", "60", "25", "3.5"):
            self.assertIn(expected, text)

    def test_specs_survive_resaving_the_form1_grid_and_blank_never_erases(self):
        project = _project()
        [row] = f9.rows(project)
        row["설계온도"] = "60"
        f9.save_specs(project, [row])
        ws.save_facility_rows(project, ws.facility_editor_rows(project))
        self.assertEqual(f9.rows(project)[0]["설계온도"], "60")
        row["설계온도"] = ""
        f9.save_specs(project, [row])
        self.assertEqual(f9.rows(project)[0]["설계온도"], "60")

    def test_page_is_wired(self):
        self.assertIn('9: "별지 제9호"', (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
