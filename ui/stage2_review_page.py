from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2.ai_drafting import (
    DEFAULT_API_URL,
    DEFAULT_MODEL,
    LLMConfig,
    OpenAIResponsesClient,
    ai_draft_field_key,
    ai_draftable_specs,
    approve_ai_draft,
    build_operating_profile,
    generate_system_ai_drafts,
    llm_config_from_sources,
    remove_ai_draft,
)
from engine.stage2.ai_report import (
    build_ai_enhanced_draft_bundle,
    build_ai_enhanced_report_draft,
    has_ai_report_prose,
)
from engine.stage2.cap_requests import build_cap_data_requests
from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.export import build_progress_workbook
from engine.stage2.intake import field_label, selected_requirement_specs
from engine.stage2.psm_requests import build_psm_data_requests
from engine.stage2.report_draft import (
    build_draft_bundle,
    build_report_draft,
    draft_filename,
    report_generation_status,
)
from engine.stage2.storage import list_projects, load_project, project_json_bytes, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {"COMMON": "공통자료", "PSM": PSM_FULL, "CAP": CAP_FULL}
AI_SECRET_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_RESPONSES_URL",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_MAX_OUTPUT_TOKENS",
)


def _secret_values() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for key in AI_SECRET_KEYS:
            value = st.secrets.get(key)
            if value not in (None, ""):
                values[key] = str(value)
    except Exception:
        pass
    return values


