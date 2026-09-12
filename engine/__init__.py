"""Core modules for the chemical safety planning assistant."""

from __future__ import annotations

from pathlib import Path


def _install_company_input_guide_hook() -> None:
    """Place the filled-in guide workbook immediately above the main Browse box.

    The simplified diagnosis page already calls ``st.file_uploader`` directly.
    Wrapping that single label lets the guide stay physically next to the upload
    control without changing the diagnosis logic. Other uploaders are untouched.
    """
    try:
        import streamlit as st
    except Exception:
        return

    original = st.file_uploader
    if getattr(original, "_planner_company_guide_wrapped", False):
        return

    project_root = Path(__file__).resolve().parents[1]
    guide_path = project_root / "assets" / "PSM_CAP_회사입력_작성예시_가이드_v0.8.xlsx"

    def guided_file_uploader(*args, **kwargs):
        label = kwargs.get("label")
        if label is None and args:
            label = args[0]
        label_text = str(label or "")

        if label_text.startswith("회사 입력파일 업로드"):
            st.markdown("#### 처음 작성하시나요? 작성예시 파일을 먼저 내려받아 보세요")
            st.caption(
                "실제 회사가 작성한 것처럼 예시값이 채워져 있습니다. 연한 노란색 입력칸을 회사 값으로 바꾸고, "
                "선택형 항목이 적용되지 않으면 '해당없음', 아직 확인하지 못했으면 '모름'을 선택하세요."
            )
            if guide_path.exists():
                st.download_button(
                    "회사 입력 작성예시·가이드 파일 다운로드",
                    data=guide_path.read_bytes(),
                    file_name="PSM_CAP_회사입력_작성예시_가이드_v0.8.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="company_input_guide_download_v08",
                    use_container_width=True,
                )
            else:
                st.warning("작성예시 파일을 찾지 못했습니다. 관리자에게 가이드 파일 배포상태를 확인해 주세요.")

        return original(*args, **kwargs)

    guided_file_uploader._planner_company_guide_wrapped = True
    st.file_uploader = guided_file_uploader


_install_company_input_guide_hook()
