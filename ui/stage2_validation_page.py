from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2.cap_requests import build_cap_data_requests
from engine.stage2.intake import selected_requirement_specs
from engine.stage2.psm_requests import build_psm_data_requests
from engine.stage2.scope_validation import validate_selected_scope
from engine.stage2.storage import list_projects, load_project, save_project
from engine.stage2.workflow import (
    ATTACHMENT_MODE_MANUAL,
    attachment_mode,
    draft_with_holds_acknowledged,
    input_kind_has_attachment,
    intake_confirmed,
    mark_draft_with_holds_acknowledged,
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
STATUS_LABELS = {
    "HOLD": "보완 필요",
    "REVIEW_REQUIRED": "담당자 확인 필요",
    "PASS": "확인 완료",
}


st.set_page_config(page_title="작성자료 점검·보완", page_icon="🔎", layout="wide")
st.title("🔎 4. 작성자료 점검·보완")
st.caption(
    "3단계에서 입력한 자료가 보고서 작성에 충분한지 확인하고, 빠진 자료나 서로 맞지 않는 내용을 정리합니다. "
    "미확인 항목이 남아 있어도 현재 확인된 자료만으로 검토용 초안을 작성할 수 있습니다."
)
st.info(
    "이 단계에서는 ① 선택한 보고서 작성범위에 필요한 자료가 빠지지 않았는지, "
    "② 회사정보·화학물질·시설·표의 내용이 서로 맞는지, "
    "③ 도면·제품 MSDS 등 최종 제출 전에 별도로 준비할 자료가 무엇인지 확인합니다."
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
    st.warning("이번 프로젝트에서 작성할 문서가 아직 선택되지 않았습니다.")
    st.page_link("ui/stage2_scope_page.py", label="2. 작성범위 선택으로 이동", icon="🧭")
    st.stop()

if not intake_confirmed(project):
    st.warning("3. 통합 작성자료의 기본 입력이 아직 완료되지 않았습니다. 먼저 3단계에서 회사자료를 입력해 주세요.")
    st.page_link("ui/stage2_intake_page.py", label="3. 통합 작성자료로 돌아가기", icon="📥")
    st.stop()

scope_labels = []
if project.psm_in_scope:
    scope_labels.append(PSM_FULL)
if project.cap_in_scope:
    scope_labels.append(CAP_FULL)
st.success("현재 점검 대상: " + ", ".join(scope_labels))

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
    return issue.code == "CROSSCHECK-SOURCE-MISSING" or any(key in attachment_fields for key in keys)


manual_issues = [issue for issue in report.issues if _manual_deferred(issue)]
text_issues = [issue for issue in report.issues if not _manual_deferred(issue)]
text_hold = sum(1 for issue in text_issues if issue.status == "HOLD")
text_review = sum(1 for issue in text_issues if issue.status == "REVIEW_REQUIRED")
text_pass = sum(1 for issue in text_issues if issue.status == "PASS")
text_validation_ready = text_hold == 0 and text_review == 0

st.markdown("### 작성자료 자동점검 결과")
c1, c2, c3, c4 = st.columns(4)
c1.metric("보완 필요", text_hold)
c2.metric("담당자 확인 필요", text_review)
c3.metric("확인 완료", text_pass)
c4.metric("최종 제출 전 별도 준비", len(manual_issues))

if text_validation_ready:
    st.success("보고서 작성에 필요한 기본 자료점검이 완료되었습니다. 5. 보고서 작성으로 진행할 수 있습니다.")
else:
    st.warning(
        "보완하거나 담당자가 확인해야 할 항목이 남아 있습니다. "
        "자료를 더 보완할 수도 있고, 현재 확인된 자료만 사용해 검토용 초안 작성을 계속할 수도 있습니다."
    )

if not report.final_export_allowed:
    st.info(
        "보고서 초안 작성 가능 여부와 최종 제출 가능 여부는 다릅니다. "
        "미확인 값은 추정하지 않고 빈칸/HOLD로 남기며, 도면·이미지·계산서·제품 MSDS 등 별도 준비자료는 "
        "최종 제출 전에 실제 자료를 확인하여 결합해야 합니다."
    )

rows = []
for issue in text_issues:
    rows.append({
        "상태": STATUS_LABELS.get(issue.status, issue.status_label),
        "문서": SYSTEM_LABELS.get(issue.system, issue.system),
        "작성항목": issue.legal_item,
        "확인할 내용": issue.message,
        "세부 확인사항": issue.details,
        "근거": issue.legal_basis,
    })

if rows:
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.success("현재 입력된 텍스트·표 자료에서 추가로 보완할 문제가 없습니다.")

st.markdown("### 보강 요청자료")
st.caption(
    "현재 자료만으로 보고서 내용을 확정하기 어려운 항목을 담당자에게 요청하기 쉬운 형태로 정리했습니다. "
    "이 목록은 검토용 초안 작성을 자동으로 막지 않으며, 확보되는 자료는 3단계 통합 작성자료에 추가 반영할 수 있습니다."
)
request_rows: list[dict[str, str]] = []
if project.psm_in_scope:
    for item in build_psm_data_requests(project):
        request_rows.append({
            "문서": PSM_FULL,
            "작성항목": item.label,
            "추가로 필요한 자료": ", ".join(item.missing_labels),
            "확인 가능한 자료": ", ".join(item.suggested_evidence),
            "담당자 요청내용": item.request_text,
            "근거": getattr(item, "legal_basis", ""),
        })
if project.cap_in_scope:
    for item in build_cap_data_requests(project):
        request_rows.append({
            "문서": CAP_FULL,
            "작성항목": item.label,
            "추가로 필요한 자료": ", ".join(item.missing_labels),
            "확인 가능한 자료": ", ".join(item.suggested_evidence),
            "담당자 요청내용": item.request_text,
            "근거": getattr(item, "legal_basis", ""),
        })

if request_rows:
    st.warning(f"추가로 확인하거나 요청할 자료가 {len(request_rows)}건 있습니다.")
    st.dataframe(pd.DataFrame(request_rows), width="stretch", hide_index=True)
    st.page_link("ui/stage2_intake_page.py", label="3. 통합 작성자료에서 보완하기", icon="📥")
else:
    st.success("현재 확인자료 기준으로 추가 요청할 보강자료가 없습니다.")

if manual_issues:
    with st.expander(f"최종 제출 전에 담당자가 별도로 준비할 자료 · {len(manual_issues)}건", expanded=False):
        st.caption("아래 자료는 현재 보고서 본문 작성을 막지는 않지만, 최종 제출본에는 실제 자료 확인이 필요합니다.")
        manual_rows = []
        for issue in manual_issues:
            manual_rows.append({
                "문서": SYSTEM_LABELS.get(issue.system, issue.system),
                "작성항목": issue.legal_item,
                "준비할 내용": issue.message,
                "근거": issue.legal_basis,
            })
        st.dataframe(pd.DataFrame(manual_rows), width="stretch", hide_index=True)

st.divider()
if not text_validation_ready:
    # Keep validation fail-closed, but permit an explicit draft-only continuation.
    if validation_confirmed(project):
        mark_validation_confirmed(project, False)
        save_project(project)

    if draft_with_holds_acknowledged(project):
        st.warning(
            "현재 자료로 검토용 초안 작성을 허용한 상태입니다. 미확인 항목은 빈칸/HOLD로 유지되며, "
            "이 상태는 최종 제출 가능 판정을 의미하지 않습니다."
        )
        st.page_link("ui/stage2_review_page.py", label="다음: 5. 보고서 초안 작성", icon="📝")
    else:
        st.caption(
            "추가 자료를 지금 확보하기 어렵다면 아래 버튼으로 현재 확인된 자료만 사용해 5단계 검토용 초안을 작성할 수 있습니다. "
            "확인되지 않은 사실·수치는 새로 추정하지 않습니다."
        )
        if st.button("현재 자료로 초안 작성 계속 → 5. 보고서 작성", type="primary", width="stretch"):
            mark_draft_with_holds_acknowledged(project, True)
            save_project(project)
            st.rerun()
else:
    if not validation_confirmed(project):
        if st.button("작성자료 확인 완료 → 5. 보고서 작성", type="primary", width="stretch"):
            mark_validation_confirmed(project, True)
            save_project(project)
            st.rerun()
    else:
        st.success("4단계 완료: 보고서 작성에 필요한 기본 자료 확인이 끝났습니다.")
        st.page_link("ui/stage2_review_page.py", label="다음: 5. 보고서 작성", icon="📝")
