from __future__ import annotations

"""Runtime adapter for tolerant local-AI JSON response shapes.

Installed after ``local_ai_resilience`` so batched generation keeps its timeout,
checkpoint and retry behavior while accepting harmless JSON-shape variations
from local Qwen/Ollama models.
"""

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
    specs = list(specs)
    prompt, global_facts = core._build_pack_prompt(project, system, specs)
    raw = client.generate_json(instructions=core._system_prompt(system), prompt=prompt)
    raw_profile, draft_rows = normalize_draft_response(raw, specs)

    return core.build_pack_result_from_rows(
        project, system, specs, global_facts, raw_profile, draft_rows, client,
        store_safe_drafts=store_safe_drafts,
    )


def install_ai_response_runtime() -> None:
    if getattr(resilience, "_ai_response_runtime_installed", False):
        return
    resilience._process_one_batch = _process_one_batch_flexible
    resilience._ai_response_runtime_installed = True
