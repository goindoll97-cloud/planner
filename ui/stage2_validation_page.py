from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine.stage2.cross_validation import PROGRAM_STATUS_LABELS
from engine.stage2.scope_validation import validate_selected_scope
from engine.stage2.storage import list_projects, load_project


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
    "선택한 작성범위 안에서 확인된 작성자료의 근거 유무와 자료 간 식별정보의 일치 여부를 보수적으로 확인합니다. "
    "도면·PDF·자유서술의 내용을 추정하지 않으며, 구조화된 값이 없으면 사람 확인이 필요한 상태로 남깁니다."
)
st.info(
    "‘검증 보류’, ‘사람 확인 필요’, ‘확인 완료’는 프로그램 내부 검증상태이며 법령상의 판정용어가 아닙니다."
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
project_id = st.selectbox(
    "작성 프로젝트",
    ids,
    index=index,
    format_func=lambda pid: labels.get(pid, pid),
)
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
st.success("현재 교차검증 범위: " + ", ".join(scope_labels))

report = validate_selected_scope(project)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("검증 보류", report.hold_count)
with c2:
    st.metric("사람 확인 필요", report.review_count)
with c3:
    st.metric("확인 완료", report.pass_count)
with c4:
    st.metric("현재 검증규칙 통과", "가능" if report.final_export_allowed else "아직 불가")

if report.final_export_allowed:
    st.success("현재 구현된 교차검증 규칙에서 미해결 항목이 없습니다.")
else:
    st.warning(
        "최종본 생성 전에 검증 보류 및 사람 확인 필요 항목을 해결해야 합니다. "
        "이 결과만으로 법적 적합성을 확정하지 않습니다."
    )

rows = []
for issue in report.issues:
    rows.append({
        "프로그램 검증상태": issue.status_label,
        "구분": SYSTEM_LABELS.get(issue.system, issue.system),
        "작성구조": issue.section,
        "작성항목": issue.legal_item,
        "확인내용": issue.message,
        "세부사항": issue.details,
        "작성근거": issue.legal_basis,
        "검증코드": issue.code,
    })

if rows:
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True)
else:
    st.info(
        "현재 자동으로 실행할 수 있는 교차검증 결과가 없습니다. "
        "구조화 작성자료가 추가되면 설비 식별번호·CAS 번호 등의 일치검사가 활성화됩니다."
    )

st.markdown("### 현재 자동검증 범위")
st.markdown(
    "- 기술자료가 확인 상태인데 근거파일이 연결되지 않은 경우 검증 보류\n"
    "- 업로드 근거자료 SHA-256 형식 확인\n"
    "- registry에 지정된 상호검증 자료의 준비 여부 확인\n"
    "- 구조화된 설비자료의 설비 식별번호 중복 확인\n"
    "- 설비목록 ↔ 설비명세의 설비 식별번호 비교\n"
    "- 설비명세 ↔ 안전밸브 및 파열판 자료의 보호대상 설비 식별번호 비교\n"
    "- 화학물질 목록 ↔ 화학사고예방관리계획서 유해화학물질 상세 명세의 CAS 번호 비교"
)

st.markdown("### 자동검증하지 않는 범위")
st.markdown(
    "P&ID, PFD, 공정위험성평가서, 자유서술 문서의 내용을 현재 단계에서 AI가 임의 해석하여 "
    "일치 여부를 확정하지 않습니다. 해당 문서의 구조화 추출·사람 검토 기능은 다음 단계에서 별도로 구현합니다."
)

payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
st.download_button(
    "교차검증 결과 JSON 다운로드",
    data=payload,
    file_name=f"{project.project_id}_작성자료_교차검증.json",
    mime="application/json",
    width="stretch",
)

st.page_link("ui/stage2_project_page.py", label="5. 작성·검토로 이동", icon="📝")
