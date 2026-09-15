from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2LocalLLMSetupUIContractTests(unittest.TestCase):
    def test_review_page_keeps_local_only_runtime_configuration(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("회사정보는 외부 AI로 보내지 않습니다", text)
        self.assertIn("로컬 AI만 사용합니다", text)
        self.assertIn("validate_local_base_url", text)
        self.assertIn("Ollama", text)
        self.assertIn("LM Studio", text)
        self.assertIn("로컬 모델 이름", text)
        self.assertIn("로컬 AI 주소", text)
        self.assertIn("probe_local_llm_runtime", text)


if __name__ == "__main__":
    unittest.main()
