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

    def test_scope_page_exposes_project_delete_and_timestamp_controls(self):
        text = (PROJECT_ROOT / "ui/stage2_scope_page.py").read_text(encoding="utf-8")
        self.assertIn("생성일시", text)
        self.assertIn("최근 수정일시", text)
        self.assertIn("선택한 작성 프로젝트 삭제", text)
        self.assertIn("프로젝트와 저장된 첨부자료를 삭제합니다", text)


if __name__ == "__main__":
    unittest.main()
