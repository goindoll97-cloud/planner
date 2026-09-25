from __future__ import annotations

from io import BytesIO
import unittest

from docx import Document

from engine.stage2 import cap_form2_workspace as f2
from engine.stage2 import cap_guideline as guide
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import FORM_TABLE_INDEX, build_cap_baseline_draft
from tests import test_stage2_cap_form1_engine as form1_tests


def _project():
    return form1_tests.CAPForm1EngineTests()._project()


def _tables(project):
    return Document(BytesIO(build_cap_baseline_draft(project))).tables


def _text(table):
    return "\n".join(cell.text for row in table.rows for cell in row.cells)


LOG = [{"일자": "2026-05-01", "변경항목": "취급시설", "변경의 종류": "㈎ 취급시설 변경",
        "변경 내용(변경전 → 변경후)": "저장탱크 2m3 → 3m3", "후속조치": "㈎ 변경제출", "담당자": "안전팀 홍길동"}]


class CAPForm2WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline_and_every_column_has_help(self):
        schema = ws.load_form_schema(2)
        self.assertTrue(schema["title"].endswith(guide.form_guidelines()[2].title))
        columns = ws.section(2, "change_log")["columns"]
        self.assertEqual([c["id"] for c in columns], list(f2.LOG_COLUMNS))
        self.assertTrue(all(c.get("help") for c in columns))
        change_kind = next(column for column in columns if column["id"] == "변경의 종류")
        follow_up = next(column for column in columns if column["id"] == "후속조치")
        self.assertEqual(tuple(change_kind["options"]), f2.CHANGE_TYPES)
        self.assertEqual(tuple(follow_up["options"]), f2.FOLLOW_UPS)
        self.assertEqual(len(f2.CHANGE_TYPES), 7)
        self.assertIn("변경 전과 변경 후", next(c["help"] for c in columns if c["id"].startswith("변경 내용")))
        item_help = next(c["help"] for c in columns if c["id"] == "변경항목")
        self.assertIn("「화학물질관리법 시행규칙」 별표 4", item_help)

    def test_change_log_accepts_multiple_legal_categories_as_text(self):
        project = _project()
        row = LOG[0] | {
            "변경항목": "장치·설비 목록 및 명세 / 설비배치도",
            "변경의 종류": "㈎ 시설규모 변경 / ㈏ 시설위치 변경",
            "후속조치": "㈎ 변경제출 / ㈑ 변경허가",
        }
        f2.save_change_log(project, [row])
        saved = f2.change_log_rows(project)[0]
        self.assertEqual(saved["변경의 종류"], "㈎ 시설규모 변경 / ㈏ 시설위치 변경")
        self.assertEqual(saved["후속조치"], "㈎ 변경제출 / ㈑ 변경허가")

    def test_choice_values_are_cleaned_for_plain_text_workbook_cells(self):
        self.assertEqual(f2._clean(["㈎ 변경제출", "㈑ 변경허가"]), "㈎ 변경제출 / ㈑ 변경허가")

    def test_new_first_submission_does_not_need_form2(self):
        project = _project()
        f2.save_submission(project, "신규제출", "최초", "염소 공장")
        state = f2.resolve_form2(project)
        self.assertFalse(state.applies)
        self.assertTrue(state.readiness.ready)

    def test_unknown_submission_type_is_undetermined(self):
        self.assertIsNone(f2.resolve_form2(_project()).applies)

    def test_change_submission_needs_a_complete_log(self):
        project = _project()
        f2.save_submission(project, "변경제출", "", "염소 공장")
        state = f2.resolve_form2(project)
        self.assertTrue(state.applies)
        self.assertTrue(state.readiness.blockers)
        f2.save_change_log(project, LOG + [{"일자": "", "담당자": ""}])
        self.assertEqual(len(f2.change_log_rows(project)), 1)
        self.assertEqual(f2.resolve_form2(project).readiness.blockers, ())

    def test_entries_reach_form2_and_form3_in_the_docx(self):
        project = _project()
        f2.save_submission(project, "변경제출", "부적합", "염소 공장")
        f2.save_change_log(project, LOG)
        tables = _tables(project)
        form2_log = _text(tables[FORM_TABLE_INDEX["2"][1]])
        self.assertIn("저장탱크 2m3 → 3m3", form2_log)
        self.assertIn("안전팀 홍길동", form2_log)
        form3 = _text(tables[FORM_TABLE_INDEX["3"][0]])
        self.assertIn("염소 공장", form3)  # 단위공장명 entered once, shown in 별지 제3호
        self.assertIn("☒ 변경제출", form3)
        self.assertIn("☒ 부적합", form3)

    def test_first_new_submission_leaves_log_table_empty(self):
        project = _project()
        f2.save_submission(project, "신규제출", "최초", "")
        f2.save_change_log(project, LOG)
        self.assertNotIn("저장탱크 2m3", _text(_tables(project)[FORM_TABLE_INDEX["2"][1]]))

    def test_page_offers_form2(self):
        from pathlib import Path

        page = (Path(__file__).resolve().parents[1] / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("cap_form{form_no}_view", page)


if __name__ == "__main__":
    unittest.main()
