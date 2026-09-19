from __future__ import annotations

import streamlit as st

from engine.stage2.cap_final_form_runtime import install_cap_final_form_runtime
from engine.stage2.storage import list_projects, load_project
from engine.stage2.workflow import draft_authoring_allowed, intake_confirmed


ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

# Stage 2 final output is DOCX-only. Keep only the CAP DOCX formatting runtime
# for checkbox/choice rendering; HWPX template loading/conversion is not
# installed during ordinary app startup.
install_cap_final_form_runtime()

# ui/stage2_review_page.py imports build_local_llm_client/
# local_llm_config_from_sources/generate_system_ai_drafts directly from
# engine.stage2.local_ai_resilience (small-batch generation with
# checkpointing, longer local read timeouts, bounded output, and tolerant
# JSON-shape parsing for local Ollama models) instead of the plain
# local_llm/ai_drafting versions, so no install step is needed here.
# _run_automatic_ai's own progress_callback (called both before and after
# each batch) surfaces progress directly, with no separate runtime needed.


def _stage2_progress() -> tuple[bool, bool]:
    """Return whether Stage 4/5 should be registered in this app run.

    Streamlit builds the navigation before the selected page executes. If page
    registration depends only on the session's previously active project, a user
    can switch projects inside Stage 3/4 and immediately render a page_link to a
    page that was not registered at app start. Register a gated page whenever
    at least one stored project is legitimately ready for it; each destination
    page still enforces the selected project's own gate before showing content.

    Stage 5 is registered for both fully validated projects and projects whose
    user explicitly acknowledged unresolved HOLD/REVIEW items for draft-only
    authoring. Final-submission readiness remains controlled by validation.
    """
    project_ids: list[str] = []
    active_id = str(st.session_state.get(ACTIVE_PROJECT_KEY) or "").strip()
    if active_id:
        project_ids.append(active_id)
    try:
        for row in list_projects():
            project_id = str(row.get("project_id") or "").strip()
            if project_id and project_id not in project_ids:
                project_ids.append(project_id)
    except Exception:
        pass

    intake_ready = False
    authoring_ready = False
    for project_id in project_ids:
        try:
            project = load_project(project_id)
        except Exception:
            continue
        intake_ready = intake_ready or intake_confirmed(project)
        authoring_ready = authoring_ready or draft_authoring_allowed(project)
        if intake_ready and authoring_ready:
            break
    return intake_ready, authoring_ready


intake_ready, authoring_ready = _stage2_progress()


def _psm_selected_somewhere() -> bool:
    """공정안전보고서를 작성 대상으로 고른 프로젝트가 하나라도 있는지(기존 3~5단계 화면 노출 기준)."""
    try:
        for row in list_projects():
            project_id = str(row.get("project_id") or "").strip()
            if project_id and load_project(project_id).psm_in_scope:
                return True
    except Exception:
        return False
    return False


# 화학사고예방관리계획서는 별지 순서대로 한 화면에서 작성한다. 엑셀 통합 작성자료 가져오기도 그 화면 안에 들어 있어
# 예전의 3~5단계 화면(엑셀 왕복 방식)은 화학사고예방관리계획서에는 더 이상 쓰이지 않는다. 공정안전보고서는 아직
# 그 방식으로 작성하므로, 그 프로젝트가 있을 때만 "공정안전보고서 (기존 방식)" 묶음으로 보여 준다.
sections: dict[str, list] = {
    "화학사고예방관리계획서": [
        st.Page("ui/cap_workspace_page.py", title="화학사고예방관리계획서 작성", icon="📝", default=True),
    ],
}

# 화학사고예방관리계획서는 작성 화면의 "새 사업장으로 시작하기"에서 법정 대상 판정까지 끝낸다. 판정진단·작성범위 선택은
# 공정안전보고서를 기존 방식으로 시작할 때만 필요하므로 그 묶음 안에 둔다.
psm_pages = [
    st.Page("ui/diagnosis_entry.py", title="1. 판정진단", icon="✅"),
    st.Page("ui/stage2_scope_page.py", title="2. 작성범위 선택", icon="🧭"),
]
if _psm_selected_somewhere():
    psm_pages.append(st.Page("ui/stage2_intake_page.py", title="3. 통합 작성자료", icon="📥"))
    if intake_ready:
        psm_pages.append(st.Page("ui/stage2_validation_page.py", title="4. 작성자료 점검·보완", icon="🔎"))
    if authoring_ready:
        psm_pages.append(st.Page("ui/stage2_review_page.py", title="5. 보고서 작성", icon="📝"))
sections["공정안전보고서 (기존 방식)"] = psm_pages

sections["참고"] = [
    st.Page("ui/regdb_page.py", title="규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="법령·근거 라이브러리", icon="📚"),
]

st.navigation(sections).run()
