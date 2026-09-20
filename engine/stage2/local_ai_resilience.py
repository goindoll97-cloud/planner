from __future__ import annotations

"""Runtime hardening and speed tuning for local report drafting.

The Stage 2 AI path must remain local-only and fact-grounded, but ordinary
Windows PCs can take a long time when a 14B model is used for every automatic
report-drafting pass.  This module therefore combines the existing timeout,
small-batch and checkpoint protections with an optional fast automatic mode:
when an installed 4B-8B Ollama model is available, automatic drafting may use
that model while keeping the larger configured model available for manual
precision use.  Missing requirements can also be regenerated selectively so a
partial retry does not redo already completed prose.
"""

from dataclasses import dataclass, replace
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence

import requests

from . import ai_drafting as core
from . import local_llm
from .ai_response_normalizer import normalize_draft_response


DEFAULT_LOCAL_AI_TIMEOUT_SECONDS = 600
DEFAULT_LOCAL_AI_MAX_OUTPUT_TOKENS = 3000
DEFAULT_LOCAL_AI_BATCH_SIZE = 3
FAST_AUTO_MODEL_MIN_B = 4.0
FAST_AUTO_MODEL_MAX_B = 8.5
FAST_AUTO_MAX_OUTPUT_TOKENS = 2200
FAST_AUTO_BATCH_SIZE = 5
OLLAMA_KEEP_ALIVE = "15m"

# A model whose file size exceeds the GPU's VRAM does not simply run slightly
# slower: Ollama offloads the overflow layers to CPU, which is dramatically
# slower than a full GPU load (this is what `ollama ps` reports as a
# CPU/GPU split, e.g. "35%/65% CPU/GPU"). The parameter-count heuristic below
# (FAST_AUTO_MODEL_MIN_B/MAX_B) is a portable fallback for when we cannot
# measure the GPU, but whenever we can measure it, an actual VRAM-fit check is
# more accurate: it correctly keeps a heavy model on a large GPU instead of
# needlessly downgrading it, and correctly downgrades a "fits the B-range"
# model that still does not fit this specific GPU's VRAM.
GPU_VRAM_SAFETY_MARGIN = 0.7  # KV-cache/context 여유. 실측: 6GB GPU에서 5.2GB 모델(qwen3:8b)이 6.6GB를 써 CPU로 넘침(192초 vs 4B 33초)
_GPU_VRAM_CACHE: dict[str, int | None] = {}


def _detect_gpu_vram_bytes() -> int | None:
    """Best-effort NVIDIA GPU VRAM detection via nvidia-smi.

    Returns None when nvidia-smi is missing or detection fails for any reason,
    so callers fall back to the parameter-count heuristic instead of guessing.
    Cached for the process lifetime since GPU hardware does not change mid-run.
    """
    if "value" in _GPU_VRAM_CACHE:
        return _GPU_VRAM_CACHE["value"]
    detected: int | None = None
    if shutil.which("nvidia-smi"):
        try:
            output = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            totals = [int(line.strip()) for line in output.stdout.splitlines() if line.strip()]
            if totals:
                detected = max(totals) * 1024 * 1024
        except (subprocess.SubprocessError, OSError, ValueError):
            detected = None
    _GPU_VRAM_CACHE["value"] = detected
    return detected


def _fits_in_vram(size_bytes: int, vram_bytes: int) -> bool:
    return size_bytes <= vram_bytes * GPU_VRAM_SAFETY_MARGIN


class LocalAIGenerationTimeout(RuntimeError):
    """The local runtime was reachable, but generation exceeded the read window."""


@dataclass(frozen=True)
class BatchedAIDraftPackResult:
    system: str
    system_label: str
    profile_summary: str
    generated: tuple[core.AIDraftItem, ...]
    rejected: tuple[core.AIDraftItem, ...]
    skipped_requirement_keys: tuple[str, ...]
    model: str
    completed_batches: int
    total_batches: int


def _model_size_billion(model_name: str) -> float | None:
    match = re.search(r":(\d+(?:\.\d+)?)b(?:$|[-_])", str(model_name or "").lower())
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _smaller_installed_models(selected: str, available: Sequence[str]) -> tuple[str, ...]:
    selected_size = _model_size_billion(selected)
    candidates: list[tuple[float, str]] = []
    for name in available:
        if name == selected:
            continue
        size = _model_size_billion(name)
        if size is None:
            continue
        if selected_size is None or size < selected_size:
            candidates.append((size, name))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return tuple(name for _, name in candidates[:4])


