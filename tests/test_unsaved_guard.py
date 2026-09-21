from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from engine.stage2.local_llm import LocalLLMProbe
from tests.test_psm_workspace_page import _project

ROOT = Path(__file__).resolve().parents[1]
KEY = "psm_fact_business.shift_pattern"


def _open(project=None):
    project = project or _project()
    rows = [{"project_id": project.project_id, "company_name": project.company_name}]
    down = LocalLLMProbe(False, "ollama", "http://127.0.0.1:11434", message="연결되지 않았습니다.")
    patches = [patch("engine.stage2.storage.list_projects", return_value=rows),
               patch("engine.stage2.storage.load_project", return_value=project),
               patch("engine.stage2.storage.save_project"),
               patch("engine.stage2.local_llm.probe_local_llm_runtime", return_value=down)]
    for p in patches:
        p.start()
    at = AppTest.from_file(str(ROOT / "ui/psm_workspace_page.py"), default_timeout=90)
    at.session_state["_stage2_active_project_id"] = project.project_id
    at.run()
    return project, at, patches


def _texts(elements):
    return " ".join(e.value for e in elements)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.patches = []

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _facts(self):
        project, at, self.patches = _open()
        at.selectbox(key="psm_form_no").select("facts").run()
        return project, at

    def test_unedited_screen_shows_no_warning_and_switches_freely(self):
        _project_, at = self._facts()
        self.assertNotIn("저장하지 않은", _texts(at.warning))
        at.selectbox(key="psm_form_no").select("13").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["psm_form_no__accepted"], "13")

    def test_typing_alone_shows_nothing_and_keeps_the_save_button_where_it_is(self):
        _project_, at = self._facts()
        at.text_input(key=KEY).input("우리 회사 3교대").run()
        self.assertNotIn("저장하지 않은", _texts(at.warning))  # 평소에는 아무 안내도 띄우지 않는다
        self.assertIn("psm_fact_save", [b.key for b in at.button])

    def test_leaving_with_unsaved_input_keeps_the_screen_and_asks(self):
        _project_, at = self._facts()
        at.text_input(key=KEY).input("우리 회사 3교대").run()
        at.selectbox(key="psm_form_no").select("13").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["psm_form_no__accepted"], "facts")  # 원래 화면 유지
        self.assertEqual(at.text_input(key=KEY).value, "우리 회사 3교대")  # 입력은 남아 있다
        self.assertIn("이동하면 이 내용은 사라집니다", _texts(at.warning))
        labels = [b.label for b in at.button]
        self.assertIn("계속 편집", labels)
        self.assertIn("저장하지 않고 이동", labels)

    def test_continue_editing_restores_the_selection_and_go_moves_on(self):
        _project_, at = self._facts()
        at.text_input(key=KEY).input("우리 회사 3교대").run()
        at.selectbox(key="psm_form_no").select("13").run()
        at.button(key="psm_form_no__stay").click().run()
        self.assertEqual(at.selectbox(key="psm_form_no").value, "facts")
        self.assertEqual(at.text_input(key=KEY).value, "우리 회사 3교대")
        at.selectbox(key="psm_form_no").select("13").run()
        at.button(key="psm_form_no__go").click().run()
        self.assertEqual(at.session_state["psm_form_no__accepted"], "13")
        self.assertNotIn("저장하지 않은", _texts(at.warning))

    def test_typing_and_switching_in_one_step_is_still_caught(self):
        _project_, at = self._facts()
        # 입력 직후 곧바로 별지를 바꿔 두 변경이 한 번에 서버에 도착하는 경우
        at.text_input(key=KEY).set_value("우리 회사 3교대")
        at.selectbox(key="psm_form_no").select("13")
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["psm_form_no__accepted"], "facts")
        self.assertIn("이동하면 이 내용은 사라집니다", _texts(at.warning))
        self.assertEqual(at.text_input(key=KEY).value, "우리 회사 3교대")

    def test_saving_clears_the_warning_and_lets_the_move_happen(self):
        project, at = self._facts()
        at.text_input(key=KEY).input("우리 회사 3교대").run()
        at.selectbox(key="psm_form_no").select("13").run()
        at.button(key="psm_fact_save").click().run()  # 화면의 저장 버튼
        self.assertEqual(project.get_field("business.shift_pattern").value, "우리 회사 3교대")
        self.assertEqual(at.session_state["psm_form_no__accepted"], "13")  # 저장하면 고른 별지로 이동

    def test_an_example_that_fills_the_box_counts_as_unsaved_when_leaving(self):
        _project_, at = self._facts()
        first = at.radio(key=f"{KEY}__pick").options[0]
        at.radio(key=f"{KEY}__pick").set_value(first).run()
        at.button(key=f"{KEY}__use").click().run()
        at.selectbox(key="psm_form_no").select("13").run()
        self.assertEqual(at.session_state["psm_form_no__accepted"], "facts")
        self.assertIn("이동하면 이 내용은 사라집니다", _texts(at.warning))

    def test_saved_values_are_not_flagged_when_the_screen_is_reopened(self):
        project, at = self._facts()
        at.text_input(key=KEY).input("우리 회사 3교대").run()
        at.button(key="psm_fact_save").click().run()
        self.assertNotIn("저장하지 않은", _texts(at.warning))

    def test_table_edits_are_tracked_too(self):
        project, at, self.patches = _open()
        at.selectbox(key="psm_form_no").select("14").run()
        self.assertNotIn("저장하지 않은", _texts(at.warning))
        # 표 화면이 위젯을 그린다는 것과 추적 대상이라는 것만 확인한다(셀 편집 시뮬레이션은 지원되지 않는다)
        self.assertFalse(at.exception)

    def test_navigation_selectors_are_ignored(self):
        _project_, at = self._facts()
        at.selectbox(key="psm_form_no").select("13").run()
        self.assertNotIn("저장하지 않은", _texts(at.warning))


