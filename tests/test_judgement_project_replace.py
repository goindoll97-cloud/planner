from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import unittest

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

from engine.stage2 import cap_chemical_workspace as chem
from tests.test_cap_judgement import BUSINESS
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests
from engine.stage2 import cap_judgement as jd

ROOT = Path(__file__).resolve().parents[1]


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


HEADER = ["제품명", "단일물질/혼합물", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위"]
NEW_ROW = ["새 물질", "단일물질", "64-17-5", None, 5, 10, "kg"]


class FakeUpload:
    name = "new.xlsx"

    def getvalue(self):
        return _xlsx([HEADER, NEW_ROW])


def fake_file_uploader(*args, **kwargs):
    return FakeUpload()


def _project_with_a_chemical():
    project = CAPForm1EngineTests()._project()  # 염소(7782-50-5)를 이미 갖고 있다
    project.stage1_snapshot["business"] = dict(BUSINESS)
    project.stage1_snapshot[jd.PENDING_KEY] = True
    project.scope_confirmed = False
    project.cap_required = project.psm_required = None
    return project


class ReplaceUIGateTests(unittest.TestCase):
    def _run(self, project, *, file_uploader=None):
        rows = [{"project_id": project.project_id, "company_name": project.company_name}]
        patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
                   patch("engine.stage2.storage.load_project", return_value=project),
                   patch("engine.stage2.storage.save_project"),
                   patch("streamlit.page_link"),
                   patch("ui.cap_start_panel._gate_hold", return_value=False)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        at = AppTest.from_file(str(ROOT / "ui/judgement_page.py"), default_timeout=90)
        at.session_state["_stage2_active_project_id"] = project.project_id
        if file_uploader is not None:
            import streamlit as st

            st.file_uploader = file_uploader
        return at.run()

    def test_uploader_is_hidden_behind_a_confirmation_when_chemicals_already_exist(self):
        project = _project_with_a_chemical()
        at = self._run(project, file_uploader=fake_file_uploader)
        self.assertFalse(at.exception)
        pid = project.project_id
        self.assertTrue(any("모두 지워지고" in w.value for w in at.warning))
        self.assertFalse(any(b.key == f"judge_upload_{pid}_add" for b in at.button))
        at.checkbox(key=f"judge_replace_confirm_{pid}").check().run()
        self.assertTrue(any(b.key == f"judge_upload_{pid}_add" for b in at.button))

    def test_confirming_and_uploading_replaces_the_whole_list(self):
        project = _project_with_a_chemical()
        self.assertIn("염소", [r.get("물질명") for r in chem._rows(project)[1]])
        at = self._run(project, file_uploader=fake_file_uploader)
        pid = project.project_id
        at.checkbox(key=f"judge_replace_confirm_{pid}").check().run()
        at.button(key=f"judge_upload_{pid}_add").click().run()
        self.assertFalse(at.exception)
        names = [r.get("물질명") for r in chem._rows(project)[1]]
        self.assertNotIn("염소", names)
        self.assertEqual(names, ["새 물질"])

    def test_no_confirmation_needed_when_the_project_has_no_chemicals_yet(self):
        project = _project_with_a_chemical()
        project.fields.pop(chem.INVENTORY_KEY, None)
        project.fields.pop(chem.DETAILS_KEY, None)
        at = self._run(project, file_uploader=fake_file_uploader)
        pid = project.project_id
        self.assertFalse(any(w for w in at.warning if "모두 지워지고" in w.value))
        self.assertTrue(any(b.key == f"judge_upload_{pid}_add" for b in at.button))


if __name__ == "__main__":
    unittest.main()
