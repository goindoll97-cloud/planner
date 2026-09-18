from __future__ import annotations

import unittest

from engine.stage2.project import Stage2Project
from engine.stage2.psm_later_form_engine import (
    build_all_psm_later_form_readiness,
    build_psm_later_form_readiness,
)
from engine.stage2.scope_validation import validate_selected_scope


class PSMLaterFormReadinessTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        p = Stage2Project(
            project_id="S2-PSM-LATER-FORMS",
            company_name="테스트화학",
            psm_required=True,
            cap_required=False,
            scope_confirmed=True,
            psm_selected=True,
            cap_selected=False,
        )
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            [
                {"서식번호": "17-2", "서식명": "인터록", "적용여부": "적용", "확인근거": "P&ID 및 인터록 목록"},
                {"서식번호": "17-3", "서식명": "소화설비", "적용여부": "적용", "확인근거": "소화설비 배치도"},
                {"서식번호": "17-4", "서식명": "화재탐지", "적용여부": "적용", "확인근거": "화재감지기 목록"},
                {"서식번호": "17-5", "서식명": "가스감지", "적용여부": "적용", "확인근거": "가스감지기 목록"},
                {"서식번호": "18", "서식명": "내화구조", "적용여부": "적용", "확인근거": "내화도면"},
                {"서식번호": "19", "서식명": "국소배기", "적용여부": "적용", "확인근거": "국소배기 명세"},
                {"서식번호": "20", "서식명": "방폭기기", "적용여부": "적용", "확인근거": "폭발위험장소 구분도"},
            ],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.interlock_conditions",
            "인터록 작동조건",
            [{
                "인터록번호": "IL-101",
                "대상설비번호": "R-101",
                "설정값-온도(℃)": "120 ℃",
                "설정값-압력(MPa)": "해당 없음",
                "설정값-액위(m)": "해당 없음",
                "설정값-기타": "해당 없음",
                "감지기번호": "TI-101",
                "최종 작동설비번호": "XV-101",
                "가동중지범위": "원료공급 및 가열 정지",
                "점검주기": "월 1회",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.fire_protection_table",
            "소화설비 설치계획 표",
            [{
                "설치지역": "원료저장동",
                "소화기": "분말 6기",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.fire_detection_table",
            "화재탐지 및 경보설비 설치계획 표",
            [{
                "설치지역": "반응동",
                "자동화재탐지설비": "연기·열감지기 12개",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.gas_detection_table",
            "가스누출감지 및 경보장치 명세 표",
            [{
                "감지기 번호": "GD-101",
                "검출대상 물질": "톨루엔",
                "설치위치": "TK-101 방유제 내",
                "작동시간": "30초 이내",
                "측정방식": "접촉연소식",
                "경보 설정값": "10% LEL",
                "경보 위치": "중앙제어실",
                "정밀도": "±3% F.S.",
                "경보시 조치내용": "원료 이송펌프 정지",
                "유지관리": "월 1회 기능점검",
                "비고": "GA-101",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.fireproofing_table",
            "내화구조 명세 표",
            [{
                "내화설비 또는 지역": "R-101 지지철골",
                "내화부위": "주기둥 및 보",
                "내화시험기준 및 시간": "2시간 내화성능",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.local_exhaust_table",
            "국소배기장치 명세 표",
            [{
                "공정 또는 작업장명": "혼합공정",
                "실내외 구분": "실내",
                "발생원": "원료 투입구",
                "유해물질 종류": "톨루엔",
                "후드형식": "포위식",
                "후드 제어풍속(m/s)": "0.5",
                "덕트내 반송속도(m/s)": "12",
                "배풍량(m3/min)": "80",
                "전동기용량(kW)": "7.5",
                "배기 및 처리순서": "후드 → 흡착기 → 배기구",
                "방폭형식": "Ex d IIB T4",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.psi.ex_equipment",
            "방폭 전기·계장 기계기구 선정기준",
            [{
                "설치장소 또는 공정": "원료저장",
                "전기/계장 기계·기구명": "모터·현장계기",
                "0종장소 선정기준(방폭형식)": "해당 없음",
                "1종장소 선정기준(방폭형식)": "Ex d IIB T4",
                "2종장소 선정기준(방폭형식)": "Ex e IIB T4",
            }],
            "USER_CONFIRMED",
        )
        p.set_field(
            "psm.risk.team",
            "위험성평가자 명단",
            [{
                "책임분야": "공정",
                "성명": "홍길동",
                "소속회사": "테스트화학",
                "직책": "공정팀장",
                "주요경력": "공정설계 및 운전 15년",
            }],
            "USER_CONFIRMED",
        )
        return p

    def test_all_later_forms_are_ready_when_applicability_and_rows_are_complete(self):
        results = build_all_psm_later_form_readiness(self._project())
        self.assertEqual(
            [item.form_no for item in results],
            ["17-2", "17-3", "17-4", "17-5", "18", "19", "20", "21"],
        )
        self.assertTrue(all(item.ready for item in results))

    def test_conditional_form_without_applicability_is_hold(self):
        p = self._project()
        p.fields.pop("psm.psi.form_applicability")

        result = build_psm_later_form_readiness(p, "17-3")

        self.assertFalse(result.ready)
        self.assertTrue(any("적용 여부가 확인되지 않았습니다" in b for b in result.blockers))

    def test_explicit_not_applicable_with_basis_passes_without_detail_rows(self):
        p = self._project()
        rows = [dict(row) for row in p.get_field("psm.psi.form_applicability").value]
        for row in rows:
            if row["서식번호"] == "18":
                row["적용여부"] = "해당 없음"
                row["확인근거"] = "내화구조 적용대상 없음 검토서"
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            rows,
            "USER_CONFIRMED",
        )
        p.fields.pop("psm.psi.fireproofing_table")

        result = build_psm_later_form_readiness(p, "18")

        self.assertTrue(result.ready)
        self.assertEqual(result.applicability, "해당 없음")
        self.assertTrue(any("확인근거" in message for message in result.messages))

    def test_not_applicable_without_basis_is_hold(self):
        p = self._project()
        rows = [dict(row) for row in p.get_field("psm.psi.form_applicability").value]
        for row in rows:
            if row["서식번호"] == "19":
                row["적용여부"] = "해당 없음"
                row["확인근거"] = ""
        p.set_field(
            "psm.psi.form_applicability",
            "PSM 조건부 별지서식 적용여부",
            rows,
            "USER_CONFIRMED",
        )
        p.fields.pop("psm.psi.local_exhaust_table")

        result = build_psm_later_form_readiness(p, "19")

        self.assertFalse(result.ready)
        self.assertTrue(any("확인근거가 없습니다" in b for b in result.blockers))

    def test_form17_2_requires_at_least_one_setpoint(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.interlock_conditions").value[0])
        for key in ("설정값-온도(℃)", "설정값-압력(MPa)", "설정값-액위(m)", "설정값-기타"):
            row[key] = ""
        p.set_field("psm.psi.interlock_conditions", "인터록 작동조건", [row], "USER_CONFIRMED")

        result = build_psm_later_form_readiness(p, "17-2")

        self.assertFalse(result.ready)
        self.assertTrue(any("최소 1개" in b for b in result.blockers))

    def test_form20_requires_at_least_one_zone_selection_basis(self):
        p = self._project()
        row = dict(p.get_field("psm.psi.ex_equipment").value[0])
        for key in (
            "0종장소 선정기준(방폭형식)",
            "1종장소 선정기준(방폭형식)",
            "2종장소 선정기준(방폭형식)",
        ):
            row[key] = ""
        p.set_field("psm.psi.ex_equipment", "방폭기기 선정기준", [row], "USER_CONFIRMED")

        result = build_psm_later_form_readiness(p, "20")

        self.assertFalse(result.ready)
        self.assertTrue(any("최소 1개" in b for b in result.blockers))

    def test_form21_is_required_without_applicability_override(self):
        p = self._project()
        p.fields.pop("psm.risk.team")

        result = build_psm_later_form_readiness(p, "21")

        self.assertFalse(result.ready)
        self.assertTrue(any("구조화 회사자료가 없습니다" in b for b in result.blockers))

    def test_stage4_exposes_later_form_ready_and_hold_issues(self):
        p = self._project()
        report = validate_selected_scope(p)
        later = [issue for issue in report.issues if issue.code.startswith("PSM-FORM17-2") or issue.code.startswith("PSM-FORM21")]
        self.assertTrue(any(issue.code == "PSM-FORM17-2-READY" for issue in later))
        self.assertTrue(any(issue.code == "PSM-FORM21-READY" for issue in later))

        p.fields.pop("psm.risk.team")
        report = validate_selected_scope(p)
        self.assertTrue(any(
            issue.code.startswith("PSM-FORM21-") and issue.status == "HOLD"
            for issue in report.issues
        ))


if __name__ == "__main__":
    unittest.main()
