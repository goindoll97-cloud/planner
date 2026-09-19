from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_form6_workspace as f6
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from engine.stage2.project import Stage2Project
from tests.test_stage2_cap_minimal_input import _kosha, _project


class CAPForm6WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline_and_columns_have_help(self):
        self.assertTrue(ws.load_form_schema(6)["title"].endswith(guide.form_guidelines()[6].title))
        self.assertTrue(all(help_text for _, _, help_text in f6.PROPERTY_COLUMNS))
        header = " ".join(guide.form_guidelines()[6].table_header(0))
        for label in ("물질 구분", "고유 번호", "물질 상태", "독성구분", "위험노출수준", "허용농도값", "부식성"):
            self.assertIn(label, header)

    def test_property_rows_start_with_identity_and_empty_properties(self):
        rows = f6.property_rows(_project())
        self.assertEqual(rows[0]["물질명"], "톨루엔")
        self.assertEqual(rows[0]["CAS 번호"], "108-88-3")
        self.assertEqual(rows[0]["물질상태"], "")

    def test_kosha_then_manual_edit_reach_the_docx_and_needs_shrink(self):
        project = _project()
        _, before = f6.legal_rows(project)
        chem.fetch_references(project, lookup=_kosha)
        chem.apply_candidates(project, ["108-88-3"])
        rows = f6.property_rows(project)
        self.assertEqual(rows[0]["물질상태"], "액체")
        rows[0]["증기압"] = "28.4"
        rows[0]["부식성"] = "무"
        self.assertGreater(f6.save_properties(project, rows), 0)
        _, after = f6.legal_rows(project)
        self.assertLess(len(after), len(before))
        joined = "\n".join(after)
        self.assertNotIn("'증기압'", joined)
        self.assertNotIn("'부식성'", joined)
        table = Document(BytesIO(build_cap_baseline_draft(project))).tables[FORM_TABLE_INDEX["6"][0]]
        text = "\n".join(c.text for r in table.rows for c in r.cells)
        for expected in ("액체", "28.4", "무"):
            self.assertIn(expected, text)

    def test_blank_cells_never_erase_saved_values(self):
        project = _project()
        rows = f6.property_rows(project)
        rows[0]["비중"] = "0.87"
        f6.save_properties(project, rows)
        rows[0]["비중"] = ""
        f6.save_properties(project, rows)
        self.assertEqual(f6.property_rows(project)[0]["비중"], "0.87")

    def test_legal_identity_is_not_asked(self):
        self.assertFalse({"물질구분", "고유번호"} & set(f6.COLUMN_IDS))

    def test_pages_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn(6, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)
        self.assertIn("cap_kosha_panel", (root / "ui/cap_form6_view.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
