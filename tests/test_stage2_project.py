from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.requirements import requirement_specs_for_project
from engine.stage2.storage import load_project, save_attachment, save_project


class Stage2ProjectTests(unittest.TestCase):
    def _snapshot(self, *, psm_status="공정안전보고서 제출 대상", cap_status="작성수준 — 2군 사업장"):
        return {
            "source_fingerprint": "a" * 64,
            "business": {
                "회사명": "테스트회사",
                "사업장명": "테스트공장",
                "사업장 소재지": "테스트시 테스트구 1",
            },
            "documents": {},
            "chemicals": [{"제품명": "물질A", "CAS No.": "50-00-0"}],
            "facilities": [{"시설명": "TK-101", "시설유형": "저장탱크"}],
            "decision": {
                "psm_status": psm_status,
                "cap_status": cap_status,
                "psm_legal_basis": ["근거1"],
                "cap_legal_basis": ["근거2"],
            },
        }

    def test_stage1_status_is_carried_without_redecision(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        self.assertTrue(project.psm_required)
        self.assertTrue(project.cap_required)
        self.assertEqual(project.cap_group, "2군")
        self.assertEqual(project.get_field("inventory.chemicals").status, "VERIFIED")

    def test_non_subject_labels_are_false(self):
        project = create_project_from_stage1_snapshot(
            self._snapshot(
                psm_status="현재 확인 범위에서 공정안전보고서 제출 대상 기준 미해당",
                cap_status="화학사고예방관리계획서 작성·제출 의무 없음 — 하위 규정수량 미만",
            )
        )
        self.assertFalse(project.psm_required)
        self.assertFalse(project.cap_required)

    def test_group2_excludes_external_emergency_requirement(self):
        project = create_project_from_stage1_snapshot(self._snapshot(cap_status="작성수준 — 2군 사업장"))
        keys = {spec.key for spec in requirement_specs_for_project(project)}
        self.assertIn("cap.internal_emergency", keys)
        self.assertNotIn("cap.external_emergency", keys)

    def test_group1_includes_external_emergency_requirement(self):
        project = create_project_from_stage1_snapshot(self._snapshot(cap_status="작성수준 — 1군 사업장"))
        keys = {spec.key for spec in requirement_specs_for_project(project)}
        self.assertIn("cap.external_emergency", keys)

    def test_ai_draft_does_not_count_as_ready(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        project.set_field("process.description", "공정 설명", "AI가 작성한 설명", "AI_DRAFT")
        result = evaluate_project_completeness(project)
        row = next(r for r in result["requirements"] if r["key"] == "common.process_description")
        self.assertEqual(row["state"], "REVIEW_REQUIRED")
        self.assertEqual(row["completion_pct"], 0.0)

    def test_project_and_attachment_persist_with_hash(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_project(project, root=root)
            loaded = load_project(project.project_id, root=root)
            self.assertEqual(loaded.company_name, "테스트회사")

            ref = save_attachment(
                project.project_id,
                "PFD test.pdf",
                b"fake-pdf-bytes",
                root=root,
            )
            self.assertEqual(len(ref.sha256), 64)
            self.assertTrue(Path(ref.location).exists())


if __name__ == "__main__":
    unittest.main()
