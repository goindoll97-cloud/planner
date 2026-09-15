from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.stage2 import ai_live_progress_runtime as ai_live
from engine.stage2 import cap_fragment_runtime as fragment
from engine.stage2 import cap_hwpx
from engine.stage2 import local_ai_resilience as resilience
from engine.stage2.local_llm import LocalLLMConfig


class CAPFragmentRuntimeTests(unittest.TestCase):
    def test_partial_builder_relaxes_only_split_form_call_and_restores_validator(self):
        strict = cap_hwpx.CAPTemplateValidation(
            ok=False,
            sha256="a" * 64,
            found_markers=("[별지 제1호서식]",),
            missing_markers=("[별지 제3호서식]",),
            section_paths=("Contents/section0.xml",),
        )
        calls = []

        def strict_validator(_data):
            return strict

        def original_build(project, template_bytes=None):
            result = cap_hwpx.validate_cap_hwpx_template(template_bytes or b"")
            calls.append(result.ok)
            if not result.ok:
                raise ValueError("strict rejection")
            return "built"

        with patch.object(cap_hwpx, "validate_cap_hwpx_template", strict_validator):
            builder = fragment._partial_builder_threadsafe(original_build)
            self.assertEqual(builder(object(), template_bytes=b"split-form"), "built")
            self.assertEqual(calls, [True])
            self.assertIs(cap_hwpx.validate_cap_hwpx_template, strict_validator)
            with self.assertRaisesRegex(ValueError, "strict rejection"):
                original_build(object(), template_bytes=b"split-form")

    def test_app_installs_fragment_runtime_after_multi_form_runtime(self):
        text = open("app.py", encoding="utf-8").read()
        multi_pos = text.index("install_cap_multi_form_runtime()")
        fragment_pos = text.index("install_cap_fragment_runtime()")
        self.assertLess(multi_pos, fragment_pos)
        self.assertIn("install_cap_fragment_runtime", text)


class AILiveProgressRuntimeTests(unittest.TestCase):
    def test_live_progress_preserves_fast_selection_and_adaptive_batching(self):
        original_select = resilience.select_fast_auto_config
        original_process = resilience._process_one_batch
        original_recommended = resilience.recommended_batch_size
        installed = getattr(resilience, "_ai_live_progress_runtime_installed", False)
        try:
            resilience._ai_live_progress_runtime_installed = False
            ai_live.install_ai_live_progress_runtime()
            configured = LocalLLMConfig(
                provider="ollama",
                model="qwen3:14b",
                base_url="http://127.0.0.1:11434",
                timeout_seconds=600,
                max_output_tokens=3000,
            )
            selected = resilience.select_fast_auto_config(configured, ("qwen3:14b", "qwen3:8b"))
            self.assertEqual(selected.model, "qwen3:8b")
            self.assertLessEqual(selected.max_output_tokens, resilience.FAST_AUTO_MAX_OUTPUT_TOKENS)
            self.assertEqual(resilience.recommended_batch_size(selected.model), resilience.FAST_AUTO_BATCH_SIZE)
            self.assertIs(resilience.select_fast_auto_config, original_select)
            self.assertIs(resilience.recommended_batch_size, original_recommended)
        finally:
            resilience.select_fast_auto_config = original_select
            resilience._process_one_batch = original_process
            resilience.recommended_batch_size = original_recommended
            resilience._ai_live_progress_runtime_installed = installed

    def test_live_progress_keeps_vram_aware_selection(self):
        original_select = resilience.select_fast_auto_config
        original_process = resilience._process_one_batch
        original_recommended = resilience.recommended_batch_size
        installed = getattr(resilience, "_ai_live_progress_runtime_installed", False)
        try:
            resilience._ai_live_progress_runtime_installed = False
            ai_live.install_ai_live_progress_runtime()
            configured = LocalLLMConfig(
                provider="ollama",
                model="qwen3:14b",
                base_url="http://127.0.0.1:11434",
                timeout_seconds=600,
                max_output_tokens=3000,
            )
            selected = resilience.select_fast_auto_config(
                configured,
                ("qwen3:14b", "qwen3:8b", "qwen3.5:4b"),
                available_model_sizes={
                    "qwen3:14b": 9_300_000_000,
                    "qwen3:8b": 5_800_000_000,
                    "qwen3.5:4b": 3_400_000_000,
                },
                gpu_vram_bytes=6 * 1024 * 1024 * 1024,
            )
            self.assertEqual(selected.model, "qwen3.5:4b")
            self.assertLessEqual(selected.max_output_tokens, resilience.FAST_AUTO_MAX_OUTPUT_TOKENS)
            self.assertEqual(resilience.recommended_batch_size(selected.model), resilience.FAST_AUTO_BATCH_SIZE)
        finally:
            resilience.select_fast_auto_config = original_select
            resilience._process_one_batch = original_process
            resilience.recommended_batch_size = original_recommended
            resilience._ai_live_progress_runtime_installed = installed

    def test_app_installs_live_progress_after_response_normalizer(self):
        text = open("app.py", encoding="utf-8").read()
        normalizer_pos = text.index("install_ai_response_runtime()")
        progress_pos = text.index("install_ai_live_progress_runtime()")
        self.assertLess(normalizer_pos, progress_pos)
        self.assertIn("install_ai_live_progress_runtime", text)


if __name__ == "__main__":
    unittest.main()
