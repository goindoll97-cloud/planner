from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2.cap_requests import build_cap_data_requests
from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.export import build_progress_workbook
from engine.stage2.intake import field_label, selected_requirement_specs
from engine.stage2.project import EVIDENCE_STATUSES
from engine.stage2.psm_requests import build_psm_data_requests
from engine.stage2.storage import list_projects, load_project, project_json_bytes, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {"COMMON": "공통자료", "PSM": PSM_FULL, "CAP": CAP_FULL}


st.set_page_config(page_title="작성·검토", page_icon="📝", layout="wide")
st.title("📝 5. 작성·검토")
st.caption(
    "선택한 작성범위만 대상으로 작성현황을 검토하고, 회사 담당자가 직접 확인한 사실이나 검토가 필요한 초안을 관리합니다."
)

projects = list_projects()
if not projects:
    st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단과 2. 작성범위 선택을 진행하세요.")
    st.stop()

labels = {
    row["project_id"]: (
        f"{row['company_name']}"
        + (f" / {row['site_name']}" if row.get("site_name") else "")
        + f" · {row['project_id']}"
    )
    for row in projects
}
ids = [row["project_id"] for row in projects]
current = st.session_state.get(ACTIVE_PROJECT_KEY)
index = ids.index(current) if current in ids else 0
project_id = st.selectbox("작성 프로젝트", ids, index=index, format_func=lambda pid: labels.get(pid, pid))
st.session_state[ACTIVE_PROJECT_KEY] = project_id

try:
    project = load_project(project_id)
