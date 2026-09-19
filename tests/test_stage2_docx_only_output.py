from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.cap_form_coverage import audit_cap_form_coverage


ROOT = Path(__file__).resolve().parents[1]


class Stage2DocxOnlyOutputTests(unittest.TestCase):

    def test_stage4_has_no_hwpx_renderer_hold(self):
        source = (ROOT / "engine" / "stage2" / "scope_validation.py").read_text(encoding="utf-8")
        self.assertNotIn("CAP-FORM12-13-HWPX-RENDERER", source)
        self.assertNotIn("CAP-FORM14-15-HWPX", source)
        self.assertNotIn("preflight_cap_risk_hwpx", source)

    def test_cap_coverage_does_not_count_hwpx_renderer_as_required_output(self):
        source = (ROOT / "engine" / "stage2" / "cap_form_coverage.py").read_text(encoding="utf-8")
        self.assertNotIn("공식 HWPX 시나리오별 원본 작성", source)
        self.assertNotIn("공식 HWPX A·B·C·D 및 점수 셀", source)
        self.assertNotIn("공식 HWPX 다단헤더 압력·온도 셀 매핑", source)

    def test_docx_runtime_does_not_override_validated_forms_12_13(self):
        source = (ROOT / "engine" / "stage2" / "cap_final_form_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("report._cap_form12 =", source)
        self.assertNotIn("report._cap_form13 =", source)
        self.assertNotIn("from . import cap_hwpx", source)


if __name__ == "__main__":
    unittest.main()
