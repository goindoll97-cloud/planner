from __future__ import annotations

import unittest

from engine.stage2 import psm_core_form_engine as core
from engine.stage2 import psm_table_workspace as tables
from engine.stage2 import statutory_report as report
from tests.test_psm_workspace_page import _project, _run
from tests.test_stage2_cap_dispersion import _toxic_project

ROW = {"기계번호": "P-101", "기계명": "염소 이송 펌프", "명세": "원심펌프 10 m3/h", "주요재질": "SUS316",
       "전동기용량": "7.5", "방호·보호장치 종류": "EOCR", "비고": "인버터"}


class Form14Tests(unittest.TestCase):
    def test_saved_rows_reach_the_statutory_form_and_pass_readiness(self):
        project = _toxic_project()
        self.assertEqual(tables.save(project, "14", [ROW, {c: "" for c in ROW}]), 1)  # 빈 행은 버린다
        [row] = report._psm_form14_rows(project)
        self.assertEqual(row[:5], ["P-101", "염소 이송 펌프", "원심펌프 10 m3/h", "SUS316", "7.5"])
        self.assertTrue(core.build_psm_core_form_readiness(project, "14").ready)

    def test_needs_lists_missing_cells_and_duplicates(self):
        project = _toxic_project()
        self.assertIn("행이 없습니다", tables.needs(project, "14")[0])
        tables.save(project, "14", [dict(ROW, 주요재질=""), dict(ROW)])
        text = "\n".join(tables.needs(project, "14"))
        self.assertIn("1행", text)
        self.assertIn("주요재질", text)
        self.assertIn("두 번 이상", text)
        tables.save(project, "14", [dict(ROW, 비고="")])
        self.assertEqual(tables.needs(project, "14"), [])  # 비고는 선택

    def test_screen_renders_and_shows_what_is_missing(self):
        project = _project()
        tables.save(project, "14", [dict(ROW, 전동기용량="")])
        at = _run(project, "14")
        self.assertFalse(at.exception)
        self.assertTrue(any("더 필요" in i.value for i in at.info))
        self.assertTrue(any("전동기용량" in w.value for w in at.markdown))


if __name__ == "__main__":
    unittest.main()
