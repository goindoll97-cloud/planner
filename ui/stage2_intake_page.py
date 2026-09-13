from __future__ import annotations

import streamlit as st

from engine.stage2.guidance import ACTION_PROGRAM, build_requirement_guidance
from engine.stage2.integrated_workbook import (
    apply_integrated_authoring_workbook,
    attach_company_file,
)
from engine.stage2.workbook_enhancements import build_enhanced_integrated_authoring_workbook
from engine.stage2.intake import (
    COVERAGE_CONFIRMED,
    COVERAGE_NOT_APPLICABLE,
    build_intake_catalog,
)
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project
from engine.stage2.workflow import (
    ATTACHMENT_MODE_MANUAL,
    ATTACHMENT_MODE_PROGRAM,
    BUCKET_AI_TEXT,
    BUCKET_CORE_INPUT,
    BUCKET_FILE,
    BUCKET_MANUAL_ATTACHMENT,
    BUCKET_PROGRAM,
    BUCKET_REVIEW,
    attachment_mode,
    intake_confirmed,
    mark_intake_confirmed,
    reset_after_intake_change,
    set_attachment_mode,
    stage3_bucket,
)


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

MODE_LABELS = {
    ATTACHMENT_MODE_MANUAL: "도면·이미지·첨부자료는 담당자가 별도 작성·취합",
    ATTACHMENT_MODE_PROGRAM: "첨부자료도 이 프로젝트에서 업로드·관리",
}


st.set_page_config(page_title="통합 작성자료", page_icon="📥", layout="wide")
st.title("📥 3. 통합 작성자료")
st.caption(
    "보고서 본문에 필요한 회사 사실·표를 먼저 정리합니다. 도면·이미지·계산서·원본 첨부자료는 회사 업무방식에 따라 "
    "담당자가 별도로 작성하거나 이 프로젝트에서 함께 관리할 수 있습니다."
)


def _project_selector() -> str | None:
    projects = list_projects()
    if not projects:
        st.info(
            "저장된 작성 프로젝트가 없습니다. 2. 작성범위 선택에서 Stage 1 판정결과로 프로젝트를 만들거나, "
            "이미 작성한 통합 작성자료를 이용해 Stage 2를 직접 시작하세요."
        )
        st.page_link("ui/stage2_scope_page.py", label="2. 작성범위 선택·Stage 2 직접 시작", icon="🧭")
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


def _line(item, guidance) -> str:
    location = " → ".join(guidance.workbook_locations)
    suffix = f" · 위치: {location}" if location else ""
    return f"- **{item.system_label} · {item.label}**{suffix}"


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

st.markdown("### 1. 작성 운영방식")
current_mode = attachment_mode(project)
selected_mode = st.radio(
    "도면·이미지·첨부자료 처리방식",
    options=[ATTACHMENT_MODE_MANUAL, ATTACHMENT_MODE_PROGRAM],
    index=0 if current_mode == ATTACHMENT_MODE_MANUAL else 1,
    format_func=lambda value: MODE_LABELS[value],
    help="법적 제출자료의 필요 여부를 없애는 설정이 아니라, 프로그램 안에서 누가 어떤 자료를 작성·관리할지 정하는 실무 설정입니다.",
)
if selected_mode != current_mode:
    set_attachment_mode(project, selected_mode)
    save_project(project)
    st.rerun()

manual_mode = attachment_mode(project) == ATTACHMENT_MODE_MANUAL
if manual_mode:
    st.info(
        "현재는 **텍스트·표 작성 우선 모드**입니다. PFD, P&ID, 배치도, MSDS, 각종 도면·이미지·계산서 원본은 담당자가 별도로 작성·취합합니다. "
        "프로그램은 확인된 회사 사실을 바탕으로 보고서 본문과 표 작성에 집중하며, 도면이 필요한 부분은 별도 첨부 예정으로 남깁니다."
    )
else:
    st.info("현재는 첨부자료까지 프로젝트에서 함께 관리합니다. 실제 도면·PDF를 아래에서 업로드하면 교차검증에 연결됩니다.")

