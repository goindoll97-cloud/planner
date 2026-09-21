from __future__ import annotations

import os
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from engine.stage2 import versioning as ver
from engine.stage2.project import Stage2Project
from engine.stage2.storage import load_project, save_project


def _app():
    import streamlit as st

    from engine.stage2.storage import load_project
    from ui import version_panel

    version_panel.render(load_project("p1"), st.session_state["doc"])


def _project(volume=5) -> Stage2Project:
    project = Stage2Project(project_id="p1", company_name="한빛화학")
    project.set_field("facility.reactor.volume", "반응기 용량", volume, "USER_CONFIRMED")
    project.set_field(
        "cap.business.submission_type",
        "화학사고예방관리계획서 제출구분",
        "신규제출",
        "USER_CONFIRMED",
    )
    return project


class VersionPanelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)  # 저장 경로(data/runtime/stage2)가 임시 폴더 안으로 잡힌다.
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        save_project(_project())

    def _run(self, doc="CAP") -> AppTest:
        at = AppTest.from_function(_app, default_timeout=60)
        at.session_state["doc"] = doc
        return at.run()

    def test_first_version_can_only_be_new_and_is_saved(self):
        at = self._run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="ver_kind_CAP_p1").options, ["신규제출"])
        at.button(key="ver_save_CAP_p1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual([m.version_id for m in ver.list_versions("p1", "CAP")], ["CAP-v1.0"])

    def test_change_is_listed_and_change_save_needs_a_reason(self):
        self._run().button(key="ver_save_CAP_p1").click().run()
        save_project(_project(volume=8))
        at = self._run()
        self.assertTrue(any("변경 1건" in e.label for e in at.expander))
        at.selectbox(key="ver_kind_CAP_p1").select("변경제출").run()
        at.button(key="ver_save_CAP_p1").click().run()
        self.assertTrue(at.error)
        self.assertEqual(len(ver.list_versions("p1", "CAP")), 1)
        at.text_input(key="ver_note_CAP_p1").set_value("반응기 증설").run()
        at.button(key="ver_save_CAP_p1").click().run()
        self.assertEqual([m.version_id for m in ver.list_versions("p1", "CAP")], ["CAP-v1.0", "CAP-v1.1"])

    def test_no_new_version_when_nothing_changed(self):
        self._run().button(key="ver_save_CAP_p1").click().run()
        at = self._run()
        at.selectbox(key="ver_kind_CAP_p1").select("재제출").run()
        at.button(key="ver_save_CAP_p1").click().run()
        self.assertTrue(at.error)
        self.assertEqual(len(ver.list_versions("p1", "CAP")), 1)

    def test_restore_requires_confirmation_when_there_are_unsaved_changes(self):
        self._run().button(key="ver_save_CAP_p1").click().run()
        save_project(_project(volume=8))
        at = self._run()
        self.assertTrue(at.button(key="ver_do_restore_CAP_p1").disabled)
        at.checkbox(key="ver_force_CAP_p1").check().run()
        at.button(key="ver_do_restore_CAP_p1").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(load_project("p1").fields["facility.reactor.volume"].value, 5)

    def test_psm_and_cap_versions_are_independent(self):
        self._run("CAP").button(key="ver_save_CAP_p1").click().run()
        self._run("PSM").button(key="ver_save_PSM_p1").click().run()
        self.assertEqual([m.version_id for m in ver.list_versions("p1")], ["CAP-v1.0", "PSM-v1.0"])


if __name__ == "__main__":
    unittest.main()
