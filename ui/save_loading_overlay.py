"""Centered accessible loading indicator for Stage ③ protected-target saves.

A full-screen overlay makes a long-running save/recalculation visible in the
page itself. It is shown only after the user submits the batch form, and is
removed even if processing raises an exception or triggers Streamlit rerun.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

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


@contextmanager
def scenario_save_loading() -> Iterator[None]:
    """Render the full-screen spinner while Step ③ saves and recalculates."""
    placeholder = st.empty()
    placeholder.markdown(_OVERLAY, unsafe_allow_html=True)
    try:
        yield
    finally:
        placeholder.empty()
