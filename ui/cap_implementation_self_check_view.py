from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_implementation_self_check as impl
from engine.stage2 import versioning
from engine.stage2.storage import save_project


def _text(project, key: str) -> str:
    rec = project.get_field(key)
    return "" if rec is None or rec.value is None else str(rec.value)


def _people_frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=impl.PERSON_COLUMNS)


def render(project) -> None:
    st.header("이행점검 · 자체점검")
    st.caption(
        "적합통보를 받은 화학사고예방관리계획서의 이행 여부를 자체점검하고, "
        "이행규정 별지 제1호부터 제3호까지 작성합니다. "
        "기존 사업장 정보는 재사용하고 점검에 새로 필요한 사실만 입력합니다."
    )

    versions = versioning.list_versions(project.project_id, "CAP")
    if not versions:
        st.warning("기준으로 삼을 CAP 제출본 버전이 없습니다. 먼저 버전 관리에서 적합·제출 당시 자료를 버전으로 저장해 주세요.")
        return

    header = impl.header_values(project)
    version_ids = [meta.version_id for meta in versions]
    saved_base = header.get("기준 버전", "")
    base = st.selectbox(
        "자체점검 기준 적합·제출본",
        version_ids,
        index=version_ids.index(saved_base) if saved_base in version_ids else len(version_ids) - 1,
        key=f"cap_impl_base_{project.project_id}",
        help="이전 적합·제출본을 기준으로 현재 이행상태를 점검합니다. 프로그램이 적합 여부를 임의로 판단하지 않습니다.",
    )

    st.markdown("### 1. 자체점검 결과서 기본정보")
    c1, c2 = st.columns(2)
    target_process = c1.text_input(
        "대상 공정",
        value=header.get("대상 공정", ""),
        key=f"cap_impl_process_{project.project_id}",
    )
    workplace_no = c2.text_input(
        "사업장등록번호",
        value=header.get("사업장등록번호", ""),
        key=f"cap_impl_regno_{project.project_id}",
        help="별지 제1호의 '사업장등록번호'입니다. 사업자등록번호와 동일하다고 추정하지 않습니다.",
    )
    c3, c4 = st.columns(2)
    permit_type = c3.text_input(
        "영업허가 구분",
        value=header.get("영업허가 구분", ""),
        key=f"cap_impl_permit_{project.project_id}",
    )
    ksic = c4.text_input(
        "표준산업분류(업종번호)",
        value=header.get("표준산업분류(업종번호)", ""),
        disabled=True,
        help="회사 기본정보의 KSIC 값을 재사용합니다. 비어 있으면 기본정보에서 확인해 주세요.",
    )

    d1, d2, d3 = st.columns(3)
    period_start = d1.text_input(
        "자체점검 시작일",
        value=header.get("자체점검 시작일", ""),
        key=f"cap_impl_start_{project.project_id}",
        placeholder="YYYY-MM-DD",
    )
    period_end = d2.text_input(
        "자체점검 종료일",
        value=header.get("자체점검 종료일", ""),
        key=f"cap_impl_end_{project.project_id}",
        placeholder="YYYY-MM-DD",
    )
    report_date = d3.text_input(
        "결과서 제출일",
        value=header.get("제출일", ""),
        key=f"cap_impl_report_{project.project_id}",
        placeholder="YYYY-MM-DD",
        help="실제 제출일을 확인해 입력합니다. 오늘 날짜를 자동 확정하지 않습니다.",
    )

    st.markdown("#### 자체점검반")
    team_edit = st.data_editor(
        _people_frame(impl.self_check_team(project)),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"cap_impl_team_{project.project_id}",
    )
    st.markdown("#### 사업장 확인자")
    confirmer_edit = st.data_editor(
        _people_frame(impl.confirmers(project)),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"cap_impl_confirmers_{project.project_id}",
    )

    if st.button("기본정보·점검반 저장", type="primary", key=f"cap_impl_header_save_{project.project_id}"):
        impl.save_header(project, {
            impl.BASE_VERSION_KEY: base,
            "cap.implementation.target_process": target_process,
            "cap.implementation.workplace_registration_no": workplace_no,
            "cap.implementation.business_permit_type": permit_type,
            "cap.implementation.period_start": period_start,
            "cap.implementation.period_end": period_end,
            "cap.implementation.report_date": report_date,
        })
        impl.save_people(project, impl.TEAM_KEY, "자체점검반", team_edit.to_dict("records"))
        impl.save_people(project, impl.CONFIRMER_KEY, "사업장 확인자", confirmer_edit.to_dict("records"))
        save_project(project)
        st.success("자체점검 기본정보를 저장했습니다.")
        st.rerun()

    st.markdown("### 2. 별지 제2호 자체점검표")
    st.caption(
        "확인: 점검 결과 이행이 확인된 항목 / 개선필요: 조치가 필요한 항목 / "
        "해당없음: 사업장에 해당하지 않는 항목. 비워 둔 항목은 미확인으로 남습니다."
    )
    rows = impl.checklist_rows(project)
    frame = pd.DataFrame(rows)
    display_cols = ["id", "section", "category", "no", "detail", "check", "status", "note"]
    edited = st.data_editor(
        frame[display_cols],
        column_config={
            "id": st.column_config.TextColumn("ID", disabled=True),
            "section": st.column_config.TextColumn("구분", disabled=True),
            "category": st.column_config.TextColumn("항목", disabled=True),
            "no": st.column_config.TextColumn("연번", disabled=True),
            "detail": st.column_config.TextColumn("세부항목", disabled=True),
            "check": st.column_config.TextColumn("확인할 항목", disabled=True, width="large"),
            "status": st.column_config.SelectboxColumn("확인", options=list(impl.CHECK_STATUSES), required=False),
            "note": st.column_config.TextColumn("점검메모·근거", width="large"),
        },
        hide_index=True,
        width="stretch",
        key=f"cap_impl_checklist_{project.project_id}",
    )
    if st.button("자체점검표 저장", type="primary", key=f"cap_impl_check_save_{project.project_id}"):
        count = impl.save_checklist(project, edited.to_dict("records"))
        save_project(project)
        st.success(f"자체점검 {count}개 항목을 저장했습니다.")
        st.rerun()

    state = impl.readiness(project)
    m1, m2, m3 = st.columns(3)
    m1.metric("점검 완료", f"{state.checked}/{state.total}")
    m2.metric("개선 필요", state.improvements_required)
    m3.metric("개선조치 완료", f"{state.improvements_completed}/{state.improvements_required}")

    st.markdown("### 3. 별지 제3호 개선사항 조치 내역")
    improvement_rows = impl.proposed_improvements(project)
    if not improvement_rows:
        st.success("현재 '개선필요'로 표시된 자체점검 항목이 없습니다.")
        improvement_edit = pd.DataFrame(columns=["_check_id", *impl.IMPROVEMENT_COLUMNS])
    else:
        improvement_frame = pd.DataFrame(improvement_rows)
        improvement_edit = st.data_editor(
            improvement_frame[["_check_id", *impl.IMPROVEMENT_COLUMNS]],
            column_config={
                "_check_id": st.column_config.TextColumn("점검ID", disabled=True),
                "연번": st.column_config.TextColumn("연번", disabled=True),
                "자체점검결과 개선사항": st.column_config.TextColumn("자체점검결과 개선사항", width="large"),
                "조치결과": st.column_config.TextColumn("조치결과", width="large"),
                "조치일자": st.column_config.TextColumn("조치일자"),
                "책임부서 (담당자)": st.column_config.TextColumn("책임부서 (담당자)"),
                "확인자": st.column_config.TextColumn("확인자"),
                "서명": st.column_config.TextColumn("서명"),
            },
            hide_index=True,
            width="stretch",
            key=f"cap_impl_improvements_{project.project_id}",
        )
        if st.button("개선조치 내역 저장", type="primary", key=f"cap_impl_improve_save_{project.project_id}"):
            impl.save_improvements(project, improvement_edit.to_dict("records"))
            save_project(project)
            st.success("개선조치 내역을 저장했습니다.")
            st.rerun()

    st.markdown("### 4. 점검 결과 및 출력")
    state = impl.readiness(project)
    if state.ready:
        st.success("자체점검 별지 1~3호의 필수 확인사항이 완료되었습니다.")
    else:
        st.warning("아직 자체점검 완료로 볼 수 없는 항목이 있습니다.")
        for blocker in state.blockers:
            st.write(f"• {blocker}")

    if impl.is_major_facility(project):
        st.info(
            "이 사업장은 1군(주요취급시설)로 확인되어, 자체점검 결과와 함께 "
            "작성 규정 별지 제2호 '변경내역 관리대장'도 확인해야 합니다. "
            "기존 CAP 별지 제2호 자료를 그대로 재사용합니다."
        )
    else:
        st.caption("현재 CAP 작성수준에서는 주요취급시설 연간 제출용 변경내역 관리대장을 추가 필수로 적용하지 않습니다.")

    if state.ready:
        st.download_button(
            "자체점검 제출패키지 ZIP 내려받기",
            data=impl.build_submission_package(project),
            file_name=impl.submission_package_filename(project),
            mime="application/zip",
            key=f"cap_impl_package_{project.project_id}",
            width="stretch",
            type="primary",
        )

    try:
        st.download_button(
            "이행규정 별지 제1호 자체점검 결과서",
            data=impl.build_form1_docx(project),
            file_name=impl.form_filename(project, 1),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"cap_impl_dl1_{project.project_id}",
            width="stretch",
        )
    except Exception as exc:
        st.caption(f"별지 제1호: {exc}")

    try:
        st.download_button(
            "이행규정 별지 제2호 자체점검표",
            data=impl.build_form2_docx(project),
            file_name=impl.form_filename(project, 2),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"cap_impl_dl2_{project.project_id}",
            width="stretch",
        )
    except Exception as exc:
        st.caption(f"별지 제2호: {exc}")

    try:
        st.download_button(
            "이행규정 별지 제3호 개선사항 조치 내역서",
            data=impl.build_form3_docx(project),
            file_name=impl.form_filename(project, 3),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"cap_impl_dl3_{project.project_id}",
            width="stretch",
        )
    except Exception as exc:
        st.caption(f"별지 제3호: {exc}")
