from __future__ import annotations

import streamlit as st

from engine.stage2.guidance import ACTION_PROGRAM, build_requirement_guidance
from engine.stage2.integrated_workbook import apply_integrated_authoring_workbook, attach_company_file
from engine.stage2.intake import COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE, build_intake_catalog
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project
from engine.stage2.workbook_enhancements import build_enhanced_integrated_authoring_workbook
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
    "보고서 본문에 필요한 회사 사실·표를 먼저 정리합니다. "
    "회사가 보유한 제품 SDS/MSDS, 도면·이미지·계산서 등 원본자료는 회사 업무방식에 따라 별도 작성하거나 이 프로젝트에서 함께 관리할 수 있습니다."
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


def _confirmed_text(project, key: str) -> str:
    record = project.get_field(key)
    if record is None or record.value in (None, ""):
        return ""
    return str(record.value).strip()


def _select_index(options: list[str], current: str) -> int:
    return options.index(current) if current in options else 0


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
        "현재는 **텍스트·표 작성 우선 모드**입니다. PFD, P&ID, 배치도, 각종 도면·이미지·계산서와 실제 제품 SDS/MSDS 원본은 담당자가 별도로 작성·취합합니다."
    )
else:
    st.info("현재는 첨부자료까지 프로젝트에서 함께 관리합니다. 실제 도면·PDF·제품 SDS/MSDS를 아래에서 업로드하면 작성자료 점검에 함께 반영됩니다.")

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
if integrated_upload is not None and st.button("통합 작성자료 반영", type="primary", width="stretch"):
    raw = integrated_upload.getvalue()
    try:
        workbook_ref = save_attachment(
            project.project_id,
            integrated_upload.name,
            raw,
            source_type="STAGE2_INTEGRATED_WORKBOOK",
            note="회사 작성 통합 작성자료 Excel",
        )
        result = apply_integrated_authoring_workbook(project, raw, workbook_evidence=workbook_ref)
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
        st.rerun()