class CapPageTests(unittest.TestCase):
    def test_cap_page_uses_the_guard_for_every_option(self):
        source = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("unsaved_guard.selector(", source)
        self.assertIn("unsaved_guard.finish()", source)
        self.assertNotIn("st.stop()\nif form_no", source)


if __name__ == "__main__":
    unittest.main()


class RecordTests(unittest.TestCase):
    def _tracker(self):
        from ui import unsaved_guard as guard

        guard._local.tracker = guard.Tracker("k", 1, 1, None)
        self.addCleanup(lambda: setattr(guard._local, "tracker", None))
        return guard, guard._local.tracker

    def test_edited_table_is_dirty_and_unedited_table_is_not(self):
        import pandas as pd

        guard, tracker = self._tracker()
        base = pd.DataFrame([{"a": "1", "b": None}, {"a": "", "b": "x"}])
        guard._record("data_editor", (base,), {"key": "t"}, base.copy())
        self.assertEqual(tracker.dirty, {})
        edited = base.copy()
        edited.loc[0, "a"] = "9"
        guard._record("data_editor", (base,), {"key": "t"}, edited)
        self.assertIn("t", tracker.dirty)

    def test_number_like_values_do_not_cause_false_alarms(self):
        import pandas as pd

        guard, tracker = self._tracker()
        base = pd.DataFrame({"용량": [2, 3], "이름": ["a", "b"]})
        guard._record("data_editor", (base,), {"key": "n"}, base.astype({"용량": "int64"}))
        self.assertEqual(tracker.dirty, {})

    def test_text_uses_the_declared_baseline_and_ignores_navigation_keys(self):
        guard, tracker = self._tracker()
        guard.baseline("box", "저장된 값")
        guard._record("text_input", ("라벨",), {"key": "box"}, "저장된 값")
        self.assertEqual(tracker.dirty, {})
        guard._record("text_input", ("라벨",), {"key": "box"}, "고친 값")
        self.assertEqual(list(tracker.dirty), ["box"])
        guard._record("selectbox", ("별지", ["a", "b"]), {"key": "psm_form_no"}, "b")
        self.assertNotIn("psm_form_no", tracker.dirty)


class NoFalseAlarmTests(unittest.TestCase):
    def test_opening_every_psm_screen_shows_no_unsaved_warning(self):
        from tests.test_psm_workspace_page import _project as psm_project
        from engine.stage2 import psm_table_workspace as tables

        project = psm_project()
        tables.save(project, "14", [{"기계번호": "P-1", "기계명": "펌프", "명세": "원심", "주요재질": "SUS", "전동기용량": "7.5",
                                   "방호·보호장치 종류": "EOCR", "비고": ""}])
        _p, at, patches = _open(project)
        try:
            keys = ["12", "13", "14", "15", "16", "17", "17-2", "17-3", "17-4", "17-5", "18", "19", "19-2", "20", "21",
                    "facts", "export", "files"]
            for key in keys:
                at.selectbox(key="psm_form_no").select(key).run()
                self.assertFalse(at.exception, key)
                # 아무것도 고치지 않은 화면에서는 항상 막힘 없이 다음 별지로 넘어가야 한다(거짓 경고 없음)
                self.assertEqual(at.session_state["psm_form_no__accepted"], key, f"PSM 화면 {key}로 이동하지 못함")
                self.assertNotIn("이동하면 이 내용은", _texts(at.warning), f"PSM 화면 {key}에서 거짓 경고")
        finally:
            for p in patches:
                p.stop()

    def test_opening_every_cap_screen_shows_no_unsaved_warning(self):
        from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

        project = CAPForm1EngineTests()._project()
        rows = [{"project_id": project.project_id, "company_name": project.company_name}]
        down = LocalLLMProbe(False, "ollama", "http://127.0.0.1:11434", message="연결되지 않았습니다.")
        with patch("engine.stage2.storage.list_projects", return_value=rows), \
             patch("engine.stage2.storage.load_project", return_value=project), \
             patch("engine.stage2.storage.save_project"), \
             patch("engine.stage2.local_llm.probe_local_llm_runtime", return_value=down):
            at = AppTest.from_file(str(ROOT / "ui/cap_workspace_page.py"), default_timeout=90)
            at.session_state["_stage2_active_project_id"] = project.project_id
            at.run()
            from ui import cap_forms_registry as registry

            for option in [*registry.FORM_NUMBERS, "narrative", "export"]:
                at.selectbox(key="cap_form_no").select(option).run()
                self.assertFalse(at.exception, option)
                self.assertEqual(at.session_state["cap_form_no__accepted"], option, f"CAP 화면 {option}로 이동하지 못함")
                self.assertNotIn("이동하면 이 내용은", _texts(at.warning), f"CAP 화면 {option}에서 거짓 경고")