def select_fast_auto_config(
    config: local_llm.LocalLLMConfig,
    available_models: Sequence[str],
    *,
    available_model_sizes: Mapping[str, int] | None = None,
    gpu_vram_bytes: int | None = None,
) -> local_llm.LocalLLMConfig:
    """Choose a faster installed Ollama model for automatic drafting.

    When actual model file sizes and a detected GPU VRAM size are available,
    selection is based on whether a model's weights actually fit in VRAM
    (``_select_by_vram_fit``): this is more accurate than guessing from the
    model's parameter count, since VRAM capacity differs across GPUs. When
    either is unavailable (no nvidia-smi, non-NVIDIA GPU, or an /api/tags
    response without size fields), this falls back to the original
    parameter-count heuristic (``_select_by_parameter_count``) so behavior on
    unmeasured setups is unchanged.
    """
    if config.provider != "ollama":
        return config

    sizes = dict(available_model_sizes or {})
    vram_bytes = gpu_vram_bytes if gpu_vram_bytes is not None else _detect_gpu_vram_bytes()
    if vram_bytes and sizes:
        return _select_by_vram_fit(config, available_models, sizes, vram_bytes)
    return _select_by_parameter_count(config, available_models)


def _select_by_parameter_count(
    config: local_llm.LocalLLMConfig,
    available_models: Sequence[str],
) -> local_llm.LocalLLMConfig:
    """Portable fallback: pick a faster model by parameter-count range only.

    The configured model is kept when it is already 8B-class or smaller, or
    when no suitable 4B-8B model is installed.  For a heavier model such as
    qwen3:14b, the largest installed model in the 4B-8B range is preferred.
    This keeps quality materially above tiny sub-1B models while avoiding the
    long latency of 14B automatic passes.
    """
    selected_size = _model_size_billion(config.model)
    if selected_size is not None and selected_size <= FAST_AUTO_MODEL_MAX_B:
        return replace(
            config,
            max_output_tokens=min(config.max_output_tokens, FAST_AUTO_MAX_OUTPUT_TOKENS),
        )

    candidates: list[tuple[float, str]] = []
    for name in available_models:
        size = _model_size_billion(name)
        if size is None:
            continue
        if FAST_AUTO_MODEL_MIN_B <= size <= FAST_AUTO_MODEL_MAX_B:
            candidates.append((size, name))
    if not candidates:
        return config

    # Prefer the largest fast model: this chooses qwen3:8b over 4b on the
    # user's current installation, preserving more drafting quality.
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, model = candidates[0]
    return replace(
        config,
        model=model,
        max_output_tokens=min(config.max_output_tokens, FAST_AUTO_MAX_OUTPUT_TOKENS),
    )


def _select_by_vram_fit(
    config: local_llm.LocalLLMConfig,
    available_models: Sequence[str],
    sizes: Mapping[str, int],
    vram_bytes: int,
) -> local_llm.LocalLLMConfig:
    configured_size = sizes.get(config.model)
    if configured_size is not None and _fits_in_vram(configured_size, vram_bytes):
        # Already fits fully in VRAM (e.g. a large-VRAM GPU running qwen3:14b):
        # no need to downgrade quality, just keep the output-length cap.
        return replace(
            config,
            max_output_tokens=min(config.max_output_tokens, FAST_AUTO_MAX_OUTPUT_TOKENS),
        )

    fitting: list[tuple[int, str]] = []
    for name in available_models:
        size = sizes.get(name)
        if size is None or not _fits_in_vram(size, vram_bytes):
            continue
        fitting.append((size, name))

    if not fitting:
        # Nothing is confirmed to fit in VRAM: keep the configured model
        # rather than guessing at an even less capable one.
        return config

    # Prefer the largest model that still fits fully in VRAM.
    fitting.sort(key=lambda item: item[0], reverse=True)
    _, model = fitting[0]
    return replace(
        config,
        model=model,
        max_output_tokens=min(config.max_output_tokens, FAST_AUTO_MAX_OUTPUT_TOKENS),
    )


