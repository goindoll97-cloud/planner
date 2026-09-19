from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import unittest

from docx import Document

from engine.stage2 import cap_form2_workspace as f2
from engine.stage2 import cap_form4_workspace as f4
from engine.stage2 import cap_form5_workspace as f5
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from tests import test_stage2_cap_form1_engine as form1_tests


def _project():
    project = form1_tests.CAPForm1EngineTests()._project()
    rows = ws.facility_editor_rows(project)
    rows[0].update({"단위공장·공정": "염소공장", "설비번호": "TK-1", "설비명": "염소 저장탱크", "시설유형": "저장탱크",
                    "물질성상": "액체", "용량": 2.5, "용량단위": "m3", "비중": 1.4})
    rows.append({"단위공장·공정": "암모니아공장", "설비번호": "TK-2", "설비명": "암모니아 저장탱크",
                 "취급물질": "암모니아", "시설유형": "저장탱크", "물질성상": "액체", "용량": 1, "용량단위": "m3", "비중": 0.7})
    rows.append({"설비번호": "R-1", "설비명": "반응기", "취급물질": "염소", "시설유형": "제조·사용시설",
                 "물질성상": "액체", "용량": 1, "용량단위": "m3", "비중": 1.4})
    ws.save_facility_rows(project, rows)
    f2.save_submission(project, "신규제출", "최초", "염소공장")
    return project


def _tables(project):
    screen = form1_tests.CAPForm1EngineTests._screen()
    with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=screen):
        return Document(BytesIO(build_cap_baseline_draft(project))).tables


def _text(table):
    return "\n".join(c.text for r in table.rows for c in r.cells)


class CAPForm5WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline(self):
        self.assertTrue(ws.load_form_schema(5)["title"].endswith(guide.form_guidelines()[5].title))

    def test_counts_only_include_this_unit_and_unnamed_facilities(self):
        project = _project()
        self.assertEqual(dict(f5.unit_counts(project)), {"저장탱크": 1, "반응시설": 1})
        self.assertEqual(dict(f4.equipment_counts(project)), {"저장탱크": 2, "반응시설": 1})  # 별지 제4호는 사업장 전체
        self.assertEqual(f5.other_units(project), ["암모니아공장"])

    def test_unit_chemical_rows_sum_this_units_holdings(self):
        project = _project()
        with patch("engine.stage2.cap_form1_engine.screen_facility_stage", return_value=form1_tests.CAPForm1EngineTests._screen()):
            rows = f5.unit_chemical_rows(project)
        self.assertEqual([r["물질명"] for r in rows], ["염소"])
        self.assertEqual(rows[0]["사업장 내 최대보유량(ton)"], "4.9")  # 2.5*1.4 + 1*1.4

    def test_form5_docx_is_filtered_while_form4_stays_site_wide(self):
        project = _project()
        f4.save_inputs(project, "전체 구성", "원료 → 반응 → 출하", "")
        f5.save_overview(project, "염소공장 구성")
        tables = _tables(project)
        form4 = _text(tables[FORM_TABLE_INDEX["4"][0]])
        form5 = _text(tables[FORM_TABLE_INDEX["5"][0]])
        self.assertIn("☒ 저장탱크 (2)기", form4)
        self.assertIn("☒ 저장탱크 (1)기", form5)
        self.assertIn("염소공장 구성", form5)
        self.assertIn("원료 → 반응 → 출하", form5)
        self.assertNotIn("암모니아", form5)

    def test_name_not_in_grid_means_no_filtering(self):
        project = _project()
        f2.save_submission(project, "신규제출", "최초", "다른이름")
        self.assertEqual(dict(f5.unit_counts(project)), {"저장탱크": 2, "반응시설": 1})

    def test_missing_items(self):
        project = _project()
        self.assertEqual(f5.missing(project), ["단위공장 구성", "공정개요(별지 제4호에서 입력)"])

    def test_page_offers_form5(self):
        page = (Path(__file__).resolve().parents[1] / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn(5, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)


if __name__ == "__main__":
    unittest.main()
