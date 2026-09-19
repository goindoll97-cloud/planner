from __future__ import annotations

"""점검·내보내기 화면 조각(화학사고예방관리계획서·공정안전보고서 공용)."""

import pandas as pd
import streamlit as st

from engine.stage2 import report_export as export
from engine.stage2.storage import save_project
from engine.stage2.workflow import validation_confirmed
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
    label = LABELS[system]
    prefix = f"export_{system.lower()}"
    st.caption(f"입력한 내용을 점검하고 {label} 보고서(DOCX)를 내려받습니다. 부족한 내용은 각 별지 화면에서 채우면 여기 점검 결과에 바로 반영됩니다.")
    try:
        state = export.evaluate(project, system)
    except Exception as exc:
        st.error(f"점검하지 못했습니다: {type(exc).__name__}: {exc}")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("보완 필요", state.hold)
    c2.metric("담당자 확인 필요", state.review)
    c3.metric("확인 완료", state.passed)
    c4.metric("최종 제출 전 별도 준비", len(state.manual_issues))
    if state.can_confirm:
        st.success("보고서 작성에 필요한 기본 자료 점검이 끝났습니다.")
    else:
        st.warning("보완하거나 담당자가 확인할 항목이 남아 있습니다. 채우고 오거나, 현재 자료만으로 검토용 초안을 만들 수 있습니다.")
    rows = [{"상태": export.STATUS_LABELS.get(i.status, i.status_label), "작성항목": i.legal_item,
             "확인할 내용": i.message, "근거": i.legal_basis} for i in state.text_issues if i.status != "PASS"]
    if rows:
        frames.show(pd.DataFrame(rows), width="stretch", hide_index=True)
    if state.manual_issues:
        with st.expander(f"최종 제출 전에 따로 준비할 자료 {len(state.manual_issues)}건"):
            st.caption("도면·MSDS 같은 첨부 자료입니다. 최종 제출 전에 실제 파일을 대조해야 합니다.")
            frames.show(pd.DataFrame([{"작성항목": i.legal_item, "준비할 내용": i.message} for i in state.manual_issues]),
                        width="stretch", hide_index=True)
    readiness = state.readiness
    if readiness is not None:
        _gate_table(f"{label} · 작성완성도·자동검증", readiness.system_gate)
        _gate_table(f"{label} · 최종 제출 체크포인트", readiness.cap_gate, with_pages=True)

    if state.can_confirm and not validation_confirmed(project):
        if st.button("작성자료 확인 완료", type="primary", key=f"{prefix}_confirm"):
            export.confirm(project, state)
            save_project(project)
            st.rerun()
    elif not state.can_confirm and not export.downloads_allowed(project):
        if st.button("현재 자료로 검토용 초안 만들기", type="primary", key=f"{prefix}_ack"):
            export.acknowledge_holds(project)
            save_project(project)
            st.rerun()
    if not export.downloads_allowed(project):
        st.info("작성자료를 확인 완료하거나 검토용 초안 만들기를 선택하면 내려받을 수 있습니다.")
        return
    try:
        outputs = export.build_outputs(project, final_ready=state.final_ready, system=system)
    except Exception as exc:
        st.error(f"보고서를 만들지 못했습니다: {type(exc).__name__}: {exc}")
        return
    if state.final_ready:
        st.success("문서별 최종 준비 기준을 통과해 '작성본'으로 표시합니다. 그래도 제출 전에는 담당자가 사실·수치·도면을 최종 대조해야 합니다.")
    else:
        st.warning("최종 준비 기준을 아직 통과하지 못해 '검토용'으로 표시합니다. 제출본이 아닙니다.")
        for reason in (readiness.reasons if readiness else ()):
            st.write(f"• {reason}")
    st.download_button("규정서식 DOCX 내려받기", data=outputs.regulation_docx, file_name=outputs.regulation_name,
                       mime=export.DOCX_MIME, key=f"{prefix}_dl_regulation", width="stretch",
                       type="primary" if state.final_ready else "secondary")
    st.download_button("내부 검토용 DOCX(서술형 항목 포함) 내려받기", data=outputs.review_docx, file_name=outputs.review_name,
                       mime=export.DOCX_MIME, key=f"{prefix}_dl_review", width="stretch")
    with st.expander("출력물 검증정보"):
        st.caption("파일이 나중에 바뀌지 않았는지 확인하는 지문(SHA-256)과 생성 기록입니다.")
        st.download_button("검증정보 JSON", data=outputs.provenance_json, file_name=outputs.provenance_name,
                           mime="application/json", key=f"{prefix}_dl_prov", width="stretch")
        st.download_button("검증 묶음 ZIP(DOCX + 검증정보)", data=outputs.bundle, file_name=outputs.bundle_name,
                           mime="application/zip", key=f"{prefix}_dl_bundle", width="stretch")
