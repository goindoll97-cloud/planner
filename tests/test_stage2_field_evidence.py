from __future__ import annotations

import unittest

from engine.stage2.field_evidence import attach_evidence_to_confirmed_field
from engine.stage2.project import EvidenceRef, Stage2Project


class Stage2FieldEvidenceTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-FIELD-EVIDENCE",
            company_name="테스트화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field(
            "cap.business.other_system_review",
            "타 제도 심사결과 활용 여부",
            "해당 - 공정안전보고서",
            "USER_CONFIRMED",
            note="회사 담당자 확인",
        )
        return project

    @staticmethod
    def _evidence() -> EvidenceRef:
        return EvidenceRef(
            source_type="COMPANY_EVIDENCE",
            source_name="psm_review_result.pdf",
            sha256="a" * 64,
            location="attachments/psm_review_result.pdf",
        )

    def test_attach_preserves_confirmed_value_and_status(self):
        project = self._project()

        linked = attach_evidence_to_confirmed_field(
            project,
            "cap.business.other_system_review",
            self._evidence(),
            note="최종 제출 증빙 연결",
        )

        record = project.get_field("cap.business.other_system_review")
        self.assertTrue(linked)
        self.assertEqual(record.value, "해당 - 공정안전보고서")
        self.assertEqual(record.status, "USER_CONFIRMED")
        self.assertEqual(len(record.evidence), 1)
        self.assertIn("최종 제출 증빙 연결", record.note)

    def test_duplicate_sha_is_not_added_twice(self):
        project = self._project()
        evidence = self._evidence()

        self.assertTrue(
            attach_evidence_to_confirmed_field(
                project,
                "cap.business.other_system_review",
                evidence,
            )
        )
        self.assertFalse(
            attach_evidence_to_confirmed_field(
                project,
                "cap.business.other_system_review",
                evidence,
            )
        )
        self.assertEqual(
            len(project.get_field("cap.business.other_system_review").evidence),
            1,
        )

    def test_missing_field_fails_closed(self):
        project = self._project()

        with self.assertRaises(ValueError):
            attach_evidence_to_confirmed_field(
                project,
                "cap.business.joint_emergency_plan",
                self._evidence(),
            )

    def test_hold_field_cannot_be_completed_by_file_upload_alone(self):
        project = self._project()
        project.set_field(
            "cap.business.other_system_review",
            "타 제도 심사결과 활용 여부",
            "해당 - 공정안전보고서",
            "HOLD",
        )

        with self.assertRaises(ValueError):
            attach_evidence_to_confirmed_field(
                project,
                "cap.business.other_system_review",
                self._evidence(),
            )


if __name__ == "__main__":
    unittest.main()
