from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.storage import (
    delete_project,
    list_projects,
    project_dir,
    save_attachment,
    save_project,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Stage2ProjectManagementTests(unittest.TestCase):
    def _project(self):
        snapshot = {
            "source_fingerprint": "a" * 64,
            "business": {
                "회사명": "프로젝트관리테스트",
                "사업장명": "테스트공장",
                "사업장 소재지": "테스트시 테스트구 1",
            },
            "documents": {},
            "chemicals": [{"제품명": "물질A", "CAS No.": "50-00-0"}],
            "facilities": [{"시설명": "TK-101", "시설유형": "저장탱크"}],
            "decision": {
                "psm_status": "공정안전보고서 제출 대상",
                "cap_status": "작성수준 — 2군 사업장",
            },
        }
        return create_project_from_stage1_snapshot(snapshot)

    def test_project_list_exposes_created_and_updated_timestamps(self):
        project = self._project()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_project(project, root=root)
            rows = list_projects(root=root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["project_id"], project.project_id)
            self.assertTrue(rows[0]["created_at"])
            self.assertTrue(rows[0]["updated_at"])

    def test_delete_project_removes_project_and_attachments(self):
        project = self._project()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_project(project, root=root)
            ref = save_attachment(
                project.project_id,
                "P&ID.pdf",
                b"drawing-bytes",
                root=root,
            )
            self.assertTrue(Path(ref.location).exists())
            self.assertTrue(project_dir(project.project_id, root=root).exists())

            self.assertTrue(delete_project(project.project_id, root=root))
            self.assertFalse(project_dir(project.project_id, root=root).exists())
            self.assertEqual(list_projects(root=root), [])
            self.assertFalse(delete_project(project.project_id, root=root))

    def test_korean_only_attachment_filename_is_stored_without_empty_identifier_error(self):
        project = self._project()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = save_attachment(
                project.project_id,
                "통합_작성자료_가상회사_완성본.xlsx",
                b"workbook-bytes",
                root=root,
                source_type="STAGE2_INTEGRATED_WORKBOOK",
            )
            stored = Path(ref.location)
            self.assertTrue(stored.exists())
            self.assertIn("통합_작성자료_가상회사_완성본", stored.name)
            self.assertEqual(ref.source_name, "통합_작성자료_가상회사_완성본.xlsx")



if __name__ == "__main__":
    unittest.main()
