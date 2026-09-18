from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.cap_final_form_runtime import (
    render_facility_type_counts,
    render_joint_emergency,
    render_other_system_review,
    render_protected_target_groups,
    render_submission_type,
    render_yes_no,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CAPFinalFormRuntimeTests(unittest.TestCase):
    def test_submission_type_keeps_all_official_choices(self):
        rendered = render_submission_type("신규")
        self.assertIn("☒ 신규제출", rendered)
        self.assertIn("☐ 변경제출", rendered)
        self.assertIn("☐ 재제출", rendered)
        self.assertIn("☐ 이행점검 불이행", rendered)
        # '신규' alone does not prove the nested reason.
        self.assertIn("☐ 최초", rendered)
        self.assertIn("☐ 부적합", rendered)

    def test_submission_type_checks_only_explicit_nested_reason(self):
        rendered = render_submission_type("변경제출 - 부적합")
        self.assertIn("☒ 변경제출", rendered)
        self.assertIn("☒ 부적합", rendered)
        self.assertIn("☐ 신규제출", rendered)

    def test_submission_reason_can_be_stored_separately(self):
        rendered = render_submission_type("신규제출", "최초")
        self.assertIn("☒ 신규제출", rendered)
        self.assertIn("☒ 최초", rendered)
        self.assertIn("☐ 부적합", rendered)

    def test_ambiguous_yes_does_not_invent_joint_submission_mode(self):
        rendered = render_joint_emergency("예")
        self.assertEqual(rendered, "☐ 공동제출   ☐ 단독제출")

    def test_other_system_review_preserves_subchoices(self):
        rendered = render_other_system_review("해당 - 공정안전보고서")
        self.assertIn("☒ 해당", rendered)
        self.assertIn("☒ 공정안전보고서", rendered)
        self.assertIn("☐ 안전성향상계획", rendered)
        self.assertIn("☐ 미해당", rendered)

    def test_yes_no_choice_is_fail_closed_when_unknown(self):
        self.assertEqual(render_yes_no(""), "☐ 있음   ☐ 없음")
        self.assertEqual(render_yes_no("있음"), "☒ 있음   ☐ 없음")
        self.assertEqual(render_yes_no("없음"), "☐ 있음   ☒ 없음")

    def test_protected_target_groups_show_every_option_and_select_matches(self):
        a, b, env = render_protected_target_groups("의료시설 하천")
        self.assertIn("☒ 의료시설", a)
        self.assertIn("☐ 종교시설", a)
        self.assertIn("☐ 주택·업무시설", b)
        self.assertIn("☒ 하천", env)
        self.assertIn("☐ 습지보호지역", env)

    def test_facility_checkbox_counts_map_company_terms_without_overclaiming_high_pressure(self):
        from engine.stage2.project import Stage2Project

        project = Stage2Project(
            project_id="S2-FACILITY-CHECKBOX",
            company_name="테스트화학",
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            cap_selected=True,
        )
        project.set_field(
            "inventory.facilities",
            "설비목록",
            [
                {"설비번호": "T-1", "설비명": "저장탱크", "설비종류": "저장탱크"},
                {"설비번호": "R-1", "설비명": "반응기", "설비종류": "반응기"},
                {"설비번호": "M-1", "설비명": "혼합조", "설비종류": "혼합조"},
                {"설비번호": "C-1", "설비명": "흡수탑", "설비종류": "흡수탑"},
                {"설비번호": "V-1", "설비명": "압력용기", "설비종류": "압력용기"},
            ],
            "USER_CONFIRMED",
        )

        rendered = render_facility_type_counts(project)
        self.assertIn("☒ 저장탱크 (1)기", rendered)
        self.assertIn("☒ 반응시설 (1)기", rendered)
        self.assertIn("☒ 혼합시설 (1)기", rendered)
        self.assertIn("☒ 탑조류(증류탑 등) (1)기", rendered)
        self.assertIn("☐ 고압시설", rendered)
        self.assertIn("☒ 기타 (1)기", rendered)

    def test_app_uses_docx_final_runtime_without_hwpx_runtime(self):
        text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_cap_final_form_runtime()", text)
        self.assertNotIn("install_cap_multi_form_runtime()", text)
        self.assertNotIn("from engine.stage2.cap_multi_form_runtime", text)

    def test_cap_final_runtime_suppresses_only_cap_review_appendix(self):
        text = (PROJECT_ROOT / "engine/stage2/cap_final_form_runtime.py").read_text(encoding="utf-8")
        self.assertIn("review_appendix_without_cap", text)
        self.assertIn('upper() != "CAP"', text)


if __name__ == "__main__":
    unittest.main()
