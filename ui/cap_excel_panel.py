from __future__ import annotations

"""기존 통합 작성자료(엑셀) 가져오기: 이미 엑셀로 정리해 둔 회사 자료를 한 번에 반영한다."""

import streamlit as st

from engine.stage2.integrated_workbook import apply_integrated_authoring_workbook
from engine.stage2.storage import save_attachment, save_project
from engine.stage2.workbook_enhancements import build_enhanced_integrated_authoring_workbook
from engine.stage2.workflow import reset_after_intake_change


def render(project) -> None:
    with st.expander("엑셀로 한 번에 입력하기 (기존 통합 작성자료)"):
        st.caption(
            "이미 엑셀로 정리한 회사 자료가 있으면 여기서 한 번에 반영할 수 있습니다. 반영한 시설·물질 자료는 아래 별지 화면의 "
            "시설 표와 물질 목록에 미리 채워집니다. 엑셀이 없으면 이 칸은 건너뛰고 별지 화면에서 바로 입력하세요."
        )
        left, right = st.columns(2)
        left.download_button(
            "통합 작성자료.xlsx 내려받기",
            data=build_enhanced_integrated_authoring_workbook(project, example=False),
            file_name=f"{project.project_id}_통합_작성자료.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"cap_excel_download_{project.project_id}",
        )
        right.download_button(
            "작성예시.xlsx 내려받기",
            data=build_enhanced_integrated_authoring_workbook(project, example=True),
            file_name=f"{project.project_id}_통합_작성자료_작성예시.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"cap_excel_example_{project.project_id}",
        )
        upload = st.file_uploader("작성 완료한 통합 작성자료 Excel", type=["xlsx"], key=f"cap_excel_upload_{project.project_id}")
        if upload is not None and st.button("엑셀 자료 반영", type="primary", key=f"cap_excel_apply_{project.project_id}"):
            raw = upload.getvalue()
            try:
                reference = save_attachment(project.project_id, upload.name, raw, source_type="STAGE2_INTEGRATED_WORKBOOK",
                                            note="회사 작성 통합 작성자료 Excel")
                result = apply_integrated_authoring_workbook(project, raw, workbook_evidence=reference)
                reset_after_intake_change(project)
                save_project(project)
            except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 그대로 보여 준다
                st.error(f"엑셀 자료를 반영하지 못했습니다: {type(exc).__name__}: {exc}")
            else:
                st.success(f"입력·확인 {result.updated_fields}개 항목, 구조화 표 {result.table_fields}개를 반영했습니다.")
                for warning in result.warnings:
                    st.warning(warning)
                st.rerun()