st.set_page_config(page_title="작성·검토", page_icon="📝", layout="wide")
st.title("📝 5. 작성·검토")
st.caption(
    "선택한 작성범위만 대상으로 작성현황을 검토하고, 회사 담당자가 직접 확인한 사실과 AI 보강 초안을 관리합니다."
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

summary_tab, request_tab, edit_tab, ai_tab, draft_tab, export_tab = st.tabs(
    ["작성현황", "부족자료·근거", "확인값·초안 관리", "AI 문장 보강", "보고서 초안 생성", "감사·검토자료"]
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
    spec_map = {spec.key: spec for spec in specs if spec.field_keys and not spec.key.startswith("ai_draft.")}
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

with ai_tab:
    st.markdown("### 사업장 사실 기반 AI 문장 보강")
    st.info(
        "AI는 1·2군 여부나 법적 대상 여부를 다시 판단하지 않습니다. Rule Engine이 확정한 작성범위와 VERIFIED/USER_CONFIRMED/CALCULATED 사실만 받아 보고서 문체를 보강합니다. "
        "없는 수치·설비·인원·주기·절차는 만들지 않고 '추가 확인하면 좋은 내용'으로 분리합니다."
    )

    profile = build_operating_profile(project)
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric("화학물질", profile["chemical_count"])
    with p2:
        st.metric("주요 설비", profile["facility_count"])
    with p3:
        st.metric("안전밸브·파열판", profile["relief_device_count"])
    with p4:
        st.metric("가스감지기", profile["gas_detector_count"])
    profile_line = []
    if project.cap_in_scope:
        profile_line.append(f"작성수준 {project.cap_group or '확인 필요'}")
    if profile["major_chemical_names"]:
        profile_line.append("주요 물질: " + ", ".join(profile["major_chemical_names"]))
    if profile_line:
        st.caption(" · ".join(profile_line))

    ai_systems = []
    if project.psm_in_scope:
        ai_systems.append("PSM")
    if project.cap_in_scope:
        ai_systems.append("CAP")
    ai_system = st.selectbox(
        "AI로 보강할 보고서",
        ai_systems,
        format_func=lambda system: SYSTEM_LABELS[system],
        key="ai_drafting_system",
    )

    try:
        candidates = ai_draftable_specs(project, ai_system)
    except Exception as exc:
        candidates = []
        st.error(str(exc))
    st.caption(f"현재 확인자료로 AI 보강 가능한 작성항목: {len(candidates)}개")

    secret_config = llm_config_from_sources(_secret_values())
    if secret_config:
        st.success("서버의 LLM API 설정을 사용할 수 있습니다. API 키는 프로젝트 데이터에 저장되지 않습니다.")
    else:
        st.caption("서버 API 키가 없으면 아래에 테스트용 키를 입력할 수 있습니다. 입력값은 현재 Streamlit 세션에서만 사용합니다.")

    session_key = st.text_input("OpenAI API Key", type="password", key="stage2_openai_api_key")
    model = st.text_input(
        "LLM 모델",
        value=secret_config.model if secret_config else DEFAULT_MODEL,
        key="stage2_openai_model",
    )
    with st.expander("고급 API 설정"):
        api_url = st.text_input(
            "Responses API URL",
            value=secret_config.api_url if secret_config else DEFAULT_API_URL,
            key="stage2_openai_api_url",
        )
        st.caption("운영환경에서는 Streamlit secrets 또는 환경변수 OPENAI_API_KEY / OPENAI_MODEL / OPENAI_RESPONSES_URL 사용을 권장합니다.")

    generate_disabled = not candidates or not (session_key or (secret_config and secret_config.api_key))
    if st.button(
        f"{SYSTEM_LABELS[ai_system]} AI 문장 보강 생성",
        type="primary",
        disabled=generate_disabled,
        width="stretch",
    ):
        base = secret_config
        config = LLMConfig(
            api_key=session_key or (base.api_key if base else ""),
            model=model.strip() or (base.model if base else DEFAULT_MODEL),
            api_url=api_url.strip() or (base.api_url if base else DEFAULT_API_URL),
            timeout_seconds=base.timeout_seconds if base else 90,
            max_output_tokens=base.max_output_tokens if base else 12000,
        )
        try:
            with st.spinner("확인된 사업장 사실과 법적 작성구조를 바탕으로 문장을 보강하고 있습니다..."):
                result = generate_system_ai_drafts(
                    project,
                    ai_system,
                    OpenAIResponsesClient(config),
                    store_safe_drafts=True,
                )
                save_project(project)
        except Exception as exc:
            st.error(f"AI 문장 보강에 실패했습니다: {type(exc).__name__}: {exc}")
        else:
            st.session_state["stage2_ai_flash"] = (
                f"{result.system_label}: 안전검증 통과 {len(result.generated)}개, "
                f"자동 저장 거부 {len(result.rejected)}개"
            )
            st.rerun()

    flash = st.session_state.pop("stage2_ai_flash", None)
    if flash:
        st.success(flash)

    system_specs = [spec for spec in selected_requirement_specs(project) if spec.system == ai_system]
    draft_entries = []
    for spec in system_specs:
        record = project.get_field(ai_draft_field_key(ai_system, spec.key))
        if record and isinstance(record.value, dict) and record.value.get("draft_text"):
            draft_entries.append((spec, record))

    st.markdown("#### 생성된 AI 보강문장 검토")
    if not draft_entries:
        st.caption("아직 저장된 AI 보강문장이 없습니다.")
    for spec, record in draft_entries:
        badge = "담당자 검토 완료" if record.status == "USER_CONFIRMED" else "사람 검토 필요"
        with st.expander(f"{spec.section} · {spec.label} — {badge}"):
            payload = dict(record.value)
            profile_summary = str(payload.get("profile_summary") or "").strip()
            if profile_summary:
                st.caption("AI가 읽은 사업장 운영·위험 특성: " + profile_summary)
            suggestions = payload.get("suggested_additions") or []
            if suggestions:
                st.warning("추가 확인하면 좋은 내용\n\n- " + "\n- ".join(str(v) for v in suggestions))
            edited = st.text_area(
                "보고서 보강문장",
                value=str(payload.get("draft_text") or ""),
                height=180,
                key=f"ai_draft_text_{project.project_id}_{ai_system}_{spec.key}",
            )
            st.caption("법적 적용판단은 Rule Engine 결과를 따르며, 이 문장은 회사 사실을 바꾸거나 새로운 법적 의무를 생성하지 않습니다.")
            left, right = st.columns(2)
            with left:
                if st.button(
                    "담당자 검토·승인",
                    key=f"approve_ai_{project.project_id}_{ai_system}_{spec.key}",
                    width="stretch",
                ):
                    try:
                        approve_ai_draft(project, ai_system, spec.key, edited)
                        save_project(project)
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()
            with right:
                if st.button(
                    "AI 보강문장 삭제",
                    key=f"remove_ai_{project.project_id}_{ai_system}_{spec.key}",
                    width="stretch",
                ):
                    remove_ai_draft(project, ai_system, spec.key)
                    save_project(project)
                    st.rerun()

with draft_tab:
    st.markdown("### 검토용 보고서 DOCX 생성")
    st.info(
        "회사에서 확인한 값과 구조화 표를 법정 작성구조에 맞춰 배치합니다. AI 문장 보강이 생성된 항목은 회사 원본 사실을 보존한 채 해당 작성항목 바로 아래에 보강문장을 함께 넣습니다."
    )
    st.warning(
        "여기서 생성하는 문서는 검토용 자동작성 초안입니다. HOLD 또는 미승인 AI 문장이 남아 있어도 생성할 수 있지만 법정 제출용 최종본으로 사용할 수 없습니다."
    )

    selected_systems = []
    if project.psm_in_scope:
        selected_systems.append(("PSM", PSM_FULL))
    if project.cap_in_scope:
        selected_systems.append(("CAP", CAP_FULL))

    for system, label in selected_systems:
        status = report_generation_status(project, system)
        st.markdown(f"#### {label}")
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("작성완성도", f"{status.completion_pct:.1f}%")
        with m2:
            st.metric("작성상태", status.state)
        with m3:
            st.metric("미해결 필드", status.unresolved_n)

        ai_applied = has_ai_report_prose(project, system)
        try:
            if ai_applied:
                draft_bytes = build_ai_enhanced_report_draft(project, system)
                download_label = f"{label} AI 보강 검토용 DOCX 다운로드"
                file_name = draft_filename(project, system).replace("_검토용_초안.docx", "_AI보강_검토용_초안.docx")
            else:
                draft_bytes = build_report_draft(project, system)
                download_label = f"{label} 검토용 DOCX 초안 다운로드"
                file_name = draft_filename(project, system)
        except Exception as exc:
            st.error(f"{label} 초안을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
        else:
            st.download_button(
                download_label,
                data=draft_bytes,
                file_name=file_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"download_draft_{system}_{project.project_id}",
                width="stretch",
            )
            if ai_applied:
                with st.expander("AI 보강 전 원자료형 DOCX도 확인하기"):
                    baseline = build_report_draft(project, system)
                    st.download_button(
                        f"{label} 원자료형 DOCX 다운로드",
                        data=baseline,
                        file_name=draft_filename(project, system),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_baseline_{system}_{project.project_id}",
                        width="stretch",
                    )

    if len(selected_systems) > 1:
        any_ai = any(has_ai_report_prose(project, system) for system, _ in selected_systems)
        try:
            bundle_bytes = build_ai_enhanced_draft_bundle(project) if any_ai else build_draft_bundle(project)
        except Exception as exc:
            st.error(f"초안 묶음을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
        else:
            st.download_button(
                "두 보고서 검토용 초안 ZIP으로 한 번에 다운로드",
                data=bundle_bytes,
                file_name=f"{project.project_id}_{'AI보강_' if any_ai else ''}보고서_검토용_초안.zip",
                mime="application/zip",
                key=f"download_draft_bundle_{project.project_id}",
                width="stretch",
            )

with export_tab:
    st.warning(
        "이 탭의 파일은 감사·자료요청 관리용입니다. 법정 제출용 최종본은 최종 검증 gate가 완성된 뒤 활성화합니다."
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
