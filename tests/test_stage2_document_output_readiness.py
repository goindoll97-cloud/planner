from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.stage2.cross_validation import CrossValidationReport
from engine.stage2.document_output_readiness import evaluate_document_output_readiness
from engine.stage2.project import Stage2Project


class DocumentOutputReadinessTests(unittest.TestCase):
    @staticmethod
    def _project(*, psm: bool = True, cap: bool = False) -> Stage2Project:
        return Stage2Project(
            project_id="S2-DOCUMENT-OUTPUT",
            company_name="테스트화학",
            psm_required=psm,
            cap_required=cap,
            cap_group="1군" if cap else "",
            scope_confirmed=True,
            psm_selected=psm,
            cap_selected=cap,
        )

    @staticmethod
    def _report() -> CrossValidationReport:
        return CrossValidationReport(issues=(), checked_rules=10)

    @staticmethod
    def _system_gate(*, ready: bool = True, system: str = "PSM"):
        return SimpleNamespace(
            ready=ready,
            system_label="공정안전보고서" if system == "PSM" else "화학사고예방관리계획서",
            hold_count=0 if ready else 1,
            review_count=0,
        )

    @staticmethod
    def _cap_gate(*, ready: bool = True):
        return SimpleNamespace(
            ready=ready,
            hold_count=0 if ready else 1,
            review_count=0,
        )

    def test_psm_authoring_label_requires_stage4_and_psm_system_gate(self):
        project = self._project(psm=True)
        with (
            patch(
                "engine.stage2.document_output_readiness.validation_confirmed",
                return_value=True,
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_system_final_gate",
                return_value=self._system_gate(ready=True, system="PSM"),
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_cap_final_gate"
            ) as cap_gate_mock,
        ):
            result = evaluate_document_output_readiness(project, "PSM", self._report())

        self.assertTrue(result.final_ready)
        self.assertTrue(result.stage4_confirmed)
        self.assertTrue(result.system_gate.ready)
        self.assertTrue(result.cap_manual_gate_ready)
        self.assertIsNone(result.cap_gate)
        self.assertEqual(result.reasons, ())
        cap_gate_mock.assert_not_called()

    def test_stage4_confirmation_alone_cannot_label_incomplete_psm_as_authoring_ready(self):
        project = self._project(psm=True)
        with (
            patch(
                "engine.stage2.document_output_readiness.validation_confirmed",
                return_value=True,
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_system_final_gate",
                return_value=self._system_gate(ready=False, system="PSM"),
            ),
        ):
            result = evaluate_document_output_readiness(project, "PSM", self._report())

        self.assertFalse(result.final_ready)
        self.assertTrue(result.stage4_confirmed)
        self.assertTrue(any("작성완성도·자동검증" in reason for reason in result.reasons))

    def test_current_stage4_fingerprint_is_required_even_when_all_gates_pass(self):
        project = self._project(psm=True)
        with (
            patch(
                "engine.stage2.document_output_readiness.validation_confirmed",
                return_value=False,
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_system_final_gate",
                return_value=self._system_gate(ready=True, system="PSM"),
            ),
        ):
            result = evaluate_document_output_readiness(project, "PSM", self._report())

        self.assertFalse(result.final_ready)
        self.assertFalse(result.stage4_confirmed)
        self.assertTrue(any("4단계" in reason for reason in result.reasons))

    def test_cap_requires_both_system_gate_and_cap_manual_gate(self):
        project = self._project(psm=False, cap=True)
        cap_gate = self._cap_gate(ready=False)
        with (
            patch(
                "engine.stage2.document_output_readiness.validation_confirmed",
                return_value=True,
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_system_final_gate",
                return_value=self._system_gate(ready=True, system="CAP"),
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_cap_final_gate",
                return_value=cap_gate,
            ),
        ):
            result = evaluate_document_output_readiness(project, "CAP", self._report())

        self.assertFalse(result.final_ready)
        self.assertTrue(result.system_gate.ready)
        self.assertFalse(result.cap_manual_gate_ready)
        self.assertIs(result.cap_gate, cap_gate)
        self.assertTrue(any("최종 제출 체크포인트" in reason for reason in result.reasons))

    def test_cap_is_authoring_ready_only_when_all_cap_checks_pass(self):
        project = self._project(psm=False, cap=True)
        with (
            patch(
                "engine.stage2.document_output_readiness.validation_confirmed",
                return_value=True,
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_system_final_gate",
                return_value=self._system_gate(ready=True, system="CAP"),
            ),
            patch(
                "engine.stage2.document_output_readiness.evaluate_cap_final_gate",
                return_value=self._cap_gate(ready=True),
            ),
        ):
            result = evaluate_document_output_readiness(project, "CAP", self._report())

        self.assertTrue(result.final_ready)
        self.assertEqual(result.reasons, ())

    def test_unselected_document_fails_closed(self):
        project = self._project(psm=True, cap=False)

        with self.assertRaises(ValueError):
            evaluate_document_output_readiness(project, "CAP", self._report())


if __name__ == "__main__":
    unittest.main()
