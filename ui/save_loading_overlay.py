"""Shared accessible full-screen loader for the entire multipage Streamlit app.

The app-level loader spans each navigation run. A more specific loader may
replace the message for an individual save/recalculation. The placeholder is
always cleared when work completes, on errors and during Streamlit reruns.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from html import escape

import streamlit as st


_OVERLAY = """
<style>
@keyframes cap-stage3-save-spin {
    to { transform: rotate(360deg); }
}
.cap-stage3-save-overlay {
    position: fixed;
    inset: 0;
    z-index: 2147483000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: rgba(15, 23, 42, 0.46);
    backdrop-filter: blur(2px);
}
.cap-stage3-save-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.9rem;
    width: min(90vw, 380px);
    padding: 2.25rem 1.5rem;
    border-radius: 16px;
    background: #ffffff;
    color: #1e293b;
    box-shadow: 0 18px 56px rgba(15, 23, 42, 0.24);
    text-align: center;
    font-family: sans-serif;
}
.cap-stage3-save-wheel {
    width: 54px;
    height: 54px;
    border: 5px solid #dbeafe;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: cap-stage3-save-spin 0.85s linear infinite;
}
.cap-stage3-save-title,
.cap-stage3-save-description {
    word-break: keep-all;
    overflow-wrap: break-word;
    text-wrap: balance;
}
.cap-stage3-save-title {
    font-size: 1.12rem;
    font-weight: 700;
}
.cap-stage3-save-description {
    font-size: 0.91rem;
    color: #475569;
    line-height: 1.5;
}
@media (prefers-reduced-motion: reduce) {
    .cap-stage3-save-wheel { animation: none; border-color: #2563eb; }
}
</style>
<div class="cap-stage3-save-overlay">
    <div class="cap-stage3-save-card" role="status" aria-live="polite" aria-busy="true">
        <div class="cap-stage3-save-wheel" aria-hidden="true"></div>
        <div class="cap-stage3-save-title">보호대상 정보를 저장하고 있습니다</div>
        <div class="cap-stage3-save-description">저장된 내용을 확인하고 사고시나리오를 다시 계산합니다.</div>
    </div>
</div>
"""


DEFAULT_TITLE = "작업을 처리하고 있습니다"
DEFAULT_DESCRIPTION = "화면을 불러오거나 입력 내용을 저장·계산하고 있습니다."


@contextmanager
def app_loading(
    title: str = DEFAULT_TITLE,
    description: str = DEFAULT_DESCRIPTION,
) -> Iterator[None]:
    """Show the same centered loader for every app page's script execution.

    The incoming values are plain text; escape them before interpolating into
    the HTML template. Streamlit's navigation and nested widget callbacks may
    raise rerun/stop exceptions, so always clear the placeholder in finally.
    """
    html = (_OVERLAY
            .replace("보호대상 정보를 저장하고 있습니다", escape(title))
            .replace("저장된 내용을 확인하고 사고시나리오를 다시 계산합니다.", escape(description)))
    placeholder = st.empty()
    placeholder.markdown(html, unsafe_allow_html=True)
    try:
        yield
    finally:
        placeholder.empty()


@contextmanager
def scenario_save_loading() -> Iterator[None]:
    """Keep the existing Stage ③-specific wording within the shared design."""
    with app_loading(
        "보호대상 정보를 저장하고 있습니다",
        "저장된 내용을 확인하고 사고시나리오를 다시 계산합니다.",
    ):
        yield
