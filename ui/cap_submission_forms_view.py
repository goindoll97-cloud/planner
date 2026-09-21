from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_submission_forms as forms
from engine.stage2 import cap_change_tracking as changes
from engine.stage2 import cap_form2_workspace as form2
from engine.stage2 import versioning
from engine.stage2.storage import save_project


def _field(project, key: str) -> str:
    rec = project.get_field(key)
    return "" if rec is None or rec.value is None else str(rec.value)


def _versions(project) -> list[str]:
    return [meta.version_id for meta in versioning.list_versions(project.project_id, "CAP")]


def _history_rows(project) -> list[dict]:
    rec = project.get_field("cap.submission.change_history")
    if rec is None or not isinstance(rec.value, list):
        return []
    return [dict(row) for row in rec.value if isinstance(row, dict)]


def _mapping(project, key: str) -> dict:
    rec = project.get_field(key)
    return dict(rec.value) if rec is not None and isinstance(rec.value, dict) else {}


def render(project) -> None:
    st.header("제출·변경 행정서식")
    st.caption(
        "화학물질관리법 시행규칙 별지 제31호·제32호를 작성합니다. "
        "회사정보는 기존 입력값을 재사용하고, 제출 단계에서 새로 필요한 값만 입력합니다. "
        "변경점 자동분류는 작성 편의를 위한 후보이며 저장 전 담당자가 확인합니다."
    )

    submission_rec = project.get_field("cap.business.submission_type")
    submission_type = str(submission_rec.value if submission_rec else "")
    st.info(f"현재 제출구분: **{submission_type or '미확정'}**")

    common = forms.form31_values(project)
    c1, c2 = st.columns(2)
    method = c1.selectbox(
        "제출방법",
        ("", "화학물질 종합정보시스템", "서면"),
        index=("", "화학물질 종합정보시스템", "서면").index(common.get("제출방법", ""))
        if common.get("제출방법", "") in ("", "화학물질 종합정보시스템", "서면") else 0,
        key=f"cap_submit_method_{project.project_id}",
    )
    permit = c2.selectbox(
        "영업허가 대상 여부",
        ("", "대상", "비대상"),
        index=("", "대상", "비대상").index(common.get("영업허가 대상", ""))
        if common.get("영업허가 대상", "") in ("", "대상", "비대상") else 0,
        key=f"cap_submit_permit_{project.project_id}",
    )

    tabs = st.tabs(["별지 제31호 · 검토신청서", "별지 제32호 · 변경 검토신청서"])

    with tabs[0]:
        st.caption("신규제출·재제출·5년 재제출·부적합 후 재제출·이행점검 부적정 재제출에 사용합니다.")
        office = st.text_input(
            "관할 유역(지방)환경관서",
            value=common.get("관할 유역(지방)환경관서", ""),
            key=f"cap31_office_{project.project_id}",
        )
        center = st.text_input(
            "관할 합동방재센터",
            value=common.get("관할 합동방재센터", ""),
            key=f"cap31_center_{project.project_id}",
        )
        skip = st.selectbox(
            "제19조의2제2항에 따른 검토생략 대상",
            ("", "안전성향상계획", "공정안전보고서", "미해당"),
            index=("", "안전성향상계획", "공정안전보고서", "미해당").index(common.get("검토생략 대상", ""))
            if common.get("검토생략 대상", "") in ("", "안전성향상계획", "공정안전보고서", "미해당") else 0,
            key=f"cap31_skip_{project.project_id}",
        )
        application_date = st.text_input(
            "신청일",
            value=common.get("신청일", ""),
            key=f"cap31_date_{project.project_id}",
            help="실제 제출일을 확인해 입력합니다. 현재 날짜를 자동 확정하지 않습니다.",
        )
        if st.button("별지 제31호 제출정보 저장", key=f"cap31_save_{project.project_id}", type="primary"):
            forms.save_submission_values(project, {
                "cap.submission.method": method,
                "cap.submission.business_permit": permit,
                "cap.submission.office": office,
                "cap.submission.center": center,
                "cap.submission.review_skip": skip,
                "cap.submission.form31.application_date": application_date,
            })
            save_project(project)
            st.success("별지 제31호 제출정보를 저장했습니다.")
            st.rerun()

        r31 = forms.form31_readiness(project)
        if r31.ready:
            st.success("별지 제31호 작성에 필요한 값이 확인되었습니다.")
            st.download_button(
                "별지 제31호 DOCX 내려받기",
                data=forms.build_form31_docx(project),
                file_name=forms.form31_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap31_download_{project.project_id}",
                width="stretch",
            )
        else:
            st.warning("별지 제31호 보완 필요")
            for blocker in r31.blockers:
                st.write(f"• {blocker}")

    with tabs[1]:
        st.caption(
            "변경제출에서 사용합니다. 이전 제출본과 현재 작업본을 비교해 뒤쪽 변경사항 상세내용과 "
            "변경내역 관리대장 후보를 자동 생성합니다."
        )
        versions = _versions(project)
        if not versions:
            st.warning("저장된 CAP 제출 버전이 없습니다. 먼저 버전 관리에서 기존 제출본을 v1.0 등으로 저장해야 합니다.")
            return

        current32 = forms.form32_values(project)
        saved_base = str(current32.get("비교 기준 버전") or "")
        base = st.selectbox(
            "비교 기준 제출본",
            versions,
            index=versions.index(saved_base) if saved_base in versions else max(0, len(versions) - 1),
            key=f"cap32_base_{project.project_id}",
        )
        final_no = st.text_input(
            "(최종) 적합통보 번호",
            value=str(current32.get("(최종) 적합통보 번호") or ""),
            key=f"cap32_final_no_{project.project_id}",
        )
        final_date = st.text_input(
            "(최종) 적합통보 일자",
            value=str(current32.get("(최종) 적합통보 일자") or ""),
            key=f"cap32_final_date_{project.project_id}",
        )
        reason_type = st.selectbox(
            "변경사항",
            ("", "사업장 구분 변경", "그 밖의 사유"),
            index=("", "사업장 구분 변경", "그 밖의 사유").index(str(current32.get("변경사유 구분") or ""))
            if str(current32.get("변경사유 구분") or "") in ("", "사업장 구분 변경", "그 밖의 사유") else 0,
            key=f"cap32_reason_type_{project.project_id}",
        )
        group_before = group_after = other_reason = ""
        if reason_type == "사업장 구분 변경":
            gc1, gc2 = st.columns(2)
            group_before = gc1.selectbox(
                "변경 전 사업장 구분",
                ("", "1군", "2군"),
                index=("", "1군", "2군").index(str(current32.get("변경 전 사업장 구분") or ""))
                if str(current32.get("변경 전 사업장 구분") or "") in ("", "1군", "2군") else 0,
                key=f"cap32_group_before_{project.project_id}",
            )
            group_after = gc2.selectbox(
                "변경 후 사업장 구분",
                ("", "1군", "2군"),
                index=("", "1군", "2군").index(str(current32.get("변경 후 사업장 구분") or ""))
                if str(current32.get("변경 후 사업장 구분") or "") in ("", "1군", "2군") else 0,
                key=f"cap32_group_after_{project.project_id}",
            )
        elif reason_type == "그 밖의 사유":
            other_reason = st.text_input(
                "그 밖의 사유",
                value=str(current32.get("그 밖의 사유") or ""),
                key=f"cap32_other_reason_{project.project_id}",
            )
        application_date32 = st.text_input(
            "변경 검토신청일",
            value=str(current32.get("신청일") or ""),
            key=f"cap32_date_{project.project_id}",
        )

        st.markdown("#### 뒤쪽 · 기존 적합 상세내용")
        oca = _mapping(project, "cap.submission.oca_details")
        rmp = _mapping(project, "cap.submission.rmp_details")
        oca_frame = pd.DataFrame([oca or {"민원번호": "", "결과번호": "", "적합날짜": "", "위험도": ""}])
        oca_edit = st.data_editor(oca_frame, hide_index=True, width="stretch", key=f"cap32_oca_{project.project_id}")
        rmp_frame = pd.DataFrame([rmp or {"민원번호": "", "결과번호": "", "적합날짜": ""}])
        rmp_edit = st.data_editor(rmp_frame, hide_index=True, width="stretch", key=f"cap32_rmp_{project.project_id}")
        st.caption("해당 없으면 각 칸에 '해당없음'으로 확인해 주세요.")

        st.markdown("#### 뒤쪽 · 변경제출 이력")
        history_cols = ["적합 결과번호", "사업장 구분", "위험도", "상세내용", "적합통보일"]
        history_frame = pd.DataFrame(_history_rows(project), columns=history_cols)
        history_edit = st.data_editor(
            history_frame, num_rows="dynamic", hide_index=True, width="stretch",
            key=f"cap32_history_{project.project_id}",
        )

        try:
            summary = changes.summarize_changes(project, base)
        except Exception as exc:
            st.error(f"버전 비교를 수행하지 못했습니다: {type(exc).__name__}: {exc}")
            summary = None

        if summary is not None:
            st.markdown("#### 자동 비교 결과")
            st.write(f"**{base} 대비 현재 작업본 변경:** {len(summary.field_changes)}건")
            if summary.field_changes:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "항목": item.label or item.key,
                            "구분": item.change,
                            "변경 전": str(item.old),
                            "변경 후": str(item.new),
                        }
                        for item in summary.field_changes
                    ]),
                    hide_index=True,
                    width="stretch",
                )
            details = summary.form32_details()
            st.markdown("**별지 제32호 뒤쪽에 자동 반영될 요약**")
            st.dataframe(
                pd.DataFrame([
                    {"변경구분": key, "변경 전": pair["변경 전"], "변경 후": pair["변경 후"]}
                    for key, pair in details.items()
                ]),
                hide_index=True,
                width="stretch",
            )

            st.markdown("#### 별지 제2호 변경내역 관리대장 후보")
            log_date = st.text_input("변경일자", key=f"cap32_log_date_{project.project_id}")
            person_default = _field(project, "cap.business.writer_name") or _field(project, "cap.business.writer_info")
            log_person = st.text_input("담당자", value=person_default, key=f"cap32_log_person_{project.project_id}")
            candidates = changes.proposed_form2_rows(project, base, change_date=log_date, person=log_person)
            candidate_frame = pd.DataFrame(candidates, columns=form2.LOG_COLUMNS)
            edited_candidates = st.data_editor(
                candidate_frame,
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"cap32_log_candidates_{project.project_id}",
            )
            st.caption("자동분류는 후보입니다. 변경종류·후속조치·문구를 담당자가 확인·수정한 뒤 저장하세요.")
        else:
            edited_candidates = pd.DataFrame(columns=form2.LOG_COLUMNS)

        if st.button("별지 제32호 제출정보와 변경이력 저장", key=f"cap32_save_{project.project_id}", type="primary"):
            oca_rows = oca_edit.to_dict("records")
            rmp_rows = rmp_edit.to_dict("records")
            history_rows = [
                {k: ("" if pd.isna(v) else v) for k, v in row.items()}
                for row in history_edit.to_dict("records")
                if any(str(v).strip() and str(v) != "nan" for v in row.values())
            ]
            forms.save_submission_values(project, {
                "cap.submission.method": method,
                "cap.submission.business_permit": permit,
                "cap.submission.final_approval_no": final_no,
                "cap.submission.final_approval_date": final_date,
                "cap.submission.change_reason_type": reason_type,
                "cap.submission.change_other_reason": other_reason,
                "cap.submission.group_before": group_before,
                "cap.submission.group_after": group_after,
                "cap.submission.form32.application_date": application_date32,
                "cap.submission.base_version_id": base,
                "cap.submission.oca_details": oca_rows[0] if oca_rows else {},
                "cap.submission.rmp_details": rmp_rows[0] if rmp_rows else {},
                "cap.submission.change_history": history_rows,
            })
            log_rows = [
                {k: ("" if pd.isna(v) else v) for k, v in row.items()}
                for row in edited_candidates.to_dict("records")
            ]
            if any(any(str(v).strip() for v in row.values()) for row in log_rows):
                form2.save_change_log(project, log_rows)
            save_project(project)
            st.success("별지 제32호 제출정보와 확인한 변경내역을 저장했습니다.")
            st.rerun()

        r32 = forms.form32_readiness(project)
        if r32.ready:
            st.success("별지 제32호 작성에 필요한 값이 확인되었습니다.")
            st.download_button(
                "별지 제32호 DOCX 내려받기",
                data=forms.build_form32_docx(project),
                file_name=forms.form32_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap32_download_{project.project_id}",
                width="stretch",
            )
        else:
            st.warning("별지 제32호 보완 필요")
            for blocker in r32.blockers:
                st.write(f"• {blocker}")