def recommended_batch_size(model_name: str) -> int:
    size = _model_size_billion(model_name)
    if size is not None and size <= FAST_AUTO_MODEL_MAX_B:
        return FAST_AUTO_BATCH_SIZE
    return DEFAULT_LOCAL_AI_BATCH_SIZE


def _timeout_message(config: local_llm.LocalLLMConfig, available_models: Sequence[str]) -> str:
    alternatives = _smaller_installed_models(config.model, available_models)
    message = (
        f"Ollama와 모델 '{config.model}'에는 연결되었지만 문장 생성이 "
        f"{config.timeout_seconds}초 안에 끝나지 않았습니다. 모델 미설치 오류가 아닙니다. "
        "현재 작성항목은 작은 배치로 자동 재시도합니다."
    )
    if alternatives:
        message += " 계속 느리면 설치되어 있는 더 작은 모델(" + ", ".join(alternatives) + ")로 바꾸면 빨라집니다."
    return message


class ResilientOllamaLocalClient:
    def __init__(
        self,
        config: local_llm.LocalLLMConfig,
        *,
        available_models: Sequence[str] = (),
    ) -> None:
        self.config = config
        self.model = config.model
        self.base_url = local_llm.validate_local_base_url(config.base_url)
        self.available_models = tuple(available_models)

    def generate_json(self, *, instructions: str, prompt: str) -> Mapping[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_predict": self.config.max_output_tokens,
                        "temperature": 0.1,
                    },
                },
                timeout=(10, self.config.timeout_seconds),
            )
            response.raise_for_status()
        except requests.ReadTimeout as exc:
            raise LocalAIGenerationTimeout(_timeout_message(self.config, self.available_models)) from exc
        except requests.ConnectTimeout as exc:
            raise RuntimeError("Ollama 로컬 서버 연결 시간이 초과되었습니다. `ollama serve` 실행상태를 확인하세요.") from exc

        raw = response.json()
        message = raw.get("message")
        text = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Ollama 응답에서 문장 출력을 찾지 못했습니다.")
        return local_llm._parse_json_object(text)


def local_llm_config_from_sources(values: Mapping[str, Any] | None = None) -> local_llm.LocalLLMConfig:
    """Resilient drop-in for local_llm.local_llm_config_from_sources.

    Ordinary Windows PCs can take a long time when a 14B model drafts many
    report items in one call, so the resulting config always gets at least
    DEFAULT_LOCAL_AI_TIMEOUT_SECONDS and at most
    DEFAULT_LOCAL_AI_MAX_OUTPUT_TOKENS, regardless of the configured/env values.
    """
    config = local_llm.local_llm_config_from_sources(values)
    return replace(
        config,
        timeout_seconds=max(config.timeout_seconds, DEFAULT_LOCAL_AI_TIMEOUT_SECONDS),
        max_output_tokens=min(config.max_output_tokens, DEFAULT_LOCAL_AI_MAX_OUTPUT_TOKENS),
    )


def build_local_llm_client(config: local_llm.LocalLLMConfig):
    """Resilient drop-in for local_llm.build_local_llm_client: an Ollama
    client gets checkpoint/retry/timeout hardening (ResilientOllamaLocalClient)
    instead of the plain OllamaLocalClient."""
    local_llm.validate_local_base_url(config.base_url)
    probe = local_llm.probe_local_llm_runtime(config)
    if not probe.ready:
        raise ValueError(local_llm.local_runtime_not_ready_message(config, probe))
    if config.provider == "ollama":
        return ResilientOllamaLocalClient(config, available_models=probe.models)
    if config.provider == "openai_compatible":
        return local_llm.OpenAICompatibleLocalClient(config)
    raise ValueError("지원하지 않는 로컬 AI 실행기입니다.")


def _chunks(items: Sequence[Any], size: int) -> list[list[Any]]:
    size = max(1, int(size))
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _process_one_batch(
    project,
    system: str,
    specs,
    client,
    *,
    store_safe_drafts: bool,
) -> tuple[str, list[core.AIDraftItem], list[core.AIDraftItem]]:
    specs = list(specs)
    prompt, global_facts = core._build_pack_prompt(project, system, specs)
    raw = client.generate_json(instructions=core._system_prompt(system), prompt=prompt)
    raw_profile, draft_rows = normalize_draft_response(raw, specs)

    return core.build_pack_result_from_rows(
        project, system, specs, global_facts, raw_profile, draft_rows, client,
        store_safe_drafts=store_safe_drafts,
    )


