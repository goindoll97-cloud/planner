from __future__ import annotations

import unittest

from engine.stage2.cross_validation import CrossValidationReport
from engine.stage2.project import Stage2Project
from engine.stage2.psm_form12_consequence_engine import (
    build_psm_form12_readiness,
    build_psm_form19_2_readiness,
)
from engine.stage2.scope_validation import validate_selected_scope


class PSMForm12AndConsequenceReadinessTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        p = Stage2Project(
            project_id="S2-PSM-PHASE24",
            company_name="테스트화학",
            psm_required=True,
            cap_required=False,
            scope_confirmed=True,
            psm_selected=True,
            cap_selected=False,
        )
        p.set_field("business.address", "사업장 소재지", "테스트시 산업로 1", "VERIFIED")
        p.set_field(
            "psm.business.form12_details",
            "별지 제12호서식 사업개요 입력자료",
            [{
                "사업장명": "테스트화학",
                "제출구분": "변경",
                "사업자등록번호": "123-45-67890",
                "대표자": "홍길동",
                "대상 유해·위험설비": "반응·저장 공정",
                "한국표준산업분류": "C20119",
                "근로자수": "85",
                "계약전력(kW)": "1500",
                "작성자 성명": "김작성",
                "작성자 자격": "산업안전기사",
                "주요 원료": "톨루엔, 아세톤",
                "주요 생산품": "혼합제품 A",
                "사업개요": "원료 저장·혼합·제품출하 공정",
                "사업장 소재지": "테스트시 산업로 1",
                "전화번호": "053-000-0000",
                "전송번호": "053-000-0001",
                "부지면적": "12,500㎡",
                "주요 건물": "생산동 2동",
                "총 사업기간": "2026-10-01 ~ 2027-03-31",
                "착공예정일": "2026-10-01",
                "시운전기간": "2027-03-01 ~ 2027-03-31",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            [{
                "서식번호": "19-2",
                "서식명": "시나리오 및 피해예측 결과",
                "적용여부": "적용",
                "확인근거": "위험성평가 결과 및 피해예측 모델 검토",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.risk.consequence_table",
            "별지 제19호의2서식 사고피해예측 수치표",
            [
                self._scenario("최악의 사고 시나리오", "1.5", "650", "300", "180"),
                self._scenario("대안의 사고 시나리오", "3.0", "320", "150", "90"),
            ],
            "USER_CONFIRMED",
        )
        return p

    @staticmethod
    def _scenario(kind: str, wind: str, erpg1: str, erpg2: str, erpg3: str):
        return {
            "시나리오 구분": kind,
            "풍속(m/s)": wind,
            "대기안정도(A~F)": "F" if "최악" in kind else "D",
            "대기온도(℃)": "25",
            "습도(%)": "50",
            "표면거칠기": "도시",
            "물질명": "염소",
            "물질의 상태": "기체",
            "설비명(또는 배관부위)": "V-201",
            "운전압력(MPa)": "0.7",
            "운전온도(℃)": "25",
            "누출구의 크기(mm2)": "25" if "최악" in kind else "10",
            "웅덩이 크기(m2)": "해당 없음",
            "누출결과": "연속누출",
            "직접계산(kg/s or kg)": "0.25" if "최악" in kind else "0.10",
            "웅덩이(kg/s)": "해당 없음",
            "설비/배관(kg/s)": "0.25" if "최악" in kind else "0.10",
            "화재-4 kW/m2": "해당 없음",
            "화재-12.5 kW/m2": "해당 없음",
            "화재-37.5 kW/m2": "해당 없음",
            "폭발-7 kPa": "해당 없음",
            "폭발-21 kPa": "해당 없음",
            "폭발-70 kPa": "해당 없음",
            "인화성-25% LEL": "해당 없음",
            "인화성-LEL": "해당 없음",
            "인화성-UEL": "해당 없음",
            "독성-ERPG 1": erpg1,
            "독성-ERPG 2": erpg2,
            "독성-ERPG 3": erpg3,
            "계산모델·결과 근거": "KORA/ALOHA 결과파일",
        }

    def test_form12_ready_when_all_fields_match_stage1_identity(self):
        result = build_psm_form12_readiness(self._project())
        self.assertTrue(result.ready)
        self.assertEqual(len(result.rows), 1)

    def test_form12_fails_closed_when_stage1_company_name_differs(self):
        p = self._project()
        row = dict(p.get_field("psm.business.form12_details").value[0])
        row["사업장명"] = "다른회사"
        p.set_field(
            "psm.business.form12_details",
            "별지 제12호서식 사업개요 입력자료",
            [row],
            "USER_CONFIRMED",
        )

        result = build_psm_form12_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("Stage 1" in blocker and "사업장명" in blocker for blocker in result.blockers))

    def test_form12_blank_requires_explicit_not_applicable_or_value(self):
        p = self._project()
        row = dict(p.get_field("psm.business.form12_details").value[0])
        row["전송번호"] = ""
        p.set_field(
            "psm.business.form12_details",
            "별지 제12호서식 사업개요 입력자료",
            [row],
            "USER_CONFIRMED",
        )

        result = build_psm_form12_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("전송번호" in blocker for blocker in result.blockers))

    def test_form19_2_ready_with_worst_and_alternative_rows(self):
        result = build_psm_form19_2_readiness(self._project())
        self.assertTrue(result.ready)
        self.assertEqual(len(result.rows), 2)

    def test_form19_2_requires_both_scenarios_when_applicable(self):
        p = self._project()
        p.set_field(
            "psm.risk.consequence_table",
            "별지 제19호의2서식 사고피해예측 수치표",
            [self._scenario("최악의 사고 시나리오", "1.5", "650", "300", "180")],
            "USER_CONFIRMED",
        )

        result = build_psm_form19_2_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("대안의 사고 시나리오" in blocker for blocker in result.blockers))

    def test_form19_2_not_applicable_requires_basis_but_not_rows(self):
        p = self._project()
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            [{
                "서식번호": "19-2",
                "적용여부": "해당 없음",
                "확인근거": "위험성평가 결과 별도 피해예측 서식 미적용 확인",
            }],
            "USER_CONFIRMED",
        )
        p.fields.pop("psm.risk.consequence_table")

        result = build_psm_form19_2_readiness(p)

        self.assertTrue(result.ready)
        self.assertEqual(result.rows, ())

    def test_form19_2_not_applicable_without_basis_is_hold(self):
        p = self._project()
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            [{"서식번호": "19-2", "적용여부": "해당 없음", "확인근거": ""}],
            "USER_CONFIRMED",
        )

        result = build_psm_form19_2_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("확인근거" in blocker for blocker in result.blockers))

    def test_stage4_exposes_form12_and_form19_2_ready(self):
        report = validate_selected_scope(self._project())
        self.assertTrue(any(issue.code == "PSM-FORM12-READY" for issue in report.issues))
        self.assertTrue(any(issue.code == "PSM-FORM19-2-READY" for issue in report.issues))

    def test_stage4_exposes_form12_hold_on_identity_mismatch(self):
        p = self._project()
        row = dict(p.get_field("psm.business.form12_details").value[0])
        row["사업장 소재지"] = "다른시 주소 999"
        p.set_field(
            "psm.business.form12_details",
            "별지 제12호서식 사업개요 입력자료",
            [row],
            "USER_CONFIRMED",
        )

        report = validate_selected_scope(p)

        self.assertTrue(any(
            issue.code.startswith("PSM-FORM12-") and issue.status == "HOLD"
            for issue in report.issues
        ))


if __name__ == "__main__":
    unittest.main()
