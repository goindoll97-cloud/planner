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


from engine.stage2 import psm_later_form_engine as later  # noqa: E402


def _filled(spec, index=1):
    return {c.id: f"{c.id[:6]}{index}" for c in spec.columns}


class AllTableFormsTests(unittest.TestCase):
    def test_every_form_saved_here_passes_the_existing_readiness_check(self):
        for form_no, spec in tables.SPECS.items():
            with self.subTest(form=form_no):
                project = _toxic_project()
                tables.save(project, form_no, [_filled(spec)])
                self.assertEqual(tables.needs(project, form_no) if not spec.conditional else
                                 tables.needs(project, form_no), [], form_no)
                if form_no in later.CONDITIONAL_FORMS:
                    tables.save_applicability(project, form_no, tables.APPLICABLE, "옥내 설비 있음")
                if form_no in ("14", "16", "17"):
                    readiness = core.build_psm_core_form_readiness(project, form_no)
                else:
                    readiness = later.build_psm_later_form_readiness(project, form_no)
                self.assertEqual(readiness.blockers, (), (form_no, readiness.blockers))
                self.assertEqual(len(readiness.rows), 1)

    def test_not_applicable_forms_need_nothing_and_pass(self):
        for form_no in later.CONDITIONAL_FORMS:
            with self.subTest(form=form_no):
                project = _toxic_project()
                tables.save_applicability(project, form_no, tables.NOT_APPLICABLE, "해당 설비 없음")
                self.assertEqual(tables.needs(project, form_no), [])
                self.assertTrue(later.build_psm_later_form_readiness(project, form_no).ready)

    def test_one_of_groups_are_enforced(self):
        project = _toxic_project()
        row = _filled(tables.INTERLOCK)
        for column in tables._SETPOINTS:
            row[column] = ""
        tables.save(project, "17-2", [row])
        self.assertTrue(any("설정값" in n for n in tables.needs(project, "17-2")))

    def test_gas_alarm_table_is_prefilled_from_the_cap_detectors(self):
        project = _toxic_project()
        project.set_field("cap.safety.gas_detection", "감지시설", [{
            "감지기 번호": "GD-1", "검출대상 물질": "염소", "설치위치": "TK-1", "작동시간": "30초", "측정방식": "전기화학식",
            "경보 설정값": "0.5 ppm", "경보 위치": "제어실", "정밀도": "±3%", "연동 설비·조치": "차단밸브 폐쇄",
            "유지관리": "월 1회"}], "USER_CONFIRMED")
        [row] = tables.rows(project, "17-5")
        self.assertEqual((row["감지기번호"], row["설치장소"], row["경보기 위치"], row["경보시 조치내용"]),
                         ("GD-1", "TK-1", "제어실", "차단밸브 폐쇄"))
        self.assertTrue(tables.needs(project, "17-5"))  # 저장 전에는 미완료로 본다

    def test_every_form_screen_renders(self):
        project = _project()
        for form_no in tables.SPECS:
            with self.subTest(form=form_no):
                at = _run(project, form_no)
                self.assertFalse(at.exception, form_no)
