from __future__ import annotations

import unittest

from engine.company_intake_fullname_runtime import LABEL_ALIASES
from engine.stage2.project import create_project_from_stage1_snapshot


class CompanyIntakeFullnameRuntimeTests(unittest.TestCase):
    """Characterization tests for the pre-release abbreviation alias fallback.

    ``install_company_intake_fullname_runtime`` renames ``COMPANY_FACT_SPECS``
    to full legal-document labels but still accepts older workbook snapshots
    that carry the pre-release ``PSM``/``CAP`` abbreviations. These tests pin
    that backward-compatible behavior down before any consolidation of the
    runtime-installer modules.
    """

    def _snapshot_with_old_labels(self):
        return {
            "source_fingerprint": "c" * 64,
            "business": {
                "사업장명": "구버전라벨공장",
                "사업장 주소": "테스트시 2",
                # Pre-release abbreviated labels only, no full-name keys.
                "PSM 사업 구분": "설치·이전",
                "PSM 심사대상 설비명": "R-201 반응공정",
                "CAP 단위공장명": "제2생산공장",
                "CAP 제출구분": "신규",
            },
            "documents": {},
            "chemicals": [],
            "facilities": [],
            "decision": {"psm_status": "", "cap_status": ""},
        }

    def test_full_labels_replace_abbreviations_in_specs(self):
        # After the runtime installs, no spec should still be keyed by the
        # bare PSM/CAP abbreviation form.
        from engine.company_intake_contract import COMPANY_FACT_SPECS

        current_labels = {spec.label for spec in COMPANY_FACT_SPECS}
        for old_label, full_label in LABEL_ALIASES:
            self.assertNotIn(old_label, current_labels)
            self.assertIn(full_label, current_labels)

    def test_old_abbreviated_business_labels_still_seed_stage2_fields(self):
        project = create_project_from_stage1_snapshot(self._snapshot_with_old_labels())

        self.assertEqual(project.get_field("psm.business.project_type").value, "설치·이전")
        self.assertEqual(project.get_field("psm.business.target_facility").value, "R-201 반응공정")
        self.assertEqual(project.get_field("cap.business.unit_plant_name").value, "제2생산공장")
        self.assertEqual(project.get_field("cap.business.submission_type").value, "신규")


if __name__ == "__main__":
    unittest.main()
