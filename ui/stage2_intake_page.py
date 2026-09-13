from __future__ import annotations

import streamlit as st

from engine.stage2.guidance import (
    ACTION_EXCEL,
    ACTION_FILE,
    ACTION_ORDER,
    ACTION_PROGRAM,
    ACTION_REVIEW,
    build_requirement_guidance,
)
from engine.stage2.integrated_workbook import (
    apply_integrated_authoring_workbook,
    attach_company_file,
    build_integrated_authoring_workbook,
)
from engine.stage2.intake import (
    COVERAGE_CONFIRMED,
    COVERAGE_NOT_APPLICABLE,
    build_intake_catalog,
)
from engine.stage2.official_forms import official_form_bytes, resolve_official_form_for_program
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
LEGAL_FOCUS_KEY = "_legal_focus_requirement_key"


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


def _show_basis_entries(title: str, entries) -> None:
    st.write(f"**{title}**")
    if not entries:
        if title == "법적 의무 근거":
            st.caption(
                "현재 작성 registry에서 이 세부 항목에 직접 연결된 법률·시행령·시행규칙 조문을 확인하지 못했습니다. "
                "근거를 임의로 만들지 않고, 아래에 확인된 세부 작성기준·작성 참고자료만 표시합니다."
            )
        else:
            st.caption("현재 구조화된 직접 근거가 없습니다.")
        return
    for entry in entries:
        st.markdown(f"- **{entry.system} · {entry.section} · {entry.label}**  \n  {entry.text}")


def _open_legal_library(requirement_key: str) -> None:
    st.session_state[LEGAL_FOCUS_KEY] = requirement_key
    st.switch_page("ui/legal_evidence_page.py")


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

catalog = build_intake_catalog(project)
unresolved = [
    item for item in catalog
    if item.coverage_status not in {COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE}
]
guided = [(item, build_requirement_guidance(project, item)) for item in unresolved]
by_action = {action: [] for action in ACTION_ORDER}
for item, guidance in guided:
    by_action.setdefault(guidance.action_type, []).append((item, guidance))

st.markdown("### 4. 해야 할 일·작성상태 확인")
st.caption(
    "법령 목차 순서보다 ‘지금 회사가 무엇을 해야 하는지’를 먼저 보여줍니다. "
    "각 항목의 ‘왜 필요한가?’를 열면 그 자리에서 법적 의무 근거, 세부 작성기준, 작성 참고자료를 확인할 수 있습니다."
)

completed_count = sum(item.coverage_status == COVERAGE_CONFIRMED for item in catalog)
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("확인 완료", completed_count)
with c2:
    st.metric("Excel 추가작성", len(by_action.get(ACTION_EXCEL, [])))
with c3:
    st.metric("파일 업로드", len(by_action.get(ACTION_FILE, [])))
with c4:
    st.metric("사람 확인", len(by_action.get(ACTION_REVIEW, [])))
with c5:
    st.metric("프로그램 처리", len(by_action.get(ACTION_PROGRAM, [])))

if not unresolved:
    st.success("현재 통합 작성자료 기준으로 추가 확인이 필요한 작성항목이 없습니다.")
else:
    section_icons = {
        ACTION_EXCEL: "📝",
        ACTION_FILE: "📎",
        ACTION_REVIEW: "👤",
        ACTION_PROGRAM: "⚙️",
    }
    for action in ACTION_ORDER:
        rows = by_action.get(action, [])
        if not rows:
            continue
        st.markdown(f"#### {section_icons.get(action, '•')} {action} · {len(rows)}건")
        for item, guidance in rows:
            title = f"{item.system_label} · {item.label} — {item.coverage_status}"
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write(f"**무엇을 해야 하나요?** {guidance.action_text}")
                if guidance.workbook_locations:
                    st.write("**작성·확인 위치** " + " → ".join(guidance.workbook_locations))
                st.write(f"**현재 부족내용** {guidance.current_gap}")
                if item.suggested_evidence:
                    st.caption("확인에 도움이 되는 자료 예: " + " · ".join(item.suggested_evidence))

                with st.expander(f"왜 필요한가? · {item.label}", expanded=False):
                    _show_basis_entries("법적 의무 근거", guidance.statutory_bases)
                    st.write("")
                    _show_basis_entries("세부 작성기준", guidance.detailed_bases)

                    st.write("")
                    st.write("**작성 참고자료**")
                    if guidance.references:
                        for ref in guidance.references:
                            pages = ", ".join(str(page) for page in ref.pages)
                            st.markdown(f"- {ref.title}" + (f" · 관련 쪽 {pages}" if pages else ""))
                    else:
                        st.caption("현재 연결된 공식 매뉴얼·작성예시 페이지가 없습니다.")

                    if guidance.form_references:
                        st.write("")
                        st.write("**관련 법정 서식**")
                        for form in guidance.form_references:
                            _download_official_form(
                                form,
                                item.system_label,
                                key_prefix=f"reason_{item.requirement_key}",
                            )

                    st.caption(
                        "위 근거는 현재 registry에 구조화되어 확인되는 범위만 표시합니다. 직접 근거가 없는 경우 프로그램이 임의의 조문을 만들어 표시하지 않습니다."
                    )
                    if st.button(
                        "법령·근거 라이브러리에서 이 항목 자세히 보기",
                        key=f"legal_library_{item.requirement_key}",
                        width="stretch",
                    ):
                        _open_legal_library(item.requirement_key)

st.info(
    "통합 작성자료에 입력된 회사 사실은 보고서 초안 작성에 사용할 수 있지만, 빈칸이나 확인되지 않은 내용은 프로그램이 임의로 만들어 채우지 않습니다."
)

st.divider()
st.page_link("ui/stage2_validation_page.py", label="다음: 작성자료 교차검증", icon="🔎")
