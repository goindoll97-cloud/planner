from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from engine.stage2.ai_drafting import (
    ai_draft_field_key,
    ai_draftable_specs,
    approve_ai_draft,
    build_operating_profile,
    generate_system_ai_drafts,
    remove_ai_draft,
)
from engine.stage2.ai_report import (
    build_ai_enhanced_draft_bundle,
    build_ai_enhanced_report_draft,
    has_ai_report_prose,
)
from engine.stage2.cap_hwpx import (
    build_cap_hwpx_draft,
    cap_hwpx_filename,
    normalize_cap_template_upload,
    register_cap_template,
    registered_cap_template,
)
from engine.stage2.cap_requests import build_cap_data_requests
from engine.stage2.completeness import evaluate_project_completeness
from engine.stage2.export import build_progress_workbook
from engine.stage2.intake import field_label, selected_requirement_specs
from engine.stage2.local_llm import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OPENAI_COMPATIBLE_URL,
    LocalLLMConfig,
    build_local_llm_client,
    local_llm_config_from_sources,
    local_runtime_label,
    local_runtime_not_ready_message,
    probe_local_llm_runtime,
    validate_local_base_url,
)
from engine.stage2.psm_requests import build_psm_data_requests
from engine.stage2.report_draft import (
    build_draft_bundle,
    build_report_draft,
    draft_filename,
    report_generation_status,
)
from engine.stage2.storage import (
    list_projects,
    load_project,
    project_json_bytes,
    save_attachment,
    save_project,
)


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {"COMMON": "공통자료", "PSM": PSM_FULL, "CAP": CAP_FULL}
LOCAL_LLM_SETTING_KEYS = (
    "LOCAL_LLM_PROVIDER",
    "LOCAL_LLM_MODEL",
    "LOCAL_LLM_URL",
    "LOCAL_LLM_TIMEOUT_SECONDS",
    "LOCAL_LLM_MAX_OUTPUT_TOKENS",
)


def _local_llm_values() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for key in LOCAL_LLM_SETTING_KEYS:
            value = st.secrets.get(key)
            if value not in (None, ""):
                values[key] = str(value)
    except Exception:
        pass
    return values


def _project_selector() -> str | None:
    projects = list_projects()
    if not projects:
        st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단과 2. 작성범위 선택을 진행하세요.")
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
    selected = st.selectbox("작성 프로젝트", ids, index=index, format_func=lambda pid: labels.get(pid, pid))
    st.session_state[ACTIVE_PROJECT_KEY] = selected
    return selected


def _render_status_metrics(project, system: str) -> None:
    status = report_generation_status(project, system)
    m1, m2, m3 = st.columns(3)
    m1.metric("작성완성도", f"{status.completion_pct:.1f}%")
    m2.metric("작성상태", status.state)
    m3.metric("미해결 필드", status.unresolved_n)


