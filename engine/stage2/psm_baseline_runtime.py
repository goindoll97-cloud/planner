from __future__ import annotations

"""Expose the preserved PSM regulation-form baseline in Stage 5.

This runtime intentionally leaves the existing internal-review DOCX path intact.
It inserts a separate regulation-form download immediately before the PSM review
section, mirroring the CAP split between official-layout forms and review prose.
"""

WRAPPER_MARKER = "_psm_baseline_runtime_wrapper"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
_INSTALLED = False


def install_psm_baseline_runtime() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        import streamlit as st
        from . import psm_baseline_docx as baseline
        from .psm_baseline_docx import build_psm_baseline_draft, psm_baseline_filename
        from .storage import load_project
    except Exception:
        return

    # Reuse the already-established Stage 2 field used by the existing PSM
    # renderer. Keep legacy aliases only as fallback; never infer interlock data.
    baseline.LATER_FORM_FIELDS["17-2"] = (
        "psm.psi.interlock_conditions",
        "psm.psi.interlock_specs",
        "psm.psi.interlocks",
    )

    current_markdown = st.markdown
    current_download = st.download_button

    def render_psm_regulation_form() -> None:
        project_id = str(st.session_state.get(ACTIVE_PROJECT_KEY) or "").strip()
        if not project_id:
            return
        try:
            project = load_project(project_id)
        except Exception:
            return
        if not getattr(project, "psm_in_scope", False):
            return

        current_markdown("### 공정안전보고서 · 규정서식 작성본")
        st.caption(
            "규정서식 baseline의 표·병합셀·글꼴·페이지 구성을 유지하고, 4단계까지 확인된 회사자료만 해당 칸에 입력합니다. "
            "확인되지 않은 값은 추정하지 않고 빈칸으로 둡니다."
        )
        try:
            data = build_psm_baseline_draft(project)
        except Exception as exc:
            st.error(f"공정안전보고서 규정서식 작성본을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
            return

        current_download(
            "공정안전보고서 규정서식 작성본 DOCX 다운로드",
            data=data,
            file_name=psm_baseline_filename(project),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"download_psm_regulation_form_{project_id}",
            width="stretch",
            type="primary",
        )

    def markdown_with_psm_baseline(body, *args, **kwargs):
        text = str(body or "")
        if text == "### 공정안전보고서 · 내부 검토용":
            render_psm_regulation_form()
        return current_markdown(body, *args, **kwargs)

    setattr(markdown_with_psm_baseline, WRAPPER_MARKER, True)
    st.markdown = markdown_with_psm_baseline
    _INSTALLED = True
