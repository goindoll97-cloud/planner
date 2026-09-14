from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.stage2.ai_drafting import (
    ai_draft_field_key,
    ai_draftable_specs,
    generate_system_ai_drafts,
)
from engine.stage2.ai_report import build_ai_enhanced_report_draft, has_ai_report_prose
from engine.stage2.cap_hwpx import (
    build_cap_hwpx_draft,
    cap_hwpx_filename,
    normalize_cap_template_upload,
    register_cap_template,
    registered_cap_template,
)
from engine.stage2.cap_requests import build_cap_data_requests
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
from engine.stage2.report_draft import build_report_draft, draft_filename
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project
from engine.stage2.workflow import validation_confirmed


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {"PSM": PSM_FULL, "CAP": CAP_FULL}
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
        st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단부터 진행하세요.")
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


def _systems(project) -> list[str]:
    out: list[str] = []
    if project.psm_in_scope:
        out.append("PSM")
    if project.cap_in_scope:
        out.append("CAP")
    return out


def _draft_exists(project, system: str, requirement_key: str) -> bool:
    record = project.get_field(ai_draft_field_key(system, requirement_key))
    return bool(
        record
        and isinstance(record.value, dict)
        and str(record.value.get("draft_text") or "").strip()
    )


def _ai_fingerprint(project, system: str, missing_keys: list[str], config: LocalLLMConfig) -> str:
    # AI-generated fields are excluded so saving a successful batch does not
    # trigger the same generation again. Any company/source fact change does.
    source_rows = []
    for key in sorted(project.fields):
        if key.startswith("ai_draft."):
            continue
        record = project.fields[key]
        source_rows.append((key, record.status, record.value))
    payload = {
        "project": project.project_id,
        "system": system,
        "missing": sorted(missing_keys),
        "provider": config.provider,
        "model": config.model,
        "url": config.base_url,
        "facts": source_rows,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def _render_shortages(project) -> None:
    rows: list[dict[str, str]] = []
    if project.psm_in_scope:
        for item in build_psm_data_requests(project):
            rows.append({
                "구분": PSM_FULL,
                "작성항목": item.label,
                "부족자료": ", ".join(item.missing_labels),
                "확인 가능한 자료": ", ".join(item.suggested_evidence),
                "작성근거": item.legal_basis,
                "요청사항": item.request_text,
            })
    if project.cap_in_scope:
        for item in build_cap_data_requests(project):
            rows.append({
                "구분": CAP_FULL,
                "작성항목": item.label,
                "부족자료": ", ".join(item.missing_labels),
                "확인 가능한 자료": ", ".join(item.suggested_evidence),
                "작성근거": getattr(item, "legal_basis", ""),
                "요청사항": item.request_text,
            })

    if rows:
        st.warning(f"현재 추가 확인이 필요한 작성자료가 {len(rows)}건 있습니다.")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.page_link("ui/stage2_intake_page.py", label="3. 통합 작성자료에서 보완", icon="📥")
    else:
        st.success("현재 요청자료 기준으로 추가 확인할 부족자료가 없습니다.")


def _build_local_config() -> tuple[LocalLLMConfig | None, object | None]:
    try:
        base = local_llm_config_from_sources(_local_llm_values())
    except Exception as exc:
        st.warning(f"로컬 AI 기본설정을 읽지 못했습니다: {exc}")
        base = LocalLLMConfig()

    with st.expander("로컬 AI 설정 · 필요할 때만 변경", expanded=False):
        st.caption(
            "회사정보는 외부 AI로 보내지 않습니다. 127.0.0.1/localhost/::1의 Ollama 또는 LM Studio 같은 로컬 서버만 허용합니다."
        )
        provider_options = ["ollama", "openai_compatible"]
        provider = st.selectbox(
            "로컬 AI 실행기",
            provider_options,
            index=provider_options.index(base.provider) if base.provider in provider_options else 0,
            format_func=lambda value: "Ollama" if value == "ollama" else "LM Studio/llama.cpp 등 OpenAI 호환 로컬 서버",
            key="stage2_local_llm_provider",
        )
        model = st.text_input("로컬 모델 이름", value=base.model or DEFAULT_MODEL, key="stage2_local_llm_model")
        default_url = (
            base.base_url
            if base.provider == provider
            else (DEFAULT_OLLAMA_URL if provider == "ollama" else DEFAULT_OPENAI_COMPATIBLE_URL)
        )
        local_url = st.text_input("로컬 AI 주소", value=default_url, key="stage2_local_llm_url")

    try:
        config = LocalLLMConfig(
            provider=provider,
            model=model.strip() or DEFAULT_MODEL,
            base_url=validate_local_base_url(local_url),
            timeout_seconds=base.timeout_seconds,
            max_output_tokens=base.max_output_tokens,
        )
        probe = probe_local_llm_runtime(config)
        return config, probe
    except Exception as exc:
        st.warning(str(exc))
        return None, None


def _run_automatic_ai(project, config: LocalLLMConfig | None, probe) -> list[dict[str, object]]:
    statuses: list[dict[str, object]] = []
    for system in _systems(project):
        try:
            candidates = ai_draftable_specs(project, system)
        except Exception as exc:
            statuses.append({"system": system, "state": "ERROR", "message": str(exc), "generated": 0, "total": 0})
            continue

        missing = [spec for spec in candidates if not _draft_exists(project, system, spec.key)]
        if not candidates:
            statuses.append({
                "system": system,
                "state": "NO_CANDIDATE",
                "message": "현재 확인자료에서 자동 문장보강이 필요한 항목이 없습니다.",
                "generated": 0,
                "total": 0,
            })
            continue
        if not missing:
            statuses.append({
                "system": system,
                "state": "READY",
                "message": "AI 문장보강이 준비되어 있습니다.",
                "generated": len(candidates),
                "total": len(candidates),
            })
            continue
        if config is None or probe is None or not getattr(probe, "ready", False):
            message = (
                local_runtime_not_ready_message(config, probe)
                if config is not None and probe is not None
                else "로컬 AI 실행상태를 확인할 수 없습니다."
            )
            statuses.append({
                "system": system,
                "state": "RUNTIME_NOT_READY",
                "message": message,
                "generated": len(candidates) - len(missing),
                "total": len(candidates),
            })
            continue

        fingerprint = _ai_fingerprint(project, system, [spec.key for spec in missing], config)
        attempt_key = f"stage2_auto_ai_attempt::{project.project_id}::{system}"
        error_key = f"stage2_auto_ai_error::{project.project_id}::{system}"
        if st.session_state.get(attempt_key) == fingerprint:
            statuses.append({
                "system": system,
                "state": "PARTIAL" if len(missing) < len(candidates) else "FAILED",
                "message": str(st.session_state.get(error_key) or "자동 문장보강을 이미 시도했습니다."),
                "generated": len(candidates) - len(missing),
                "total": len(candidates),
            })
            continue

        # Mark before the slow call so a Streamlit rerun cannot start an
        # accidental duplicate generation for the same source facts.
        st.session_state[attempt_key] = fingerprint
        st.session_state.pop(error_key, None)
        try:
            client = build_local_llm_client(config)
            result = generate_system_ai_drafts(project, system, client, store_safe_drafts=True)
            save_project(project)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            st.session_state[error_key] = message
            now_generated = sum(1 for spec in candidates if _draft_exists(project, system, spec.key))
            statuses.append({
                "system": system,
                "state": "PARTIAL" if now_generated else "FAILED",
                "message": message,
                "generated": now_generated,
                "total": len(candidates),
            })
        else:
            now_generated = sum(1 for spec in candidates if _draft_exists(project, system, spec.key))
            statuses.append({
                "system": system,
                "state": "READY" if now_generated == len(candidates) else "PARTIAL",
                "message": (
                    f"자동 문장보강 완료 · 저장 {len(result.generated)}개"
                    + (f" · 안전검증 보류 {len(result.rejected)}개" if result.rejected else "")
                ),
                "generated": now_generated,
                "total": len(candidates),
            })
    return statuses


def _render_ai_status(project) -> None:
    st.info(
        "AI 문장보강은 별도 생성 버튼 없이 자동으로 수행됩니다. 법적 대상 여부와 작성수준은 다시 판단하지 않고, 확인된 회사자료만 문장으로 정리합니다."
    )
    config, probe = _build_local_config()
    if config is not None:
        st.caption("현재 로컬 AI: " + local_runtime_label(config))
    if probe is not None and getattr(probe, "ready", False):
        st.success(str(getattr(probe, "message", "로컬 AI를 사용할 수 있습니다.")))

    with st.spinner("필요한 항목의 로컬 AI 문장보강을 자동 확인하고 있습니다..."):
        statuses = _run_automatic_ai(project, config, probe)

    for item in statuses:
        label = SYSTEM_LABELS.get(str(item["system"]), str(item["system"]))
        state = str(item["state"])
        text = f"{label}: {item['generated']}/{item['total']}개 · {item['message']}"
        if state == "READY":
            st.success(text)
        elif state in {"NO_CANDIDATE"}:
            st.caption(text)
        elif state in {"PARTIAL", "RUNTIME_NOT_READY"}:
            st.warning(text)
        else:
            st.error(text)

    st.caption("AI 보강에 실패하거나 일부 항목이 보류되어도 AI 보강 없는 기본 초안은 항상 만들 수 있습니다.")

    for system in _systems(project):
        entries = []
        for spec in ai_draftable_specs(project, system):
            record = project.get_field(ai_draft_field_key(system, spec.key))
            if record and isinstance(record.value, dict) and str(record.value.get("draft_text") or "").strip():
                entries.append((spec, record))
        if not entries:
            continue
        with st.expander(f"{SYSTEM_LABELS[system]} 자동 보강문장 확인 · {len(entries)}개", expanded=False):
            for spec, record in entries:
                st.markdown(f"**{spec.section} · {spec.label}**")
                st.write(str(record.value.get("draft_text") or ""))
                suggestions = record.value.get("suggested_additions") or []
                if suggestions:
                    st.caption("추가 확인: " + " / ".join(str(v) for v in suggestions))
                st.divider()


def _render_docx_pair(project, system: str, label: str) -> None:
    try:
        baseline = build_report_draft(project, system)
    except Exception as exc:
        st.error(f"{label} 기본 초안을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
        return

    left, right = st.columns(2)
    left.download_button(
        f"{label} · AI 보강 없음",
        data=baseline,
        file_name=draft_filename(project, system),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key=f"draft_plain_{project.project_id}_{system}",
        width="stretch",
        type="primary",
    )

    if has_ai_report_prose(project, system):
        try:
            enhanced = build_ai_enhanced_report_draft(project, system)
        except Exception as exc:
            right.warning(f"AI 보강본 생성 실패: {type(exc).__name__}: {exc}")
        else:
            right.download_button(
                f"{label} · AI 보강 포함",
                data=enhanced,
                file_name=draft_filename(project, system).replace("_검토용_초안.docx", "_AI보강_검토용_초안.docx"),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"draft_ai_{project.project_id}_{system}",
                width="stretch",
                type="primary",
            )
    else:
        right.info("아직 사용할 수 있는 AI 보강문장이 없어 기본 초안만 제공합니다.")


def _render_cap_hwpx(project) -> None:
    st.markdown("#### 화학사고예방관리계획서 · 법제처 원본서식 HWPX")
    template_meta = registered_cap_template(project)
    if not template_meta:
        st.warning("현재 승인된 법제처 원본 HWPX를 찾지 못했습니다. 최신 법령자료를 확인하거나 원본서식을 등록해야 합니다.")
        with st.expander("법제처 원본서식 직접 등록 · 필요한 경우만", expanded=False):
            upload = st.file_uploader(
                "법제처 CAP 별표·별지 원본 HWPX/HWP",
                type=["hwpx", "hwp"],
                key=f"cap_official_hwpx_{project.project_id}",
            )
            if upload is not None and st.button(
                "원본서식 등록",
                key=f"register_cap_hwpx_{project.project_id}",
                width="stretch",
            ):
                try:
                    normalized, source_format = normalize_cap_template_upload(upload.name, upload.getvalue())
                    original = Path(upload.name)
                    stored_name = original.name if original.suffix.lower() == ".hwpx" else f"{original.stem}_converted.hwpx"
                    evidence = save_attachment(
                        project.project_id,
                        stored_name,
                        normalized,
                        source_type="OFFICIAL_LEGAL_TEMPLATE",
                        note="국가법령정보센터 CAP 별표·별지 원본서식",
                    )
                    register_cap_template(
                        project,
                        evidence=evidence,
                        hwpx_bytes=normalized,
                        source_format=source_format,
                    )
                    save_project(project)
                except Exception as exc:
                    st.error(f"법제처 원본서식을 등록하지 못했습니다: {type(exc).__name__}: {exc}")
                else:
                    st.rerun()
        return

    try:
        result = build_cap_hwpx_draft(project)
    except Exception as exc:
        st.error(f"법제처 원본서식 HWPX 작성본을 생성하지 못했습니다: {type(exc).__name__}: {exc}")
        return

    st.download_button(
        "화학사고예방관리계획서 법제처 원본서식 HWPX · 확인값 기준",
        data=result.data,
        file_name=cap_hwpx_filename(project),
        mime="application/vnd.hancom.hwpx",
        key=f"download_cap_hwpx_{project.project_id}",
        width="stretch",
        type="primary",
    )
    st.caption(
        "HWPX는 법제처 원본서식을 그대로 사용하고 확인된 회사값만 입력합니다. 현재 AI 문장보강 비교본은 아래 DOCX 초안에서 선택할 수 있습니다."
    )
    if result.warnings:
        with st.expander(f"HWPX 자동입력 확인사항 · {len(result.warnings)}건", expanded=False):
            for warning in result.warnings:
                st.write(f"• {warning}")


st.set_page_config(page_title="작성·검토", page_icon="📝", layout="wide")
st.title("📝 5. 작성·검토")
st.caption("부족자료를 확인하고, 로컬 AI가 자동으로 문장을 보강한 뒤, 기본 초안과 AI 보강 초안을 선택해 내려받습니다.")

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
if not validation_confirmed(project):
    st.warning("4. 작성자료 교차검증 확인이 완료되지 않았습니다.")
    st.page_link("ui/stage2_validation_page.py", label="4. 작성자료 교차검증으로 이동", icon="🔎")
    st.stop()

scope = [SYSTEM_LABELS[system] for system in _systems(project)]
st.success("현재 작성범위: " + ", ".join(scope))

shortage_tab, ai_tab, draft_tab = st.tabs(["부족자료", "AI 문장보강", "보고서 초안 생성"])

with shortage_tab:
    _render_shortages(project)

with ai_tab:
    _render_ai_status(project)

with draft_tab:
    st.info("같은 자료로 만든 기본 초안과 AI 보강 초안을 나란히 제공합니다. AI 보강본도 검토용이며 회사 확인자료를 대체하지 않습니다.")
    if project.cap_in_scope:
        _render_cap_hwpx(project)
        st.markdown("#### 화학사고예방관리계획서 · 비교용 DOCX 초안")
        _render_docx_pair(project, "CAP", CAP_FULL)
    if project.psm_in_scope:
        if project.cap_in_scope:
            st.divider()
        st.markdown("#### 공정안전보고서")
        _render_docx_pair(project, "PSM", PSM_FULL)
