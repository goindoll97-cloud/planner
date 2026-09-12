"""Core modules for the chemical safety planning assistant."""

from __future__ import annotations


def _install_company_input_guide_hook() -> None:
    """Attach the canonical generated example/guide workbook to the main uploader.

    The workbook is generated from ``engine.template`` at download time instead
    of being stored as a separate static XLSX.  This keeps the guide structure
    identical to the example/input template and prevents future version drift.
    """
    try:
        import streamlit as st
    except Exception:
        return

    original = st.file_uploader
    if getattr(original, "_planner_company_guide_wrapped", False):
        return

    def guided_file_uploader(*args, **kwargs):
        label = kwargs.get("label")
        if label is None and args:
            label = args[0]
        label_text = str(label or "")

        if label_text.startswith("회사 입력파일 업로드"):
            from .template import build_minimal_input_workbook

            st.markdown("#### 처음 작성하시나요? 최신 작성예시·가이드 파일을 먼저 내려받아 보세요")
            st.caption(
                "판정진단에서 사용하는 최신 회사 입력 구조와 완전히 동일한 파일입니다. "
                "초록색 예시값을 참고하고, 노란색 빈 입력칸에는 귀사 정보를 입력하세요. "
                "선택형 항목이 적용되지 않으면 '해당없음', 아직 확인하지 못했으면 '모름'을 선택하세요."
            )
            st.download_button(
                "회사 입력 작성예시·가이드 파일 다운로드",
                data=build_minimal_input_workbook(),
                file_name="PSM_CAP_회사입력_작성예시_가이드_v1.0.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="company_input_guide_download_v10",
                width="stretch",
            )

        return original(*args, **kwargs)

    guided_file_uploader._planner_company_guide_wrapped = True
    st.file_uploader = guided_file_uploader


_install_company_input_guide_hook()
