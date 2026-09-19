from __future__ import annotations

from unittest.mock import patch
import unittest

from engine.stage2 import ai_drafting as drafting
from engine.stage2 import psm_narrative_workspace as nw
from engine.stage2 import statutory_report as report
from engine.stage2 import psm_table_workspace as tables
from tests.test_psm_workspace_page import _project, _run


class FakeClient:
    model = "fake-local"

    def generate_json(self, *, instructions, prompt):
        return {
            "profile_summary": "염소를 저장하고 이송하는 공정입니다.",
            "drafts": [{"requirement_key": key,
                        "draft_text": "확인된 설비와 물질을 기준으로 운전자가 따라야 할 절차를 단계별로 기술합니다.",
                        "used_fact_keys": ["inventory.chemicals"],
                        "suggested_additions": ["회사 고유 절차가 있으면 추가해 주세요."]}
                       for key in nw.AI_ITEMS],
        }


def _with_facts(project):
    for fact in nw.BASIC_FACTS:
        nw.save_fact(project, fact, "염소를 탱크에 받아 이송한다." if fact.long else "연속 운전")
    return project


class NarrativeTests(unittest.TestCase):
    def test_items_wait_for_the_basic_facts_and_say_what_is_missing(self):
        project = _project()
        items = {i["key"]: i for i in nw.item_status(project)}
        self.assertTrue(all(i["state"] == "만들 수 없음" for i in items.values()))
        self.assertIn("공정 개요", items["psm.operation.sop"]["reason"])
        self.assertEqual(nw.missing_basics(_with_facts(project)), [])

    def test_mitigation_needs_the_risk_report_first(self):
        project = _with_facts(_project())
        items = {i["key"]: i for i in nw.item_status(project)}
        self.assertEqual(items[nw.RISK_ITEM]["state"], "만들 수 없음")
        self.assertIn("위험성평가 보고서", items[nw.RISK_ITEM]["reason"])
        self.assertEqual(items["psm.operation.sop"]["state"], "초안 만들기 가능")

    def test_blank_fact_input_never_erases(self):
        project = _project()
        nw.save_fact(project, nw.BASIC_FACTS[0], "공정 설명")
        self.assertFalse(nw.save_fact(project, nw.BASIC_FACTS[0], ""))
        self.assertEqual(nw.facts_value(project, nw.BASIC_FACTS[0]), "공정 설명")
        decision = nw.DECISION_FACTS[0]
        nw.save_fact(project, decision, {"대상": "운전원", "주기": ""})
        self.assertEqual(nw.facts_value(project, decision), {"대상": "운전원"})

    def test_generate_stores_drafts_that_are_not_final_until_adopted(self):
        project = _with_facts(_project())
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient())
        self.assertTrue(result.generated, result.rejected and [r.validation_warnings for r in result.rejected])
        key = result.generated[0].requirement_key
        record = project.get_field(drafting.ai_draft_field_key("PSM", key))
        self.assertEqual(record.status, "AI_DRAFT")
        spec = nw._specs(project)[key]
        self.assertIsNone(project.get_field(spec.field_keys[0]))  # 보고서 칸은 아직 비어 있다
        state = {i["key"]: i["state"] for i in nw.item_status(project)}
        self.assertEqual(state[key], "초안 있음")

    def test_adopting_a_draft_puts_it_where_the_report_reads_it(self):
        project = _with_facts(_project())
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient())
        key = result.generated[0].requirement_key
        nw.adopt(project, key)
        spec = nw._specs(project)[key]
        record = project.get_field(spec.field_keys[0])
        self.assertEqual(record.status, "USER_CONFIRMED")
        self.assertIn("절차", record.value)
        self.assertEqual({i["key"]: i["state"] for i in nw.item_status(project)}[key], "확인 완료")

    def test_adoption_refuses_text_with_ungrounded_numbers(self):
        project = _with_facts(_project())
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient())
        key = result.generated[0].requirement_key
        with self.assertRaises(ValueError):
            nw.adopt(project, key, "설정압력은 9.87 MPa로 한다.")


class FactTablesTests(unittest.TestCase):
    def test_fact_tables_are_registered_and_reach_the_ai_context(self):
        for form_no in ("emergency-resources", "emergency-contacts", "wash-ppe"):
            self.assertIn(form_no, tables.SPECS)
        self.assertIn("psm.emergency.resources", drafting._GLOBAL_FACT_KEYS)
        project = _project()
        tables.save(project, "emergency-contacts", [{"연락처 구분": "소방서", "기관·부서·담당자": "관할 소방서",
                                                     "전화번호": "119", "연락 순서": "1"}])
        self.assertEqual(tables.needs(project, "emergency-contacts"), [])


class ScreenTests(unittest.TestCase):
    def test_facts_screen_renders_with_and_without_a_local_ai(self):
        project = _with_facts(_project())
        from engine.stage2.local_llm import LocalLLMProbe
        down = LocalLLMProbe(False, "ollama", "http://127.0.0.1:11434", message="연결되지 않았습니다.")
        with patch("engine.stage2.local_llm.probe_local_llm_runtime", return_value=down):
            at = _run(project, "facts")
        self.assertFalse(at.exception)
        self.assertTrue(any("연결" in w.value for w in at.warning))
        self.assertTrue(any(b.label == "초안 만들기" and b.disabled for b in at.button))


if __name__ == "__main__":
    unittest.main()


class FinalDocumentTests(unittest.TestCase):
    def test_adopted_text_and_facts_appear_in_the_final_report_chapters(self):
        from docx import Document

        project = _with_facts(_project())
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient())
        for item in result.generated:
            nw.adopt(project, item.requirement_key)
        doc = Document()
        report._render_psm_narrative(doc, project)
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("염소를 탱크에 받아 이송한다.", text)  # 공정 개요(사실)
        self.assertIn("운전자가 따라야 할 절차", text)  # 승인한 AI 초안
