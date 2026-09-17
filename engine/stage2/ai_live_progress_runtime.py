from __future__ import annotations

"""Surface Stage 5 local-AI drafting progress without disabling batching.

The resilient generator already chooses a model-appropriate batch size and
checkpoints successful batches. Earlier live-progress behavior forced one
requirement per model call, which made the progress bar smoother but multiplied
prompt-prefill and HTTP overhead. This runtime now observes each real batch
instead: progress moves after a checkpoint while the underlying 4B-8B/large
model batch-size policy remains intact.
"""

import re
from typing import Any

from . import local_ai_resilience as resilience


WRAPPER_MARKER = "_ai_live_progress_runtime_wrapper"
_PROGRESS_RE = re.compile(r"^0/(\d+)개\s*·\s*준비 중$")
_active: dict[str, Any] = {"bar": None, "total": 0, "done": 0}


def install_ai_live_progress_runtime() -> None:
    if bool(getattr(resilience, "_ai_live_progress_runtime_installed", False)):
        return

    original_process = resilience._process_one_batch
    if not bool(getattr(original_process, WRAPPER_MARKER, False)):
        def process_one_with_live_progress(project, system, specs, client, *, store_safe_drafts: bool):
            specs = list(specs)
            bar = _active.get("bar")
            total = int(_active.get("total") or 0)
            done = int(_active.get("done") or 0)
            labels = [str(getattr(spec, "label", "설명문") or "설명문") for spec in specs]
            if not labels:
                batch_label = "설명문"
            elif len(labels) == 1:
                batch_label = labels[0]
            else:
                batch_label = f"{labels[0]} 외 {len(labels) - 1}개"

            if bar is not None and total > 0:
                bar.progress(
                    min(1.0, done / total),
                    text=f"{done}/{total}개 완료 · '{batch_label}' 묶음 정리 중",
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
                bar.progress(min(1.0, done / total), text=f"{done}/{total}개 · 묶음 저장 완료")
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
