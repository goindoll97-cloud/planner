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
        self.assertTrue(any(b.key == "psm_export_ack" for b in at.button))
        self.assertTrue(any("내려받을 수 있습니다" in i.value for i in at.info))

    def test_acknowledging_reveals_the_downloads_labelled_as_review(self):
        project = _project()
        with patch("engine.stage2.storage.save_project"):
            def click(at):
                at.button(key="psm_export_ack").click().run()
            at = _run(project, "export", click)
        self.assertFalse(at.exception)
        self.assertTrue(any("검토용" in w.value for w in at.warning))
        self.assertFalse(any(b.key == "psm_export_ack" for b in at.button))


if __name__ == "__main__":
    unittest.main()
