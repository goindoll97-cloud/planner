from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from engine.stage2 import cap_chemical_upload as up
from engine.stage2 import cap_chemical_workspace as chem
from engine.stage2.storage import delete_project, list_projects, load_project, project_dir, save_project
from tests.test_upload_products_and_mixtures import MIX1, MIX2, SINGLE, _pending, _products


class UploadDoesNotWipeExistingListTests(unittest.TestCase):
    def test_a_second_upload_keeps_the_first_uploads_substances(self):
        project = _pending()
        up.add_to_project(project, _products([SINGLE]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
        before = {r.get("제품명") for r in chem._rows(project)[1]}
        self.assertIn("톨루엔", before)

        up.add_to_project(project, _products([MIX1, MIX2]), file_name="b.xlsx", sha256="def456789012", sds_confirmed=True)
        after = {r.get("제품명") for r in chem._rows(project)[1]}
        self.assertTrue(before <= after)  # 두 번째 업로드가 첫 번째 업로드분을 지우지 않는다
        self.assertIn("세척제A", after)


class DeletingTheProjectRemovesItsChemicalListEverywhereTests(unittest.TestCase):
    def test_deleted_projects_chemical_list_cannot_be_loaded_from_the_cap_writing_screen(self):
        """사업장 판정하기에서 삭제하면, 화사계 작성 화면이 쓰는 같은 load_project/list_projects로도 그 물질 목록을 더 이상 볼 수 없다."""
        project = _pending()
        up.add_to_project(project, _products([SINGLE, MIX1, MIX2]), file_name="a.xlsx", sha256="abc123456789", sds_confirmed=True)
        project.project_id = "S2-DELETE-CHECK-TEST"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_project(project, root=root)
            self.assertGreater(len(chem._rows(load_project(project.project_id, root=root))[1]), 0)

            self.assertTrue(delete_project(project.project_id, root=root))

            self.assertFalse(project_dir(project.project_id, root=root).exists())
            with self.assertRaises(FileNotFoundError):
                load_project(project.project_id, root=root)  # 화사계 작성 화면(cap_workspace_page)도 이 함수로 프로젝트를 읽는다
            self.assertNotIn(project.project_id, [row["project_id"] for row in list_projects(root=root)])  # 작성 화면의 선택 목록에도 안 뜬다


if __name__ == "__main__":
    unittest.main()
