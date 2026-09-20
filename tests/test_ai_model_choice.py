from __future__ import annotations

from pathlib import Path
import unittest

from engine.stage2.local_ai_resilience import select_fast_auto_config
from engine.stage2.local_llm import LocalLLMConfig

GB = 1024 ** 3
MODELS = ("qwen3:14b", "qwen3:8b", "qwen3.5:4b")
SIZES = {"qwen3:14b": 9276198565, "qwen3:8b": 5225388164, "qwen3.5:4b": 3389983735}


class ModelChoiceTests(unittest.TestCase):
    def _pick(self, vram_gb):
        config = LocalLLMConfig(model="qwen3:14b")
        return select_fast_auto_config(config, MODELS, available_model_sizes=SIZES, gpu_vram_bytes=int(vram_gb * GB)).model

    def test_six_gb_gpu_gets_the_4b_model_because_the_8b_spills_to_cpu(self):
        self.assertEqual(self._pick(6), "qwen3.5:4b")  # 실측: 8B는 6GB GPU에서 CPU로 넘쳐 6배 느렸다

    def test_larger_gpus_keep_bigger_models(self):
        self.assertEqual(self._pick(12), "qwen3:8b")
        self.assertEqual(self._pick(24), "qwen3:14b")

    def test_narrative_panel_applies_the_automatic_choice(self):
        text = (Path(__file__).resolve().parents[1] / "ui/narrative_panel.py").read_text(encoding="utf-8")
        self.assertIn("select_fast_auto_config(", text)
        self.assertIn("build_client(run_config)", text)


if __name__ == "__main__":
    unittest.main()
