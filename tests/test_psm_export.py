from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch
import zipfile

from docx import Document

from engine.stage2 import psm_export as export
from engine.stage2.workflow import draft_authoring_allowed, validation_confirmed
from tests.test_psm_workspace_page import _project, _run


class ExportTests(unittest.TestCase):
    def test_evaluate_splits_issues_and_never_confirms_with_open_items(self):
        project = _project()
        state = export.evaluate(project)
        self.assertGreater(state.hold + state.review, 0)  # 비어 있는 별지가 많다
        self.assertFalse(state.can_confirm)
        self.assertFalse(state.final_ready)
        self.assertFalse(export.confirm(project, state))
        self.assertFalse(validation_confirmed(project))
        self.assertFalse(export.downloads_allowed(project))

    def test_review_only_download_after_acknowledging_holds(self):
        project = _project()
        export.acknowledge_holds(project)
        self.assertTrue(draft_authoring_allowed(project))
        self.assertFalse(validation_confirmed(project))
        outputs = export.build_outputs(project, final_ready=False)
        self.assertIn("검토용", outputs.regulation_name)
        self.assertNotIn("작성본", outputs.regulation_name)
        self.assertFalse(outputs.final_ready)
        Document(BytesIO(outputs.regulation_docx))
        Document(BytesIO(outputs.review_docx))
        with zipfile.ZipFile(BytesIO(outputs.bundle)) as archive:
            self.assertTrue(any(n.endswith(".docx") for n in archive.namelist()))
        self.assertIn(b"REVIEW_ONLY", outputs.provenance_json)

    def test_final_label_is_refused_without_confirmed_validation(self):
        project = _project()
        with self.assertRaises(ValueError):
            export.build_outputs(project, final_ready=True)

    def test_export_requires_psm_in_scope(self):
        project = _project()
        project.psm_selected = False
        with self.assertRaises(ValueError):
            export.evaluate(project)


class ScreenTests(unittest.TestCase):
    def test_screen_shows_open_items_and_gates_downloads(self):
        project = _project()
        at = _run(project, "export")
        self.assertFalse(at.exception)
        self.assertTrue(any("남아 있습니다" in w.value for w in at.warning))
        self.assertTrue(any(b.key == "export_psm_ack" for b in at.button))
        self.assertTrue(any("내려받을 수 있습니다" in i.value for i in at.info))

    def test_acknowledging_reveals_the_downloads_labelled_as_review(self):
        project = _project()
        with patch("engine.stage2.storage.save_project"):
            def click(at):
                at.button(key="export_psm_ack").click().run()
            at = _run(project, "export", click)
        self.assertFalse(at.exception)
        self.assertTrue(any("검토용" in w.value for w in at.warning))
        self.assertFalse(any(b.key == "export_psm_ack" for b in at.button))


if __name__ == "__main__":
    unittest.main()


class CapExportTests(unittest.TestCase):
    def _cap_project(self):
        from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

        project = CAPForm1EngineTests()._project()
        project.psm_required = False
        return project

    def test_cap_review_download_is_labelled_as_review_until_final_gates_pass(self):
        from engine.stage2 import report_export as shared

        project = self._cap_project()
        self.assertTrue(project.cap_in_scope)
        state = shared.evaluate(project, "CAP")
        self.assertFalse(state.final_ready)
        self.assertIsNotNone(state.readiness.cap_gate)  # 최종 체크포인트도 함께 판정
        shared.acknowledge_holds(project)
        outputs = shared.build_outputs(project, final_ready=False, system="CAP")
        self.assertIn("규정서식_검토용", outputs.regulation_name)
        self.assertNotIn("작성본", outputs.regulation_name)
        self.assertIn(b"REVIEW_ONLY", outputs.provenance_json)
        Document(BytesIO(outputs.regulation_docx))
        with self.assertRaises(ValueError):
            shared.build_outputs(project, final_ready=True, system="CAP")

    def test_scope_is_checked_per_system(self):
        from engine.stage2 import report_export as shared

        project = self._cap_project()
        with self.assertRaises(ValueError):
            shared.evaluate(project, "PSM")
        with self.assertRaises(ValueError):
            shared.evaluate(project, "XYZ")


class CapScreenTests(unittest.TestCase):
    def test_cap_workspace_export_step_uses_the_shared_panel(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn('report_export_panel.render(project, "CAP")', source)
        self.assertNotIn("cap_form01_download_", source)  # 항상 '작성본'으로 이름 붙이던 예전 다운로드 제거


class CapPanelRenderTests(unittest.TestCase):
    def test_panel_renders_for_a_cap_project_and_gates_downloads(self):
        from streamlit.testing.v1 import AppTest

        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from unittest.mock import patch\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from ui import report_export_panel\n"
            "project = CAPForm1EngineTests()._project()\n"
            "with patch('ui.report_export_panel.save_project'):\n"
            "    report_export_panel.render(project, 'CAP')\n"
        ) % str(__import__("pathlib").Path(__file__).resolve().parents[1])
        at = AppTest.from_string(code, default_timeout=90).run()
        self.assertFalse(at.exception)
        self.assertTrue(any(b.key == "export_cap_ack" for b in at.button))
        self.assertTrue(any("내려받을 수 있습니다" in i.value for i in at.info))  # 확정·초안 선택 전에는 내려받기를 막는다
