from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.export import build_progress_workbook
from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.requirements import requirement_specs_for_project
from engine.stage2.storage import (
    list_projects,
    load_project,
    project_json_bytes,
    save_attachment,
    save_project,
)


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
SNAPSHOT_KEY = "_stage2_stage1_snapshot"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {
    "COMMON": "공통자료",
    "PSM": PSM_FULL,
    "CAP": CAP_FULL,
}
FIELD_LABELS = {
    "business.company_name": "회사명",
    "business.address": "사업장 소재지",
    "inventory.chemicals": "화학물질 목록",
    "inventory.facilities": "시설·설비 목록",
    "process.description": "공정 설명",
    "documents.pfd": "공정흐름도(PFD)",
    "documents.pid": "배관계장도(P&ID)",
    "documents.site_plan": "사업장·설비 배치도",
    "psm.hazard_assessment": "공정위험성평가",
    "psm.safe_operation_plan": "안전운전계획",
    "emergency.internal_plan": "내부 비상대응계획",
    "cap.offsite_assessment": "장외평가정보",
    "cap.prevention_policy": "사전관리방침",
    "emergency.external_plan": "외부 비상대응계획",
}

st.set_page_config(page_title="작성 프로젝트", page_icon="📝", layout="wide")
st.title("📝 2. 작성 프로젝트")
st.caption(
    "Stage 1에서 확정된 회사 사실을 그대로 승계하고, 이후 작성자료는 근거와 상태를 함께 관리합니다. "
    "AI 초안이나 근거가 확인되지 않은 값은 최종 완료로 처리하지 않습니다."
)


def _truth_label(value: bool | None) -> str:
    if value is True:
        return "대상"
    if value is False:
        return "비대상"
    return "미확정"


def _field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key)


def _project_selector() -> str | None:
    projects = list_projects()
    snapshot = st.session_state.get(SNAPSHOT_KEY)

    with st.container(border=True):
        st.markdown("### 프로젝트 선택")
        if snapshot:
            decision = snapshot.get("decision", {})
            st.caption(
                f"최근 Stage 1 결과: {PSM_FULL} {decision.get('psm_status', '')} / "
                f"{CAP_FULL} {decision.get('cap_status', '')}"
            )
            if st.button("최근 판정결과로 새 작성 프로젝트 만들기", type="primary", width="stretch"):
                project = create_project_from_stage1_snapshot(snapshot)
                save_project(project)
                st.session_state[ACTIVE_PROJECT_KEY] = project.project_id
                st.success(f"작성 프로젝트를 생성했습니다: {project.project_id}")
                st.rerun()

        if not projects:
            st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단을 완료한 뒤 프로젝트를 생성하세요.")
            return None

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
        selected = st.selectbox(
            "작성 프로젝트",
            ids,
            index=index,
            format_func=lambda pid: labels.get(pid, pid),
        )
        st.session_state[ACTIVE_PROJECT_KEY] = selected
        return selected


project_id = _project_selector()
if not project_id:
    st.stop()

try:
    project = load_project(project_id)
