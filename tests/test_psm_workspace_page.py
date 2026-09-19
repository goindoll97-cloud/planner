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

    def test_form19_2_shows_results_after_a_scenario_is_chosen(self):
        project = _project()

        def choose(at):
            at.selectbox(key="psm19_kind_0").select("최악의사고시나리오").run()
            at.text_input(key="psm19_temp").input("30").run()
            at.text_input(key="psm19_humidity").input("70").run()

        at = _run(project, "19-2", choose)
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe), 1)
        frame = at.dataframe[0].value
        self.assertIn("독성-ERPG 2", list(frame["항목"]))

    def test_navigation_offers_the_page_only_when_psm_is_selected(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('sections["공정안전보고서"] = [st.Page("ui/psm_workspace_page.py"', app)
        self.assertLess(app.index("if _psm_selected_somewhere():\n    # 공정안전보고서를 새 방식"),
                        app.index('sections["공정안전보고서 (기존 방식)"]'))


if __name__ == "__main__":
    unittest.main()
