from __future__ import annotations

"""Runtime hardening for local report drafting on ordinary Windows PCs.

The original Stage 2 AI path sent every eligible report item in one request and
allowed up to 12,000 output tokens with a 180 second read timeout.  A 14B Ollama
model can legitimately exceed that limit even though the server and model are
healthy.  This module keeps the same local-only/fact-grounded drafting rules but
uses smaller batches, a longer read window, bounded output, Ollama non-thinking
mode, and checkpoint saves after each successful batch.

It is installed once from ``app.py`` before Streamlit loads the selected page,
so existing imports and tests remain compatible.
"""

from dataclasses import dataclass, replace
import math
import re
from typing import Any, Mapping, Sequence

import requests

from . import ai_drafting as core
from . import local_llm


DEFAULT_LOCAL_AI_TIMEOUT_SECONDS = 600
DEFAULT_LOCAL_AI_MAX_OUTPUT_TOKENS = 3000
DEFAULT_LOCAL_AI_BATCH_SIZE = 3
OLLAMA_KEEP_ALIVE = "15m"


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
    # Prefer the largest model that is still smaller: quality before raw speed.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return tuple(name for _, name in candidates[:4])


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
                    # Qwen3-class models can spend a substantial amount of time
                    # in reasoning mode.  For grounded form drafting we need
                    # deterministic prose, not long hidden reasoning.
                    "think": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_predict": self.config.max_output_tokens,
                        "temperature": 0.1,
                    },
                },
                # Separate connect/read timeouts: connection problems fail fast,
                # while local 14B generation is allowed enough time to finish.
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


def _resilient_config_from_sources(values: Mapping[str, Any] | None = None) -> local_llm.LocalLLMConfig:
    config = _ORIGINAL_CONFIG_FROM_SOURCES(values)
    # An explicitly lower output cap remains respected.  Large legacy/default
    # caps are reduced because report drafting is now performed in small batches.
    return replace(
        config,
        timeout_seconds=max(config.timeout_seconds, DEFAULT_LOCAL_AI_TIMEOUT_SECONDS),
        max_output_tokens=min(config.max_output_tokens, DEFAULT_LOCAL_AI_MAX_OUTPUT_TOKENS),
    )


def _resilient_build_client(config: local_llm.LocalLLMConfig):
    local_llm.validate_local_base_url(config.base_url)
    probe = local_llm.probe_local_llm_runtime(config)
    if not probe.ready:
        raise ValueError(local_llm.local_runtime_not_ready_message(config, probe))
    if config.provider == "ollama":
        return ResilientOllamaLocalClient(config, available_models=probe.models)
    if config.provider == "openai_compatible":
        # LM Studio/llama.cpp receives the same longer timeout and bounded token
        # config; its standard local-only client is otherwise retained.
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
    prompt, global_facts = core._build_pack_prompt(project, system, list(specs))
    raw = client.generate_json(instructions=core._system_prompt(system), prompt=prompt)
    profile_summary = core.normalize_public_prose(str(raw.get("profile_summary") or "").strip(), system)
    if core.validate_public_prose(profile_summary, system):
        profile_summary = ""

    draft_rows = raw.get("drafts")
    if not isinstance(draft_rows, list):
        raise ValueError("로컬 AI 응답에 문장 배열이 없습니다.")

    spec_map = {spec.key: spec for spec in specs}
    generated: list[core.AIDraftItem] = []
    rejected: list[core.AIDraftItem] = []
    seen: set[str] = set()

    for row in draft_rows:
        if not isinstance(row, Mapping):
            continue
        requirement_key = str(row.get("requirement_key") or "").strip()
        spec = spec_map.get(requirement_key)
        if spec is None or requirement_key in seen:
            continue
        seen.add(requirement_key)

        draft_text = core.normalize_public_prose(str(row.get("draft_text") or "").strip(), system)
        suggestions = core._normalize_suggestions(row.get("suggested_additions"), system)
        used_fact_keys = core._normalize_fact_keys(row.get("used_fact_keys"))
        warnings: list[str] = []
        if not draft_text:
            warnings.append("로컬 AI가 본문 초안을 반환하지 않았습니다.")

        allowed_keys = set(global_facts)
        unknown_keys = sorted(key for key in used_fact_keys if key not in allowed_keys)
        if unknown_keys:
            warnings.append("확인되지 않은 내부 사실키를 참조함: " + ", ".join(unknown_keys[:8]))

        source = core._source_corpus(project, spec, global_facts)
        warnings.extend(core._unsupported_tokens(draft_text, source))
        warnings.extend(core._language_warnings(draft_text, system, "보고서 문장"))
        for suggestion in suggestions:
            warnings.extend(core._language_warnings(suggestion, system, "추가 확인 제안"))

        item = core.AIDraftItem(
            system=system,
            requirement_key=spec.key,
            section=spec.section,
            label=spec.label,
            draft_text=draft_text,
            profile_summary=profile_summary,
            suggested_additions=suggestions,
            used_fact_keys=used_fact_keys,
            legal_basis=spec.legal_basis,
            model=getattr(client, "model", "로컬 AI"),
            validation_warnings=tuple(dict.fromkeys(warnings)),
        )
        if item.safe_to_store:
            generated.append(item)
            if store_safe_drafts:
                core.store_ai_draft(project, item)
        else:
            rejected.append(item)

    return profile_summary, generated, rejected


