from __future__ import annotations

import unittest
from unittest.mock import patch

import engine.stage2.cap_hwpx as cap_hwpx
from engine.stage2.project import Stage2Project


class CAPTemplatePriorityTests(unittest.TestCase):
    """registered_cap_template must keep the CURRENT approved law.go.kr CAP
    form as the layout authority, with an older project-uploaded template as
    fallback only while the central CAP legal source is not CURRENT."""

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
        with patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=current):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertEqual(chosen["file_name"], "current-law.hwpx")
        self.assertEqual(chosen["template_source"], "APPROVED_LAW_ARCHIVE")

    def test_manual_project_template_remains_fallback_before_central_source_is_current(self):
        project = self._project_with_old_manual_template()
        with (
            patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=None),
            patch("engine.stage2.cap_hwpx.approved_source_is_current", return_value=False),
        ):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertEqual(chosen["file_name"], "old-project.hwpx")
        self.assertEqual(chosen["template_source"], "PROJECT_UPLOAD")

    def test_current_central_source_never_falls_back_to_stale_project_template(self):
        project = self._project_with_old_manual_template()
        # Central source is CURRENT but the newly amended HWP/HWPX cannot be
        # resolved by the current form-mapping engine. Fail closed.
        with (
            patch.object(cap_hwpx, "_approved_current_cap_template_meta", return_value=None),
            patch("engine.stage2.cap_hwpx.approved_source_is_current", return_value=True),
        ):
            chosen = cap_hwpx.registered_cap_template(project)
        self.assertIsNone(chosen)


if __name__ == "__main__":
    unittest.main()
