from __future__ import annotations

import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

import engine.stage2.cap_hwpx as cap_hwpx
import engine.stage2.cap_template_priority as priority
from engine.stage2.project import Stage2Project


ROOT = Path(__file__).resolve().parents[1]


class CAPTemplatePriorityTests(unittest.TestCase):
    def setUp(self):
        importlib.reload(cap_hwpx)
        importlib.reload(priority)

    def tearDown(self):
        importlib.reload(cap_hwpx)
        importlib.reload(priority)

    @staticmethod
    def _project_with_old_manual_template() -> Stage2Project:
        project = Stage2Project(
            project_id="S2-TEMPLATE-PRIORITY",
            company_name="테스트화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field(
            cap_hwpx.TEMPLATE_FIELD_KEY,
            "화학사고예방관리계획서 법제처 원본 HWPX 서식",
            {
                "file_name": "old-project.hwpx",
                "stored_path": "/tmp/old-project.hwpx",
                "sha256": "a" * 64,
                "source_format": "HWPX",
                "template_source": "PROJECT_UPLOAD",
            },
            "USER_CONFIRMED",
        )
        return project

    def test_current_approved_law_template_outranks_old_project_upload(self):
        project = self._project_with_old_manual_template()
        current = {
            "file_name": "current-law.hwpx",
            "stored_path": "/tmp/current-law.hwpx",
            "sha256": "b" * 64,
            "source_format": "법제처 자동동기화 HWPX",
            "template_source": "APPROVED_LAW_ARCHIVE",
        }
        with patch("engine.law_attachment_archive.approved_source_is_current", return_value=True):
            priority.install_current_cap_template_priority()
        with patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=current):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertEqual(chosen["file_name"], "current-law.hwpx")
        self.assertEqual(chosen["template_source"], "APPROVED_LAW_ARCHIVE")

    def test_manual_project_template_remains_fallback_before_central_source_is_current(self):
        project = self._project_with_old_manual_template()
        with patch("engine.law_attachment_archive.approved_source_is_current", return_value=False):
            priority.install_current_cap_template_priority()
        with patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=None):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertEqual(chosen["file_name"], "old-project.hwpx")
        self.assertEqual(chosen["template_source"], "PROJECT_UPLOAD")

    def test_current_central_source_never_falls_back_to_stale_project_template(self):
        project = self._project_with_old_manual_template()
        with patch("engine.law_attachment_archive.approved_source_is_current", return_value=True):
            priority.install_current_cap_template_priority()
        # Central source is CURRENT but the newly amended HWP/HWPX cannot be
        # resolved by the current form-mapping engine. Fail closed.
        with patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=None):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertIsNone(chosen)

    def test_app_installs_current_template_priority_before_pages_run(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_current_cap_template_priority", source)
        self.assertIn("install_current_cap_template_priority()", source)


if __name__ == "__main__":
    unittest.main()
