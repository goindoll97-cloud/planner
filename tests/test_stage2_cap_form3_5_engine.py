from __future__ import annotations

import unittest

from engine.stage2.cap_form3_5_engine import (
    build_cap_form3_readiness,
    build_cap_form4_readiness,
    build_cap_form5_readiness,
)
from engine.stage2.project import Stage2Project


class CAPForms3To5ReadinessTests(unittest.TestCase):
    def _project(self, *, explicit_residents: bool = True) -> Stage2Project:
        p = Stage2Project(
            project_id="S2-CAP-FORM3-5",
            company_name="한빛정밀화학(주)",
            site_name="울산제1공장",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        values = (
            ("cap.business.unit_plant_name", "단위공장명", "울산제1공장"),
            ("cap.business.registration_no", "사업자등록번호", "123-45-67890"),
            ("cap.business.representative", "대표자", "홍길동"),
            ("business.address", "사업장 주소", "울산광역시 테스트로 1"),
            ("cap.business.industrial_complex", "산업단지", "해당 없음"),
            ("cap.business.contact", "대표전화", "052-260-4000"),
            ("cap.business.submission_type", "제출구분", "신규제출"),
            ("cap.business.submission_reason", "제출 사유", "최초"),
            ("cap.business.joint_emergency_plan", "공동비상대응계획", "단독제출"),
            ("cap.business.other_system_review", "유사제도 심사결과 활용", "미해당"),
            ("cap.business.recent_accident", "최근 3년 화학사고", "아니오"),
            ("cap.business.writer_name", "작성자", "최유진"),
            ("cap.business.writer_contact", "담당자 연락처", "052-260-4123"),
            ("cap.business.writer_email", "담당자 이메일", "safety@example.com"),
            ("cap.basic.total_facility_overview", "총괄 취급시설 구성", "염소 저장·공급 계통으로 구성"),
            ("cap.basic.unit_facility_overview", "단위공장 취급시설 구성", "염소 저장탱크와 공급배관으로 구성"),
            ("cap.basic.loading_transport", "입출하 및 운반시설", "입·출하 시설 1기 / 보유 탱크로리 1기"),
            ("process.description", "공정개요", "염소를 저장한 뒤 공급배관을 통해 공정에 공급한다."),
        )
        for key, label, value in values:
            p.set_field(key, label, value, "USER_CONFIRMED")

        if explicit_residents:
            p.set_field(
                "cap.business.residents_in_overall_range",
                "총괄영향범위 내 주민 여부",
                "예",
                "USER_CONFIRMED",
            )

        p.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "최대보유량": 800, "단위": "kg"}],
            "USER_CONFIRMED",
        )
        p.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{"설비번호": "TK-301", "설비명": "염소 저장탱크", "설비종류": "저장탱크"}],
            "USER_CONFIRMED",
        )
        return p

    def test_complete_company_data_makes_forms_3_to_5_ready(self):
        p = self._project()

        self.assertTrue(build_cap_form3_readiness(p).ready)
        self.assertTrue(build_cap_form4_readiness(p).ready)
        self.assertTrue(build_cap_form5_readiness(p).ready)

    def test_form3_fails_closed_when_registration_number_is_missing(self):
        p = self._project()
        p.fields.pop("cap.business.registration_no")

        result = build_cap_form3_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("사업자등록번호" in blocker for blocker in result.blockers))

    def test_form4_requires_total_facility_overview(self):
        p = self._project()
        p.fields.pop("cap.basic.total_facility_overview")

        self.assertFalse(build_cap_form4_readiness(p).ready)
        self.assertTrue(build_cap_form5_readiness(p).ready)

    def test_form5_requires_unit_facility_overview(self):
        p = self._project()
        p.fields.pop("cap.basic.unit_facility_overview")

        self.assertTrue(build_cap_form4_readiness(p).ready)
        self.assertFalse(build_cap_form5_readiness(p).ready)

    def test_form3_can_derive_resident_presence_from_confirmed_overall_impact_summary(self):
        p = self._project(explicit_residents=False)
        p.set_field(
            "cap.offsite.overall_impact_summary",
            "총괄영향범위 요약",
            [{"총괄영향범위 내 거주민수": 65}],
            "USER_CONFIRMED",
        )

        self.assertTrue(build_cap_form3_readiness(p).ready)

    def test_hold_status_does_not_count_as_confirmed(self):
        p = self._project()
        p.set_field(
            "cap.business.writer_email",
            "담당자 이메일",
            "safety@example.com",
            "HOLD",
        )

        result = build_cap_form3_readiness(p)

        self.assertFalse(result.ready)
        self.assertTrue(any("메일주소" in blocker for blocker in result.blockers))


if __name__ == "__main__":
    unittest.main()
