from __future__ import annotations

"""점검·내보내기 화면 조각(화학사고예방관리계획서·공정안전보고서 공용)."""

import pandas as pd
import streamlit as st

from engine.stage2 import report_export as export
from engine.stage2.ai_drafting import ai_written_items
from engine.stage2 import psm_admin_forms
from ui import cap_frames as frames

LABELS = {"PSM": "공정안전보고서", "CAP": "화학사고예방관리계획서"}


def _gate_table(title: str, gate, *, with_pages: bool = False) -> None:
    if gate is None or not gate.checkpoints:
        return
    with st.expander(f"{title}{'' if gate.ready else ' — 보완할 항목 있음'}", expanded=not gate.ready):
        rows = []
        for item in gate.checkpoints:
            row = {"상태": item.status_label, "점검항목": item.label, "확인내용": item.message}
            if with_pages:
                row["매뉴얼"] = ", ".join(f"p.{page}" for page in item.manual_pages)
            rows.append(row)
        frames.show(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("담당자 확인 필요 항목은 프로그램이 임의로 완료 처리하지 않습니다.")


def render(project, system: str) -> None:
    if system == "CAP":
        render_workspace_download(project)
        return
    label = LABELS[system]
    prefix = f"export_{system.lower()}"
    st.caption(f"회사 파일에서 프로그램이 채운 {label} 초안(DOCX)을 내려받습니다. 승인 절차는 없습니다. "
               "비어 있거나 틀린 곳은 해당 파일을 고쳐 다시 올리거나, 내려받은 문서를 직접 고치세요.")
    try:
        state = export.evaluate(project, system)
    except Exception as exc:
        st.error(f"점검하지 못했습니다: {type(exc).__name__}: {exc}")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("파일 보완이 필요한 곳", state.hold)
    c2.metric("값 확인이 필요한 곳", state.review)
    c3.metric("채워진 곳", state.passed)
    c4.metric("따로 준비할 자료", len(state.manual_issues))
    rows = [{"상태": export.STATUS_LABELS.get(i.status, i.status_label), "작성항목": i.legal_item,
             "확인할 내용": i.message, "근거": i.legal_basis} for i in state.text_issues if i.status != "PASS"]
    if rows:
        frames.show(pd.DataFrame(rows), width="stretch", hide_index=True)
    if state.manual_issues:
        with st.expander(f"따로 준비할 자료 {len(state.manual_issues)}건"):
            st.caption("도면·MSDS 같은 첨부 자료입니다. 제출 전에 실제 파일을 대조하세요.")
            frames.show(pd.DataFrame([{"작성항목": i.legal_item, "준비할 내용": i.message} for i in state.manual_issues]),
                        width="stretch", hide_index=True)
    readiness = state.readiness
    if readiness is not None:
        _gate_table(f"{label} · 작성완성도·자동검증", readiness.system_gate)
        _gate_table(f"{label} · 제출 전 체크포인트", readiness.cap_gate, with_pages=True)

    try:
        outputs = export.build_outputs(project, system=system)
    except Exception as exc:
        st.error(f"초안을 만들지 못했습니다: {type(exc).__name__}: {exc}")
        return
    st.info("초안입니다. 제출 전에 담당자가 사실·수치·도면을 대조하고 필요하면 문서를 직접 고치세요.")
    st.download_button("규정서식 DOCX 초안 내려받기", data=outputs.regulation_docx, file_name=outputs.regulation_name,
                       mime=export.DOCX_MIME, key=f"{prefix}_dl_regulation", width="stretch", type="primary")
    st.download_button("서술형 포함 DOCX 초안(보완 안내 포함) 내려받기", data=outputs.review_docx, file_name=outputs.review_name,
                       mime=export.DOCX_MIME, key=f"{prefix}_dl_review", width="stretch")

    if system == "PSM":
        st.markdown("### 심사 제출 행정서식")
        form1 = psm_admin_forms.form1_readiness(project)
        if form1.ready:
            st.download_button(
                "별지 제1호 심사신청서 DOCX 내려받기",
                data=psm_admin_forms.build_form1_docx(project),
                file_name=psm_admin_forms.form1_filename(project),
                mime=export.DOCX_MIME,
                key=f"{prefix}_dl_admin_form1",
                width="stretch",
            )
        else:
            st.info(
                "별지 제1호 심사신청서는 '제출·확인 행정서식' 화면에서 "
                "사업장관리번호와 실제 신청일을 확인하면 내려받을 수 있습니다."
            )
        st.caption(
            "별지 제9호 확인요청서는 심사 후 확인 단계의 서식이므로 초기 공정안전보고서 제출 READY 판정에는 포함하지 않습니다."
        )
    ai_rows = ai_written_items(project, system)
    if ai_rows:
        with st.expander(f"AI가 쓴 항목 {len(ai_rows)}개 — 제출 전 다시 점검", expanded=True):
            st.warning("아래 항목의 문장은 AI가 초안을 쓴 것입니다. 규정서식 본문에는 AI 표시가 들어가지 않으니, 제출 전에 사실·숫자·설비·직책을 한 번 더 대조하세요.")
            frame = pd.DataFrame([{"항목": f"{r['section']} {r['label']}".strip(), "상태": r["state"],
                                   "담당자 수정": "수정함" if r["edited_by_reviewer"] else "수정 없음",
                                   "[확인 필요] 표시": "있음" if r["has_check_mark"] else "없음"} for r in ai_rows])
            frames.show(frame, width="stretch", hide_index=True)
            st.download_button("AI 작성 항목 점검표 DOCX 내려받기", data=export.build_ai_review_sheet(project, system),
                               file_name=export.ai_review_sheet_name(project, system), mime=export.DOCX_MIME,
                               key=f"{prefix}_dl_ai_sheet", width="stretch")
    with st.expander("출력물 검증정보"):
        st.caption("파일이 나중에 바뀌지 않았는지 확인하는 지문(SHA-256)과 생성 기록입니다.")
        st.download_button("검증정보 JSON", data=outputs.provenance_json, file_name=outputs.provenance_name,
                           mime="application/json", key=f"{prefix}_dl_prov", width="stretch")
        st.download_button("검증 묶음 ZIP(DOCX + 검증정보)", data=outputs.bundle, file_name=outputs.bundle_name,
                           mime="application/zip", key=f"{prefix}_dl_bundle", width="stretch")


def render_workspace_download(project) -> None:
    """자료 접수 ④의 단일 다운로드. 상세 보완은 ②에서 안내합니다."""
    if not project.cap_in_scope:
        st.caption("화학사고예방관리계획서 작성 대상이 확인되면 초안을 내려받을 수 있어요.")
        return
    try:
        draft = export.build_cap_workspace_draft(project)
    except Exception:
        st.error("초안을 생성·검증하지 못했어요. 자료와 서식 구성을 확인한 뒤 다시 시도해 주세요.")
        return
    st.caption("현재 자료와 서술형을 포함한 초안입니다. 제출 전에 내용을 확인하고, 보완할 자료는 ②에서 확인하세요.")
    st.download_button("규정서식 초안 DOCX 내려받기", data=draft.docx, file_name=draft.name,
                       mime=export.DOCX_MIME, key="workspace_cap_docx_" + project.project_id,
                       width="stretch", type="primary")
