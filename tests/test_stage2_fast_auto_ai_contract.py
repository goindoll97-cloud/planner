from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Stage2FastAutoAIContractTests(unittest.TestCase):




    def test_fast_mode_keeps_tiny_model_out_of_automatic_selection(self):
        source = (ROOT / "engine/stage2/local_ai_resilience.py").read_text(encoding="utf-8")
        self.assertIn("FAST_AUTO_MODEL_MIN_B = 4.0", source)
        self.assertIn("FAST_AUTO_MODEL_MAX_B = 8.5", source)
        self.assertIn("FAST_AUTO_BATCH_SIZE = 5", source)


if __name__ == "__main__":
    unittest.main()
