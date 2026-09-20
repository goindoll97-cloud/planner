from __future__ import annotations

from unittest.mock import patch
import unittest

from engine.stage2 import psm_narrative_workspace as nw
from engine.stage2.ai_drafting import typed_fact_owner
from engine.stage2.local_ai_resilience import retry_instruction
from tests.test_psm_narrative_workspace import _with_facts
from tests.test_psm_workspace_page import _project
from ui.narrative_panel import progress_lines


class Item:
    def __init__(self, key, warnings):
        self.requirement_key, self.validation_warnings = key, tuple(warnings)


class RetryInstructionTests(unittest.TestCase):
    def test_borrowed_fact_hint_names_the_items_own_fact(self):
        hint = retry_instruction(Item("psm.emergency.training", ["다른 항목의 사실을 가져다 썼습니다: psm.facts.training"]))
        self.assertIn("psm.facts.emergency_training", hint)
        self.assertIn("psm.emergency.training", hint)

    def test_unfixable_reasons_are_not_retried(self):
        self.assertEqual(retry_instruction(Item("psm.operation.sop", ["로컬 AI가 본문 초안을 반환하지 않았습니다."])), "")

    def test_number_and_internal_key_hints(self):
        self.assertIn("숫자", retry_instruction(Item("k", ["확인자료에 없는 수치: 3, 4"])))
        self.assertIn("내부 변수", retry_instruction(Item("k", ["확인되지 않은 내부 사실키를 참조함: cap_group"])))


class FlakyClient:
    """처음에는 다른 항목의 사실을 섞어 쓰고, 재시도 지시를 받으면 제대로 쓴다."""
    model = "fake"

    def __init__(self):
        self.prompts = []

    def generate_json(self, *, instructions, prompt):
        self.prompts.append(prompt)
        retry = "[재시도 지시]" in prompt
        keys = [k for k in nw.AI_ITEMS if f'"requirement_key": "{k}"' in prompt]
        return {"profile_summary": "염소 저장 공정입니다.",
                "drafts": [{"requirement_key": k, "draft_text": "본 사업장은 정해진 방법으로 실시한다.",
                            "used_fact_keys": [typed_fact_owner(k)] if retry and typed_fact_owner(k) else
                            ["psm.facts.training"], "suggested_additions": []} for k in keys]}


class RetryFlowTests(unittest.TestCase):
    def test_a_rejected_item_is_retried_once_and_saved_when_the_retry_passes(self):
        project = _with_facts(_project())
        for fact in nw.DECISION_FACTS:
            nw.save_fact(project, fact, {name: "예시 내용" for name, _, _ in fact.fields})
        client, events = FlakyClient(), []
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, client, progress=events.append)
        ok = {d.requirement_key for d in result.generated}
        self.assertIn("psm.emergency.public_information", ok)  # 재시도로 살아났다
        self.assertIn("psm.emergency.training", ok)
        self.assertTrue(any(e["event"] == "retry" for e in events))
        self.assertTrue(any("[재시도 지시]" in p for p in client.prompts))

    def test_retry_progress_text(self):
        ratio, text = progress_lines({"event": "retry", "done": 2, "total": 2, "labels": ["주민홍보계획"], "elapsed": 30,
                                      "generated": 6, "rejected": 2})
        self.assertEqual(ratio, 1.0)
        self.assertIn("다시 만드는 중", text)


if __name__ == "__main__":
    unittest.main()
