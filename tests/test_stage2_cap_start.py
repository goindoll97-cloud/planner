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


def _decision(cap_status="화학사고예방관리계획서 작성·제출 대상 — 2군", system=(), requests=()):
    return SimpleNamespace(
        cap_status=cap_status, cap_explanation="설명", psm_status="공정안전보고서 제출 대상 아님",
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

    def test_company_requests_and_system_blockers_stop_the_start(self):
        request = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(requests=["함량 확인"]))
        system = cap_start.start(BUSINESS, CHEMICALS, assess=lambda intake: _decision(system=["규정 DB 필요"]))
        self.assertEqual((request.status, request.messages), ("REQUEST", ("함량 확인",)))
        self.assertEqual((system.status, system.messages), ("SYSTEM", ("규정 DB 필요",)))
        self.assertIsNone(request.project)

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