def _checkpoint_project(project) -> None:
    # Import lazily to avoid coupling the reusable drafting engine to storage at
    # import time.  A successful batch is persisted before the next slow call.
    from .storage import save_project

    save_project(project)


def generate_system_ai_drafts_batched(
    project,
    system: str,
    client,
    *,
    store_safe_drafts: bool = True,
    batch_size: int = DEFAULT_LOCAL_AI_BATCH_SIZE,
) -> BatchedAIDraftPackResult:
    system = core._normalize_system(system)
    specs = core.ai_draftable_specs(project, system)
    all_system_specs = [spec for spec in core.selected_requirement_specs(project) if spec.system == system]
    skipped = tuple(spec.key for spec in all_system_specs if spec not in specs)
    if not specs:
        raise ValueError("AI 문장 보강에 사용할 확인된 회사 사실이 없습니다.")

    batches = _chunks(specs, batch_size)
    generated: list[core.AIDraftItem] = []
    rejected: list[core.AIDraftItem] = []
    profile_summary = ""
    completed = 0

    for batch_index, batch in enumerate(batches, 1):
        try:
            summary, good, bad = _process_one_batch(
                project,
                system,
                batch,
                client,
                store_safe_drafts=store_safe_drafts,
            )
        except LocalAIGenerationTimeout as batch_exc:
            # A large batch can time out on CPU/RAM-bound 14B models. Retry the
            # same work one requirement at a time before giving up.
            if len(batch) <= 1:
                if store_safe_drafts and (generated or rejected):
                    _checkpoint_project(project)
                raise LocalAIGenerationTimeout(
                    f"{batch_exc} 현재 {completed}/{len(batches)}개 배치는 완료되어 저장되었습니다. "
                    "같은 버튼을 다시 누르면 남은 항목을 다시 시도할 수 있습니다."
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


_ORIGINAL_CONFIG_FROM_SOURCES = local_llm.local_llm_config_from_sources
_ORIGINAL_BUILD_CLIENT = local_llm.build_local_llm_client
_ORIGINAL_GENERATE_SYSTEM_DRAFTS = core.generate_system_ai_drafts


def install_local_ai_resilience() -> None:
    """Install the resilient runtime once, before Streamlit page imports."""
    if getattr(local_llm, "_local_ai_resilience_installed", False):
        return
    local_llm.local_llm_config_from_sources = _resilient_config_from_sources
    local_llm.build_local_llm_client = _resilient_build_client
    core.generate_system_ai_drafts = generate_system_ai_drafts_batched
    local_llm._local_ai_resilience_installed = True
