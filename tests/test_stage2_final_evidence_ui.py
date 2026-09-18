from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2FinalEvidenceUITests(unittest.TestCase):
    def test_cap_final_evidence_uploads_are_explicit_and_field_specific(self):
        text = (ROOT / "ui/stage2_intake_page.py").read_text(encoding="utf-8")

        self.assertIn("#### 최종 제출 관련 증빙 연결", text)
        self.assertIn("타 제도 심사결과 증빙파일", text)
        self.assertIn("공동비상대응계획 증빙파일", text)
        self.assertIn("attach_evidence_to_confirmed_field", text)
        self.assertIn('"cap.business.other_system_review"', text)
        self.assertIn('"cap.business.joint_emergency_plan"', text)
        self.assertIn('source_type="COMPANY_EVIDENCE"', text)

    def test_final_evidence_upload_requires_confirmed_source_fact(self):
        text = (ROOT / "ui/stage2_intake_page.py").read_text(encoding="utf-8")

        self.assertIn("CONFIRMED_STATUSES", text)
        self.assertIn("other_review_record.status in CONFIRMED_STATUSES", text)
        self.assertIn("joint_record.status in CONFIRMED_STATUSES", text)
        self.assertIn("reset_after_intake_change(project)", text)


if __name__ == "__main__":
    unittest.main()
