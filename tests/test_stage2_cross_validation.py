from __future__ import annotations

import unittest

from engine.stage2.cross_validation import validate_stage2_project
from engine.stage2.project import EvidenceRef, create_project_from_stage1_snapshot


class Stage2CrossValidationTests(unittest.TestCase):
    def _project(self):
        snapshot = {
            "source_fingerprint": "a" * 64,
            "business": {
                "회사명": "테스트회사",
                "사업장명": "테스트공장",
                "사업장 소재지": "테스트시 테스트구 1",
            },
            "documents": {},
            "chemicals": [
                {"제품명": "물질A", "CAS No.": "50-00-0"},
                {"제품명": "물질B", "CAS No.": "67-56-1"},
            ],
            "facilities": [
                {"설비번호": "TK-101", "시설유형": "저장탱크"},
                {"설비번호": "R-201", "시설유형": "반응기"},
            ],
            "decision": {
                "psm_status": "공정안전보고서 제출 대상",
                "cap_status": "작성수준 — 1군 사업장",
            },
        }
        return create_project_from_stage1_snapshot(snapshot)

    def test_program_validation_terms_are_not_presented_as_legal_terms(self):
        report = validate_stage2_project(self._project()).to_dict()
        self.assertIn("프로그램의 검증상태", report["program_status_note"])

    def test_confirmed_pid_without_evidence_is_hold(self):
        project = self._project()
        project.set_field("documents.pid", "공정배관·계장도(P&ID)", "PID-001.pdf", "USER_CONFIRMED")
        report = validate_stage2_project(project)
        rows = [issue for issue in report.issues if issue.code == "EVIDENCE-MISSING" and "documents.pid" in issue.field_keys]
        self.assertTrue(rows)
        self.assertTrue(all(issue.status == "HOLD" for issue in rows))

    def test_duplicate_equipment_tag_is_hold(self):
        project = self._project()
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            [
                {"설비번호": "TK-101", "설비명": "탱크1"},
                {"설비번호": "TK-101", "설비명": "탱크2"},
            ],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.xlsx", sha256="b" * 64)],
        )
        report = validate_stage2_project(project)
        row = next(issue for issue in report.issues if issue.code == "DUPLICATE-IDENTIFIER" and "psm.psi.equipment_specs" in issue.field_keys)
        self.assertEqual(row.status, "HOLD")
        self.assertIn("TK-101", row.details)

    def test_relief_device_unknown_protected_equipment_is_hold(self):
        project = self._project()
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            [{"설비번호": "TK-101"}, {"설비번호": "R-201"}],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.xlsx", sha256="b" * 64)],
        )
        project.set_field(
            "psm.psi.relief_device_specs",
            "안전밸브 및 파열판 명세",
            [{"안전밸브번호": "PSV-101", "보호대상설비": "V-999"}],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="relief.xlsx", sha256="c" * 64)],
        )
        report = validate_stage2_project(project)
        row = next(issue for issue in report.issues if issue.code == "PSM-EQUIPMENT-RELIEF")
        self.assertEqual(row.status, "HOLD")
        self.assertIn("V-999", row.details)

    def test_relief_device_protected_equipment_match_passes(self):
        project = self._project()
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            [{"설비번호": "TK-101"}, {"설비번호": "R-201"}],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.xlsx", sha256="b" * 64)],
        )
        project.set_field(
            "psm.psi.relief_device_specs",
            "안전밸브 및 파열판 명세",
            [{"안전밸브번호": "PSV-101", "보호대상설비": "TK-101"}],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="relief.xlsx", sha256="c" * 64)],
        )
        report = validate_stage2_project(project)
        row = next(issue for issue in report.issues if issue.code == "PSM-EQUIPMENT-RELIEF")
        self.assertEqual(row.status, "PASS")

    def test_cap_cas_scope_difference_requires_human_review(self):
        project = self._project()
        project.set_field(
            "cap.chemical.details",
            "유해화학물질 목록 및 명세",
            [{"CAS No.": "50-00-0"}],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="chemicals.xlsx", sha256="d" * 64)],
        )
        report = validate_stage2_project(project)
        row = next(issue for issue in report.issues if issue.code == "CAP-CAS-CONSISTENCY")
        self.assertEqual(row.status, "REVIEW_REQUIRED")
        self.assertIn("67-56-1", row.details)

    def test_free_text_is_not_semantically_guessed(self):
        project = self._project()
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            "TK-101, R-201이 포함되어 있음",
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.pdf", sha256="b" * 64)],
        )
        report = validate_stage2_project(project)
        rows = [issue for issue in report.issues if issue.code == "PSM-FACILITY-EQUIPMENT"]
        self.assertFalse(rows)

    def test_invalid_attachment_hash_is_hold(self):
        project = self._project()
        project.set_field(
            "documents.pid",
            "공정배관·계장도(P&ID)",
            "PID-001.pdf",
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="PID-001.pdf", sha256="bad-hash")],
        )
        report = validate_stage2_project(project)
        row = next(issue for issue in report.issues if issue.code == "EVIDENCE-HASH-INVALID")
        self.assertEqual(row.status, "HOLD")


if __name__ == "__main__":
    unittest.main()
