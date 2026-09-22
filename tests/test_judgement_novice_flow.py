from __future__ import annotations

from types import SimpleNamespace
import unittest

from engine.stage2 import cap_judgement as jd
from ui import judgement_panel as panel


class UnitTests(unittest.TestCase):
    def test_kg_and_ton_convert_both_ways_and_unknown_stays_unknown(self):
        self.assertEqual(jd.convert_quantity("500", "kg", "ton"), "0.5")
        self.assertEqual(jd.convert_quantity("0.5", "ton", "kg"), "500")
        self.assertEqual(jd.convert_quantity("1,250", "kg", "ton"), "1.25")
        self.assertEqual(jd.convert_quantity("", "kg", "ton"), "")           # 모르는 값을 0으로 만들지 않는다
        self.assertEqual(jd.convert_quantity("0", "kg", "ton"), "0")         # 0은 '없음'
        self.assertEqual(jd.convert_quantity("약 500", "kg", "ton"), "약 500")  # 숫자가 아니면 손대지 않는다

    def test_table_rows_are_unified_to_ton_using_each_rows_unit(self):
        rows = jd.rows_to_ton([
            {"최대 제조·사용량": "500", "최대 저장량": "2000", "단위": "kg", "함량(%)": "99"},
            {"최대 제조·사용량": "3", "최대 저장량": "", "단위": "ton", "함량(%)": ""},
            {"최대 저장량": "10"},  # 단위가 없으면 ton으로 본다
        ])
        self.assertEqual((rows[0]["최대 제조·사용량"], rows[0]["최대 저장량"], rows[0]["함량(%)"]), ("0.5", "2", "99"))
        self.assertEqual((rows[1]["최대 제조·사용량"], rows[1]["최대 저장량"]), ("3", ""))
        self.assertEqual(rows[2]["최대 저장량"], "10")
        self.assertTrue(all("단위" not in row for row in rows))

    def test_content_percent_is_never_converted(self):
        self.assertEqual(jd.rows_to_ton([{"함량(%)": "50", "단위": "kg"}])[0]["함량(%)"], "50")


class StepTests(unittest.TestCase):
    def test_current_step_follows_what_the_engine_asks_for(self):
        self.assertEqual(panel.current_step(SimpleNamespace(status="COMPOSITION")), 1)
        self.assertEqual(panel.current_step(SimpleNamespace(status="REQUEST", questions=("q",))), 2)
        self.assertEqual(panel.current_step(SimpleNamespace(status="REQUEST", questions=())), 3)
        self.assertEqual(panel.current_step(SimpleNamespace(status="PENDING")), 3)
        self.assertEqual(panel.current_step(SimpleNamespace(status="DECIDED")), 4)

    def test_step_line_marks_only_the_current_step(self):
        line = panel.step_line(2)
        self.assertIn("**2. 판정 조건**", line)
        self.assertNotIn("**1.", line)
        self.assertEqual(panel.step_line(0).count("**"), 0)


class WordingTests(unittest.TestCase):
    def test_the_screens_no_longer_contradict_themselves_about_units_and_optional_fields(self):
        text = open("ui/judgement_panel.py", encoding="utf-8").read()
        self.assertNotIn("수량 단위는 ton 기준으로 적으세요", text)
        self.assertNotIn("(선택 입력)\",", text.replace('"SDS 제2항 유해성·위험성 분류(선택 입력)":', ""))
        self.assertIn("빈 칸은 '아직 모름', 0은 '없음'", text)
        self.assertIn("법정 방식으로 계산했나요", text)
        start = open("ui/cap_start_panel.py", encoding="utf-8").read()
        self.assertIn("모르면 비워 두고", start)


if __name__ == "__main__":
    unittest.main()


class AskScreenTests(unittest.TestCase):
    def test_a_kg_question_lets_the_user_pick_ton_and_stores_kg(self):
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        root = str(Path(__file__).resolve().parents[1])
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from types import SimpleNamespace\n"
            "from unittest.mock import patch\n"
            "import streamlit as st\n"
            "from engine.stage2 import cap_judgement as jd\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from ui import judgement_panel as panel\n"
            "if 'project' not in st.session_state:\n"
            "    st.session_state['project'] = CAPForm1EngineTests()._project()\n"
            "project = st.session_state['project']\n"
            "q = [x for x in jd.QUESTIONS if x.item.endswith('(kg)')][0]\n"
            "outcome = SimpleNamespace(status='REQUEST', questions=(q,), messages=())\n"
            "with patch('engine.stage2.storage.save_project'), patch('ui.judgement_panel.judgement.judge', return_value=SimpleNamespace(status='REQUEST', questions=(q,), messages=())):\n"
            "    panel._ask(project, outcome)\n"
        ) % root
        at = AppTest.from_string(code, default_timeout=60).run()
        self.assertFalse(at.exception)
        key = next(t.key for t in at.text_input if t.key and t.key.endswith("(kg)"))
        at.text_input(key=key).set_value("1.5")
        at.selectbox(key=key + "_unit").select("ton")
        next(b for b in at.button if b.label == "판정 조건 확정하기").click()
        at.run()
        project = at.session_state["project"]
        self.assertEqual(jd.answers(project)[[q for q in jd.QUESTIONS if q.item.endswith("(kg)")][0].item], "1500")