if project.cap_in_scope:
    st.markdown("### 4. 회사 확인 질문")
    st.caption(
        "회사자료만으로 확정하기 어려운 법정서식 항목을 담당자에게 확인하는 단계입니다. "
        "답한 내용은 회사 확정사실로 저장되며, AI가 추측해서 채우지 않습니다."
    )
    with st.form(f"cap_business_clarification_{project.project_id}"):
        q_unit = st.text_input(
            "단위공장명",
            value=_confirmed_text(project, "cap.business.unit_plant_name"),
            help="법정서식에 표시할 단위공장명을 회사 내부 명칭 기준으로 입력합니다.",
        )
        q_complex = st.text_input(
            "산업단지",
            value=_confirmed_text(project, "cap.business.industrial_complex"),
            help="해당하는 경우 산업단지의 공식 명칭을 입력하고, 해당하지 않으면 '해당 없음'으로 입력합니다.",
        )

        submission_options = ["선택하세요", "신규제출", "변경제출", "재제출", "이행점검 불이행"]
        reason_options = ["선택하세요", "최초", "부적합"]
        joint_options = ["선택하세요", "공동제출", "단독제출"]
        other_review_options = [
            "선택하세요", "미해당", "해당 - 공정안전보고서",
            "해당 - 안전성향상계획", "해당 - 공정안전보고서 + 안전성향상계획",
        ]
        accident_options = ["선택하세요", "예", "아니오"]

        q_submission = st.selectbox(
            "제출구분",
            submission_options,
            index=_select_index(submission_options, _confirmed_text(project, "cap.business.submission_type")),
        )
        q_reason = st.selectbox(
            "제출 사유",
            reason_options,
            index=_select_index(reason_options, _confirmed_text(project, "cap.business.submission_reason")),
            help="선택한 제출구분에서 법정서식의 '최초/부적합' 하위 체크에 사용합니다.",
        )
        q_joint = st.selectbox(
            "공동비상대응계획 제출 방식",
            joint_options,
            index=_select_index(joint_options, _confirmed_text(project, "cap.business.joint_emergency_plan")),
        )
        q_other_review = st.selectbox(
            "타 제도 심사결과 활용",
            other_review_options,
            index=_select_index(other_review_options, _confirmed_text(project, "cap.business.other_system_review")),
        )
        q_recent_accident = st.selectbox(
            "최근 3년간 화학사고 발생 여부",
            accident_options,
            index=_select_index(accident_options, _confirmed_text(project, "cap.business.recent_accident")),
        )

        q_writer_department = st.text_input(
            "작성자 부서",
            value=_confirmed_text(project, "cap.business.writer_department"),
        )
        q_writer_name = st.text_input(
            "작성자 성명",
            value=_confirmed_text(project, "cap.business.writer_name"),
        )
        q_writer_contact = st.text_input(
            "담당자 연락처",
            value=_confirmed_text(project, "cap.business.writer_contact"),
        )
        q_writer_email = st.text_input(
            "담당자 메일주소",
            value=_confirmed_text(project, "cap.business.writer_email"),
        )

        clarification_submit = st.form_submit_button("회사 확인내용 저장", type="primary", width="stretch")

    if clarification_submit:
        answers = {
            "cap.business.unit_plant_name": ("단위공장명", q_unit),
            "cap.business.industrial_complex": ("산업단지", q_complex),
            "cap.business.submission_type": ("제출구분", "" if q_submission == "선택하세요" else q_submission),
            "cap.business.submission_reason": ("제출 사유", "" if q_reason == "선택하세요" else q_reason),
            "cap.business.joint_emergency_plan": ("공동비상대응계획 수립 여부", "" if q_joint == "선택하세요" else q_joint),
            "cap.business.other_system_review": ("타 제도 심사결과 활용 여부", "" if q_other_review == "선택하세요" else q_other_review),
            "cap.business.recent_accident": ("최근 3년간 화학사고 발생 여부", "" if q_recent_accident == "선택하세요" else q_recent_accident),
            "cap.business.writer_department": ("작성자 부서", q_writer_department),
            "cap.business.writer_name": ("작성자 성명", q_writer_name),
            "cap.business.writer_contact": ("담당자 연락처", q_writer_contact),
            "cap.business.writer_email": ("담당자 메일주소", q_writer_email),
        }
        saved = 0
        for key, (label, value) in answers.items():
            value = str(value or "").strip()
            if not value:
                continue
            if _confirmed_text(project, key) == value:
                continue
            project.set_field(
                key,
                label,
                value,
                "USER_CONFIRMED",
                note="Stage 3 회사 확인 질문에서 담당자가 직접 확인한 값",
            )
            saved += 1
        if saved:
            reset_after_intake_change(project)
            save_project(project)
            st.success(f"회사 확인내용 {saved}개를 저장했습니다.")
            st.rerun()
        else:
            st.info("새로 저장할 확인내용이 없습니다.")

st.markdown("### 5. 회사 보유 SDS/MSDS·도면·첨부자료")
if manual_mode:
    st.success("도면·이미지·원본 첨부자료는 담당자가 별도 작성·취합하도록 설정되어 있어 이 단계의 텍스트 작성 완료조건에 포함하지 않습니다.")
    with st.expander("필요한 경우 제품 SDS/MSDS·참고자료를 선택적으로 업로드", expanded=False):
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
                st.rerun()
else:
    st.caption("통합 작성자료의 ‘07_도면_첨부자료목록’ 시트에 적은 PFD, P&ID, 배치도, 제품 SDS/MSDS 등의 실제 파일을 한 번에 올리세요.")
    attachments = st.file_uploader(
        "도면·제품 SDS/MSDS·첨부자료 업로드",
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
                    note="통합 작성자료와 함께 제출된 도면·제품 SDS/MSDS·첨부자료",
                )
                if attach_company_file(project, ref):
                    linked += 1
                else:
                    unlinked += 1
            reset_after_intake_change(project)
            save_project(project)
            st.success(f"첨부자료 {len(attachments)}개를 접수했습니다. 목록 자동연결 {linked}개, 연결대상 확인 필요 {unlinked}개입니다.")
            st.rerun()

