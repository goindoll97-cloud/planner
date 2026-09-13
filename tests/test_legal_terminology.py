from __future__ import annotations

import unittest

from engine.legal_terminology import load_legal_terminology, psm_field_label, psm_section_name
from engine.stage2.requirements import psm_field_labels, psm_requirement_specs


class LegalTerminologyTests(unittest.TestCase):
    def test_policy_uses_current_statutory_section_names(self):
        policy = load_legal_terminology()
        self.assertEqual(
            policy["psm"]["canonical"]["sections"],
            ["공정안전자료", "공정위험성평가서", "안전운전계획", "비상조치계획"],
        )
        self.assertEqual(
            policy["cap"]["canonical"]["sections"],
            ["기본정보", "시설정보", "장외평가정보", "사전관리방침", "내부 비상대응계획", "외부 비상대응계획"],
        )

    def test_psm_section_names_are_canonicalized(self):
        specs = psm_requirement_specs()
        risk = [spec for spec in specs if spec.key.startswith("psm.risk.")]
        operation = [spec for spec in specs if spec.key.startswith("psm.operation.")]
        emergency = [spec for spec in specs if spec.key.startswith("psm.emergency.")]
        self.assertTrue(risk)
        self.assertTrue(operation)
        self.assertTrue(emergency)
        self.assertTrue(all(spec.section == "공정위험성평가서" for spec in risk))
        self.assertTrue(all(spec.section == "안전운전계획" for spec in operation))
        self.assertTrue(all(spec.section == "비상조치계획" for spec in emergency))

    def test_psm_statutory_field_labels_override_legacy_example_wording(self):
        labels = psm_field_labels()
        self.assertEqual(
            labels["inventory.chemicals"],
            "취급·저장하고 있거나 취급·저장하려는 유해·위험물질의 종류 및 수량",
        )
        self.assertEqual(labels["psm.psi.msds"], "유해·위험물질에 대한 물질안전보건자료")
        self.assertEqual(labels["psm.risk.report"], "공정위험성평가서")
        self.assertEqual(
            labels["psm.operation.maintenance"],
            "설비점검·검사 및 보수계획, 유지계획 및 지침서",
        )
        self.assertEqual(
            labels["psm.emergency.resources"],
            "비상조치를 위한 장비·인력 보유현황",
        )

    def test_internal_keys_remain_stable_while_display_terms_are_legal_terms(self):
        self.assertEqual(psm_section_name("psm.risk.report", "legacy"), "공정위험성평가서")
        self.assertEqual(psm_field_label("psm.operation.moc", "legacy"), "변경요소 관리계획")


if __name__ == "__main__":
    unittest.main()
