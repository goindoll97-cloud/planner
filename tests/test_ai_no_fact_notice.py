from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.stage2 import ai_drafting as drafting
from engine.stage2 import psm_narrative_workspace as nw
from tests.test_psm_narrative_workspace import _with_facts
from tests.test_psm_workspace_page import _project


class Client:
    model = "fake"

    def __init__(self, used):
        self.used = used

    def generate_json(self, *, instructions, prompt):
        return {"profile_summary": "염소 저장 공정입니다.",
                "drafts": [{"requirement_key": key, "draft_text": "본 사업장은 절차를 수립하여 관리한다.",
                            "used_fact_keys": self.used, "suggested_additions": ["세부 절차"]} for key in nw.AI_ITEMS]}


class NoFactNoticeTests(unittest.TestCase):
    def _texts(self, used):
        project = _with_facts(_project())
        for fact in nw.DECISION_FACTS:
            nw.save_fact(project, fact, {name: "예시 내용" for name, _, _ in fact.fields})
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, Client(used))
        return [d.draft_text for d in result.generated]

    def test_a_draft_that_used_no_typed_fact_gets_the_check_notice_even_with_suggestions(self):
        texts = self._texts(["inventory.chemicals"])
        self.assertTrue(texts)
        self.assertTrue(all(drafting.NO_FACT_NOTICE in text for text in texts))

    def test_a_draft_built_from_a_typed_fact_is_not_flagged(self):
        texts = self._texts(["psm.facts.training"])
        self.assertTrue(texts)
        self.assertTrue(all(drafting.NO_FACT_NOTICE not in text for text in texts))

    def test_the_prompt_forbids_inventing_procedures_and_ownership_claims(self):
        prompt = drafting._system_prompt("PSM")
        self.assertIn("덧붙이지 않는다", prompt)
        self.assertIn("수립하여 관리한다", prompt)


if __name__ == "__main__":
    unittest.main()
