from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine.stage2 import ai_live_progress_runtime as ai_live
from engine.stage2 import cap_hwpx
from engine.stage2 import cap_multi_form_runtime as multi
from engine.stage2 import local_ai_resilience as resilience
from engine.stage2.local_llm import LocalLLMConfig


class CAPMultiFormPartialBuilderTests(unittest.TestCase):
    """Split official CAP files contain only some statutory form markers, so
    cap_multi_form_runtime._partial_builder relaxes the monolithic validation
    only for that approved split-form writer; every other caller of
    cap_hwpx.validate_cap_hwpx_template (manual uploads, single-template
    validation) must stay strict, including immediately after a relaxed call."""

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
            builder = multi._partial_builder(original_build)
            self.assertEqual(builder(object(), template_bytes=b"split-form"), "built")
            self.assertEqual(calls, [True])
            self.assertIs(cap_hwpx.validate_cap_hwpx_template, strict_validator)
            with self.assertRaisesRegex(ValueError, "strict rejection"):
                original_build(object(), template_bytes=b"split-form")


class AILiveProgressRuntimeTests(unittest.TestCase):
    def test_compact_fast_selection_caps_output(self):
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
            self.assertLessEqual(selected.max_output_tokens, 1200)
            self.assertEqual(resilience.recommended_batch_size(selected.model), 1)
        finally:
            resilience.select_fast_auto_config = original_select
            resilience._process_one_batch = original_process
            resilience.recommended_batch_size = original_recommended
            resilience._ai_live_progress_runtime_installed = installed

    def test_compact_fast_selection_forwards_vram_keywords(self):
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
            self.assertLessEqual(selected.max_output_tokens, 1200)
        finally:
            resilience.select_fast_auto_config = original_select
            resilience._process_one_batch = original_process
            resilience.recommended_batch_size = original_recommended
            resilience._ai_live_progress_runtime_installed = installed

    def test_app_installs_live_progress_after_local_ai_resilience(self):
        # install_ai_live_progress_runtime wraps resilience._process_one_batch,
        # so it must install after local_ai_resilience (which now also owns the
        # tolerant-JSON-shape normalization that used to be a separate step).
        text = open("app.py", encoding="utf-8").read()
        resilience_pos = text.index("install_local_ai_resilience()")
        progress_pos = text.index("install_ai_live_progress_runtime()")
        self.assertLess(resilience_pos, progress_pos)
        self.assertIn("install_ai_live_progress_runtime", text)


if __name__ == "__main__":
    unittest.main()
