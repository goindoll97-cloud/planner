from __future__ import annotations

import unittest

from engine.stage2.project import EvidenceRef, create_project_from_stage1_snapshot
from engine.stage2.scope_validation import validate_selected_scope


class Stage2ScopeValidationTests(unittest.TestCase):
    def _project(self):
        snapshot = {
            "source_fingerprint": "a" * 64,
            "business": {"회사명": "테스트회사", "사업장 소재지": "테스트시 1"},
            "chemicals": [{"제품명": "물질A", "CAS No.": "50-00-0"}],
            "facilities": [{"설비번호": "TK-101"}],
            "decision": {
                "psm_status": "공정안전보고서 제출 대상",
                "cap_status": "작성수준 — 1군 사업장",
            },
        }
        return create_project_from_stage1_snapshot(snapshot)

    def test_unselected_psm_issues_are_not_in_selected_scope_report(self):
        project = self._project()
        project.set_authoring_scope(psm_selected=False, cap_selected=True)
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            [
                {"설비번호": "TK-101"},
                {"설비번호": "TK-101"},
            ],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.xlsx", sha256="b" * 64)],
        )
        report = validate_selected_scope(project)
        self.assertTrue(all(issue.system != "PSM" for issue in report.issues))

    def test_selected_psm_issue_remains_visible(self):
        project = self._project()
        project.set_authoring_scope(psm_selected=True, cap_selected=False)
        project.set_field(
            "psm.psi.equipment_specs",
            "유해하거나 위험한 설비의 목록 및 사양",
            [
                {"설비번호": "TK-101"},
                {"설비번호": "TK-101"},
            ],
            "VERIFIED",
            evidence=[EvidenceRef(source_type="ATTACHMENT", source_name="equipment.xlsx", sha256="b" * 64)],
        )
        report = validate_selected_scope(project)
        self.assertTrue(any(issue.system == "PSM" and issue.code == "DUPLICATE-IDENTIFIER" for issue in report.issues))

    def test_no_scope_returns_no_validation_issues(self):
        project = self._project()
        report = validate_selected_scope(project)
        self.assertEqual(report.checked_rules, 0)
        self.assertEqual(report.issues, ())


if __name__ == "__main__":
    unittest.main()
