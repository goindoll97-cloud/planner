from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2 import cap_form11_workspace as f11
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


SPECS = {"작동시간": "30초 이내", "측정방식": "전기화학식", "경보 설정값": "0.5 ppm", "경보 위치": "제어실",
         "연동여부": "예", "연동 설비·조치": "입구 밸브 차단", "정밀도": "±3% F.S.", "유지관리": "월 1회 점검"}


class CAPForm11WorkspaceTests(unittest.TestCase):
    def test_schema_follows_guideline(self):
        self.assertTrue(ws.load_form_schema(11)["title"].endswith(guide.form_guidelines()[11].title))
        header = " ".join(guide.form_guidelines()[11].table_header(0))
        for label in ("감지대상", "설치위치", "작동시간", "측정방식", "경보 설정값", "연동여부", "정밀도", "유지관리"):
            self.assertIn(label, header)
        self.assertTrue(all(c[3] for c in f11.COLUMNS))

    def test_skeleton_is_proposed_from_facilities_and_skips_covered_ones(self):
        project = _project()
        [row] = f11.skeleton(project)
        self.assertEqual((row["감지기 번호"], row["검출대상 물질"], row["설치위치"]), ("GD-001", "염소", "TK-1"))
        f11.save(project, [row])
        self.assertEqual(f11.skeleton(project), [])

    def test_specs_are_never_invented_so_needs_are_listed(self):
        project = _project()
        f11.save(project, f11.skeleton(project))
        joined = "\n".join(f11.needs(project))
        for label in ("작동시간", "측정방식", "경보설정값", "정밀도", "유지관리"):
            self.assertIn(label, joined)

    def test_completed_rows_pass_and_reach_the_docx(self):
        project = _project()
        [row] = f11.skeleton(project)
        row.update(SPECS)
        f11.save(project, [row])
        self.assertEqual(f11.needs(project), [])
        table = Document(BytesIO(build_cap_baseline_draft(project))).tables[FORM_TABLE_INDEX["11"][0]]
        text = "\n".join(c.text for r in table.rows for c in r.cells)
        for expected in ("GD-001", "염소", "TK-1", "30초 이내", "0.5 ppm", "±3% F.S.", "입구 밸브 차단"):
            self.assertIn(expected, text)

    def test_portable_rows_are_kept_out_of_the_fixed_form(self):
        project = _project()
        [row] = f11.skeleton(project)
        row.update(SPECS)
        f11.save(project, [row, dict(row, **{"감지기 번호": "GD-002", "설치형태": "휴대식"})])
        saved = f11.saved_rows(project)
        self.assertEqual(saved[1]["설치형태"], "휴대식")
        self.assertEqual(f11.needs(project), [])

    def test_blank_rows_are_dropped(self):
        self.assertEqual(f11.save(_project(), [{"감지기 번호": "", "설치위치": ""}]), 0)

    def test_page_is_wired(self):
        self.assertIn(11, __import__("ui.cap_forms_registry", fromlist=["x"]).FORM_NUMBERS)


if __name__ == "__main__":
    unittest.main()
