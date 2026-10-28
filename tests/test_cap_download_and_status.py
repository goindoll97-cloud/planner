"""왼쪽 메뉴에서 별지 입력 화면을 뺀 뒤의 구조: 자료 접수의 O/X 현황표와 내려받기·지도 전용 화면."""
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine.stage2 import demo_full_company as d, evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import save_project

ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_download_page_only_downloads_and_never_edits(self):
        page = (ROOT / "ui/cap_download_page.py").read_text(encoding="utf-8")
        self.assertIn("download_button", page)
        for editing in ("data_editor", "text_input", "st.form(", "save_project(project)"):
            self.assertNotIn(editing, page)

    def test_map_page_keeps_only_the_drawing_panel(self):
        page = (ROOT / "ui/surroundings_map_page.py").read_text(encoding="utf-8")
        self.assertIn("surroundings_map_panel.render", page)
        self.assertNotIn("cap_common.page", page)

    def test_status_table_marks_every_cap_requirement_with_o_or_x(self):
        from ui import evidence_workspace_page as page

        self.assertEqual(page.OX["확인"], "O")
        self.assertEqual(page.OX["자료 요청 필요"], "X")
        self.assertEqual(page.OX["해당 없음"], "—")
        self.assertIn("_status_table", (ROOT / "ui/evidence_workspace_page.py").read_text(encoding="utf-8"))

    def test_status_table_renders_for_a_project_with_uploaded_files(self):
        project = create_direct_cap_project(d.COMPANY, address=d.company("")["주소"], cap_group="1군")
        for name, kind in d.UPLOAD.items():
            ew.ingest(project, name, d.files("")[name], kind)
        save_project(project)
        from engine.stage2.intake import build_intake_catalog

        rows = [r for r in build_intake_catalog(project) if r.system in {"CAP", "COMMON"}]
        self.assertTrue(rows)
        from ui.evidence_workspace_page import OX

        self.assertTrue(all(r.coverage_status in OX for r in rows))


if __name__ == "__main__":
    unittest.main()
