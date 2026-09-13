from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook

from engine.stage2.cap_requests import build_cap_data_requests
from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.export import build_progress_workbook
from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.requirements import (
    cap_manual_source,
    cap_requirement_specs,
    requirement_specs_for_project,
)
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

    def test_manual_source_is_versioned_by_hash(self):
        source = cap_manual_source()
        self.assertEqual(source["document_code"], "NICS-GP2026-8")
        self.assertEqual(source["pdf_pages"], 156)
        self.assertEqual(len(source["sha256"]), 64)
        self.assertEqual(source["source_role"], "작성 실무지침")

    def test_group2_excludes_external_emergency_requirements(self):
        specs = cap_requirement_specs("2군")
        self.assertEqual(len(specs), 33)
        self.assertTrue(all(spec.section != "3.6 외부 비상대응계획" for spec in specs))
        self.assertTrue(any(spec.key == "cap.internal.facility_response" for spec in specs))

    def test_group1_includes_external_emergency_requirements(self):
        specs = cap_requirement_specs("1군")
        self.assertEqual(len(specs), 37)
        external = [spec for spec in specs if spec.section == "3.6 외부 비상대응계획"]
        self.assertEqual(len(external), 4)
        self.assertTrue(any(spec.key == "cap.external.public_notice" for spec in external))

    def test_project_requirements_use_detailed_manual_registry(self):
        project = create_project_from_stage1_snapshot(self._snapshot(cap_status="작성수준 — 2군 사업장"))
        keys = {spec.key for spec in requirement_specs_for_project(project)}
        self.assertIn("cap.facility.pid", keys)
        self.assertIn("cap.offsite.risk", keys)
        self.assertIn("cap.prevention.self_inspection", keys)
        self.assertNotIn("cap.external.public_notice", keys)

    def test_request_engine_does_not_ask_confirmed_stage1_fields_again(self):
        project = create_project_from_stage1_snapshot(self._snapshot(cap_status="작성수준 — 2군 사업장"))
        rows = build_cap_data_requests(project)
        chemical_row = next(row for row in rows if row.requirement_key == "cap.basic.chemical_inventory")
        self.assertNotIn("inventory.chemicals", chemical_row.missing_fields)
        self.assertIn("cap.chemical.details", chemical_row.missing_fields)
        site_row = next(row for row in rows if row.requirement_key == "cap.basic.site_location")
        self.assertIn("documents.site_plan", site_row.missing_fields)

    def test_ai_draft_does_not_count_as_ready(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        project.set_field("process.description", "공정 설명", "AI가 작성한 설명", "AI_DRAFT")
        result = evaluate_project_completeness(project)
        row = next(r for r in result["requirements"] if r["key"] == "common.process_description")
        self.assertEqual(row["state"], "REVIEW_REQUIRED")
        self.assertEqual(row["completion_pct"], 0.0)

    def test_hold_has_priority_over_review_required(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        project.set_field("process.description", "공정 설명", "AI가 작성한 설명", "AI_DRAFT")
        result = evaluate_project_completeness(project)
        self.assertEqual(result["overall"]["state"], "HOLD")
        self.assertEqual(result["psm"]["state"], "HOLD")
        self.assertEqual(result["cap"]["state"], "HOLD")

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

    def test_review_workbook_uses_full_legal_names(self):
        project = create_project_from_stage1_snapshot(self._snapshot())
        workbook = load_workbook(BytesIO(build_progress_workbook(project)))
        sheet = workbook["작성현황"]
        visible_system_values = {sheet.cell(row=row, column=1).value for row in range(2, sheet.max_row + 1)}
        self.assertIn("공정안전보고서", visible_system_values)
        self.assertIn("화학사고예방관리계획서", visible_system_values)
        self.assertNotIn("PSM", visible_system_values)
        self.assertNotIn("CAP", visible_system_values)


if __name__ == "__main__":
    unittest.main()
