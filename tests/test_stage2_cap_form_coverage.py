from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.cap_form_coverage import (
    ASK_COMPANY,
    CALCULATION,
    EXTERNAL_ANALYSIS,
    LEGAL_ENGINE,
    READY,
    RENDERER_GAP,
    audit_cap_form_coverage,
)
from engine.stage2.project import Stage2Project


ROOT = Path(__file__).resolve().parents[1]


class CAPFormCoverageTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-CAP-COVERAGE",
            company_name="가상화학",
            site_name="울산공장",
            psm_required=False,
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            psm_selected=False,
            cap_selected=True,
        )
        project.set_field("business.company_name", "회사명", "가상화학", "USER_CONFIRMED")
        project.set_field("business.address", "주소", "울산광역시 테스트로 1", "USER_CONFIRMED")
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "함량(%)": 100, "최대보유량": 800, "단위": "kg"}],
            "USER_CONFIRMED",
        )
        project.set_field(
            "inventory.facilities",
            "시설목록",
            [{
                "설비번호": "V-301",
                "설비명": "염소 공급용기군",
                "설비종류": "압력용기",
                "설계압력": "7.0 MPa",
                "운전압력": "0.9 MPa",
                "설계온도": "50 ℃",
                "운전온도": "25 ℃",
                "최대보유량": 800,
            }],
            "USER_CONFIRMED",
        )
        project.set_field("process.description", "공정개요", "염소를 저장 후 공정에 공급한다.", "USER_CONFIRMED")
        project.set_field("cap.business.unit_plant_name", "단위공장명", "제1공장", "USER_CONFIRMED")
        project.set_field("cap.business.submission_type", "제출구분", "신규제출", "USER_CONFIRMED")
        project.set_field("cap.business.submission_reason", "제출 사유", "최초", "USER_CONFIRMED")
        project.set_field("cap.business.writer_name", "작성자", "최유진", "USER_CONFIRMED")
        project.set_field("cap.business.writer_contact", "연락처", "052-000-0000", "USER_CONFIRMED")
        project.set_field("cap.business.writer_email", "메일", "safety@example.com", "USER_CONFIRMED")
        return project

    def test_audit_distinguishes_blank_causes_instead_of_one_generic_hold(self):
        items = audit_cap_form_coverage(self._project())
        by_key = {(item.form_no, item.item): item for item in items}

        self.assertEqual(
            by_key[(1, "유해화학물질별 물질구분·하위/상위 규정수량")].state,
            LEGAL_ENGINE,
        )
        self.assertEqual(
            by_key[(1, "최대보유량 단위 정규화(ton)")].state,
            RENDERER_GAP,
        )
        self.assertEqual(
            by_key[(3, "제출구분·최초/부적합")].state,
            READY,
        )
        self.assertEqual(
            by_key[(3, "산업단지")].state,
            ASK_COMPANY,
        )
        self.assertEqual(
            by_key[(12, "사고시나리오명·반경·장외거리·사고원점")].state,
            EXTERNAL_ANALYSIS,
        )
        self.assertEqual(
            by_key[(15, "시나리오 수·시설빈도·장외거리·주민수·구간점수·위험도")].state,
            CALCULATION,
        )

    def test_form9_connection_size_requires_engineering_source(self):
        items = audit_cap_form_coverage(self._project())
        target = next(item for item in items if item.form_no == 9 and item.item == "최대 연결구 크기")
        self.assertEqual(target.state, ASK_COMPANY)
        self.assertIn("P&ID", target.source_kind)

    def test_stage4_ui_exposes_statutory_form_blank_audit(self):
        source = (ROOT / "ui" / "stage2_validation_page.py").read_text(encoding="utf-8")
        self.assertIn("### 법정서식 공란·작성가능성 점검", source)
        self.assertIn("법령조회, 계산, 영향평가 또는 출력엔진 보완", source)
        self.assertIn("audit_cap_form_coverage", source)


if __name__ == "__main__":
    unittest.main()
