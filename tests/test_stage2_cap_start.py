from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from engine.stage2 import cap_start
from engine.stage2 import cap_workspace as ws

ROOT = Path(__file__).resolve().parents[1]

BUSINESS = {"사업장명": "가상화학", "사업장 주소": "울산광역시 남구 산업로 1", "업종 또는 주요 생산품": "화학제품 제조"}
CHEMICALS = [{"제품명": "염소", "CAS No.": "7782-50-5", "함량(%)": 100.0, "최대 동시보유량(ton)": 3.0},
             {"제품명": "", "CAS No.": "", "함량(%)": 100.0, "최대 동시보유량(ton)": None}]  # 빈 줄


def _decision(cap_status="화학사고예방관리계획서 작성·제출 대상 — 2군", system=(), requests=(),
              psm_status="현재 확인 범위에서 공정안전보고서 제출 대상 기준 미해당"):
    return SimpleNamespace(
        cap_status=cap_status, cap_explanation="설명", psm_status=psm_status,
        system_blockers=list(system), company_requests=list(requests), psm_explanation="", psm_r_value=None,
        psm_legal_basis=[], cap_legal_basis=[], psm_ratio_rows=[], cap_quantity_rows=[],
    )


class CapStartTests(unittest.TestCase):
    def test_typed_rows_become_stage1_intake_and_blank_rows_are_dropped(self):
        intake = cap_start.build_intake(BUSINESS, CHEMICALS)
        self.assertEqual(len(intake.chemicals), 1)
        row = intake.chemicals.iloc[0]
        self.assertEqual((row["제품명"], row["CAS No."], row["수량 단위"]), ("염소", "7782-50-5", "ton"))
        self.assertEqual(row["최대 동시보유량(알면 입력)"], 3.0)
        self.assertTrue(intake.source_fingerprint)

    def test_missing_basics_are_reported_before_any_judgement(self):
        called = []
        outcome = cap_start.start({"사업장명": "", "사업장 주소": "", "업종 또는 주요 생산품": ""}, [],
                                  assess=lambda intake: called.append(1))
        self.assertEqual(outcome.status, "INVALID")
        self.assertEqual(called, [])
        self.assertTrue(any("사업장" in m for m in outcome.messages))

    def test_a_target_site_gets_a_project_with_cap_scope_confirmed(self):
        outcome = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision())
        self.assertEqual(outcome.status, "STARTED")
        project = outcome.project
        self.assertTrue(project.cap_in_scope)
        self.assertFalse(project.psm_in_scope)
        self.assertEqual(project.cap_group, "2군")
        self.assertEqual(project.company_name, "가상화학")
        self.assertEqual(project.get_field("business.address").value, "울산광역시 남구 산업로 1")
        [chemical] = project.get_field("inventory.chemicals").value
        self.assertEqual(chemical["물질명"], "염소")

    def test_a_psm_only_site_starts_with_psm_in_scope(self):
        outcome = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(
            cap_status="화학사고예방관리계획서 작성·제출 의무 없음 — 하위 규정수량 미만", psm_status="공정안전보고서 제출 대상"))
        self.assertEqual(outcome.status, "STARTED")
        self.assertTrue(outcome.project.psm_in_scope)
        self.assertFalse(outcome.project.cap_in_scope)

    def test_a_site_targeted_by_both_documents_starts_both(self):
        outcome = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(psm_status="공정안전보고서 제출 대상"))
        self.assertTrue(outcome.project.psm_in_scope and outcome.project.cap_in_scope)

    def test_the_new_project_feeds_the_form1_workspace(self):
        project = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision()).project
        rows = ws.facility_editor_rows(project)
        self.assertEqual(rows, [])  # 시설은 별지 제1호에서 입력
        chemicals = ws.form1._chemical_identity_rows(project)
        self.assertEqual(ws.form1._row_value(chemicals[0], "물질명", "제품명"), "염소")

    def test_a_site_that_is_not_a_target_does_not_start_authoring(self):
        outcome = cap_start.start(BUSINESS, CHEMICALS,
                                  assess=lambda intake: _decision("화학사고예방관리계획서 작성·제출 의무 없음 — 하위 규정수량 미만"))
        self.assertEqual(outcome.status, "NOT_REQUIRED")
        self.assertIsNone(outcome.project)
        self.assertIn("의무 없음", outcome.cap_status)

    def test_engine_requests_create_a_pending_site_and_only_system_blockers_stop_the_start(self):
        request = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(requests=["함량 확인"]))
        system = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(system=["규정 DB 필요"]))
        self.assertEqual((request.status, request.messages), ("PENDING", ("함량 확인",)))
        self.assertIsNotNone(request.project)  # 막다른 길 대신 사업장을 만들고 판정에 필요한 질문은 그 화면에서 묻는다
        self.assertTrue(request.project.stage1_snapshot["judgement_pending"])
        self.assertFalse(request.project.scope_confirmed)
        self.assertEqual((system.status, system.messages), ("SYSTEM", ("규정 DB 필요",)))
        self.assertIsNone(system.project)

    def test_unknown_quantity_no_longer_blocks_the_start(self):
        chemicals = [{**CHEMICALS[0], "최대 동시보유량(ton)": None}]
        called = []
        outcome = cap_start.start(BUSINESS, chemicals, assess=lambda intake: called.append(1))
        self.assertEqual(outcome.status, "PENDING")
        self.assertEqual(called, [])  # 판정 엔진은 양을 알 때까지 부르지 않는다
        self.assertIn("최대보유량", outcome.messages[0])
        self.assertEqual(outcome.project.get_field("inventory.chemicals").value[0]["물질명"], "염소")

    def test_explicit_single_direct_entry_requires_a_valid_cas(self):
        chemicals = [{
            "제품명": "CAS 없는 단일물질", "단일물질/혼합물": "단일물질", "CAS No.": "",
            "최대 제조·사용량": 1, "최대 저장량": 2, "단위": "ton",
        }]
        outcome = cap_start.start(BUSINESS, chemicals, assess=lambda intake: _decision())
        self.assertEqual(outcome.status, "INVALID")
        self.assertTrue(any("CAS No." in message for message in outcome.messages))

    def test_explicit_mixture_creates_a_pending_site_for_the_second_file(self):
        chemicals = [{
            "제품명": "세척제 A", "단일물질/혼합물": "혼합물", "CAS No.": "",
            "최대 제조·사용량": 1, "최대 저장량": 2, "단위": "ton",
        }]
        called = []
        outcome = cap_start.start(BUSINESS, chemicals, assess=lambda intake: called.append(1))
        self.assertEqual(outcome.status, "PENDING")
        self.assertEqual(called, [])
        self.assertIn("혼합제품", outcome.messages[0])
        self.assertIsNotNone(outcome.project)

    def test_other_input_problems_still_block(self):
        outcome = cap_start.start({**BUSINESS, "사업장명": ""}, CHEMICALS, assess=lambda intake: None)
        self.assertEqual(outcome.status, "INVALID")

    def test_real_stage1_engine_fails_closed_without_the_approved_database(self):
        outcome = cap_start.start(BUSINESS, CHEMICALS)  # 이 저장소에는 승인 규정 DB가 없다
        self.assertIn(outcome.status, ("SYSTEM", "REQUEST", "NOT_REQUIRED", "STARTED"))
        self.assertNotEqual(outcome.status, "STARTED")

    def test_page_offers_the_start_panel_and_the_legal_gate(self):
        page = (ROOT / "ui/cap_workspace_page.py").read_text(encoding="utf-8")
        self.assertIn("cap_start_panel.render", page)
        panel = (ROOT / "ui/cap_start_panel.py").read_text(encoding="utf-8")
        self.assertIn("decision_readiness_gate", panel)
        self.assertIn("cap_start.start(", panel)


if __name__ == "__main__":
    unittest.main()
