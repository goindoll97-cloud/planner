from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2LocalLLMSetupUIContractTests(unittest.TestCase):
    def test_review_page_keeps_local_only_runtime_configuration(self):
        text = (ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1/localhost/::1", text)
        self.assertIn("Ollama/LM Studio", text)
        self.assertIn("로컬 모델 이름", text)
        self.assertIn("로컬 LLM 주소", text)


if __name__ == "__main__":
    unittest.main()
