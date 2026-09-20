from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.stage2 import ai_drafting as drafting
from engine.stage2 import cap_narrative_workspace as cn
from engine.stage2 import psm_narrative_workspace as nw
from tests.test_psm_narrative_workspace import _with_facts
from tests.test_psm_workspace_page import _project


class OwnerTests(unittest.TestCase):
    def test_each_item_maps_to_its_own_typed_fact(self):
        self.assertEqual(drafting.typed_fact_owner("cap.external.public_notice"), "cap.facts.public_notice")
        self.assertEqual(drafting.typed_fact_owner("cap.external.communication"), "cap.facts.community")
        self.assertEqual(drafting.typed_fact_owner("cap.internal.shutdown"), "cap.facts.shutdown")
        self.assertEqual(drafting.typed_fact_owner("psm.emergency.training"), "psm.facts.emergency_training")
        self.assertEqual(drafting.typed_fact_owner("psm.operation.sop"), "")

    def test_every_typed_fact_has_an_item_that_owns_it(self):
        owners = {drafting.typed_fact_owner(key) for key in nw.AI_ITEMS}
        self.assertTrue({f.key for f in nw.DECISION_FACTS} <= owners)


class Client:
    model = "fake"

    def generate_json(self, *, instructions, prompt):
        wrong = "psm.facts.training"  # 교육 사실을 비상 훈련·주민 홍보 항목에 가져다 쓴 경우
        return {"profile_summary": "염소 저장 공정입니다.",
                "drafts": [{"requirement_key": key, "draft_text": "본 사업장은 정해진 방법으로 실시한다.",
                            "used_fact_keys": [wrong], "suggested_additions": []} for key in nw.AI_ITEMS]}


class BorrowedFactTests(unittest.TestCase):
    def test_a_draft_that_borrows_another_items_fact_is_rejected(self):
        project = _with_facts(_project())
        for fact in nw.DECISION_FACTS:
            nw.save_fact(project, fact, {name: "예시 내용" for name, _, _ in fact.fields})
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, Client())
        ok = {d.requirement_key for d in result.generated}
        rejected = {r.requirement_key for r in result.rejected}
        self.assertIn("psm.operation.training", ok)          # 자기 사실이라 통과
        self.assertIn("psm.emergency.public_information", rejected)
        self.assertIn("psm.emergency.training", rejected)


if __name__ == "__main__":
    unittest.main()
