from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RequestWordingContractTests(unittest.TestCase):
    def test_request_ui_hides_workbook_sheet_names(self) -> None:
        text = (PROJECT_ROOT / "ui/diagnosis_page.py").read_text(encoding="utf-8")
        self.assertIn("_display_request", text)
        self.assertIn("re.sub", text)

    def test_psm_requests_name_full_legal_basis(self) -> None:
        text = (PROJECT_ROOT / "engine/stage1_workbook.py").read_text(encoding="utf-8")
        self.assertIn("「산업안전보건법」 제44조제1항", text)
        self.assertIn("「산업안전보건법 시행령」 제43조제1항", text)
        self.assertIn("별표 13 「유해·위험물질 규정량」 제{item_no}호", text)
        self.assertIn('1: ("인화성 가스"', text)
        self.assertIn('2: ("인화성 액체"', text)
        self.assertIn("별표 13 「유해·위험물질 규정량」 제42호 니트로셀룰로오스(질소 함유량 12.6% 이상)", text)


if __name__ == "__main__":
    unittest.main()
