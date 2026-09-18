from __future__ import annotations

import unittest

from engine.stage2.cap_form2_engine import (
    HOLD,
    NOT_APPLICABLE,
    PASS,
    REVIEW_REQUIRED,
    build_cap_form2_readiness,
)
from engine.stage2.project import Stage2Project


class CAPForm2ReadinessTests(unittest.TestCase):
    def _project(self, submission_type: str, reason: str = "") -> Stage2Project:
        project = Stage2Project(
            project_id="S2-CAP-FORM2",
            company_name="테스트화학",
            site_name="제1공장",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field(
            "cap.business.submission_type",
            "제출구분",
            submission_type,
            "USER_CONFIRMED",
        )
        if reason:
            project.set_field(
                "cap.business.submission_reason",
                "제출 사유",
                reason,
                "USER_CONFIRMED",
            )
        return project

    @staticmethod
    def _valid_log():
        return [{
            "일자": "2026-09-18",
            "변경항목": "장치·설비 목록 및 명세",
            "변경의 종류": "설비변경",
            "변경 내용(변경전 → 변경후)": "TK-101 → TK-101A",
            "후속조치": "관련 도면 및 명세 갱신",
            "담당자": "홍길동",
        }]

    def test_initial_new_submission_does_not_require_change_log(self):
        project = self._project("신규제출", "최초")

        result = build_cap_form2_readiness(project)

        self.assertEqual(result.status, NOT_APPLICABLE)
        self.assertTrue(result.ready)
        self.assertFalse(result.blockers)

    def test_change_submission_requires_confirmed_change_log(self):
        project = self._project("변경제출")

        result = build_cap_form2_readiness(project)

        self.assertEqual(result.status, HOLD)
        self.assertFalse(result.ready)
        self.assertTrue(any("변경내역 관리대장" in item for item in result.blockers))

    def test_change_submission_passes_with_complete_confirmed_log(self):
        project = self._project("변경제출")
        project.set_field(
            "cap.prevention.change_log",
            "변경내역 관리대장",
            self._valid_log(),
            "USER_CONFIRMED",
        )

        result = build_cap_form2_readiness(project)

        self.assertEqual(result.status, PASS)
        self.assertTrue(result.ready)

    def test_incomplete_change_log_fails_closed(self):
        project = self._project("변경제출")
        row = self._valid_log()[0].copy()
        row["후속조치"] = ""
        project.set_field(
            "cap.prevention.change_log",
            "변경내역 관리대장",
            [row],
            "USER_CONFIRMED",
        )

        result = build_cap_form2_readiness(project)

        self.assertEqual(result.status, HOLD)
        self.assertTrue(any("후속조치" in item for item in result.blockers))

    def test_unconfirmed_change_log_does_not_satisfy_change_submission(self):
        project = self._project("변경제출")
        project.set_field(
            "cap.prevention.change_log",
            "변경내역 관리대장",
            self._valid_log(),
            "HOLD",
        )

        self.assertEqual(build_cap_form2_readiness(project).status, HOLD)

    def test_resubmission_without_log_requires_human_review(self):
        project = self._project("재제출", "부적합")

        result = build_cap_form2_readiness(project)

        self.assertEqual(result.status, REVIEW_REQUIRED)
        self.assertFalse(result.ready)

    def test_resubmission_with_confirmed_log_is_accepted_as_company_confirmation(self):
        project = self._project("재제출", "부적합")
        project.set_field(
            "cap.prevention.change_log",
            "변경내역 관리대장",
            self._valid_log(),
            "USER_CONFIRMED",
        )

        self.assertEqual(build_cap_form2_readiness(project).status, PASS)

    def test_missing_submission_type_requires_review(self):
        project = Stage2Project(
            project_id="S2-CAP-FORM2-NO-TYPE",
            company_name="테스트화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )

        self.assertEqual(build_cap_form2_readiness(project).status, REVIEW_REQUIRED)


if __name__ == "__main__":
    unittest.main()
