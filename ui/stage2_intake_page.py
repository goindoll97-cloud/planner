from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2.intake import (
    COVERAGE_CONFIRMED,
    COVERAGE_NOT_APPLICABLE,
    build_intake_catalog,
    build_missing_request_text,
    build_program_input_workbook,
    intake_summary,
)
from engine.stage2.official_forms import (
    list_official_forms_for_program,
    official_form_bytes,
    resolve_official_form,
)
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


st.set_page_config(page_title="자료준비·접수", page_icon="📥", layout="wide")
st.title("📥 3. 자료준비·접수")
st.caption(
    "선택한 작성문서의 작성항목, 작성근거, 관련 법정 서식·참고자료를 먼저 확인하고 회사가 보유한 자료를 접수합니다. "
    "파일이 접수되었다는 사실과 그 내용이 확인되었다는 사실을 구분합니다."
)


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


def _download_form(form, *, key: str) -> None:
    left, right = st.columns([4, 1])
    left.write(f"**{form.form_reference}** · {form.source_title}")
    meta = []
    if form.effective_date:
        meta.append(f"시행일 {form.effective_date}")
    if form.issue_number:
        meta.append(f"발령번호 {form.issue_number}")
    meta.append(f"SHA-256 {form.sha256}")
    left.caption(" · ".join(meta))
    right.download_button(
        "공식 PDF",
        data=official_form_bytes(form),
        file_name=form.file_name,
        mime="application/pdf",
        key=key,
        width="stretch",
    )