st.markdown("### 2. 통합 작성자료 내려받기")
st.write(
    "실제 입력용 파일에는 확인된 회사정보·화학물질·시설자료를 가능한 범위에서 미리 채워 둡니다. "
    "정형화 가능한 항목은 드롭다운으로 선택할 수 있고, 사업장 고유값은 직접 입력할 수 있습니다."
)
left, right = st.columns(2)
with left:
    st.download_button(
        "통합 작성자료.xlsx 다운로드",
        data=build_enhanced_integrated_authoring_workbook(project, example=False),
        file_name=f"{project.project_id}_통합_작성자료.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
with right:
    st.download_button(
        "통합 작성자료_작성예시.xlsx 다운로드",
        data=build_enhanced_integrated_authoring_workbook(project, example=True),
        file_name=f"{project.project_id}_통합_작성자료_작성예시.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
st.caption("작성예시 파일은 입력 방법을 보기 위한 자료이며 실제 사업장 자료로 제출할 수 없습니다.")

st.markdown("### 3. 작성한 통합 작성자료 제출")
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
            reset_after_intake_change(project)
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

st.markdown("### 4. 도면·첨부자료")
if manual_mode:
    st.success("도면·이미지·원본 첨부자료는 담당자가 별도 작성·취합하도록 설정되어 있어 이 단계의 완료조건에 포함하지 않습니다.")
    with st.expander("필요한 경우 참고자료만 선택적으로 업로드", expanded=False):
        attachments = st.file_uploader(
            "선택적 참고자료 업로드",
            accept_multiple_files=True,
            key="stage2_optional_attachments",
        )
        if st.button("선택한 참고자료 접수", width="stretch"):
            if not attachments:
                st.warning("접수할 파일을 하나 이상 선택하세요.")
            else:
                linked = 0
                for upload in attachments:
                    ref = save_attachment(
                        project.project_id,
                        upload.name,
                        upload.getvalue(),
                        source_type="ATTACHMENT",
                        note="텍스트 우선 작성 중 선택적으로 접수한 참고자료",
                    )
                    if attach_company_file(project, ref):
                        linked += 1
                reset_after_intake_change(project)
                save_project(project)
                st.success(f"참고자료 {len(attachments)}개를 접수했습니다. 목록 자동연결 {linked}개입니다.")
else:
    st.caption(
        "통합 작성자료의 ‘07_도면_첨부자료목록’ 시트에 적은 PFD, P&ID, 배치도, MSDS 등의 실제 파일을 한 번에 올리세요."
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
                if attach_company_file(project, ref):
                    linked += 1
                else:
                    unlinked += 1
            reset_after_intake_change(project)
            save_project(project)
            st.success(f"첨부자료 {len(attachments)}개를 접수했습니다. 목록 자동연결 {linked}개, 연결대상 확인 필요 {unlinked}개입니다.")

catalog = build_intake_catalog(project)
unresolved = [
    item
    for item in catalog
    if item.coverage_status not in {COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE}
]
classified = []
for item in unresolved:
    guidance = build_requirement_guidance(project, item)
    if guidance.action_type == ACTION_PROGRAM:
        continue
    classified.append((item, guidance, stage3_bucket(project, item, guidance)))

core_rows = [(i, g) for i, g, b in classified if b == BUCKET_CORE_INPUT]
ai_rows = [(i, g) for i, g, b in classified if b == BUCKET_AI_TEXT]
manual_rows = [(i, g) for i, g, b in classified if b == BUCKET_MANUAL_ATTACHMENT]
file_rows = [(i, g) for i, g, b in classified if b == BUCKET_FILE]
review_rows = [(i, g) for i, g, b in classified if b == BUCKET_REVIEW]
program_rows = [(i, g) for i, g, b in classified if b == BUCKET_PROGRAM]

st.markdown("### 추가로 필요한 항목")
st.caption("회사 직접 입력, 로컬 AI 보강, 담당자 별도 첨부를 역할별로 나누어 표시합니다.")
if core_rows:
    st.warning(f"교차검증 전에 회사가 직접 확인해야 할 핵심 텍스트·표 자료가 {len(core_rows)}건 남아 있습니다.")
    with st.expander(f"통합 Excel 보완 필요 · {len(core_rows)}건", expanded=True):
        for item, guidance in core_rows:
            st.markdown(_line(item, guidance))
else:
    st.success("교차검증에 필요한 핵심 회사 사실·구조화 표가 준비되었습니다.")

if ai_rows:
    with st.expander(f"로컬 AI가 보고서 본문 초안으로 보완할 수 있는 항목 · {len(ai_rows)}건", expanded=False):
        st.caption(
            "이 항목은 회사가 직접 입력해야 하는 핵심 원자료가 아니라 보고서용 서술항목입니다. 5단계에서 확인된 회사 사실과 법정 용어지침을 바탕으로 로컬 AI가 초안을 작성합니다. "
            "확인되지 않은 사업장 사실은 만들어 넣지 않고 확인 필요 사항으로 남깁니다."
        )
        for item, guidance in ai_rows:
            st.markdown(_line(item, guidance))

if manual_rows:
    with st.expander(f"담당자 별도 작성·첨부 예정 · {len(manual_rows)}건", expanded=False):
        st.caption(
            "현재 운영방식에서는 아래 도면·이미지·계산서·원본자료가 프로그램의 텍스트 작성 진행을 막지 않습니다. "
            "최종 제출 전에는 담당자가 실제 자료를 작성·확인하여 결합해야 합니다."
        )
        for item, guidance in manual_rows:
            st.markdown(_line(item, guidance))

if file_rows:
    with st.expander(f"파일 업로드 필요 · {len(file_rows)}건", expanded=False):
        for item, guidance in file_rows:
            st.markdown(_line(item, guidance))

if review_rows:
    with st.expander(f"4단계에서 확인할 접수자료 · {len(review_rows)}건", expanded=False):
        for item, guidance in review_rows:
            st.markdown(_line(item, guidance))

st.info(
    "도면·첨부자료를 별도 작성하는 경우에도 법정 제출자료에서 해당 자료가 없어지는 것은 아닙니다. "
    "이 프로그램에서는 텍스트·표 초안 작성과 최종 첨부자료 완성 여부를 분리해 관리합니다."
)

st.divider()
if core_rows:
    mark_intake_confirmed(project, False)
    save_project(project)
    st.button("텍스트·표 자료 준비 완료 → 4. 작성자료 교차검증 열기", disabled=True, width="stretch")
    st.caption("위의 통합 Excel 보완 필요 항목을 먼저 작성해 주세요.")
else:
    if not intake_confirmed(project):
        if st.button("텍스트·표 자료 준비 완료 → 4. 작성자료 교차검증 열기", type="primary", width="stretch"):
            mark_intake_confirmed(project, True)
            save_project(project)
            st.rerun()
    else:
        st.success("3단계 완료: 4. 작성자료 교차검증이 열렸습니다.")
        st.page_link("ui/stage2_validation_page.py", label="다음: 4. 작성자료 교차검증", icon="🔎")
