from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from engine.stage2 import local_ai_resilience as resilience
from engine.stage2.local_llm import LocalLLMConfig


class Stage2LocalAIResilienceTests(unittest.TestCase):
    def test_legacy_heavy_defaults_are_tuned_for_local_14b(self):
        config = resilience.local_llm_config_from_sources(
            {
                "LOCAL_LLM_PROVIDER": "ollama",
                "LOCAL_LLM_MODEL": "qwen3:14b",
                "LOCAL_LLM_URL": "http://127.0.0.1:11434",
                "LOCAL_LLM_TIMEOUT_SECONDS": "180",
                "LOCAL_LLM_MAX_OUTPUT_TOKENS": "12000",
            }
        )
        self.assertEqual(config.timeout_seconds, 600)
        self.assertEqual(config.max_output_tokens, 3000)

    def test_explicit_longer_timeout_and_lower_token_cap_are_respected(self):
        config = resilience.local_llm_config_from_sources(
            {
                "LOCAL_LLM_PROVIDER": "ollama",
                "LOCAL_LLM_MODEL": "qwen3:14b",
                "LOCAL_LLM_URL": "http://127.0.0.1:11434",
                "LOCAL_LLM_TIMEOUT_SECONDS": "900",
                "LOCAL_LLM_MAX_OUTPUT_TOKENS": "1800",
            }
        )
        self.assertEqual(config.timeout_seconds, 900)
        self.assertEqual(config.max_output_tokens, 1800)

    def test_fast_auto_prefers_installed_8b_over_14b(self):
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        fast = resilience.select_fast_auto_config(
            configured,
            ("qwen3:14b", "qwen3:8b", "qwen3.5:4b", "qwen3.5:0.8b"),
        )
        self.assertEqual(fast.model, "qwen3:8b")
        self.assertEqual(fast.max_output_tokens, 2200)
        self.assertEqual(configured.model, "qwen3:14b")

    def test_fast_auto_never_drops_to_tiny_sub_1b_model(self):
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        fast = resilience.select_fast_auto_config(configured, ("qwen3:14b", "qwen3.5:0.8b"))
        self.assertEqual(fast.model, "qwen3:14b")

    def test_parameter_heuristic_is_used_when_gpu_is_not_detectable(self):
        # No available_model_sizes/gpu_vram_bytes supplied, and nvidia-smi is
        # not present in this environment, so this exercises the same
        # fallback path a non-NVIDIA machine would take.
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        with patch.object(resilience, "_detect_gpu_vram_bytes", return_value=None):
            fast = resilience.select_fast_auto_config(
                configured, ("qwen3:14b", "qwen3:8b", "qwen3.5:4b")
            )
        self.assertEqual(fast.model, "qwen3:8b")

    def test_vram_fit_downgrades_model_that_does_not_fit_6gb_gpu(self):
        # Mirrors an RTX 2060 6GB: qwen3:14b (9.3GB) cannot fully load, which
        # is what `ollama ps` reports as a CPU/GPU split. qwen3.5:4b (3.4GB)
        # fits, so it should be preferred even though a bigger 8B model is
        # also installed but does not fit.
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        six_gb = 6 * 1024 * 1024 * 1024
        sizes = {
            "qwen3:14b": 9_300_000_000,
            "qwen3:8b": 5_800_000_000,  # exceeds the 6GB*0.85 safety budget
            "qwen3.5:4b": 3_400_000_000,
        }
        fast = resilience.select_fast_auto_config(
            configured,
            ("qwen3:14b", "qwen3:8b", "qwen3.5:4b"),
            available_model_sizes=sizes,
            gpu_vram_bytes=six_gb,
        )
        self.assertEqual(fast.model, "qwen3.5:4b")
        self.assertEqual(fast.max_output_tokens, 2200)

    def test_vram_fit_keeps_configured_model_when_it_already_fits(self):
        # A 24GB GPU can run qwen3:14b fully in VRAM, so it should not be
        # needlessly downgraded to a smaller/lower-quality model.
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        twenty_four_gb = 24 * 1024 * 1024 * 1024
        sizes = {"qwen3:14b": 9_300_000_000, "qwen3.5:4b": 3_400_000_000}
        fast = resilience.select_fast_auto_config(
            configured,
            ("qwen3:14b", "qwen3.5:4b"),
            available_model_sizes=sizes,
            gpu_vram_bytes=twenty_four_gb,
        )
        self.assertEqual(fast.model, "qwen3:14b")

    def test_vram_fit_keeps_configured_model_when_nothing_installed_fits(self):
        configured = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        two_gb = 2 * 1024 * 1024 * 1024
        sizes = {"qwen3:14b": 9_300_000_000, "qwen3:8b": 5_400_000_000}
        fast = resilience.select_fast_auto_config(
            configured,
            ("qwen3:14b", "qwen3:8b"),
            available_model_sizes=sizes,
            gpu_vram_bytes=two_gb,
        )
        self.assertEqual(fast.model, "qwen3:14b")

    def test_detect_gpu_vram_bytes_parses_nvidia_smi_output(self):
        resilience._GPU_VRAM_CACHE.clear()
        completed = SimpleNamespace(stdout="6144\n", returncode=0)
        with (
            patch.object(resilience.shutil, "which", return_value="/usr/bin/nvidia-smi"),
            patch.object(resilience.subprocess, "run", return_value=completed),
        ):
            result = resilience._detect_gpu_vram_bytes()
        self.assertEqual(result, 6144 * 1024 * 1024)
        resilience._GPU_VRAM_CACHE.clear()

    def test_detect_gpu_vram_bytes_returns_none_without_nvidia_smi(self):
        resilience._GPU_VRAM_CACHE.clear()
        with patch.object(resilience.shutil, "which", return_value=None):
            result = resilience._detect_gpu_vram_bytes()
        self.assertIsNone(result)
        resilience._GPU_VRAM_CACHE.clear()

    def test_ollama_payload_disables_thinking_and_keeps_model_loaded(self):
        config = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": {"content": '{"profile_summary":"ok","drafts":[]}'}}
        with patch("engine.stage2.local_ai_resilience.requests.post", return_value=response) as post:
            client = resilience.ResilientOllamaLocalClient(
                config,
                available_models=("qwen3:14b", "qwen3:8b", "qwen3.5:4b"),
            )
            result = client.generate_json(instructions="system", prompt="user")
        self.assertEqual(result["profile_summary"], "ok")
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"], "15m")
        self.assertEqual(payload["options"]["num_predict"], 3000)
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 600))

    def test_read_timeout_is_not_misreported_as_model_missing(self):
        config = LocalLLMConfig(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600,
            max_output_tokens=3000,
        )
        with patch("engine.stage2.local_ai_resilience.requests.post", side_effect=requests.ReadTimeout("slow")):
            client = resilience.ResilientOllamaLocalClient(
                config,
                available_models=("qwen3:14b", "qwen3:8b", "qwen3.5:4b", "qwen3.5:0.8b"),
            )
            with self.assertRaises(resilience.LocalAIGenerationTimeout) as ctx:
                client.generate_json(instructions="system", prompt="user")
        message = str(ctx.exception)
        self.assertIn("모델 미설치 오류가 아닙니다", message)
        self.assertIn("qwen3:8b", message)
        self.assertIn("qwen3.5:4b", message)

    def test_generation_uses_small_batches_and_checkpoints_each_success(self):
        specs = [SimpleNamespace(key=f"k{i}", system="CAP", label=f"항목{i}") for i in range(7)]
        project = object()
        calls: list[list[str]] = []

        def process(_project, _system, batch, _client, *, store_safe_drafts):
            calls.append([spec.key for spec in batch])
            item = SimpleNamespace(safe_to_store=True)
            return "요약", [item], []

        with (
            patch.object(resilience.core, "ai_draftable_specs", return_value=specs),
            patch.object(resilience.core, "selected_requirement_specs", return_value=specs),
            patch.object(resilience, "_process_one_batch", side_effect=process),
            patch.object(resilience, "_checkpoint_project") as checkpoint,
        ):
            result = resilience.generate_system_ai_drafts_batched(
                project,
                "CAP",
                SimpleNamespace(model="qwen3:14b"),
                batch_size=3,
            )
        self.assertEqual(calls, [["k0", "k1", "k2"], ["k3", "k4", "k5"], ["k6"]])
        self.assertEqual(result.completed_batches, 3)
        self.assertEqual(result.total_batches, 3)
        self.assertEqual(len(result.generated), 3)
        self.assertEqual(checkpoint.call_count, 3)

    def test_8b_default_batch_processes_more_items_per_call(self):
        specs = [SimpleNamespace(key=f"k{i}", system="CAP", label=f"항목{i}") for i in range(7)]
        calls: list[list[str]] = []

        def process(_project, _system, batch, _client, *, store_safe_drafts):
            calls.append([spec.key for spec in batch])
            return "요약", [SimpleNamespace(safe_to_store=True)], []

        with (
            patch.object(resilience.core, "ai_draftable_specs", return_value=specs),
            patch.object(resilience.core, "selected_requirement_specs", return_value=specs),
            patch.object(resilience, "_process_one_batch", side_effect=process),
            patch.object(resilience, "_checkpoint_project"),
        ):
            result = resilience.generate_system_ai_drafts_batched(
                object(),
                "CAP",
                SimpleNamespace(model="qwen3:8b"),
            )
        self.assertEqual(calls, [["k0", "k1", "k2", "k3", "k4"], ["k5", "k6"]])
        self.assertEqual(result.total_batches, 2)

    def test_selective_retry_only_regenerates_requested_missing_items(self):
        specs = [SimpleNamespace(key=f"k{i}", system="CAP", label=f"항목{i}") for i in range(5)]
        calls: list[list[str]] = []

        def process(_project, _system, batch, _client, *, store_safe_drafts):
            calls.append([spec.key for spec in batch])
            return "요약", [SimpleNamespace(safe_to_store=True)], []

        with (
            patch.object(resilience.core, "ai_draftable_specs", return_value=specs),
            patch.object(resilience.core, "selected_requirement_specs", return_value=specs),
            patch.object(resilience, "_process_one_batch", side_effect=process),
            patch.object(resilience, "_checkpoint_project"),
        ):
            resilience.generate_system_ai_drafts_batched(
                object(),
                "CAP",
                SimpleNamespace(model="qwen3:8b"),
                requirement_keys=["k3", "k4"],
            )
        self.assertEqual(calls, [["k3", "k4"]])

    def test_timed_out_multi_item_batch_retries_one_item_at_a_time(self):
        specs = [SimpleNamespace(key=f"k{i}", system="CAP", label=f"항목{i}") for i in range(3)]
        project = object()
        calls: list[list[str]] = []

        def process(_project, _system, batch, _client, *, store_safe_drafts):
            keys = [spec.key for spec in batch]
            calls.append(keys)
            if len(batch) > 1:
                raise resilience.LocalAIGenerationTimeout("batch slow")
            return "요약", [SimpleNamespace(safe_to_store=True)], []

        with (
            patch.object(resilience.core, "ai_draftable_specs", return_value=specs),
            patch.object(resilience.core, "selected_requirement_specs", return_value=specs),
            patch.object(resilience, "_process_one_batch", side_effect=process),
            patch.object(resilience, "_checkpoint_project") as checkpoint,
        ):
            result = resilience.generate_system_ai_drafts_batched(
                project,
                "CAP",
                SimpleNamespace(model="qwen3:14b"),
                batch_size=3,
            )
        self.assertEqual(calls, [["k0", "k1", "k2"], ["k0"], ["k1"], ["k2"]])
        self.assertEqual(len(result.generated), 3)
        self.assertEqual(checkpoint.call_count, 3)

    def test_review_page_imports_resilient_client_and_drafting(self):
        # ui/stage2_review_page.py imports build_local_llm_client/
        # local_llm_config_from_sources/generate_system_ai_drafts directly
        # from local_ai_resilience (not the plain local_llm/ai_drafting
        # versions), so there is no install step needed to make the real app
        # use the resilient behavior.
        with open("ui/stage2_review_page.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("from engine.stage2.local_ai_resilience import (", source)
        self.assertIn("build_local_llm_client", source)
        self.assertIn("generate_system_ai_drafts", source)
        self.assertIn("local_llm_config_from_sources", source)

    def test_fast_auto_selection_picks_smaller_installed_model_and_batch(self):
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

    def test_fast_auto_selection_is_vram_aware_when_model_sizes_are_known(self):
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


if __name__ == "__main__":
    unittest.main()
