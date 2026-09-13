from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine.stage2.intake import selected_requirement_specs
from engine.stage2.scope_validation import validate_selected_scope
from engine.stage2.storage import list_projects, load_project, save_project
from engine.stage2.workflow import (
    ATTACHMENT_MODE_MANUAL,
    attachment_mode,
    input_kind_has_attachment,
    intake_confirmed,
    mark_validation_confirmed,
    validation_confirmed,
)


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"
SYSTEM_LABELS = {
    "COMMON": "공통자료",
    "PSM": PSM_FULL,
    "CAP": CAP_FULL,
}


st.set_page_config(page_title="작성자료 교차검증", page_icon="🔎", layout="wide")
st.title("🔎 4. 작성자료 교차검증")
st.caption(
    "3단계에서 준비한 회사 사실·구조화 표의 일치 여부를 확인합니다. 도면·이미지·원본 첨부자료를 담당자가 별도로 작성하는 경우에는 "
    "그 항목을 텍스트 작성 진행조건과 분리해 표시합니다."
)

projects = list_projects()
if not projects:
    st.info("저장된 작성 프로젝트가 없습니다. 먼저 2. 작성범위 선택과 3. 통합 작성자료를 진행하세요.")
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
    st.stop()

if not intake_confirmed(project):
    st.warning("3. 통합 작성자료의 텍스트·표 준비가 아직 완료 처리되지 않았습니다. 먼저 3단계를 완료해 주세요.")
    st.page_link("ui/stage2_intake_page.py", label="3. 통합 작성자료로 돌아가기", icon="📥")
    st.stop()

scope_labels = []
if project.psm_in_scope:
    scope_labels.append(PSM_FULL)
if project.cap_in_scope:
    scope_labels.append(CAP_FULL)
st.success("현재 교차검증 범위: " + ", ".join(scope_labels))

report = validate_selected_scope(project)
manual_mode = attachment_mode(project) == ATTACHMENT_MODE_MANUAL

attachment_fields: set[str] = {"documents.pfd", "documents.pid", "documents.site_plan", "psm.psi.msds"}
for spec in selected_requirement_specs(project):
    if input_kind_has_attachment(spec.input_kind):
        attachment_fields.update(spec.field_keys)


def _manual_deferred(issue) -> bool:
    if not manual_mode:
        return False
    keys = set(issue.field_keys)
    if not keys.intersection(attachment_fields):
        return False
    # Source-missing and attachment-evidence checks are exactly the items the
    # responsible employee will finish outside the text-authoring workflow.
    return issue.code == "CROSSCHECK-SOURCE-MISSING" or any(key in attachment_fields for key in keys)


manual_issues = [issue for issue in report.issues if _manual_deferred(issue)]
text_issues = [issue for issue in report.issues if not _manual_deferred(issue)]
text_hold = sum(1 for issue in text_issues if issue.status == "HOLD")
text_review = sum(1 for issue in text_issues if issue.status == "REVIEW_REQUIRED")
text_pass = sum(1 for issue in text_issues if issue.status == "PASS")
text_validation_ready = text_hold == 0 and text_review == 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("텍스트·표 검증 보류", text_hold)
c2.metric("텍스트·표 사람 확인", text_review)
c3.metric("확인 완료", text_pass)
c4.metric("담당자 별도 첨부 확인", len(manual_issues))

if text_validation_ready:
    st.success("텍스트·표 작성에 필요한 현재 자동 교차검증은 통과했습니다. 5단계의 로컬 AI 문장 보강과 보고서 초안 작성으로 진행할 수 있습니다.")
else:
    st.warning("텍스트·표 자료에서 해결할 교차검증 항목이 남아 있습니다. 아래 내용을 먼저 확인해 주세요.")

if not report.final_export_allowed:
    st.info(
        "검토용 텍스트 초안 작성과 법정 제출용 최종본 완성은 별개입니다. 별도 작성하기로 한 도면·이미지·계산서·원본 첨부자료가 확인되기 전에는 최종 제출 가능 상태로 보지 않습니다."
    )

rows = []
for issue in text_issues:
    rows.append({
        "프로그램 검증상태": issue.status_label,
        "구분": SYSTEM_LABELS.get(issue.system, issue.system),
        "작성구조": issue.section,
        "작성항목": issue.legal_item,
        "확인내용": issue.message,
        "세부사항": issue.details,
        "작성근거": issue.legal_basis,
    })

if rows:
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.success("텍스트·표 범위에서 추가로 표시할 교차검증 문제가 없습니다.")

if manual_issues:
    with st.expander(f"담당자가 최종 제출 전 별도로 확인할 도면·첨부자료 · {len(manual_issues)}건", expanded=False):
        st.caption("이 항목은 현재 텍스트 작성 진행을 막지 않지만, 법정 제출용 최종본에서는 실제 자료 확인이 필요합니다.")
        manual_rows = []
        for issue in manual_issues:
            manual_rows.append({
                "구분": SYSTEM_LABELS.get(issue.system, issue.system),
                "작성항목": issue.legal_item,
                "확인내용": issue.message,
                "작성근거": issue.legal_basis,
            })
        st.dataframe(pd.DataFrame(manual_rows), width="stretch", hide_index=True)

payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
st.download_button(
    "전체 교차검증 결과 JSON 다운로드",
    data=payload,
    file_name=f"{project.project_id}_작성자료_교차검증.json",
    mime="application/json",
    width="stretch",
)

st.divider()
if not text_validation_ready:
    mark_validation_confirmed(project, False)
    save_project(project)
    st.button("교차검증 확인 완료 → 5. 작성·검토 열기", disabled=True, width="stretch")
else:
    if not validation_confirmed(project):
        if st.button("교차검증 확인 완료 → 5. 작성·검토 열기", type="primary", width="stretch"):
            mark_validation_confirmed(project, True)
            save_project(project)
            st.rerun()
    else:
        st.success("4단계 완료: 5. 작성·검토가 열렸습니다.")
        st.page_link("ui/stage2_review_page.py", label="다음: 5. 작성·검토", icon="📝")
