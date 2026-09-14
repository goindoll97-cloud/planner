from __future__ import annotations

"""Runtime adapter for tolerant local-AI JSON response shapes.

Installed after ``local_ai_resilience`` so batched generation keeps its timeout,
checkpoint and retry behavior while accepting harmless JSON-shape variations
from local Qwen/Ollama models.
"""

from typing import Mapping

from . import ai_drafting as core
from . import local_ai_resilience as resilience
from .ai_response_normalizer import normalize_draft_response


def _process_one_batch_flexible(
    project,
    system: str,
    specs,
    client,
    *,
    store_safe_drafts: bool,
):
    prompt, global_facts = core._build_pack_prompt(project, system, list(specs))
    raw = client.generate_json(instructions=core._system_prompt(system), prompt=prompt)
    raw_profile, draft_rows = normalize_draft_response(raw, specs)
    profile_summary = core.normalize_public_prose(str(raw_profile or "").strip(), system)
    if core.validate_public_prose(profile_summary, system):
        profile_summary = ""

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


def install_ai_response_runtime() -> None:
    if getattr(resilience, "_ai_response_runtime_installed", False):
        return
    resilience._process_one_batch = _process_one_batch_flexible
    resilience._ai_response_runtime_installed = True
