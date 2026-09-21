from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.inventory import _map_sds_text_to_app1_keys
from engine.stage2 import cap_judgement as j
from engine.stage2 import kosha_candidates as kc
from engine.stage2.storage import load_project
from tests.test_judgement_inputs import JudgementPanelTests


class KoshaCandidateTests(unittest.TestCase):
    def test_only_classifications_with_a_category_become_a_candidate(self):
        text = kc.candidate_text(["급성 독성(흡입) : 구분 1", "열로부터 멀리하시오", "인화성 액체 : 구분 2"])
        self.assertEqual(text, "급성 독성(흡입) : 구분 1|인화성 액체 : 구분 2")
        self.assertEqual(kc.candidate_text(["예방조치문구만 있음"]), "")  # '해당없음'을 대신 채우지 않는다

    def test_fetch_dedupes_cas_and_turns_failures_into_a_status(self):
        calls = []

        def fake(cas):
            calls.append(cas)
            if cas == "1-1-1":
                raise RuntimeError("boom")
            return SimpleNamespace(status="MATCHED", ghs_classifications=["인화성 액체 : 구분 2"], chemical_name="아세톤",
                                   message="ok", checked_at_utc="t")

        out = kc.fetch(["67-64-1", "67-64-1", "1-1-1", ""], lookup=fake)
        self.assertEqual(sorted(calls), ["1-1-1", "67-64-1"])
        self.assertTrue(out["67-64-1"].usable)
        self.assertEqual(out["1-1-1"].status, "API_ERROR")
        self.assertFalse(out["1-1-1"].usable)

    def test_candidate_text_is_in_the_format_the_engine_sds_parser_reads(self):
        from engine.cap_sds_app1 import SDSApp1Option

        options = [SDSApp1Option("급성독성 (흡입)||1", "급성 유해성", "급성독성 (흡입)", 1, 1.0, 20.0),
                   SDSApp1Option("인화성 액체||2", "물리적 위험성", "인화성 액체", 2, 5.0, 200.0)]
        text = kc.candidate_text(["급성 독성(흡입) : 구분 1", "인화성 액체 : 구분 2"])
        with patch("engine.cap_sds_app1.app1_sds_options", return_value=options):
            selected, verified_none = _map_sds_text_to_app1_keys(text)
        self.assertFalse(verified_none)
        self.assertEqual(set(selected), {"급성독성 (흡입)||1", "인화성 액체||2"})


class KoshaPanelTests(JudgementPanelTests):
    def test_fetching_fills_blank_cells_and_saving_needs_the_confirmation(self):
        seen = []

        def fake(cas):
            seen.append(cas)
            return SimpleNamespace(status="MATCHED", ghs_classifications=["인화성 액체 : 구분 2"], chemical_name="x",
                                   message="ok", checked_at_utc="t")

        with patch("engine.kosha_msds.lookup_by_cas", side_effect=fake):
            at = self._screen()
            at.button(key="judge_kosha_go_jp").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(seen)
        self.assertTrue(at.button(key="judge_answer_jp").disabled)  # 확인하기 전에는 저장할 수 없다
        at.checkbox(key="judge_kosha_ok_jp").check().run()
        self.assertFalse(at.button(key="judge_answer_jp").disabled)
        at.button(key="judge_answer_jp").click().run()
        project = load_project("jp")
        self.assertIn("인화성 액체 : 구분 2", str(j.chemical_inputs(project)))
        self.assertIsNotNone(project.get_field("stage1.kosha_sds_candidates"))


# 부모 테스트(JudgementPanelTests)가 이 모듈에서 다시 실행되지 않게 한다.
del JudgementPanelTests

if __name__ == "__main__":
    unittest.main()
