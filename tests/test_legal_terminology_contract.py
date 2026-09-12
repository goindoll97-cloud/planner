from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

USER_FACING_FILES = [
    "ui/diagnosis_entry.py",
    "ui/diagnosis_page.py",
    "ui/psm_followup_panel.py",
    "engine/consulting_guidance.py",
    "engine/template.py",
    "engine/psm_engine.py",
    "engine/psm_followup.py",
    "engine/cap_engine.py",
    "engine/cap_scope_engine.py",
    "engine/cap_quick_holding.py",
    "engine/cap_holding.py",
    "engine/cap_final_decision.py",
]

FORBIDDEN_AMBIGUOUS_TERMS = [
    "트리거",
    "PSM 대상 후보",
    "작성 대상 후보",
    "작성대상 후보",
    "수량기준",
    "최종 R",
    "R 재계산",
    "규정량 비율",
    "위험도",
    "화사계 상위기준 후보",
    "화사계 하위기준 후보",
    "상위 규정수량 이상 후보",
    "포괄 물질범위 후보",
    "규제범위 후보",
]


class LegalTerminologyContractTests(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    def test_stage1_user_facing_text_avoids_ambiguous_nonstatutory_terms(self) -> None:
        violations: list[str] = []
        for relative_path in USER_FACING_FILES:
            text = self._read(relative_path)
            for term in FORBIDDEN_AMBIGUOUS_TERMS:
                if term in text:
                    violations.append(f"{relative_path}: {term}")
        self.assertEqual([], violations, "법령용어가 아닌 혼동 가능 표현이 남아 있습니다: " + ", ".join(violations))

    def test_psm_ui_uses_annex13_statutory_terms(self) -> None:
        text = self._read("ui/diagnosis_page.py") + self._read("ui/psm_followup_panel.py") + self._read("engine/consulting_guidance.py")
        self.assertIn("유해·위험물질 규정량", text)
        self.assertIn("합산한 값(R)", text)
        self.assertIn("공정안전보고서 제출 대상", text)

    def test_cap_quantity_labels_use_statutory_terms(self) -> None:
        text = self._read("engine/cap_quick_holding.py") + self._read("engine/cap_holding.py") + self._read("engine/cap_engine.py")
        self.assertIn("최대보유량이 상위 규정수량 이상", text)
        self.assertIn("최대보유량이 하위 규정수량 이상·상위 규정수량 미만", text)

    def test_cap_final_labels_use_writing_level_and_exemption_terms(self) -> None:
        text = self._read("engine/cap_final_decision.py")
        self.assertIn("작성수준 — 1군 사업장", text)
        self.assertIn("작성수준 — 2군 사업장", text)
        self.assertIn("작성 면제", text)


if __name__ == "__main__":
    unittest.main()
