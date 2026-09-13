from __future__ import annotations

import streamlit as st

from engine.stage2.project import create_project_from_stage1_snapshot
from engine.stage2.storage import list_projects, load_project, save_project


PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"
SNAPSHOT_KEY = "_stage2_stage1_snapshot"
ACTIVE_PROJECT_KEY = "_stage2_active_project_id"


st.set_page_config(page_title="작성범위 선택", page_icon="🧭", layout="wide")
st.title("🧭 2. 작성범위 선택")
st.caption(
    "Stage 1의 법적 대상 여부와 이번 프로젝트에서 실제로 작성할 문서를 분리합니다. "
    "작성범위에서 제외하더라도 Stage 1의 법적 판정은 변경되지 않습니다."
)


def _legal_status(value: bool | None) -> str:
    if value is True:
        return "대상"
    if value is False:
        return "비대상"
    return "미확정"


def _project_selector() -> str | None:
    projects = list_projects()
    snapshot = st.session_state.get(SNAPSHOT_KEY)

    with st.container(border=True):
        st.markdown("### 작성 프로젝트")
        if snapshot:
            decision = snapshot.get("decision", {})
            st.caption(
                f"최근 Stage 1 결과 · {PSM_FULL}: {decision.get('psm_status', '')} / "
                f"{CAP_FULL}: {decision.get('cap_status', '')}"
            )
            if st.button("최근 판정결과로 새 작성 프로젝트 만들기", type="primary", width="stretch"):
                project = create_project_from_stage1_snapshot(snapshot)
                save_project(project)
                st.session_state[ACTIVE_PROJECT_KEY] = project.project_id
                st.success(f"새 작성 프로젝트를 생성했습니다: {project.project_id}")
                st.rerun()

        projects = list_projects()
        if not projects:
            st.info("저장된 작성 프로젝트가 없습니다. 먼저 1. 판정진단을 완료하세요.")
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
        selected = st.selectbox(
            "작성 프로젝트",
            ids,
            index=index,
            format_func=lambda pid: labels.get(pid, pid),
        )
        st.session_state[ACTIVE_PROJECT_KEY] = selected
        return selected


project_id = _project_selector()
if not project_id:
    st.stop()

try:
    project = load_project(project_id)
except Exception as exc:
    st.error(f"프로젝트를 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

st.markdown("### Stage 1 법적 판정결과")
c1, c2 = st.columns(2)
with c1:
    st.metric(PSM_FULL, _legal_status(project.psm_required))
    psm_status = project.stage1_snapshot.get("decision", {}).get("psm_status", "")
    if psm_status:
        st.caption(str(psm_status))
with c2:
    cap_value = _legal_status(project.cap_required)
    if project.cap_group:
        cap_value += f" · {project.cap_group}"
    st.metric(CAP_FULL, cap_value)
    cap_status = project.stage1_snapshot.get("decision", {}).get("cap_status", "")
    if cap_status:
        st.caption(str(cap_status))

st.markdown("### 이번 프로젝트에서 작성할 문서")
st.info(
    "아래 선택은 작성 지원 범위만 정합니다. 법적 제출 대상 여부를 다시 판단하거나 변경하지 않습니다."
)

psm_default = project.psm_selected if project.scope_confirmed else False
cap_default = project.cap_selected if project.scope_confirmed else False

psm_selected = st.checkbox(
    f"{PSM_FULL} 작성 지원",
    value=psm_default,
    disabled=project.psm_required is not True,
    help="Stage 1에서 제출 대상으로 확정된 경우에만 선택할 수 있습니다.",
)
cap_selected = st.checkbox(
    f"{CAP_FULL} 작성 지원",
    value=cap_default,
    disabled=project.cap_required is not True,
    help="Stage 1에서 작성·제출 대상으로 확정된 경우에만 선택할 수 있습니다.",
)

if project.psm_required is True and not psm_selected:
    st.warning(
        f"{PSM_FULL}는 Stage 1 판정상 제출 대상입니다. 선택하지 않으면 이번 작성 프로젝트의 지원 범위에서만 제외되며, "
        "법적 대상 판정은 그대로 유지됩니다."
    )
if project.cap_required is True and not cap_selected:
    st.warning(
        f"{CAP_FULL}는 Stage 1 판정상 작성·제출 대상입니다. 선택하지 않으면 이번 작성 프로젝트의 지원 범위에서만 제외되며, "
        "법적 대상 판정은 그대로 유지됩니다."
    )

if project.psm_required is not True and project.cap_required is not True:
    st.info("Stage 1에서 작성대상으로 확정된 문서가 없어 작성범위를 선택할 수 없습니다.")
else:
    if st.button("작성범위 저장", type="primary", width="stretch"):
        try:
            project.set_authoring_scope(
                psm_selected=bool(psm_selected),
                cap_selected=bool(cap_selected),
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            save_project(project)
            st.success("작성범위를 저장했습니다. 다음 단계에서 필요한 자료와 관련 근거·서식을 확인할 수 있습니다.")
            st.rerun()

if project.scope_confirmed:
    selected_labels = []
    if project.psm_in_scope:
        selected_labels.append(PSM_FULL)
    if project.cap_in_scope:
        selected_labels.append(CAP_FULL)
    st.success("현재 작성범위: " + ", ".join(selected_labels))
    st.page_link("ui/stage2_intake_page.py", label="3. 자료준비·접수로 이동", icon="📥")