def _render_docx_fallback(project, system: str, label: str, *, key_suffix: str = "") -> None:
    ai_applied = has_ai_report_prose(project, system)
    try:
        if ai_applied:
            draft_bytes = build_ai_enhanced_report_draft(project, system)
            file_name = draft_filename(project, system).replace(
                "_검토용_초안.docx", "_AI보강_검토용_초안.docx"
            )
            button_label = f"{label} AI 보강 보조 검토용 DOCX 다운로드"
        else:
            draft_bytes = build_report_draft(project, system)
            file_name = draft_filename(project, system)
            button_label = f"{label} 보조 검토용 DOCX 다운로드"
    except Exception as exc:
        st.error(f"{label} 보조 검토본을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
        return

    st.download_button(
        button_label,
        data=draft_bytes,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"download_docx_{system}_{project.project_id}_{key_suffix}",
        width="stretch",
    )
    if ai_applied:
        try:
            baseline = build_report_draft(project, system)
        except Exception:
            return
        st.download_button(
            f"{label} AI 보강 전 원자료형 DOCX 다운로드",
            data=baseline,
            file_name=draft_filename(project, system),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"download_docx_baseline_{system}_{project.project_id}_{key_suffix}",
            width="stretch",
        )


st.set_page_config(page_title="작성·검토", page_icon="📝", layout="wide")
st.title("📝 5. 작성·검토")
st.caption(
    "선택한 작성범위만 대상으로 작성현황을 검토하고, 회사 담당자가 확인한 사실과 로컬 AI 보강 초안을 관리합니다."
)

project_id = _project_selector()
if not project_id:
    st.stop()

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
c1.metric("전체 작성률", f"{completeness['overall']['completion_pct']:.1f}%")
c2.metric("완료 작성항목", completeness["overall"]["ready_n"])
c3.metric("프로그램 작성상태", completeness["overall"]["state"])

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
    st.markdown("### 사업장 사실 기반 로컬 AI 문장 보강")
    st.info(
        "AI는 법적 대상 여부나 1·2군을 다시 판단하지 않습니다. 규칙 기반 판정으로 정해진 작성범위와 확인된 회사자료만 사용하며, "
        "없는 수치·설비·인원·주기·절차는 만들지 않습니다."
    )
    st.success(
        "회사 정보 보호를 위해 AI 문장 보강은 같은 PC의 로컬 AI만 사용합니다. 127.0.0.1/localhost/::1 주소만 허용합니다."
    )

    profile = build_operating_profile(project)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("화학물질", profile["chemical_count"])
    p2.metric("주요 설비", profile["facility_count"])
    p3.metric("안전밸브·파열판", profile["relief_device_count"])
    p4.metric("가스감지기", profile["gas_detector_count"])

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

    try:
        base_config = local_llm_config_from_sources(_local_llm_values())
    except Exception as exc:
        st.error(f"로컬 AI 기본설정을 읽지 못했습니다: {exc}")
        base_config = LocalLLMConfig()

    provider_options = ["ollama", "openai_compatible"]
    provider = st.selectbox(
        "로컬 AI 실행기",
        provider_options,
        index=provider_options.index(base_config.provider) if base_config.provider in provider_options else 0,
        format_func=lambda value: "Ollama" if value == "ollama" else "LM Studio/llama.cpp 등 OpenAI 호환 로컬 서버",
        key="stage2_local_llm_provider",
    )
    model = st.text_input("로컬 모델 이름", value=base_config.model or DEFAULT_MODEL, key="stage2_local_llm_model")
    default_url = (
        base_config.base_url
        if base_config.provider == provider
        else (DEFAULT_OLLAMA_URL if provider == "ollama" else DEFAULT_OPENAI_COMPATIBLE_URL)
    )
    local_url = st.text_input("로컬 AI 주소", value=default_url, key="stage2_local_llm_url")

    local_config = None
    runtime_probe = None
    try:
        local_config = LocalLLMConfig(
            provider=provider,
            model=model.strip() or DEFAULT_MODEL,
            base_url=validate_local_base_url(local_url),
            timeout_seconds=base_config.timeout_seconds,
            max_output_tokens=base_config.max_output_tokens,
        )
        st.caption("현재 로컬 AI 설정: " + local_runtime_label(local_config))
        runtime_probe = probe_local_llm_runtime(local_config)
    except Exception as exc:
        st.error(str(exc))
    else:
        if runtime_probe.ready:
            st.success(runtime_probe.message)
        else:
            st.warning(local_runtime_not_ready_message(local_config, runtime_probe))

    if st.button(
        f"{SYSTEM_LABELS[ai_system]} 로컬 AI 문장 보강 생성",
        type="primary",
        disabled=(not candidates or local_config is None or runtime_probe is None or not runtime_probe.ready),
        width="stretch",
    ):
        try:
            client = build_local_llm_client(local_config)
            with st.spinner("확인된 사업장 사실과 법적 작성구조를 바탕으로 문장을 보강하고 있습니다..."):
                result = generate_system_ai_drafts(project, ai_system, client, store_safe_drafts=True)
                save_project(project)
        except Exception as exc:
            st.error(f"로컬 AI 문장 보강에 실패했습니다: {type(exc).__name__}: {exc}")
        else:
            st.session_state["stage2_ai_flash"] = (
                f"{result.system_label}: 안전검증 통과 {len(result.generated)}개, 자동 저장 거부 {len(result.rejected)}개"
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
                st.caption("사업장 운영·위험 특성: " + profile_summary)
            suggestions = payload.get("suggested_additions") or []
            if suggestions:
                st.warning("추가 확인하면 좋은 내용\n\n- " + "\n- ".join(str(v) for v in suggestions))
            edited = st.text_area(
                "보고서 보강문장",
                value=str(payload.get("draft_text") or ""),
                height=180,
                key=f"ai_draft_text_{project.project_id}_{ai_system}_{spec.key}",
            )
            st.caption("이 문장은 확인된 회사 사실을 바꾸거나 새로운 법적 의무를 생성하지 않습니다.")
            left, right = st.columns(2)
            with left:
                if st.button("담당자 검토·승인", key=f"approve_ai_{project.project_id}_{ai_system}_{spec.key}", width="stretch"):
                    try:
                        approve_ai_draft(project, ai_system, spec.key, edited)
                        save_project(project)
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()
            with right:
                if st.button("AI 보강문장 삭제", key=f"remove_ai_{project.project_id}_{ai_system}_{spec.key}", width="stretch"):
                    remove_ai_draft(project, ai_system, spec.key)
                    save_project(project)
                    st.rerun()

with draft_tab:
    st.markdown("### 보고서 초안 생성")
    st.warning(
        "HOLD, 미확인 값 또는 미승인 AI 문장이 남아 있어도 검토용 초안은 만들 수 있지만, 최종 제출 가능 상태를 의미하지는 않습니다."
    )

    if project.cap_in_scope:
        st.markdown("#### 화학사고예방관리계획서 · 법제처 원본서식 HWPX")
        st.info(
            "화학사고예방관리계획서는 프로그램이 표를 새로 그리지 않습니다. 국가법령정보센터에서 받은 현행 HWPX 원본의 "
            "셀 병합·열 너비·행 높이·글꼴·주석·페이지 구조를 그대로 두고, 고유하게 식별되는 칸에만 회사 확인값을 입력합니다."
        )
        st.caption(
            "권장: 법제처 원본 .hwpx. .hwp만 있는 경우에는 Windows PC에 한컴오피스와 pyhwpx가 설치되어 있을 때 HWPX로 변환한 뒤 사용합니다. "
            "DOCX로 변환된 서식은 법정 원본 레이아웃 템플릿으로 등록하지 않습니다."
        )

        template_upload = st.file_uploader(
            "법제처 CAP 별표·별지 원본 HWPX/HWP 등록 또는 교체",
            type=["hwpx", "hwp"],
            key=f"cap_official_hwpx_{project.project_id}",
        )
        if template_upload is not None and st.button(
            "법제처 원본서식 등록·검증",
            type="primary",
            width="stretch",
            key=f"register_cap_hwpx_{project.project_id}",
        ):
            try:
                normalized, source_format = normalize_cap_template_upload(
                    template_upload.name,
                    template_upload.getvalue(),
                )
                original = Path(template_upload.name)
                stored_name = original.name if original.suffix.lower() == ".hwpx" else f"{original.stem}_converted.hwpx"
                evidence = save_attachment(
                    project.project_id,
                    stored_name,
                    normalized,
                    source_type="OFFICIAL_LEGAL_TEMPLATE",
                    note=(
                        "국가법령정보센터 CAP 별표·별지 원본서식. 법정 출력 레이아웃 기준으로 사용하며 "
                        "회사 사실 또는 규제판정 근거 자체로 사용하지 않음."
                    ),
                )
                validation = register_cap_template(
                    project,
                    evidence=evidence,
                    hwpx_bytes=normalized,
                    source_format=source_format,
                )
                save_project(project)
            except Exception as exc:
                st.error(f"법제처 원본서식을 등록하지 못했습니다: {type(exc).__name__}: {exc}")
            else:
                st.session_state["cap_hwpx_flash"] = (
                    f"법제처 원본서식 검증 완료 · 별지 표식 {len(validation.found_markers)}개 · SHA-256 {validation.sha256[:12]}…"
                )
                st.rerun()

        hwpx_flash = st.session_state.pop("cap_hwpx_flash", None)
        if hwpx_flash:
            st.success(hwpx_flash)

        template_meta = registered_cap_template(project)
        if not template_meta:
            st.warning(
                "아직 법제처 원본 HWPX가 등록되지 않았습니다. 현재 가지고 있는 DOCX 변환본은 내용 대조용으로는 사용할 수 있지만, "
                "원본서식 보존 출력에는 법제처에서 받은 .hwpx 또는 .hwp 원본이 필요합니다."
            )
        else:
            st.success(
                f"등록 원본: {template_meta.get('file_name', '')} · {template_meta.get('source_format', '')} · "
                f"SHA-256 {str(template_meta.get('sha256', ''))[:12]}…"
            )
            _render_status_metrics(project, "CAP")
            try:
                hwpx_result = build_cap_hwpx_draft(project)
            except Exception as exc:
                st.error(f"법제처 원본서식 HWPX 작성본을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
            else:
                st.download_button(
                    "화학사고예방관리계획서 법제처 원본서식 HWPX 작성본 다운로드",
                    data=hwpx_result.data,
                    file_name=cap_hwpx_filename(project),
                    mime="application/vnd.hancom.hwpx",
                    key=f"download_cap_hwpx_{project.project_id}",
                    width="stretch",
                    type="primary",
                )
                st.caption(
                    f"원본 HWPX에서 자동 입력한 셀 {hwpx_result.applied_count}개. 자동으로 고유하게 찾을 수 없는 칸은 추측해서 입력하지 않습니다."
                )
                if hwpx_result.warnings:
                    with st.expander(f"HWPX 자동입력 보류·확인사항 {len(hwpx_result.warnings)}건", expanded=False):
                        for warning in hwpx_result.warnings:
                            st.markdown(f"- {warning}")

        with st.expander("화학사고예방관리계획서 보조 검토용 DOCX", expanded=False):
            st.caption(
                "DOCX는 회사자료와 AI 보강문장을 검토하기 위한 보조자료입니다. 법제처 원본 HWPX 서식을 재현한 제출서식으로 간주하지 않습니다."
            )
            _render_docx_fallback(project, "CAP", CAP_FULL, key_suffix="cap_fallback")

    if project.psm_in_scope:
        st.divider()
        st.markdown("#### 공정안전보고서")
        _render_status_metrics(project, "PSM")
        st.info("공정안전보고서는 현재 법정 작성구조 기반 DOCX 검토본을 생성합니다. PSM 원본 HWPX 서식 적용은 별도 전환 대상입니다.")
        _render_docx_fallback(project, "PSM", PSM_FULL, key_suffix="psm")

    if project.psm_in_scope and project.cap_in_scope:
        with st.expander("두 보고서 보조 검토용 DOCX 묶음", expanded=False):
            any_ai = any(has_ai_report_prose(project, system) for system in ("PSM", "CAP"))
            try:
                bundle_bytes = build_ai_enhanced_draft_bundle(project) if any_ai else build_draft_bundle(project)
            except Exception as exc:
                st.error(f"보조 검토본 묶음을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
            else:
                st.download_button(
                    "PSM·CAP 보조 검토용 DOCX ZIP 다운로드",
                    data=bundle_bytes,
                    file_name=f"{project.project_id}_{'AI보강_' if any_ai else ''}보조_검토용_DOCX.zip",
                    mime="application/zip",
                    key=f"download_draft_bundle_{project.project_id}",
                    width="stretch",
                )

with export_tab:
    st.warning(
        "이 탭의 파일은 감사·자료요청 관리용입니다. 법정 제출용 최종본은 최종 검증 단계가 완성된 뒤 활성화합니다."
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
