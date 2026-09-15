from __future__ import annotations

"""Make Stage 5 local-AI drafting visibly progress one item at a time.

The page groups UI work in threes, but the underlying resilient generator can
still process those three items in one long model call.  On ordinary Windows
PCs that leaves the progress bar at 0/N until the first large response returns.
This runtime keeps the same grounding and validation rules while forcing one
requirement per local-model call and surfacing progress before and after each
item.
"""

from dataclasses import replace
import re
from typing import Any

from . import local_ai_resilience as resilience


WRAPPER_MARKER = "_ai_live_progress_runtime_wrapper"
_PROGRESS_RE = re.compile(r"^0/(\d+)개\s*·\s*준비 중$")
_active: dict[str, Any] = {"bar": None, "total": 0, "done": 0}


def install_ai_live_progress_runtime() -> None:
    if bool(getattr(resilience, "_ai_live_progress_runtime_installed", False)):
        return

    # One requirement per call keeps each JSON response compact and lets every
    # completed item be checkpointed independently.
    resilience.recommended_batch_size = lambda _model_name: 1

    original_select = resilience.select_fast_auto_config
    if not bool(getattr(original_select, WRAPPER_MARKER, False)):
        def select_fast_with_compact_output(config, available_models):
            selected = original_select(config, available_models)
            size = resilience._model_size_billion(selected.model)
            cap = 1200 if size is not None and size <= resilience.FAST_AUTO_MODEL_MAX_B else 1600
            return replace(selected, max_output_tokens=min(selected.max_output_tokens, cap))

        setattr(select_fast_with_compact_output, WRAPPER_MARKER, True)
        resilience.select_fast_auto_config = select_fast_with_compact_output

    original_process = resilience._process_one_batch
    if not bool(getattr(original_process, WRAPPER_MARKER, False)):
        def process_one_with_live_progress(project, system, specs, client, *, store_safe_drafts: bool):
            specs = list(specs)
            bar = _active.get("bar")
            total = int(_active.get("total") or 0)
            done = int(_active.get("done") or 0)
            label = getattr(specs[0], "label", "설명문") if specs else "설명문"
            if bar is not None and total > 0:
                next_no = min(total, done + 1)
                bar.progress(
                    min(1.0, done / total),
                    text=f"{done}/{total}개 완료 · {next_no}번째 '{label}' 정리 중",
                )
            result = original_process(
                project,
                system,
                specs,
                client,
                store_safe_drafts=store_safe_drafts,
            )
            if bar is not None and total > 0:
                done = min(total, done + max(1, len(specs)))
                _active["done"] = done
                bar.progress(min(1.0, done / total), text=f"{done}/{total}개 · 저장 완료")
            return result

        setattr(process_one_with_live_progress, WRAPPER_MARKER, True)
        resilience._process_one_batch = process_one_with_live_progress

    try:
        import streamlit as st

        original_progress = st.progress
        if not bool(getattr(original_progress, WRAPPER_MARKER, False)):
            def progress_capture(value, *args, **kwargs):
                text = str(kwargs.get("text") or "")
                bar = original_progress(value, *args, **kwargs)
                match = _PROGRESS_RE.match(text)
                if match:
                    _active.update(bar=bar, total=int(match.group(1)), done=0)
                return bar

            setattr(progress_capture, WRAPPER_MARKER, True)
            st.progress = progress_capture
    except Exception:
        pass

    resilience._ai_live_progress_runtime_installed = True
