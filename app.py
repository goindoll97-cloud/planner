from __future__ import annotations

import streamlit as st

from engine.stage2.cap_final_form_runtime import install_cap_final_form_runtime
from engine.stage2.storage import list_projects, load_project


ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

# Stage 2 final output is DOCX-only. Keep only the CAP DOCX formatting runtime
# for checkbox/choice rendering; HWPX template loading/conversion is not
# installed during ordinary app startup.
install_cap_final_form_runtime()

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

# 두 문서 모두 작성 화면의 "새 사업장으로 시작하기"에서 법정 대상 판정까지 끝낸다. 공정안전보고서는 화학사고예방관리계획서에서
# 이미 입력한 사실을 재사용하는 새 화면에서 작성한다. 예전 3~5단계(엑셀 왕복 방식)는 메뉴에서 뺐다.
if _psm_selected_somewhere():
    sections["공정안전보고서"] = [st.Page("ui/psm_workspace_page.py", title="공정안전보고서 작성", icon="🏭")]

# 물질이 많아 엑셀로 한꺼번에 판정하고 싶을 때만 쓰는 고급 통로(Stage 1 판정엔진은 시작하기와 같다)
sections["엑셀로 판정하기 (고급)"] = [
    st.Page("ui/diagnosis_entry.py", title="판정진단", icon="✅"),
    st.Page("ui/stage2_scope_page.py", title="작성범위 선택", icon="🧭"),
]

sections["참고"] = [
    st.Page("ui/regdb_page.py", title="규정 DB 관리", icon="🗂️"),
    st.Page("ui/legal_evidence_page.py", title="법령·근거 라이브러리", icon="📚"),
]

st.navigation(sections).run()