except Exception as exc:
    st.error(f"프로젝트를 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

completeness = evaluate_project_completeness(project)

a, b, c, d = st.columns(4)
with a:
    st.metric("전체 작성률", f"{completeness['overall']['completion_pct']:.1f}%")
with b:
    st.metric(PSM_FULL, _truth_label(project.psm_required))
with c:
    cap_text = _truth_label(project.cap_required)
    if project.cap_group:
        cap_text += f" · {project.cap_group}"
    st.metric(CAP_FULL, cap_text)
with d:
    st.metric("작성상태", completeness["overall"]["state"])

st.caption(
    f"프로젝트 ID: {project.project_id} · Stage 1 원본 SHA-256: "
    f"{project.stage1_source_fingerprint or '미기록'}"
)

summary_tab, register_tab, export_tab = st.tabs(["작성현황", "자료·근거 등록", "검토자료 내보내기"])

with summary_tab:
    st.markdown("### 법정 작성구조별 현황")
    req_df = pd.DataFrame(completeness["requirements"])
    if not req_df.empty:
        req_df["system"] = req_df["system"].map(lambda value: SYSTEM_LABELS.get(value, value))
        req_df = req_df.rename(columns={
            "system": "구분",
            "section": "절",
            "label": "작성항목",
            "state": "상태",
            "completion_pct": "완성도(%)",
            "missing_fields": "미확인 필드",
            "draft_fields": "AI 초안 필드",
            "hold_fields": "HOLD 필드",
            "legal_basis": "작성근거",
        })
        for col in ["미확인 필드", "AI 초안 필드", "HOLD 필드"]:
            req_df[col] = req_df[col].map(lambda values: tuple(_field_label(v) for v in values))
        st.dataframe(
            req_df[["구분", "절", "작성항목", "상태", "완성도(%)", "미확인 필드", "AI 초안 필드", "HOLD 필드", "작성근거"]],
            width="stretch",
            hide_index=True,
        )

    st.markdown("### 등록된 자료")
    field_rows = []
    for key in sorted(project.fields):
        record = project.fields[key]
        value = record.value
        if isinstance(value, (list, dict)):
            value = f"구조화 자료 {len(value)}건" if isinstance(value, list) else "구조화 자료"
        field_rows.append({
            "항목": record.label,
            "상태": record.status,
            "값/자료": value,
            "증빙수": len(record.evidence),
            "비고": record.note,
        })
    if field_rows:
        st.dataframe(pd.DataFrame(field_rows), width="stretch", hide_index=True)
    else:
        st.info("아직 등록된 작성자료가 없습니다.")

with register_tab:
    st.markdown("### 작성자료 등록")
    st.info(
        "회사자료 파일을 첨부하면 해당 파일의 SHA-256을 계산하여 VERIFIED 근거로 저장합니다. "
        "파일 없이 담당자가 직접 확인한 사실은 USER_CONFIRMED로 저장합니다."
    )
    specs = requirement_specs_for_project(project)
    spec_map = {spec.key: spec for spec in specs}
    spec_key = st.selectbox(
        "작성항목",
        list(spec_map),
        format_func=lambda key: (
            f"[{SYSTEM_LABELS.get(spec_map[key].system, spec_map[key].system)}] "
            f"{spec_map[key].section} · {spec_map[key].label}"
        ),
    )
    spec = spec_map[spec_key]
    field_key = st.selectbox(
        "등록할 데이터 필드",
        list(spec.field_keys),
        format_func=_field_label,
    )
    existing = project.get_field(field_key)
    default_value = ""
    if existing and not isinstance(existing.value, (list, dict)) and existing.value is not None:
        default_value = str(existing.value)

    with st.form("stage2_field_register_form", clear_on_submit=False):
        value = st.text_area(
            "확인값 또는 설명",
            value=default_value,
            help="도면·SDS 등 파일 자체가 값인 경우에는 비워두고 아래 증빙파일만 첨부해도 됩니다.",
        )
        upload = st.file_uploader("증빙파일(선택)", key=f"evidence_{field_key}")
        source_page = st.text_input("근거 페이지/위치(선택)")
        note = st.text_input("비고(선택)")
        hold_only = st.checkbox("아직 확인되지 않은 항목으로 HOLD 저장")
        submitted = st.form_submit_button("저장", type="primary", width="stretch")

    if submitted:
        evidence = list(existing.evidence) if existing else []
        if upload is not None:
            ref = save_attachment(
                project.project_id,
                upload.name,
                upload.getvalue(),
                note=note,
            )
            ref.page = source_page
            evidence.append(ref)

        if hold_only:
            status = "HOLD"
        elif upload is not None:
            status = "VERIFIED"
        elif value.strip():
            status = "USER_CONFIRMED"
        else:
            st.error("확인값을 입력하거나 증빙파일을 첨부하세요. 미확인 상태라면 HOLD 저장을 선택하세요.")
            st.stop()

        stored_value = value.strip()
        if not stored_value and upload is not None:
            stored_value = upload.name
        project.set_field(
            field_key,
            _field_label(field_key),
            stored_value,
            status,
            evidence=evidence,
            note=note,
        )
        save_project(project)
        st.success(f"{_field_label(field_key)} 항목을 {status} 상태로 저장했습니다.")
        st.rerun()

with export_tab:
    st.markdown("### 검토용 산출물")
    st.warning(
        "현재 Stage 2-1 산출물은 작성현황·근거 추적용입니다. 법정 제출용 최종 DOCX/PDF는 "
        "세부 작성엔진과 최종 검증 gate를 구현한 뒤 활성화합니다."
    )
    json_bytes = project_json_bytes(project)
    xlsx_bytes = build_progress_workbook(project)
    left, right = st.columns(2)
    with left:
        st.download_button(
            "프로젝트 원본 JSON 다운로드",
            data=json_bytes,
            file_name=f"{project.project_id}_project.json",
            mime="application/json",
            width="stretch",
        )
    with right:
        st.download_button(
            "작성현황·근거 XLSX 다운로드",
            data=xlsx_bytes,
            file_name=f"{project.project_id}_작성현황_근거.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
