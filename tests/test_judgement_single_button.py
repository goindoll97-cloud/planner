from __future__ import annotations

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
JUDGE_LABELS = {"판정 시작하기", "판정 다시 시작하기", "물질 성분 확정하기", "판정 조건 확정하기", "최대보유량 확정하기", "최종판정하기"}


class SingleJudgeButtonTests(unittest.TestCase):
    def _run(self, kind):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from types import SimpleNamespace\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from engine.stage2 import cap_judgement as jd\n"
            "from tests.test_judgement_selected_project import _pending\n"
            "from tests.test_judgement_needed_values import REAL_REQUESTS\n"
            "from tests.test_judgement_questions_plain import ENGINE_REQUESTS\n"
            "from ui import judgement_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = _pending()\n"
            "project = st.session_state['project']\n"
            "kind = %r\n"
            "if kind == 'asking':\n"
            "    msgs = [ENGINE_REQUESTS[2]]\n"
            "    st.session_state['judge_out_' + project.project_id] = SimpleNamespace(status='REQUEST', messages=tuple(msgs), questions=jd._questions_for(msgs, {}))\n"
            "elif kind == 'facility_only':\n"
            "    st.session_state['judge_out_' + project.project_id] = SimpleNamespace(status='REQUEST', messages=(REAL_REQUESTS[4],), questions=())\n"
            "elif kind == 'decided':\n"
            "    st.session_state['judge_out_' + project.project_id] = SimpleNamespace(status='DECIDED', messages=(), questions=(), cap_status='1군', psm_status='비대상', decision=SimpleNamespace(cap_explanation='', psm_explanation=''), cap_target=True, psm_target=False)\n"
            "with patch('engine.stage2.storage.save_project'), patch('engine.stage2.cap_judgement.holding_target_names', return_value=['염소']):\n"
            "    panel.render(project)\n"
        ) % (str(ROOT), kind)
        return AppTest.from_string(code, default_timeout=60).run()

    def _judge_buttons(self, at):
        return [b.label for b in at.button if b.label in JUDGE_LABELS]

    def test_before_the_first_judgement_there_is_exactly_one_button(self):
        at = self._run("none")
        self.assertFalse(at.exception)
        self.assertEqual(self._judge_buttons(at), ["판정 시작하기"])

    def test_while_questions_are_being_asked_only_the_save_and_rejudge_button_is_shown(self):
        at = self._run("asking")
        self.assertFalse(at.exception)
        self.assertEqual(self._judge_buttons(at), ["판정 조건 확정하기"])

    def test_facility_only_stage_shows_only_the_holding_confirmation_button(self):
        at = self._run("facility_only")
        self.assertFalse(at.exception)
        self.assertEqual(self._judge_buttons(at), ["최대보유량 확정하기"])

    def test_final_stage_uses_final_judgement_button(self):
        at = self._run("decided")
        self.assertFalse(at.exception)
        self.assertEqual(self._judge_buttons(at), ["최종판정하기"])

    def test_the_explanations_live_in_question_mark_help_not_in_visible_text(self):
        at = self._run("asking")
        heading = next(m for m in at.markdown if m.value.startswith("#### 판정에 필요한 확인 사항"))
        self.assertIn("왜 묻나요?", heading.help)
        status = next(m for m in at.markdown if m.value.startswith("**현재 판정:**"))
        self.assertIn("물질 성분 확정 → 판정 조건 확정", status.help)
        captions = " ".join(c.value for c in at.caption)
        self.assertNotIn("판정은 1. 성분 확인", captions)                  # 예전의 긴 설명 문구는 화면에 없다
        self.assertNotIn("시설을 입력하면 최대보유량이 계산됩니다", captions)


if __name__ == "__main__":
    unittest.main()
