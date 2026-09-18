from __future__ import annotations

import unittest

from engine.stage2.cap_final_gate import (
    HOLD,
    INFO,
    PASS,
    REVIEW_REQUIRED,
    evaluate_cap_final_gate,
)
from engine.stage2.cross_validation import CrossValidationReport, ValidationIssue
from engine.stage2.project import EvidenceRef, Stage2Project


class CAPFinalGateTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-CAP-FINAL-GATE",
            company_name="테스트화학",
            site_name="제1공장",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        for key, label, value in (
            ("cap.business.submission_type", "제출구분", "신규제출"),
            ("cap.business.submission_reason", "제출 사유", "최초"),
            ("cap.business.other_system_review", "타 제도 심사결과 활용", "미해당"),
            ("cap.business.joint_emergency_plan", "공동비상대응계획", "단독제출"),
        ):
            project.set_field(key, label, value, "USER_CONFIRMED")
        return project

    @staticmethod
    def _clean_report() -> CrossValidationReport:
        return CrossValidationReport(issues=(), checked_rules=10)

    @staticmethod
    def _evidence(name: str = "evidence.pdf") -> EvidenceRef:
        return EvidenceRef(
            source_type="COMPANY_EVIDENCE",
            source_name=name,
            sha256="a" * 64,
            location=f"attachments/{name}",
        )

    def test_registry_final_checkpoints_are_all_evaluated(self):
        result = evaluate_cap_final_gate(self._project(), self._clean_report())

        self.assertEqual(
            [item.key for item in result.checkpoints],
            [
                "cap.final.form_type",
                "cap.final.other_system_review",
                "cap.final.joint_emergency",
                "cap.final.omission_check",
                "cap.final.post_submission",
                "cap.final.revision_map",
            ],
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.hold_count, 0)
        self.assertEqual(result.review_count, 0)
        self.assertEqual(result.checkpoints[4].status, INFO)

    def test_other_system_applicable_without_file_evidence_requires_review(self):
        project = self._project()
        project.set_field(
            "cap.business.other_system_review",
            "타 제도 심사결과 활용",
            "해당 - 공정안전보고서",
            "USER_CONFIRMED",
        )

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.other_system_review")

        self.assertEqual(item.status, REVIEW_REQUIRED)
        self.assertFalse(result.ready)

    def test_other_system_applicable_with_company_file_evidence_passes(self):
        project = self._project()
        project.set_field(
            "cap.business.other_system_review",
            "타 제도 심사결과 활용",
            "해당 - 공정안전보고서",
            "USER_CONFIRMED",
            evidence=[self._evidence("psm_review_result.pdf")],
        )

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.other_system_review")

        self.assertEqual(item.status, PASS)

    def test_joint_submission_without_file_evidence_requires_review(self):
        project = self._project()
        project.set_field(
            "cap.business.joint_emergency_plan",
            "공동비상대응계획",
            "공동제출",
            "USER_CONFIRMED",
        )

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.joint_emergency")

        self.assertEqual(item.status, REVIEW_REQUIRED)
        self.assertFalse(result.ready)

    def test_joint_submission_with_company_file_evidence_passes(self):
        project = self._project()
        project.set_field(
            "cap.business.joint_emergency_plan",
            "공동비상대응계획",
            "공동제출",
            "USER_CONFIRMED",
            evidence=[self._evidence("joint_emergency_plan.pdf")],
        )

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.joint_emergency")

        self.assertEqual(item.status, PASS)

    def test_unresolved_selected_scope_validation_blocks_omission_checkpoint(self):
        project = self._project()
        report = CrossValidationReport(
            issues=(
                ValidationIssue(
                    code="TEST-HOLD",
                    status="HOLD",
                    system="CAP",
                    section="기본정보",
                    legal_item="테스트",
                    message="누락자료",
                ),
            ),
            checked_rules=10,
        )

        result = evaluate_cap_final_gate(project, report)
        item = next(i for i in result.checkpoints if i.key == "cap.final.omission_check")

        self.assertEqual(item.status, HOLD)
        self.assertFalse(result.ready)

    def test_resubmission_without_change_log_keeps_revision_map_in_review(self):
        project = self._project()
        project.set_field(
            "cap.business.submission_type",
            "제출구분",
            "재제출",
            "USER_CONFIRMED",
        )
        project.set_field(
            "cap.business.submission_reason",
            "제출 사유",
            "부적합",
            "USER_CONFIRMED",
        )

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.revision_map")

        self.assertEqual(item.status, REVIEW_REQUIRED)
        self.assertFalse(result.ready)

    def test_psm_only_issue_does_not_fail_cap_omission_checkpoint(self):
        project = self._project()
        project.psm_required = True
        project.psm_selected = True
        report = CrossValidationReport(
            issues=(
                ValidationIssue(
                    code="PSM-ONLY-HOLD",
                    status="HOLD",
                    system="PSM",
                    section="공정안전자료",
                    legal_item="PSM 전용 항목",
                    message="PSM만의 문제",
                ),
            ),
            checked_rules=10,
        )

        result = evaluate_cap_final_gate(project, report)
        item = next(i for i in result.checkpoints if i.key == "cap.final.omission_check")

        self.assertEqual(item.status, PASS)
        self.assertTrue(result.ready)

    def test_common_issue_still_fails_cap_omission_checkpoint(self):
        project = self._project()
        report = CrossValidationReport(
            issues=(
                ValidationIssue(
                    code="COMMON-HOLD",
                    status="HOLD",
                    system="COMMON",
                    section="근거자료 관리",
                    legal_item="공통자료",
                    message="공통 문제",
                ),
            ),
            checked_rules=10,
        )

        result = evaluate_cap_final_gate(project, report)
        item = next(i for i in result.checkpoints if i.key == "cap.final.omission_check")

        self.assertEqual(item.status, HOLD)
        self.assertFalse(result.ready)

    def test_missing_submission_type_fails_closed(self):
        project = self._project()
        project.fields.pop("cap.business.submission_type")

        result = evaluate_cap_final_gate(project, self._clean_report())
        item = next(i for i in result.checkpoints if i.key == "cap.final.form_type")

        self.assertEqual(item.status, HOLD)
        self.assertFalse(result.ready)


if __name__ == "__main__":
    unittest.main()