def _checkpoint_project(project) -> None:
    from .storage import save_project

    save_project(project)


def generate_system_ai_drafts_batched(
    project,
    system: str,
    client,
    *,
    store_safe_drafts: bool = True,
    batch_size: int | None = None,
    requirement_keys: Sequence[str] | None = None,
    progress: Any = None,
) -> BatchedAIDraftPackResult:
    system = core._normalize_system(system)
    draftable = core.ai_draftable_specs(project, system)
    wanted = set(requirement_keys or ())
    specs = [spec for spec in draftable if not wanted or spec.key in wanted]
    all_system_specs = [spec for spec in core.selected_requirement_specs(project) if spec.system == system]
    skipped = tuple(spec.key for spec in all_system_specs if spec not in specs)
    if not specs:
        raise ValueError("AI 문장 보강에 사용할 확인된 회사 사실이 없습니다.")

    effective_batch_size = batch_size or recommended_batch_size(getattr(client, "model", ""))
    batches = _chunks(specs, effective_batch_size)
    generated: list[core.AIDraftItem] = []
    rejected: list[core.AIDraftItem] = []
    profile_summary = ""
    completed = 0
    started = time.monotonic()

    def report(event: str, batch_specs) -> None:
        """화면에 진행 상황을 알린다. 화면 표시가 실패해도 생성은 계속한다."""
        if progress is None:
            return
        try:
            progress({"event": event, "done": completed, "total": len(batches), "items": len(specs),
                      "labels": [spec.label for spec in batch_specs], "elapsed": time.monotonic() - started,
                      "generated": len(generated), "rejected": len(rejected), "model": getattr(client, "model", "")})
        except Exception:
            pass

    for batch in batches:
        report("start", batch)
        try:
            summary, good, bad = _process_one_batch(
                project,
                system,
                batch,
                client,
                store_safe_drafts=store_safe_drafts,
            )
        except LocalAIGenerationTimeout as batch_exc:
            if len(batch) <= 1:
                if store_safe_drafts and (generated or rejected):
                    _checkpoint_project(project)
                raise LocalAIGenerationTimeout(
                    f"{batch_exc} 현재 {completed}/{len(batches)}개 배치는 완료되어 저장되었습니다. "
                    "다음 자동 시도에서는 남은 항목만 다시 처리합니다."
                ) from batch_exc

            for spec in batch:
                try:
                    summary, good, bad = _process_one_batch(
                        project,
                        system,
                        [spec],
                        client,
                        store_safe_drafts=store_safe_drafts,
                    )
                except LocalAIGenerationTimeout as item_exc:
                    if store_safe_drafts and generated:
                        _checkpoint_project(project)
                    raise LocalAIGenerationTimeout(
                        f"{item_exc} '{spec.label}' 항목에서 시간이 초과되었습니다. "
                        f"그 전까지 생성된 {len(generated)}개 문장은 저장했습니다."
                    ) from item_exc
                if summary and not profile_summary:
                    profile_summary = summary
                generated.extend(good)
                rejected.extend(bad)
                if store_safe_drafts and good:
                    _checkpoint_project(project)
            completed += 1
            continue

        if summary and not profile_summary:
            profile_summary = summary
        generated.extend(good)
        rejected.extend(bad)
        completed += 1
        if store_safe_drafts and good:
            _checkpoint_project(project)
        report("done", batch)

    return BatchedAIDraftPackResult(
        system=system,
        system_label=core.SYSTEM_LABELS[system],
        profile_summary=profile_summary,
        generated=tuple(generated),
        rejected=tuple(rejected),
        skipped_requirement_keys=skipped,
        model=getattr(client, "model", "로컬 AI"),
        completed_batches=completed,
        total_batches=len(batches),
    )


# Resilient drop-in for ai_drafting.generate_system_ai_drafts: small-batch
# generation with checkpointing and tolerant JSON-shape parsing instead of
# one large single-shot call.
generate_system_ai_drafts = generate_system_ai_drafts_batched