catalog = build_intake_catalog(project)
unresolved = [item for item in catalog if item.coverage_status not in {COVERAGE_CONFIRMED, COVERAGE_NOT_APPLICABLE}]
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

st.markdown("### 아직 준비가 필요한 자료")
st.caption("회사에서 직접 입력할 자료, 5단계에서 보고서 문장으로 정리할 항목, 담당자가 별도로 준비할 첨부자료를 구분해 표시합니다.")
if core_rows:
    st.warning(f"4단계 작성자료 점검 전에 회사가 직접 확인해야 할 핵심 텍스트·표 자료가 {len(core_rows)}건 남아 있습니다.")
    with st.expander(f"통합 Excel 보완 필요 · {len(core_rows)}건", expanded=True):
        for item, guidance in core_rows:
            st.markdown(_line(item, guidance))
else:
    st.success("4단계 작성자료 점검에 필요한 핵심 회사 사실·구조화 표가 준비되었습니다.")

if ai_rows:
    with st.expander(f"5단계에서 보고서 문장으로 정리할 항목 · {len(ai_rows)}건", expanded=False):
        st.caption(
            "이 항목은 회사가 직접 입력해야 하는 핵심 원자료가 아니라 보고서 설명문에 해당합니다. "
            "5단계에서 기본 초안으로 작성되며, 원하면 확인된 회사 사실을 바탕으로 로컬 AI가 문장을 자연스럽게 다듬을 수 있습니다. "
            "확인되지 않은 사업장 사실은 만들어 넣지 않습니다."
        )
        for item, guidance in ai_rows:
            st.markdown(_line(item, guidance))

if manual_rows:
    with st.expander(f"담당자 별도 작성·첨부 예정 · {len(manual_rows)}건", expanded=False):
        st.caption(
            "현재 운영방식에서는 아래 도면·이미지·계산서·제품 SDS/MSDS 원본이 프로그램의 보고서 본문 작성 진행을 막지 않습니다. "
            "최종 제출 전에는 담당자가 실제 자료를 작성·확인하여 결합해야 합니다."
        )
        for item, guidance in manual_rows:
            st.markdown(_line(item, guidance))

if file_rows:
    with st.expander(f"파일 업로드 필요 · {len(file_rows)}건", expanded=False):
        for item, guidance in file_rows:
            st.markdown(_line(item, guidance))

if review_rows:
    with st.expander(f"4단계 작성자료 점검에서 확인할 자료 · {len(review_rows)}건", expanded=False):
        for item, guidance in review_rows:
            st.markdown(_line(item, guidance))

st.info(
    "회사가 보유한 SDS/MSDS와 도면·첨부자료를 별도 관리하더라도 법정 제출자료에서 필요한 원본자료가 없어지는 것은 아닙니다. "
    "프로그램에서는 회사 확정사실, 법령·계산 결과, 최종 회사 첨부자료의 역할을 나누어 관리합니다."
)

st.divider()
if core_rows:
    mark_intake_confirmed(project, False)
    save_project(project)
    st.button("기본자료 입력 완료 → 4. 작성자료 점검·보완", disabled=True, width="stretch")
    st.caption("위의 통합 Excel 보완 필요 항목을 먼저 작성해 주세요.")
else:
    if not intake_confirmed(project):
        if st.button("기본자료 입력 완료 → 4. 작성자료 점검·보완", type="primary", width="stretch"):
            mark_intake_confirmed(project, True)
            save_project(project)
            st.rerun()
    else:
        st.success("3단계 완료: 작성자료 점검·보완 단계로 진행할 수 있습니다.")
        st.page_link("ui/stage2_validation_page.py", label="다음: 4. 작성자료 점검·보완", icon="🔎")
