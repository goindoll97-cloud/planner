from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.cap_final_form_runtime import (
    render_joint_emergency,
    render_other_system_review,
    render_protected_target_groups,
    render_submission_type,
    render_writing_level,
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

    def test_writing_level_checks_only_the_matching_group(self):
        # Regression: cap_hwpx.py must hand this function the raw group
        # value (e.g. "1군"), not a pre-rendered checkbox string. A
        # pre-rendered "■ 1군   □ 2군" string contains both "1군" and "2군"
        # as substrings, which previously caused both boxes to render as
        # checked regardless of the actual group.
        self.assertEqual(render_writing_level("1군"), "☒ 1군   ☐ 2군")
        self.assertEqual(render_writing_level("2군"), "☐ 1군   ☒ 2군")
        self.assertEqual(render_writing_level(""), "☐ 1군   ☐ 2군")

    def test_writing_level_rejects_a_pre_rendered_checkbox_string(self):
        # Guards against the exact regression above: if some caller ever
        # again hands this an already-rendered "■ ... □ ..." string instead
        # of the raw group, it must fail closed (neither box checked) rather
        # than falsely showing both as selected.
        self.assertEqual(render_writing_level("■ 1군   □ 2군"), "☐ 1군   ☐ 2군")

    def test_protected_target_groups_show_every_option_and_select_matches(self):
        a, b, env = render_protected_target_groups("의료시설 하천")
        self.assertIn("☒ 의료시설", a)
        self.assertIn("☐ 종교시설", a)
        self.assertIn("☐ 주택·업무시설", b)
        self.assertIn("☒ 하천", env)
        self.assertIn("☐ 습지보호지역", env)

    def test_app_installs_final_form_runtime_after_split_form_hardening(self):
        text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        fragment = text.index("install_cap_fragment_runtime()")
        final_form = text.index("install_cap_final_form_runtime()")
        local_ai = text.index("install_local_ai_resilience()")
        self.assertLess(fragment, final_form)
        self.assertLess(final_form, local_ai)

    def test_cap_final_runtime_suppresses_only_cap_review_appendix(self):
        text = (PROJECT_ROOT / "engine/stage2/cap_final_form_runtime.py").read_text(encoding="utf-8")
        self.assertIn("review_appendix_without_cap", text)
        self.assertIn('upper() != "CAP"', text)


if __name__ == "__main__":
    unittest.main()