def _render_reference_form(reference: str, *, key_prefix: str) -> None:
    matches = resolve_official_form(reference)
    if len(matches) == 1:
        _download_form(matches[0], key=f"{key_prefix}_{matches[0].law_key}_{reference}")
    elif len(matches) > 1:
        st.warning(
            f"{reference}: 현재 공식자료에서 둘 이상의 서식이 연결되어 자동 선택하지 않습니다. "
            "법령 근거 화면에서 적용 법령·고시를 확인해 주세요."
        )
    else:
        st.warning(
            f"{reference}: 현재 법령감시에서 CURRENT로 확인된 공식 PDF를 찾지 못했습니다. "
            "규정 DB 관리에서 최신 공식본 확인 후 다시 시도해 주세요."
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
    st.warning("이번 프로젝트에서 작성할 문서가 아직 선택되지 않았습니다.")
    st.page_link("ui/stage2_scope_page.py", label="2. 작성범위 선택으로 이동", icon="🧭")
    st.stop()

scope_labels = []
if project.psm_in_scope:
    scope_labels.append(PSM_FULL)
if project.cap_in_scope:
    scope_labels.append(CAP_FULL)
st.success("현재 작성범위: " + ", ".join(scope_labels))

st.markdown("### 현행 공식 법정 서식")
st.caption(
    "법제처 공식자료에서 내려받아 현재 감시상태가 CURRENT인 별지서식 PDF만 제공합니다. "
    "프로그램이 서식을 재작성하거나 임의 변환하지 않습니다."
)
form_count = 0
for program in scope_labels:
    forms = list_official_forms_for_program(program)
    if not forms:
        st.warning(
            f"{program}: 현재 CURRENT 상태로 직접 제공할 공식 별지서식 PDF가 없습니다. "
            "법령 최신성 또는 공식 첨부파일 상태를 확인해 주세요."
        )
        continue
    with st.expander(f"{program} 공식 별지서식 {len(forms)}건", expanded=False):
        for idx, form in enumerate(forms):
            _download_form(form, key=f"scope_form_{program}_{idx}_{form.law_key}")
            form_count += 1
if form_count == 0:
    st.info("공식 서식 다운로드가 비활성화된 경우에도 아래 작성근거와 부족자료 안내는 계속 확인할 수 있습니다.")

summary = intake_summary(project)
catalog = build_intake_catalog(project)
counts = summary["counts"]

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("확인", counts.get("확인", 0))
with c2:
    st.metric("일부 확인", counts.get("일부 확인", 0))
with c3:
    st.metric("사람 확인 필요", counts.get("사람 확인 필요", 0))
with c4:
    st.metric("자료 요청 필요", counts.get("자료 요청 필요", 0))

st.info(
    "자료상태는 프로그램 내부 업무상태입니다. 법령상의 판정용어가 아닙니다. "
    "파일만 업로드된 경우에는 내용을 확인하기 전까지 ‘사람 확인 필요’로 남깁니다."
)

st.markdown("### 작성에 필요한 자료와 근거")
rows = []
for item in catalog:
    rows.append({
        "구분": item.system_label,
        "작성구조": item.section,
        "작성항목": item.label,
        "자료상태": item.coverage_status,
        "현재 확인되지 않은 항목": ", ".join(item.missing_labels),
        "접수 후 확인이 필요한 항목": ", ".join(item.received_unconfirmed_labels),
        "확인 가능한 자료 예": ", ".join(item.suggested_evidence),
        "관련 법정 서식": ", ".join(item.form_references),
        "작성근거": item.legal_basis,
        "작성 참고자료": item.reference_label,
        "관련 쪽": ", ".join(str(v) for v in item.reference_pages),
    })
if rows:
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.info("현재 선택한 작성범위에 표시할 작성항목이 없습니다.")

left, right = st.columns(2)
with left:
    st.download_button(
        "프로그램 입력양식 XLSX 다운로드",
        data=build_program_input_workbook(project),
        file_name=f"{project.project_id}_자료준비_프로그램입력양식.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        help="법정 별지서식이 아니라 회사자료 정리 편의를 위한 프로그램 입력양식입니다.",
    )
with right:
    st.page_link(
        "ui/legal_evidence_page.py",
        label="법령·공식 근거자료 확인",
        icon="📚",
        help="법정 별지서식이 있는 경우 현행 법령·고시 원문을 여기서 확인합니다.",
    )

st.caption(
    "‘프로그램 입력양식’은 법정 서식이 아닙니다. ‘관련 법정 서식’이 표시된 항목은 현행 법령·고시의 별지서식을 우선 확인해야 합니다."
)

unresolved = [
    item for item in catalog
    if item.coverage_status not in {COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE}
]

st.markdown("### 부족하거나 추가 확인이 필요한 자료")
if not unresolved:
    st.success("현재 자료준비 단계에서 추가 요청할 항목이 없습니다.")
else:
    for item in unresolved:
        icon = "❌" if item.coverage_status == "자료 요청 필요" else "⚠️"
        title = f"{icon} [{item.system_label}] {item.section} · {item.label} — {item.coverage_status}"
        with st.expander(title, expanded=False):
            st.text(build_missing_request_text(item))
            if item.form_references:
                st.write("**관련 법정 서식**")
                for form in item.form_references:
                    _render_reference_form(form, key_prefix=f"missing_{item.requirement_key}")
            if item.legal_basis:
                st.write("**작성근거**")
                st.code(item.legal_basis)
            if item.reference_label:
                pages = ", ".join(str(v) for v in item.reference_pages)
                st.write(f"**작성 참고자료**: {item.reference_label}" + (f" · 관련 쪽 {pages}" if pages else ""))
            st.page_link("ui/legal_evidence_page.py", label="관련 법령·서식 원문 확인", icon="📚")

st.markdown("### 회사자료 업로드")
st.caption(
    "보유 중인 기존 자료를 먼저 올리세요. 별도 법정 서식으로 다시 작성해야 하는지는 접수자료와 작성근거를 비교한 뒤 부족항목에서 안내합니다."
)

upload_candidates = catalog if not unresolved else unresolved
if not upload_candidates:
    st.info("업로드 대상 작성항목이 없습니다.")
else:
    item_map = {item.requirement_key: item for item in upload_candidates}
    requirement_key = st.selectbox(
        "자료와 연결할 작성항목",
        list(item_map),
        format_func=lambda key: f"[{item_map[key].system_label}] {item_map[key].section} · {item_map[key].label}",
    )
    selected_item = item_map[requirement_key]

    candidate_fields = list(selected_item.received_unconfirmed_fields + selected_item.missing_fields)
    if not candidate_fields:
        candidate_fields = list(selected_item.confirmed_fields)

    if not candidate_fields:
        st.warning("이 작성항목은 개별 데이터 필드가 없어 현재 파일 직접 연결 대상이 아닙니다. 작성근거를 확인해 주세요.")
    else:
        label_map = {
            key: label
            for key, label in zip(
                selected_item.confirmed_fields + selected_item.received_unconfirmed_fields + selected_item.missing_fields,
                selected_item.confirmed_labels + selected_item.received_unconfirmed_labels + selected_item.missing_labels,
            )
        }
        field_key = st.selectbox("자료로 확인할 내용", candidate_fields, format_func=lambda key: label_map.get(key, key))
        uploads = st.file_uploader(
            "회사 보유자료 업로드",
            accept_multiple_files=True,
            key=f"intake_upload_{requirement_key}_{field_key}",
        )
        source_page = st.text_input("관련 페이지·시트·도면번호(선택)")
        note = st.text_input("자료 메모(선택)")
        user_confirmed = st.checkbox(
            "담당자가 이 자료에 해당 내용이 포함되어 있음을 직접 확인했습니다.",
            help=(
                "체크하지 않으면 파일은 접수하되 내용은 확정하지 않고 사람 확인 필요 상태로 둡니다. "
                "프로그램이 파일 내용까지 자동 검증한 것으로 처리하지 않습니다."
            ),
        )

        if st.button("선택한 회사자료 접수", type="primary", width="stretch"):
            if not uploads:
                st.error("접수할 파일을 하나 이상 선택하세요.")
            else:
                existing = project.get_field(field_key)
                evidence = list(existing.evidence) if existing else []
                names: list[str] = []
                for upload in uploads:
                    ref = save_attachment(
                        project.project_id,
                        upload.name,
                        upload.getvalue(),
                        source_type="ATTACHMENT",
                        note=note,
                    )
                    ref.page = source_page
                    evidence.append(ref)
                    names.append(upload.name)

                stored_value = existing.value if existing is not None and existing.value not in (None, "", [], {}) else names
                status = "USER_CONFIRMED" if user_confirmed else "HOLD"
                status_note = note
                if not user_confirmed:
                    status_note = f"자료 접수됨. 파일 내용은 아직 확인되지 않아 사람 확인이 필요합니다. {note}".strip()

                project.set_field(
                    field_key,
                    label_map.get(field_key, field_key),
                    stored_value,
                    status,
                    evidence=evidence,
                    note=status_note,
                )
                save_project(project)
                if user_confirmed:
                    st.success("자료를 접수하고 담당자 확인 상태로 저장했습니다.")
                else:
                    st.warning("자료는 접수했지만 내용은 확정하지 않았습니다. 사람 확인 필요 상태로 저장했습니다.")
                st.rerun()

st.divider()
st.page_link("ui/stage2_validation_page.py", label="4. 작성자료 교차검증으로 이동", icon="🔎")
