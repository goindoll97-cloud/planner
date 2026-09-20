from __future__ import annotations

import unittest

from engine.stage2.project import Stage2Project
from engine.stage2.scope_validation import validate_selected_scope
from engine.stage2.psm_core_form_engine import (
    build_all_psm_core_form_readiness,
    build_psm_core_form_readiness,
)


class PSMCoreFormReadinessTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        p = Stage2Project(
            project_id="S2-PSM-CORE-FORMS",
            company_name="테스트화학",
            psm_required=True,
            cap_required=False,
            scope_confirmed=True,
            psm_selected=True,
            cap_selected=False,
        )
        p.set_field(
            "psm.psi.chemical_details",
            "공정안전보고서 유해·위험물질 상세명세",
            [{
                "물질명": "톨루엔",
                "CAS 번호": "108-88-3",
                "분자식": "C7H8",
                "폭발한계 하한": "1.2 vol%",
                "폭발한계 상한": "7.1 vol%",
                "노출기준": "TWA 50 ppm",
                "독성치": "경구: 회사 SDS 확인 / 경피: 회사 SDS 확인 / 흡입: 회사 SDS 확인",
                "인화점": "4 ℃",
                "발화점": "480 ℃",
                "증기압": "28.4 mmHg (25℃)",
                "부식성": "해당 없음",
                "이상반응 유무": "해당 없음",
                "일일사용량": "2500 kg/day",
                "저장량": "15000 kg",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.machinery_list",
            "동력기계 목록",
            [{
                "기계번호": "P-101",
                "기계명": "원료 이송펌프",
                "기계종류": "원심펌프",
                "처리량": "10 m3/h",
                "토출압력": "0.5 MPa",
                "회전수": "1750 rpm",
                "재질": "SUS304",
                "동력": "7.5 kW",
                "방호·보호장치 종류": "커플링 가드·모터 과부하 보호",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.equipment_specs",
            "장치 및 설비명세",
            [{
                "설비번호": "TK-101",
                "설비명": "톨루엔 저장탱크",
                "취급물질": "톨루엔",
                "용량": "20 m3",
                "운전압력": "0.15 MPa",
                "설계압력": "0.49 MPa",
                "운전온도": "30 ℃",
                "설계온도": "80 ℃",
                "재질": "SUS304",
                "부속품재질": "SUS304",
                "개스킷재질": "PTFE",
                "용접효율": "1.0",
                "계산두께": "6 mm",
                "부식여유": "1 mm",
                "사용두께": "8 mm",
                "후열처리 여부": "해당 없음",
                "비파괴검사율": "10%",
                "비고": "해당 없음",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.piping_gasket_specs",
            "배관 및 개스킷 명세",
            [{
                "배관번호·Class": "PCL-150",
                "유체명": "톨루엔",
                "설계온도": "80 ℃",
                "설계압력": "0.49 MPa",
                "배관재질": "SUS304",
                "개스킷 재질": "PTFE",
                "비파괴검사율": "10%",
                "후열처리여부": "해당 없음",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.relief_device_specs",
            "안전밸브 및 파열판 명세",
            [{
                "안전밸브·파열판 번호": "PSV-101",
                "배출물질": "톨루엔 증기",
                "배출상태": "증기",
                "배출용량": "1200 kg/h",
                "정격용량": "1300 kg/h",
                "노즐크기 입구": "25A",
                "노즐크기 출구": "40A",
                "보호대상 설비번호": "TK-101",
                "보호기기 운전압력": "0.15 MPa",
                "보호기기 설계압력": "0.49 MPa",
                "설정압력": "0.45 MPa",
                "몸체재질": "WCB",
                "TRIM 재질": "SUS316",
                "정밀도": "±3%",
                "최종 배출·처리 지점": "스크러버",
                "배출원인": "화재",
                "형식": "안전밸브",
            }],
            "USER_CONFIRMED",
        )
        return p

    def test_complete_core_forms_13_to_17_are_ready(self):
        results = build_all_psm_core_form_readiness(self._project())
        self.assertEqual([item.form_no for item in results], ["13", "14", "15", "16", "17"])
        self.assertTrue(all(item.ready for item in results))

    def test_missing_form13_core_value_fails_closed(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.chemical_details").value[0])
        row.pop("독성치")
        p.set_field(
            "psm.psi.chemical_details",
            "공정안전보고서 유해·위험물질 상세명세",
            [row],
            "USER_CONFIRMED",
        )

        result = build_psm_core_form_readiness(p, "13")

        self.assertFalse(result.ready)
        self.assertTrue(any("독성치" in blocker for blocker in result.blockers))

    def test_explicit_not_applicable_is_a_confirmed_value(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.chemical_details").value[0])
        row["인화점"] = "해당 없음"
        row["발화점"] = "해당 없음"
        p.set_field(
            "psm.psi.chemical_details",
            "공정안전보고서 유해·위험물질 상세명세",
            [row],
            "USER_CONFIRMED",
        )

        self.assertTrue(build_psm_core_form_readiness(p, "13").ready)

    def test_psm_specific_chemical_details_take_priority_over_stage1_inventory(self):
        p = self._project()
        p.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "톨루엔", "CAS 번호": "108-88-3"}],
            "VERIFIED",
        )

        result = build_psm_core_form_readiness(p, "13")

        self.assertTrue(result.ready)
        self.assertEqual(result.rows[0][2], "C7H8")

    def test_stage4_exposes_psm_core_form_passes_when_complete(self):
        report = validate_selected_scope(self._project())
        core = [
            issue
            for issue in report.issues
            if (
                issue.code.startswith(("PSM-FORM13-", "PSM-FORM14-", "PSM-FORM15-", "PSM-FORM16-"))
                or (issue.code.startswith("PSM-FORM17-") and issue.code.count("-") == 2)
            )
        ]

        self.assertTrue(core)
        self.assertTrue(any(issue.code == "PSM-FORM13-READY" for issue in core))
        self.assertTrue(any(issue.code == "PSM-FORM17-READY" for issue in core))
        self.assertFalse(any(issue.status == "HOLD" for issue in core))

    def test_stage4_exposes_form13_hold_when_core_value_is_missing(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.chemical_details").value[0])
        row.pop("독성치")
        p.set_field(
            "psm.psi.chemical_details",
            "공정안전보고서 유해·위험물질 상세명세",
            [row],
            "USER_CONFIRMED",
        )

        report = validate_selected_scope(p)
        form13_holds = [
            issue
            for issue in report.issues
            if issue.code.startswith("PSM-FORM13-") and issue.status == "HOLD"
        ]

        self.assertTrue(form13_holds)
        self.assertTrue(any("독성치" in issue.message for issue in form13_holds))

    def test_form13_generic_sds_note_does_not_satisfy_toxicity_routes(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.chemical_details").value[0])
        row["독성치"] = "회사 SDS 확인값"
        p.set_field(
            "psm.psi.chemical_details",
            "공정안전보고서 유해·위험물질 상세명세",
            [row],
            "USER_CONFIRMED",
        )

        result = build_psm_core_form_readiness(p, "13")

        self.assertFalse(result.ready)
        self.assertTrue(any("경구·경피·흡입" in blocker for blocker in result.blockers))

    def test_form14_pump_requires_discharge_pressure_and_rpm(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.machinery_list").value[0])
        row.pop("토출압력")
        row.pop("회전수")
        p.set_field("psm.psi.machinery_list", "동력기계 목록", [row], "USER_CONFIRMED")

        result = build_psm_core_form_readiness(p, "14")

        self.assertFalse(result.ready)
        self.assertTrue(any("토출측 압력" in blocker and "분당 회전수" in blocker for blocker in result.blockers))

    def test_form15_requires_explicit_regulatory_inspection_note(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.equipment_specs").value[0])
        row.pop("비고")
        p.set_field("psm.psi.equipment_specs", "장치 및 설비명세", [row], "USER_CONFIRMED")

        result = build_psm_core_form_readiness(p, "15")

        self.assertFalse(result.ready)
        self.assertTrue(any("비고" in blocker for blocker in result.blockers))

    def test_missing_structured_table_is_hold(self):
        p = self._project()
        p.fields.pop("psm.psi.piping_gasket_specs")

        result = build_psm_core_form_readiness(p, "16")

        self.assertFalse(result.ready)
        self.assertTrue(any("구조화 회사자료가 없습니다" in blocker for blocker in result.blockers))


if __name__ == "__main__":
    unittest.main()
