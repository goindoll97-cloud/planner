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


class LegalRefreshPanelTests(unittest.TestCase):
    """법령 개정 반영(작성본 최신화) 화면 흐름."""

    def setUp(self):
        from unittest.mock import patch

        from engine.stage2 import legal_baseline_stamp as stamp
        from tests.test_legal_refresh import FORM1_OLD, OLD, _new_sources

        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        project = _project()
        project.set_field("cap.internal.facility_response_plan", "시설별 대응계획", "누출 시 차단", "USER_CONFIRMED")
        save_project(project)
        self.sources = OLD
        p1 = patch.object(stamp, "approved_law_sources", side_effect=lambda *a, **k: self.sources)
        p2 = patch.object(stamp, "_form1_rows", return_value=FORM1_OLD)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self._new_sources = _new_sources
        ver.freeze_version(load_project("p1"), "CAP", "신규제출")

    def _run(self) -> AppTest:
        at = AppTest.from_function(_app, default_timeout=60)
        at.session_state["doc"] = "CAP"
        return at.run()

    def test_no_amendment_reports_nothing_to_do(self):
        at = self._run()
        at.button(key="lr_check_CAP_p1").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("법령 개정이 없습니다" in s.value for s in at.success))

    def test_amendment_is_listed_and_applied_to_a_new_working_copy(self):
        self.sources = self._new_sources(CAP_DRAFT={"effective_date": "20261201"})
        at = self._run()
        at.button(key="lr_check_CAP_p1").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("개정된 법령 1건" in w.value for w in at.warning))
        at.button(key="lr_apply_CAP_p1").click().run()
        self.assertFalse(at.exception)
        project = load_project("p1")
        rec = project.fields["cap.internal.facility_response_plan"]
        self.assertEqual((rec.value, rec.status), ("누출 시 차단", "HOLD"))
        self.assertIn("법령 개정 재확인", rec.note)
        # CAP 작성규정 범위 밖의 공유 사실은 그대로 확인 완료 상태
        self.assertEqual(project.fields["facility.reactor.volume"].status, "USER_CONFIRMED")


def _workspace_like_app():
    import streamlit as st

    from engine.stage2.storage import load_project
    from ui import version_panel

    project = load_project("p1")
    version_panel.render_refresh_banner(project, "CAP")
    version_panel.render(project, "CAP")


class RefreshBannerTests(LegalRefreshPanelTests):
    """프로젝트를 열면 상단에 개정 알림 → 반영 후에는 남은 칸 알림."""

    def _run(self) -> AppTest:
        return AppTest.from_function(_workspace_like_app, default_timeout=60).run()

    def test_no_amendment_reports_nothing_to_do(self):
        at = self._run()
        self.assertFalse(any("개정" in w.value for w in at.warning))

    def test_amendment_is_listed_and_applied_to_a_new_working_copy(self):
        self.sources = self._new_sources(CAP_DRAFT={"effective_date": "20261201", "attachment_hashes": {"별지1": "new"}})
        at = self._run()
        self.assertFalse(at.exception)
        banner = [w.value for w in at.warning if "🔔" in w.value]
        self.assertEqual(len(banner), 1)
        self.assertIn("다시 작성 필요 2칸", banner[0])

        at.button(key="lr_check_CAP_p1").click().run()
        frames = [df.value for df in at.dataframe]
        self.assertTrue(any("구분" in f.columns and "다시 작성 필요" in set(f["구분"]) for f in frames))
        at.button(key="lr_apply_CAP_p1").click().run()
        self.assertFalse(at.exception)

        at = self._run()  # 다시 열면 남은 칸 알림
        pending = [w.value for w in at.warning if "⚖️" in w.value]
        self.assertEqual(len(pending), 1)
        self.assertIn("다시 작성할 칸 2개", pending[0])
        self.assertFalse(any("🔔" in w.value for w in at.warning))

    def test_old_new_articles_are_fetched_on_demand(self):
        from unittest.mock import patch

        from engine import law_old_new

        self.sources = self._new_sources(CAP_DRAFT={"effective_date": "20261201"})
        at = self._run()
        at.button(key="lr_check_CAP_p1").click().run()
        fake = {"status": "OK", "new_info": {"시행일자": "20261201"},
                "rows": [{"조문": "제3조", "변경": "개정", "개정 전": "매 5년", "개정 후": "매 4년"},
                         {"조문": "제5조", "변경": "같음", "개정 전": "같다", "개정 후": "같다"}]}
        with patch.object(law_old_new, "fetch_old_new", return_value=fake) as fetch:
            at.button(key="lr_oldnew_CAP_p1_CAP_DRAFT_btn").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(fetch.call_args.args[0], "CAP_DRAFT")
        table = [df.value for df in at.dataframe if "개정 후" in df.value.columns][0]
        self.assertEqual(list(table["조문"]), ["제3조"])  # 같은 조문은 숨김


class VersionPageTests(unittest.TestCase):
    """왼쪽 메뉴의 독립 ‘버전 관리’ 화면과, 작성 화면에 남기는 한 줄 상태."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        save_project(_project())

    def _page(self):
        from pathlib import Path
        page = Path(__file__).resolve().parents[1] / "ui" / "version_page.py"
        at = AppTest.from_file(str(page), default_timeout=60)
        at.session_state["_stage2_active_project_id"] = "p1"
        return at.run()

    def test_page_saves_and_compares_versions_without_opening_a_writing_screen(self):
        at = self._page()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(len(at.expander), 0)                     # 접지 않고 바로 펼침
        at.button(key="ver_save_CAP_p1").click().run()
        self.assertEqual([m.version_id for m in ver.list_versions("p1", "CAP")], ["CAP-v1.0"])
        save_project(_project(volume=8))
        at = self._page()
        self.assertTrue(any("저장하지 않은 변경 1건" in m.value for m in at.markdown))

    def test_writing_screen_shows_one_line_status_only(self):
        def app():
            from engine.stage2.storage import load_project
            from ui import version_panel
            version_panel.render_status(load_project("p1"), "CAP")

        at = AppTest.from_function(app, default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.expander), 0)
        self.assertEqual(len(at.button), 0)
        self.assertIn("버전 없음", at.caption[0].value)
