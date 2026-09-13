from __future__ import annotations

import streamlit as st

from engine.stage2.integrated_workbook import (
    apply_integrated_authoring_workbook,
    attach_company_file,
    build_integrated_authoring_workbook,
)
from engine.stage2.intake import (
    COVERAGE_CONFIRMED,
    COVERAGE_NOT_APPLICABLE,
    build_intake_catalog,
    intake_summary,
)
from engine.stage2.official_forms import official_form_bytes, resolve_official_form_for_program
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


st.set_page_config(page_title="통합 작성자료", page_icon="📥", layout="wide")
st.title("📥 3. 통합 작성자료")
st.caption(
    "선택한 보고서에 필요한 텍스트·표 정보를 하나의 Excel에서 작성합니다. "
    "공통정보는 한 번만 입력하고, 도면·이미지·물질안전보건자료(MSDS) 등 파일은 별도로 한 번에 업로드합니다."
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


def _download_official_form(reference: str, program_label: str, *, key_prefix: str) -> None:
    matches = resolve_official_form_for_program(reference, program_label)
    if len(matches) == 1:
        form = matches[0]
        st.download_button(
            f"{reference} 공식 PDF",
            data=official_form_bytes(form),
            file_name=form.file_name,
            mime="application/pdf",
            key=f"{key_prefix}_{form.law_key}_{reference}",
            width="stretch",
        )
        meta = []
        if form.effective_date:
            meta.append(f"시행일 {form.effective_date}")
        if form.issue_number:
            meta.append(f"발령번호 {form.issue_number}")
        meta.append(f"SHA-256 {form.sha256[:16]}…")
        st.caption(" · ".join(meta))
    elif len(matches) > 1:
        st.warning(f"{reference}: 적용 가능한 공식 서식이 둘 이상 확인되어 자동 선택하지 않습니다.")
    else:
        st.caption(f"{reference}: 현재 최신성 확인이 완료된 공식 PDF를 직접 연결하지 못했습니다.")


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

scope_labels: list[str] = []
if project.psm_in_scope:
    scope_labels.append(PSM_FULL)
if project.cap_in_scope:
    scope_labels.append(CAP_FULL)
st.success("현재 작성범위: " + ", ".join(scope_labels))
if len(scope_labels) == 2:
    st.info(
        "두 보고서를 모두 작성하더라도 회사명·화학물질·설비·안전밸브·감지기 등 공통정보는 통합 작성자료에서 한 번만 입력합니다."
    )

st.markdown("### 1. 통합 작성자료 내려받기")
st.write(
    "실제 입력용 파일에는 Stage 1에서 확인된 회사정보·화학물질·시설자료를 가능한 범위에서 미리 채워 둡니다. "
    "작성예시 파일은 같은 구조에 예시값이 들어 있어 신입 담당자도 작성방법을 참고할 수 있습니다."
)
left, right = st.columns(2)
with left:
    st.download_button(
        "통합 작성자료.xlsx 다운로드",
        data=build_integrated_authoring_workbook(project, example=False),
        file_name=f"{project.project_id}_통합_작성자료.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
with right:
    st.download_button(
        "통합 작성자료_작성예시.xlsx 다운로드",
        data=build_integrated_authoring_workbook(project, example=True),
        file_name=f"{project.project_id}_통합_작성자료_작성예시.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
st.caption(
    "통합 작성자료는 프로그램 입력용 자료이며 법정 별지서식 자체가 아닙니다. 작성예시 파일은 실제 사업장 자료로 제출할 수 없습니다."
)

st.markdown("### 2. 작성한 통합 작성자료 제출")
integrated_upload = st.file_uploader(
    "작성 완료한 통합 작성자료 Excel 업로드",
    type=["xlsx"],
    key="stage2_integrated_workbook_upload",
)
if integrated_upload is not None:
    if st.button("통합 작성자료 반영", type="primary", width="stretch"):
        raw = integrated_upload.getvalue()
        try:
            workbook_ref = save_attachment(
                project.project_id,
                integrated_upload.name,
                raw,
                source_type="STAGE2_INTEGRATED_WORKBOOK",
                note="회사 작성 통합 작성자료 Excel",
            )
            result = apply_integrated_authoring_workbook(
                project,
                raw,
                workbook_evidence=workbook_ref,
            )
            save_project(project)
        except Exception as exc:
            st.error(f"통합 작성자료를 반영하지 못했습니다: {type(exc).__name__}: {exc}")
        else:
            st.success(
                f"통합 작성자료를 반영했습니다. 입력·확인 {result.updated_fields}개 항목, "
                f"구조화 표 {result.table_fields}개 연결, 첨부파일명 {result.attachment_declarations}건을 확인했습니다."
            )
            for warning in result.warnings:
                st.warning(warning)
            st.rerun()

st.markdown("### 3. 도면·첨부자료 한 번에 업로드")
st.caption(
    "통합 작성자료의 ‘07_도면_첨부자료목록’ 시트에 적은 PFD, P&ID, 배치도, 물질안전보건자료(MSDS) 등의 실제 파일을 한 번에 올리세요. "
    "파일명과 목록을 자동 연결하며, 파일 내용 자체는 확인 전까지 사람 확인 필요 상태로 둡니다."
)
attachments = st.file_uploader(
    "도면·첨부자료 업로드",
    accept_multiple_files=True,
    key="stage2_bulk_attachments",
)
if st.button("도면·첨부자료 접수", width="stretch"):
    if not attachments:
        st.warning("접수할 파일을 하나 이상 선택하세요.")
    else:
        linked = 0
        unlinked = 0
        for upload in attachments:
            ref = save_attachment(
                project.project_id,
                upload.name,
                upload.getvalue(),
                source_type="ATTACHMENT",
                note="통합 작성자료와 함께 제출된 도면·첨부자료",
            )
            matches = attach_company_file(project, ref)
            if matches:
                linked += 1
            else:
                unlinked += 1
        save_project(project)
        st.success(f"첨부자료 {len(attachments)}개를 접수했습니다. 목록 자동연결 {linked}개, 연결대상 확인 필요 {unlinked}개입니다.")
        st.rerun()

summary = intake_summary(project)
catalog = build_intake_catalog(project)
counts = summary["counts"]

st.markdown("### 4. 작성상태 확인")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("확인", counts.get("확인", 0))
with c2:
    st.metric("일부 확인", counts.get("일부 확인", 0))
with c3:
    st.metric("사람 확인 필요", counts.get("사람 확인 필요", 0))
with c4:
    st.metric("미작성·자료 필요", counts.get("자료 요청 필요", 0))

unresolved = [
    item for item in catalog
    if item.coverage_status not in {COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE}
]

if not unresolved:
    st.success("현재 통합 작성자료 기준으로 추가 확인이 필요한 작성항목이 없습니다.")
else:
    st.write("아래는 아직 비어 있거나 사람이 확인해야 하는 항목입니다. 평소에는 항목만 보고, 필요한 경우에만 ‘왜 필요한가?’를 열어 근거를 확인하세요.")
    for item in unresolved:
        missing = list(item.missing_labels) + list(item.received_unconfirmed_labels)
        detail = ", ".join(missing) if missing else item.label
        st.write(f"• **{item.system_label} · {item.label}** — {item.coverage_status} · {detail}")
        with st.expander(f"왜 필요한가? · {item.system_label} · {item.label}", expanded=False):
            if item.request_text:
                st.write(item.request_text)
            if item.suggested_evidence:
                st.write("**확인에 도움이 되는 자료 예**")
                st.write(" · ".join(item.suggested_evidence))
            if item.legal_basis:
                st.write("**작성근거**")
                st.code(item.legal_basis)
            if item.form_references:
                st.write("**관련 법정 서식**")
                for form in item.form_references:
                    _download_official_form(
                        form,
                        item.system_label,
                        key_prefix=f"reason_{item.requirement_key}",
                    )
            if item.reference_label:
                pages = ", ".join(str(v) for v in item.reference_pages)
                st.write(f"**작성 참고자료**: {item.reference_label}" + (f" · 관련 쪽 {pages}" if pages else ""))
            st.page_link("ui/legal_evidence_page.py", label="법령·공식 근거자료 자세히 보기", icon="📚")

st.info(
    "통합 작성자료에 입력된 회사 사실은 보고서 초안 작성에 사용할 수 있지만, 빈칸이나 확인되지 않은 내용은 프로그램이 임의로 만들어 채우지 않습니다."
)

st.divider()
st.page_link("ui/stage2_validation_page.py", label="4. 작성자료 교차검증으로 이동", icon="🔎")
