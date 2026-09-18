from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.stage2.cross_validation import CrossValidationReport, ValidationIssue
from engine.stage2.project import Stage2Project
from engine.stage2.system_final_gate import (
    HOLD,
    PASS,
    REVIEW_REQUIRED,
    evaluate_system_final_gate,
)


class SystemFinalGateTests(unittest.TestCase):
    def _project(self, *, psm: bool = True, cap: bool = False) -> Stage2Project:
        return Stage2Project(
            project_id="S2-SYSTEM-FINAL-GATE",
            company_name="테스트화학",
            psm_required=psm,
            cap_required=cap,
            cap_group="1군" if cap else "",
            scope_confirmed=True,
            psm_selected=psm,
            cap_selected=cap,
        )

    @staticmethod
    def _report(*issues: ValidationIssue) -> CrossValidationReport:
        return CrossValidationReport(issues=tuple(issues), checked_rules=10)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_missing_required_content_blocks_final_readiness_even_when_cross_validation_is_clean(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=False,
            state="HOLD",
            completion_pct=62.5,
            blocking_labels=("공정흐름도", "안전운전계획"),
        )
        project = self._project(psm=True)

        result = evaluate_system_final_gate(project, "PSM", self._report())

        self.assertFalse(result.ready)
        completeness = next(i for i in result.checkpoints if i.key == "psm.final.completeness")
        validation = next(i for i in result.checkpoints if i.key == "psm.final.validation")
        self.assertEqual(completeness.status, HOLD)
        self.assertEqual(validation.status, PASS)
        self.assertIn("62.5", completeness.message)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_ai_draft_completeness_requires_human_review(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=False,
            state="REVIEW_REQUIRED",
            completion_pct=95.0,
            blocking_labels=("비상조치계획",),
        )
        project = self._project(psm=True)

        result = evaluate_system_final_gate(project, "PSM", self._report())

        item = next(i for i in result.checkpoints if i.key == "psm.final.completeness")
        self.assertEqual(item.status, REVIEW_REQUIRED)
        self.assertFalse(result.ready)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_foreign_system_issue_does_not_block_psm_gate(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=True,
            state="READY",
            completion_pct=100.0,
            blocking_labels=(),
        )
        project = self._project(psm=True, cap=True)
        report = self._report(
            ValidationIssue(
                code="CAP-ONLY-HOLD",
                status="HOLD",
                system="CAP",
                section="기본정보",
                legal_item="CAP 전용 항목",
                message="CAP만의 문제",
            )
        )

        result = evaluate_system_final_gate(project, "PSM", report)

        self.assertTrue(result.ready)
        validation = next(i for i in result.checkpoints if i.key == "psm.final.validation")
        self.assertEqual(validation.status, PASS)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_common_issue_blocks_psm_gate(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=True,
            state="READY",
            completion_pct=100.0,
            blocking_labels=(),
        )
        project = self._project(psm=True)
        report = self._report(
            ValidationIssue(
                code="EVIDENCE-HASH-INVALID",
                status="HOLD",
                system="COMMON",
                section="근거자료 관리",
                legal_item="공통 첨부자료",
                message="SHA-256 확인 필요",
            )
        )

        result = evaluate_system_final_gate(project, "PSM", report)

        self.assertFalse(result.ready)
        validation = next(i for i in result.checkpoints if i.key == "psm.final.validation")
        self.assertEqual(validation.status, HOLD)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_psm_statutory_form_hold_blocks_final_gate(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=True,
            state="READY",
            completion_pct=100.0,
            blocking_labels=(),
        )
        project = self._project(psm=True)
        report = self._report(
            ValidationIssue(
                code="PSM-FORM12-1",
                status="HOLD",
                system="PSM",
                section="사업개요",
                legal_item="별지 제12호서식 사업개요",
                message="필수 작성칸 누락",
            )
        )

        result = evaluate_system_final_gate(project, "PSM", report)

        self.assertFalse(result.ready)
        item = next(i for i in result.checkpoints if i.key == "psm.final.statutory_forms")
        self.assertEqual(item.status, HOLD)
        self.assertIn("별지 제12호서식", item.message)

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_cap_gate_does_not_get_psm_statutory_checkpoint(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=True,
            state="READY",
            completion_pct=100.0,
            blocking_labels=(),
        )
        project = self._project(psm=False, cap=True)

        result = evaluate_system_final_gate(project, "CAP", self._report())

        self.assertTrue(result.ready)
        self.assertFalse(any(i.key == "psm.final.statutory_forms" for i in result.checkpoints))

    @patch("engine.stage2.system_final_gate.report_generation_status")
    def test_ready_requires_both_completeness_and_scoped_validation(self, status_mock):
        status_mock.return_value = SimpleNamespace(
            final_ready=True,
            state="READY",
            completion_pct=100.0,
            blocking_labels=(),
        )
        project = self._project(psm=True)

        result = evaluate_system_final_gate(project, "PSM", self._report())

        self.assertTrue(result.ready)
        self.assertTrue(all(i.status == PASS for i in result.checkpoints))


if __name__ == "__main__":
    unittest.main()
