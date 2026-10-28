from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_scenario_workspace as sc
from engine.stage2 import cap_workspace as ws
from tests.test_stage2_cap_dispersion import LIQUID, _toxic_project

ROOT = Path(__file__).resolve().parents[1]


def _project():
    project = _toxic_project()
    project.psm_required = True
    project.scope_confirmed = True
    project.set_authoring_scope(psm_selected=True, cap_selected=True)
    sc.save_scenarios(project, [dict(LIQUID)])
    return project


def _run(project, form_label=None, interact=None):
    rows = [{"project_id": project.project_id, "company_name": project.company_name}]
    with patch("engine.stage2.storage.list_projects", return_value=rows), \
         patch("engine.stage2.storage.load_project", return_value=project), \
         patch("engine.stage2.storage.save_project"):
        at = AppTest.from_file(str(ROOT / "ui/psm_workspace_page.py"), default_timeout=90)
        at.session_state["_stage2_active_project_id"] = project.project_id
        at.run()
        if form_label:
            at.selectbox(key="psm_form_no").select(form_label).run()
        if interact:
            interact(at)
        return at


class PsmWorkspacePageTests(unittest.TestCase):
    def test_form13_and_form15_reuse_cap_facts(self):
        project = _project()
        for key, label in (("13", "13"), ("15", "15")):
            at = _run(project, label)
            self.assertFalse(at.exception, key)
            self.assertTrue(any("가져왔습니다" in s.value for s in at.success), key)

    def test_form19_2_shows_the_saved_scenario_results_read_only(self):
        from engine.stage2 import psm_form19_2_workspace as f19

        project = _project()
        at = _run(project, "19-2")
        self.assertFalse(at.exception)
        self.assertTrue(any("아직 계산된" in i.value for i in at.info))
        results = f19.build(project, {LIQUID["사고시나리오명"]: f19.WORST}, {"대기온도(℃)": "30", "습도(%)": "70"})
        f19.save(project, results)
        at = _run(project, "19-2")
        self.assertFalse(at.exception)
        self.assertEqual(len(at.text_input) + len(at.selectbox), 2)          # 프로젝트·서식 고르기뿐
        self.assertIn("독성-ERPG 2", list(at.dataframe[0].value["항목"]))

    def test_every_view_renders_without_input_widgets(self):
        project = _project()
        for key in ("status", "12", "14", "17-2", "17-5", "admin", "narrative", "files"):
            at = _run(project, key)
            self.assertFalse(at.exception, key)
            if key not in ("files",):
                self.assertEqual(len(at.text_input), 0, key)          # 서식을 화면에서 쓰지 않음
                self.assertEqual(len(at.get("data_editor") if hasattr(at, "get") else []), 0, key)
        at = _run(project, "12")
        self.assertTrue(any("비어 있는 칸" in i.value for i in at.info))
        at = _run(project, "status")
        self.assertIn("서식", at.dataframe[0].value.columns)

    def test_navigation_always_offers_the_psm_page(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('sections["공정안전보고서"] = [st.Page("ui/psm_workspace_page.py"', app)
        self.assertNotIn("_psm_selected_somewhere", app)


if __name__ == "__main__":
    unittest.main()
