"""④ 단일 다운로드는 검증을 유지하고 규정서식과 서술형을 함께 제공합니다."""
from io import BytesIO
import unittest
from unittest.mock import patch
from docx import Document
from engine.stage2 import report_export as export, cap_fact_drafting as fd
from tests.test_cap_fact_drafting import _project


class WorkspaceDownloadTests(unittest.TestCase):
    def test_current_narratives_are_included_and_validation_is_preserved(self):
        project = _project()
        fd.refresh_rule_drafts(project)
        with patch.object(export, 'evaluate', wraps=export.evaluate) as check:
            draft = export.build_cap_workspace_draft(project)
        check.assert_called_once_with(project, 'CAP')
        doc = Document(BytesIO(draft.docx))
        self.assertGreaterEqual(len(doc.tables), 16)
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('안전관리 책임자: 공장장', text)
        self.assertNotIn('AI 초안', text)
        self.assertIn('초안', draft.name)
        self.assertGreater(draft.state.hold + draft.state.review, 0)
        self.assertIn(b'REVIEW_ONLY', draft.provenance_json)

    def test_validation_failure_never_produces_downloadable_bytes(self):
        with patch.object(export, 'evaluate', side_effect=RuntimeError('validation unavailable')):
            with self.assertRaises(RuntimeError):
                export.build_cap_workspace_draft(_project())


    def test_hwp_converter_runs_only_after_explicit_click_and_cache_tracks_docx(self):
        """Entering/rerendering Step ④ never starts Hancom or creates HWP."""
        from contextlib import nullcontext
        from types import SimpleNamespace
        from ui import report_export_panel as panel

        class FakeUI:
            def __init__(self):
                self.session_state = {}
                self.convert_pressed = False
                self.downloads = []
                self.warnings = []

            def expander(self, *args, **kwargs):
                return nullcontext()

            def spinner(self, *args, **kwargs):
                return nullcontext()

            def caption(self, *args, **kwargs):
                pass

            def write(self, *args, **kwargs):
                pass

            def dataframe(self, *args, **kwargs):
                pass

            def warning(self, value):
                self.warnings.append(value)

            def error(self, value):
                raise AssertionError(value)

            def button(self, *args, **kwargs):
                return self.convert_pressed

            def download_button(self, label, **kwargs):
                self.downloads.append((label, kwargs["data"]))

        ui = FakeUI()
        project = SimpleNamespace(cap_in_scope=True, project_id="CAP-TEST")
        draft = SimpleNamespace(name="사업장_규정서식_초안.docx", docx=b"PK original draft")
        converted = SimpleNamespace(data=b"HWP version 1", mode="docx_converted", warnings=())
        with (
            patch.object(panel, "st", ui),
            patch.object(panel.export, "build_cap_workspace_draft", return_value=draft),
            patch.object(panel.cap_template_gap_audit, "rows", return_value=[]),
            patch.object(panel.cap_template_gap_audit, "csv_bytes", return_value=b"test,csv"),
            patch.object(panel.cap_hwp_export, "build_workspace_hwp", return_value=converted) as converter,
            patch("engine.stage2.cap_form8_engine.build_cap_form8_data",
                  return_value=SimpleNamespace(rows=())),
        ):
            panel.render_workspace_download(project)
            converter.assert_not_called()
            self.assertIn(("규정서식 초안 DOCX 내려받기", draft.docx), ui.downloads)
            self.assertFalse(any("HWP 내려받기" in label for label, _ in ui.downloads))

            # Streamlit reruns for normal widgets/CSV/DOCX downloads must not
            # open Hancom or create a new HWP.
            ui.downloads.clear()
            panel.render_workspace_download(project)
            converter.assert_not_called()
            self.assertFalse(any("HWP 내려받기" in label for label, _ in ui.downloads))

            ui.convert_pressed = True
            ui.downloads.clear()
            panel.render_workspace_download(project)
            converter.assert_called_once_with(project, draft.docx)
            self.assertIn(("규정서식 초안 HWP 내려받기", converted.data), ui.downloads)

            # An ordinary rerun reuses the explicit result without conversion.
            ui.convert_pressed = False
            ui.downloads.clear()
            panel.render_workspace_download(project)
            converter.assert_called_once()
            self.assertIn(("규정서식 초안 HWP 내려받기", converted.data), ui.downloads)

            # After the source DOCX changes, the old HWP is never downloadable
            # until the user explicitly regenerates it.
            draft.docx = b"PK updated draft"
            ui.downloads.clear()
            panel.render_workspace_download(project)
            converter.assert_called_once()
            self.assertNotIn("workspace_cap_hwp_CAP-TEST_filled", ui.session_state)
            self.assertIn(("규정서식 초안 DOCX 내려받기", draft.docx), ui.downloads)
            self.assertFalse(any("HWP 내려받기" in label for label, _ in ui.downloads))

            ui.convert_pressed = True
            ui.downloads.clear()
            panel.render_workspace_download(project)
            self.assertEqual(converter.call_count, 2)
            self.assertEqual(converter.call_args.args, (project, draft.docx))
            self.assertIn(("규정서식 초안 HWP 내려받기", converted.data), ui.downloads)
