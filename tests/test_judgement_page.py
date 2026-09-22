from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_judgement as jd
from tests.test_cap_judgement import BUSINESS, _decision
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

ROOT = Path(__file__).resolve().parents[1]


class DisplayRequestTests(unittest.TestCase):
    def test_workbook_sheet_names_are_hidden_from_requests(self):
        self.assertEqual(jd.display_request("05_최종판정조건: '법 제23조제1항 단서 해당 여부'를 확인해 주세요."),
                         "'법 제23조제1항 단서 해당 여부'를 확인해 주세요.")
        self.assertEqual(jd.display_request("회사 입력파일: 사업장명 확인"), "사업장명 확인")
        self.assertEqual(jd.display_request("이미 깨끗한 문장"), "이미 깨끗한 문장")

    def test_the_judgement_screens_use_it_for_every_engine_message(self):
        panel = (ROOT / "ui/judgement_panel.py").read_text(encoding="utf-8")
        start = (ROOT / "ui/cap_start_panel.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(panel.count("display_request("), 3)
        self.assertIn("display_request(", start)


class WiringTests(unittest.TestCase):
    def test_menu_has_one_judgement_page_and_no_excel_judgement(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.Page("ui/judgement_page.py", title="사업장 판정하기"', app)
        for gone in ("diagnosis_entry.py", "stage2_scope_page.py", "엑셀로 판정하기"):
            self.assertNotIn(gone, app)
        for removed in ("ui/diagnosis_entry.py", "ui/diagnosis_page.py", "ui/stage2_scope_page.py"):
            self.assertFalse((ROOT / removed).exists(), removed)

    def test_page_reuses_the_start_form_and_the_judgement_panel_and_links_to_writing(self):
        page = (ROOT / "ui/judgement_page.py").read_text(encoding="utf-8")
        for expected in ("cap_start_panel.render", "judgement_panel.render", "ui/cap_workspace_page.py",
                         "ui/psm_workspace_page.py", "delete_project(", "프로젝트와 저장된 첨부자료를 삭제합니다"):
            self.assertIn(expected, page)
        self.assertNotIn("PSM", page.replace("psm_workspace_page", ""))  # 화면 문구는 정식 명칭만 쓴다

    def test_full_names_only_in_user_facing_text(self):
        for name in ("ui/judgement_page.py", "ui/judgement_panel.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for abbreviation in ("화사계", "화관법", "(PSM)", "(CAP)"):
                self.assertNotIn(abbreviation, text, name)


class ScreenTests(unittest.TestCase):
    def _run(self, projects, project=None):
        rows = [{"project_id": p.project_id, "company_name": p.company_name} for p in projects]
        patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
                   patch("engine.stage2.storage.load_project", return_value=project),
                   patch("engine.stage2.storage.save_project"),
                   patch("engine.stage2.storage.delete_project", return_value=True),
                   patch("streamlit.page_link"),  # AppTest에는 멀티페이지 탐색 정보가 없다
                   patch("ui.cap_start_panel._gate_hold", return_value=False)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        at = AppTest.from_file(str(ROOT / "ui/judgement_page.py"), default_timeout=90)
        if project is not None:
            at.session_state["_stage2_active_project_id"] = project.project_id
        return at.run()

    def _pending(self):
        project = CAPForm1EngineTests()._project()
        project.stage1_snapshot["business"] = dict(BUSINESS)
        project.stage1_snapshot[jd.PENDING_KEY] = True
        project.scope_confirmed = False
        project.cap_required = project.psm_required = None
        return project

    def test_first_visit_shows_the_start_form_with_the_chemical_upload(self):
        at = self._run([])
        self.assertFalse(at.exception)
        self.assertTrue(any("판정한 사업장이 아직 없습니다" in i.value for i in at.info))
        labels = [e.label for e in at.expander]
        self.assertTrue(any("새 사업장으로 시작하기" in label for label in labels))
        self.assertTrue(any("엑셀·CSV로 물질 목록 올리기" in label for label in labels))

    def test_a_pending_site_shows_the_panel_next_steps_and_a_guarded_delete(self):
        project = self._pending()
        at = self._run([project], project)
        self.assertFalse(at.exception)
        self.assertTrue(any("판정 전" in e.label for e in at.expander))
        self.assertTrue(any(b.key == f"judge_run_{project.project_id}" for b in at.button))
        delete = next(b for b in at.button if b.key == f"delete_project_{project.project_id}")
        self.assertTrue(delete.disabled)  # 확인 체크 전에는 삭제할 수 없다
        at.checkbox(key=f"delete_confirm_{project.project_id}").check().run()
        delete = next(b for b in at.button if b.key == f"delete_project_{project.project_id}")
        self.assertFalse(delete.disabled)

    def test_delete_path_clears_material_draft_and_project_ui_state(self):
        page = (ROOT / "ui/judgement_page.py").read_text(encoding="utf-8")
        start = (ROOT / "ui/cap_start_panel.py").read_text(encoding="utf-8")

        self.assertIn("def _clear_project_ui_state(project_id: str)", page)
        self.assertIn("_clear_project_ui_state(selected)", page)
        self.assertIn("cap_start_panel.clear_start_draft_state()", page)
        self.assertIn("def clear_start_draft_state()", start)
        self.assertIn('if str(key).startswith("cap_start_")', start)
        # 프로젝트 삭제 성공 뒤 활성 프로젝트도 반드시 비운다.
        self.assertIn("st.session_state.pop(ACTIVE_PROJECT_KEY, None)", page)


    def test_deciding_on_the_page_moves_the_site_into_the_writing_scope(self):
        project = self._pending()
        original = jd.judge
        jd.judge = lambda proj, assess=None: original(proj, assess=lambda intake: _decision())
        self.addCleanup(lambda: setattr(jd, "judge", original))
        at = self._run([project], project)
        at.button(key=f"judge_run_{project.project_id}").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("근거 설명" in c.value for c in at.caption))  # 판정 근거 설명이 화면에 보인다
        at.button(key=f"judge_apply_{project.project_id}").click().run()
        self.assertTrue(project.cap_in_scope)
        at = self._run([project], project)
        self.assertFalse(at.exception)

    def test_deleting_a_project_clears_the_leftover_new_site_chemical_draft(self):
        # cap_start_seed는 '새 사업장으로 시작하기'의 물질 표(프로젝트별이 아닌 화면 하나짜리 상태)다.
        # 지우지 않으면 이 프로젝트를 지운 뒤에도 전에 거기 올렸던 물질 목록이 그대로 남아 보인다.
        project = self._pending()
        at = self._run([project], project)
        at.session_state["cap_start_seed"] = [{"제품명": "이전 사업장 물질", "CAS No.": "108-88-3"}]
        at.checkbox(key=f"delete_confirm_{project.project_id}").check().run()
        at.button(key=f"delete_project_{project.project_id}").click().run()
        self.assertFalse(at.exception)
        self.assertNotIn("cap_start_seed", at.session_state)


if __name__ == "__main__":
    unittest.main()