except Exception as exc:
    st.error(f"프로젝트를 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

if not project.scope_confirmed:
    st.warning("작성범위가 아직 선택되지 않았습니다.")
    st.page_link("ui/stage2_scope_page.py", label="2. 작성범위 선택으로 이동", icon="🧭")
    st.stop()

scope_labels = []
if project.psm_in_scope:
    scope_labels.append(PSM_FULL)
if project.cap_in_scope:
    scope_labels.append(CAP_FULL)
st.success("현재 작성범위: " + ", ".join(scope_labels))

completeness = evaluate_project_completeness(project)
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("전체 작성률", f"{completeness['overall']['completion_pct']:.1f}%")
with c2:
    st.metric("완료 작성항목", completeness["overall"]["ready_n"])
with c3:
    st.metric("프로그램 작성상태", completeness["overall"]["state"])

summary_tab, request_tab, edit_tab, export_tab = st.tabs(
    ["작성현황", "부족자료·근거", "확인값·초안 관리", "검토자료 내보내기"]
)

with summary_tab:
    rows = []
    for item in completeness["requirements"]:
        rows.append({
            "구분": SYSTEM_LABELS.get(item["system"], item["system"]),
            "작성구조": item["section"],
            "작성항목": item["label"],
            "상태": item["state"],
            "완성도(%)": item["completion_pct"],
            "미확인 항목": ", ".join(field_label(v) for v in item["missing_fields"]),
            "AI 초안 항목": ", ".join(field_label(v) for v in item["draft_fields"]),
            "검증 보류 항목": ", ".join(field_label(v) for v in item["hold_fields"]),
            "작성근거": item["legal_basis"],
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("### 등록된 자료와 확인값")
    field_rows = []
    for key in sorted(project.fields):
        record = project.fields[key]
        value = record.value
        if isinstance(value, list):
            value = f"구조화/접수 자료 {len(value)}건"
        elif isinstance(value, dict):
            value = "구조화 자료"
        field_rows.append({
            "항목": record.label,
            "상태": record.status,
            "값/자료": value,
            "증빙수": len(record.evidence),
            "비고": record.note,
        })
    if field_rows:
        st.dataframe(pd.DataFrame(field_rows), width="stretch", hide_index=True)

with request_tab:
    request_rows = []
    if project.psm_in_scope:
        for item in build_psm_data_requests(project):
            request_rows.append({
                "구분": PSM_FULL,
                "작성구조": item.section,
                "작성항목": item.label,
                "미확인 항목": ", ".join(item.missing_labels),
                "확인 가능한 자료 예": ", ".join(item.suggested_evidence),
                "작성근거": item.legal_basis,
                "요청사항": item.request_text,
            })
    if project.cap_in_scope:
        for item in build_cap_data_requests(project):
            request_rows.append({
                "구분": CAP_FULL,
                "작성구조": item.section,
                "작성항목": item.label,
                "미확인 항목": ", ".join(item.missing_labels),
                "확인 가능한 자료 예": ", ".join(item.suggested_evidence),
                "작성근거": getattr(item, "legal_basis", ""),
                "요청사항": item.request_text,
            })
    if request_rows:
        st.dataframe(pd.DataFrame(request_rows), width="stretch", hide_index=True)
    else:
        st.success("현재 요청자료 엔진 기준으로 추가 요청할 항목이 없습니다.")
    st.page_link("ui/stage2_intake_page.py", label="자료 추가접수로 이동", icon="📥")
    st.page_link("ui/legal_evidence_page.py", label="법령·공식 근거자료 확인", icon="📚")

with edit_tab:
    specs = selected_requirement_specs(project)
    spec_map = {spec.key: spec for spec in specs if spec.field_keys}
    if not spec_map:
        st.info("현재 작성범위에 편집할 작성항목이 없습니다.")
    else:
        spec_key = st.selectbox(
            "작성항목",
            list(spec_map),
            format_func=lambda key: (
                f"[{SYSTEM_LABELS.get(spec_map[key].system, spec_map[key].system)}] "
                f"{spec_map[key].section} · {spec_map[key].label}"
            ),
        )
        spec = spec_map[spec_key]
        field_key = st.selectbox("확인할 내용", list(spec.field_keys), format_func=field_label)
        existing = project.get_field(field_key)
        current_value = ""
        if existing and existing.value is not None and not isinstance(existing.value, (list, dict)):
            current_value = str(existing.value)

        st.caption(f"작성근거: {spec.legal_basis or '별도 표시 없음'}")
        if spec.suggested_evidence:
            st.caption("확인 가능한 자료 예: " + ", ".join(spec.suggested_evidence))

        with st.form("stage2_review_edit_form"):
            value = st.text_area("확인값 또는 검토용 초안", value=current_value)
            status = st.selectbox(
                "저장상태",
                ["USER_CONFIRMED", "AI_DRAFT", "HOLD"],
                format_func=lambda v: {
                    "USER_CONFIRMED": "담당자 확인",
                    "AI_DRAFT": "AI 초안(사람 검토 필요)",
                    "HOLD": "검증 보류",
                }[v],
            )
            note = st.text_input("비고", value=existing.note if existing else "")
            submitted = st.form_submit_button("확인값 저장", type="primary", width="stretch")
        if submitted:
            if not value.strip() and status != "HOLD":
                st.error("확인값 또는 초안을 입력하세요.")
            else:
                project.set_field(
                    field_key,
                    field_label(field_key),
                    value.strip(),
                    status,
                    evidence=list(existing.evidence) if existing else [],
                    note=note,
                )
                save_project(project)
                st.success("저장했습니다.")
                st.rerun()

with export_tab:
    st.warning(
        "현재 파일은 검토·감사·자료요청 관리용입니다. 법정 제출용 최종본은 최종 검증 gate가 완성된 뒤 활성화합니다."
    )
    left, right = st.columns(2)
    with left:
        st.download_button(
            "프로젝트 원본 JSON 다운로드",
            data=project_json_bytes(project),
            file_name=f"{project.project_id}_project.json",
            mime="application/json",
            width="stretch",
        )
    with right:
        st.download_button(
            "작성현황·근거·요청자료 XLSX 다운로드",
            data=build_progress_workbook(project),
            file_name=f"{project.project_id}_작성현황_근거_요청자료.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
