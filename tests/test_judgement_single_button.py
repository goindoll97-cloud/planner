from __future__ import annotations

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
JUDGE_LABELS = {"판정 시작하기", "판정 다시 시작하기", "판정정보 확인하기", "다음 단계로 이동", "최대보유량 먼저 입력", "최종판정하기"}


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
            "elif kind == 'saved_unknown':\n"
            "    question = jd.QUESTIONS[0]\n"
            "    jd.save_answers(project, {question.item: question.options[-1]})\n"
            "    st.session_state['judge_out_' + project.project_id] = SimpleNamespace(status='REQUEST', messages=(question.trigger,), questions=(question,))\n"
            "elif kind == 'decided':\n"
            "    st.session_state['judge_out_' + project.project_id] = SimpleNamespace(status='DECIDED', messages=(), questions=(), cap_status='Group1', psm_status='NotApplicable', decision=SimpleNamespace(cap_explanation='', psm_explanation=''), cap_target=True, psm_target=False)\n"
            # AppTest.from_string은 스크립트를 시스템 기본 인코딩(이 환경에서는 cp949)으로 임시
            # 파일에 쓰지만 다시 읽을 때는 UTF-8을 가정하므로, 코드 문자열 안에 직접 한글을 넣으면
            # UnicodeDecodeError로 스크립트 자체가 컴파일되지 않는다(한글은 모듈 임포트로만 전달한다).
            "with patch('engine.stage2.storage.save_project'), patch('engine.stage2.cap_judgement.holding_target_names', return_value=['Chlorine']):\n"
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
        self.assertEqual(self._judge_buttons(at), ["판정정보 확인하기"])

    def test_facility_only_stage_shows_only_the_holding_confirmation_button(self):
        at = self._run("facility_only")
        self.assertFalse(at.exception)
        # 시설 입력 화면(cap_facility_editor, compact 모드)은 PSM 수량 단계와 같은
        # "다음 단계로 이동" 문구를 쓴다(둘 다 "2. 최대보유량 확인"의 하위 단계).
        self.assertEqual(self._judge_buttons(at), ["다음 단계로 이동"])

    def test_saved_unknown_stays_on_questions_until_the_holding_action_is_explicit(self):
        at = self._run("saved_unknown")
        self.assertFalse(at.exception)
        self.assertIn("판정정보 확인하기", self._judge_buttons(at))
        self.assertIn("최대보유량 먼저 입력", self._judge_buttons(at))
        self.assertFalse(any(m.value.startswith("**시설 입력") for m in at.markdown))

        pid = at.session_state["project"].project_id
        at.button(key=f"judge_answer_{pid}").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any("최종 판정은 보류 중입니다" in warning.value for warning in at.warning))
        self.assertFalse(any(m.value.startswith("**시설 입력") for m in at.markdown))

        self.assertIn("최대보유량 먼저 입력", self._judge_buttons(at))
        at.button(key=f"judge_open_holding_{pid}").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any(m.value.startswith("**시설 입력") for m in at.markdown))
        self.assertTrue(any("최종 판정 전에 확인해야 합니다" in info.value for info in at.info))

    def test_final_stage_uses_final_judgement_button(self):
        at = self._run("decided")
        self.assertFalse(at.exception)
        self.assertEqual(self._judge_buttons(at), ["최종판정하기"])

    def test_the_explanations_live_in_question_mark_help_not_in_visible_text(self):
        at = self._run("asking")
        heading = next(m for m in at.markdown if m.value.startswith("#### 판정에 필요한 확인 사항"))
        self.assertIn("왜 묻나요?", heading.help)
        status = next(m for m in at.markdown if m.value.startswith("**현재 판정:**"))
        self.assertIn("판정정보 확인 → 최대보유량 확인", status.help)
        captions = " ".join(c.value for c in at.caption)
        self.assertNotIn("판정은 1. 성분 확인", captions)                  # 예전의 긴 설명 문구는 화면에 없다
        self.assertNotIn("시설을 입력하면 최대보유량이 계산됩니다", captions)


if __name__ == "__main__":
    unittest.main()
