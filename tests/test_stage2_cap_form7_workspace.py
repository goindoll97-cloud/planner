from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2 import cap_form6_workspace as f6
from engine.stage2 import cap_form7_workspace as f7
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from tests.test_stage2_cap_authoritative import Stage2CAPAuthoritativeSourceTests


def _project():
    """Toluene with a stored KOSHA reference; 별지 제6호 물성 accepted from it."""
    project = Stage2CAPAuthoritativeSourceTests()._project()
    chem.apply_candidates(project, ["108-88-3"])
    return project


class CAPForm7WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline(self):
        self.assertTrue(ws.load_form_schema(7)["title"].endswith(guide.form_guidelines()[7].title))
        headings = " ".join(cell for row in guide.form_guidelines()[7].tables[0] for cell in row)
        for label in ("인체유해성", "물리적 위험성", "환경유해성", "출처", "선정 사유"):
            self.assertIn(label, headings)

    def test_representatives_are_suggested_from_form6_facts(self):
        project = _project()
        [suggestion] = f7.suggest_representatives(project)
        self.assertEqual(suggestion.cas, "108-88-3")
        self.assertEqual(set(suggestion.kinds), {f7.FIRE, f7.TOXIC})
        self.assertIn("1.2%", suggestion.reason)

    def test_no_suggestion_without_form6_facts(self):
        project = Stage2CAPAuthoritativeSourceTests()._project()
        self.assertEqual(f7.suggest_representatives(project), [])

    def test_draft_uses_kosha_text_and_keeps_reason_editable(self):
        project = _project()
        draft = f7.draft_row(project, "108-88-3", "시험물질", "사유")
        self.assertIn("중추신경계", draft["인체유해성"])
        self.assertIn("수생생물", draft["환경유해성"])
        self.assertEqual(draft["선정 사유"], "사유")
        self.assertTrue(draft["SDS 개정일"])

    def test_saved_selection_reaches_form7_docx_with_reused_holding(self):
        project = _project()
        [suggestion] = f7.suggest_representatives(project)
        row = f7.draft_row(project, suggestion.cas, suggestion.name, suggestion.reason)
        self.assertEqual(f7.save_rows(project, [row, {"물질명": "", "CAS 번호": ""}]), 1)
        self.assertEqual(project.get_field(f7.HAZARD_KEY).status, "USER_CONFIRMED")
        table = Document(BytesIO(build_cap_baseline_draft(project))).tables[FORM_TABLE_INDEX["7"][0]]
        text = "\n".join(c.text for r in table.rows for c in r.cells)
        self.assertIn("중추신경계", text)
        self.assertIn("폭발한계 하한이 1.2%", text)
        joined = "\n".join(f7.needs(project))
        self.assertNotIn("'인체유해성'이 비어", joined)
        self.assertNotIn("'선정 사유'이 비어", joined)

    def test_law_allows_two_representatives_and_both_reach_the_docx(self):
        project = _project()
        first = f7.draft_row(project, "108-88-3", "시험물질", "사유1")
        second = dict(first, **{"CAS 번호": "67-64-1", "물질명": "아세톤", "선정 사유": "사유2"})
        f7.save_rows(project, [first, second])
        self.assertFalse(any("2종" in item and "입력되어" in item for item in f7.needs(project)))
        doc = Document(BytesIO(build_cap_baseline_draft(project)))
        texts = [" ".join(c.text for r in t.rows for c in r.cells) for t in doc.tables]
        self.assertTrue(any("시험물질" in t and "사유1" in t for t in texts))
        self.assertTrue(any("아세톤" in t and "사유2" in t for t in texts))

    def test_more_than_two_representatives_is_flagged_by_the_enforcement_rule(self):
        project = _project()
        row = f7.draft_row(project, "108-88-3", "시험물질", "사유")
        f7.save_rows(project, [row, dict(row, **{"CAS 번호": "67-64-1", "물질명": "아세톤"}),
                               dict(row, **{"CAS 번호": "71-43-2", "물질명": "벤젠"})])
        self.assertTrue(any("시행규칙 별표 4" in item and "2종" in item for item in f7.needs(project)))

    def test_suggestion_follows_the_law_two_substances_one_per_accident_type(self):
        project = _project()
        chem.apply_candidates(project, ["108-88-3"])
        rows = f6.property_rows(project)
        other = dict(rows[0], **{"물질명": "아세톤", "CAS 번호": "67-64-1", "폭발한계 하한": "2.6", "독성구분": "구분 4"})
        third = dict(rows[0], **{"물질명": "벤젠", "CAS 번호": "71-43-2", "폭발한계 하한": "1.3", "독성구분": "구분 3"})
        details = project.get_field("cap.chemical.details").value + [other, third]
        project.set_field("cap.chemical.details", "화학물질 상세", details, "USER_CONFIRMED")
        picked = f7.suggest_representatives(project)
        self.assertEqual(len(picked), 2)
        self.assertEqual({s.cas for s in picked}, {"108-88-3", "71-43-2"})  # 최저 폭발하한 1.2 / 최저 독성구분 2

    def test_page_is_wired(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn(7, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)


if __name__ == "__main__":
    unittest.main()
