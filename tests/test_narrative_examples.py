from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from engine.stage2 import narrative_examples as ex
from engine.stage2 import psm_narrative_workspace as nw
from tests.test_psm_workspace_page import _project, _run


class ExampleDataTests(unittest.TestCase):
    def test_every_free_text_fact_has_examples_and_no_example_is_duplicated(self):
        for fact in nw.BASIC_FACTS:
            if fact.key in ("business.process_count", "business.employee_count"):
                continue  # 숫자만 적는 칸에는 예시가 필요 없다
            self.assertTrue(ex.choices(fact.key), fact.key)
        for fact in nw.DECISION_FACTS:
            for name, _label, _help in fact.fields:
                options = ex.choices(fact.key, name)
                self.assertGreaterEqual(len(options), 3, (fact.key, name))
                self.assertEqual(len(options), len(set(options)), (fact.key, name))

    def test_examples_do_not_name_companies_or_statutes_or_long_numbers(self):
        every = ex.choices("process.description") + [ex.template("process.description")]
        for fact in nw.DECISION_FACTS:
            for name, _l, _h in fact.fields:
                every += ex.choices(fact.key, name)
        for text in every:
            self.assertFalse(re.search(r"\d{3,}", text), text)  # 사양·번호처럼 보이는 숫자 없음
            self.assertIsNone(re.search(r"제\d+조", text), text)  # 특정 조문 인용 없음
        self.assertIn("예시입니다", ex.notice())

    def test_verbatim_detection_ignores_whitespace_only(self):
        sample = ex.choices("business.shift_pattern")[0]
        self.assertTrue(ex.is_example("business.shift_pattern", "", "  " + sample.replace(" ", "  ") + " "))
        self.assertFalse(ex.is_example("business.shift_pattern", "", sample + " (우리 공장)"))
        self.assertFalse(ex.is_example("business.shift_pattern", "", ""))


class SavingTests(unittest.TestCase):
    def test_verbatim_example_is_flagged_and_edited_text_is_not(self):
        project = _project()
        fact = next(f for f in nw.BASIC_FACTS if f.key == "business.shift_pattern")
        nw.save_fact(project, fact, ex.choices(fact.key)[0])
        self.assertEqual(nw.chosen_as_is(project), [fact.label])
        nw.save_fact(project, fact, ex.choices(fact.key)[0] + ", 명절 연휴는 2교대")
        self.assertEqual(nw.chosen_as_is(project), [])

    def test_grouped_facts_flag_only_the_subfields_left_as_is(self):
        project = _project()
        fact = nw.DECISION_FACTS[0]
        nw.save_fact(project, fact, {"대상": ex.choices(fact.key, "대상")[0], "주기": "월 1회 우리 방식", "방법": ""})
        record = project.get_field(fact.key)
        self.assertIn("대상", record.note)
        self.assertNotIn("주기", record.note)


class ScreenTests(unittest.TestCase):
    def _facts_screen(self, interact=None):
        from engine.stage2.local_llm import LocalLLMProbe

        down = LocalLLMProbe(False, "ollama", "http://127.0.0.1:11434", message="연결되지 않았습니다.")
        project = _project()
        with patch("engine.stage2.local_llm.probe_local_llm_runtime", return_value=down):
            return project, _run(project, "facts", interact)

    def test_choosing_an_example_fills_the_box_without_saving(self):
        sample = ex.choices("process.description")[0]

        def click(at):
            at.button(key="psm_fact_process.description__ex0").click().run()
        project, at = self._facts_screen(click)
        self.assertFalse(at.exception)
        self.assertEqual(at.text_area(key="psm_fact_process.description").value, sample)
        self.assertIsNone(project.get_field("process.description"))  # 저장은 사용자가 눌러야 한다

    def test_the_screen_shows_the_template_and_the_notice(self):
        _project_, at = self._facts_screen()
        self.assertFalse(at.exception)
        self.assertTrue(any("문장 틀" in c.value for c in at.caption))
        self.assertTrue(any("예시입니다" in c.value for c in at.caption))
        self.assertTrue(any("확인할 점" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
